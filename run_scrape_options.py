"""
Scrape Zehitomo contractors using exact questionnaire combinations from options.json.

Usage:
    # login once
    python login_profile.py azimon

    # scrape first combination of エアコンクリーニング
    python run_scrape_options.py azimon --service エアコンクリーニング --limit 1

    # scrape combination1 and combination2 only
    python run_scrape_options.py azimon --service エアコンクリーニング \\
        --combination combination1 --combination combination2

    # scrape all combinations for a service
    python run_scrape_options.py azimon --service エアコンクリーニング

Requires .env:
    GOOGLE_API_KEY=...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from browser_use import ActionResult, Agent, Browser, ChatGoogle, Tools
from browser_use.tools.views import NoParamsAction

load_dotenv()

ROOT = Path(__file__).resolve().parent
PROFILES_ROOT = ROOT / "profiles"
OPTIONS_FILE = ROOT / "combination_creation" / "options.json"
BASE_URL = "https://www.zehitomo.com"
START_URL = f"{BASE_URL}/"
MODEL = os.getenv("GOOGLE_MODEL", "gemini-3.6-flash")
MAX_STEPS = 250
PAUSE_BETWEEN = 15


class Contractor(BaseModel):
    contractor_name: str = Field(description="Name at top of chat box")
    location: str = Field(description="Location from details/map")
    phone_number: str = Field(default="", description="Phone or empty")
    email: str = Field(default="", description="Email or empty")


class ScrapingResult(BaseModel):
    postal_code: str
    service: str
    combination_id: str = ""
    contractors: list[Contractor]


def profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "profile"
    return PROFILES_ROOT / safe


def load_options(path: Path = OPTIONS_FILE) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(
            f"options.json not found or empty: {path}\n"
            "Run: python combination_creation/zehitomo_combination.py"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"No services in {path}")
    return data


def list_combinations(service_data: dict[str, Any]) -> list[tuple[str, dict]]:
    items: list[tuple[str, dict]] = []
    for key, value in service_data.items():
        if key.startswith("combination") and isinstance(value, dict):
            items.append((key, value))

    def sort_key(item: tuple[str, dict]) -> int:
        m = re.search(r"(\d+)$", item[0])
        return int(m.group(1)) if m else 0

    return sorted(items, key=sort_key)


def absolute_service_url(service_url: str) -> str:
    service_url = (service_url or "").strip()
    if service_url.startswith("http"):
        return service_url
    if not service_url.startswith("/"):
        service_url = "/" + service_url
    return BASE_URL + service_url


def format_steps_for_prompt(steps: list[dict]) -> str:
    lines: list[str] = []
    for i, step in enumerate(steps, start=1):
        label = step.get("label", "")
        select = step.get("select", "")
        if "郵便番号" in label or re.match(r"\d{3}-\d{4}", str(select)):
            lines.append(
                f"{i}. Postal / address step「{label}」:\n"
                f"   - Enter postal code `{select}`\n"
                f"   - Click 「プロを見る」"
            )
        else:
            lines.append(
                f"{i}. Question「{label}」:\n"
                f"   - Select exactly: 「{select}」\n"
                f"   - Then click 「次へ」 if that button is visible "
                f"(entry-button choices may advance automatically)."
            )
    return "\n".join(lines)


def build_tools() -> Tools:
    tools = Tools()

    @tools.action(
        "Wait for the user to manually complete login, then continue. "
        "ONLY call this when there is NO circular profile/avatar button "
        "in the TOP-RIGHT of the header. Seeing the word 「ログイン」 "
        "somewhere else on the page does NOT mean logged out.",
        param_model=NoParamsAction,
    )
    async def wait_for_manual_login(_: NoParamsAction) -> ActionResult:
        print(
            "\nNot logged in. Log in manually in the browser, then press ENTER here."
        )
        await asyncio.to_thread(input, "Press ENTER when login is complete: ")
        return ActionResult(extracted_content="Manual login completed.")

    @tools.action(
        "Wait 60 seconds for contractor list to load.",
        param_model=NoParamsAction,
    )
    async def wait_one_minute(_: NoParamsAction) -> ActionResult:
        print("Waiting 60 seconds...")
        await asyncio.sleep(60)
        return ActionResult(extracted_content="Finished waiting 60 seconds.")

    @tools.action(
        "If captcha appears or 「プロを見る」 does nothing, call this and stop. "
        "Pass reason describing what you saw."
    )
    async def report_captcha(reason: str = "") -> ActionResult:
        print(f"[CAPTCHA] {reason or 'blocked'}")
        return ActionResult(
            extracted_content="CAPTCHA_DETECTED. Stop now.",
            error="CAPTCHA_DETECTED",
        )

    @tools.action("Extract phone and email from the open chat page.")
    async def extract_current_contractor(browser_session) -> ActionResult:
        page = await browser_session.get_current_page()
        text = await page.inner_text("body")

        email_match = re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            text,
        )
        phone_match = re.search(
            r"(?<!\d)(?:0\d{1,4}[-−]\d{1,4}[-−]\d{3,4}|0\d{9,10})(?!\d)",
            text,
        )
        return ActionResult(
            extracted_content=json.dumps(
                {
                    "phone_number": (
                        phone_match.group(0).replace("−", "-")
                        if phone_match
                        else ""
                    ),
                    "email": email_match.group(0) if email_match else "",
                    "page_text_preview": text[:3000],
                },
                ensure_ascii=False,
            )
        )

    return tools


def build_task(
    *,
    service_name: str,
    service_url: str,
    combination_id: str,
    combination: dict,
    index: int,
    total: int,
) -> str:
    postal_code = combination.get("postal_code", "")
    steps = combination.get("steps") or []
    answers = combination.get("answers") or []
    steps_text = format_steps_for_prompt(steps)

    return f"""
You are scraping Zehitomo with a saved Chrome profile (already logged in earlier).
This is {combination_id} ({index}/{total}) for service 「{service_name}」.

You MUST follow the fixed questionnaire answers below. Do NOT pick random options.
Do NOT skip steps. Do NOT invent answers.

Exact answers list: {json.dumps(answers, ensure_ascii=False)}

LOGIN CHECK (important — do not get this wrong):
- LOGGED IN = a circular profile / avatar button is visible in the TOP-RIGHT
  corner of the site header.
- LOGGED OUT = that top-right profile circle is missing, and the header shows
  「ログイン」 / 「新規登録」 as header buttons instead.
- The word 「ログイン」 may still appear elsewhere on the page (footer, banners,
  marketing). IGNORE that. Only look at the TOP-RIGHT header.
- If the top-right profile circle is present: you ARE logged in.
  Do NOT call wait_for_manual_login.
- Only call wait_for_manual_login when the top-right profile circle is missing.

Flow:
1. Go to {START_URL}.
2. Check login using the TOP-RIGHT profile circle rule above.
3. Go directly to the service page:
   {service_url}
4. Open the request form if needed (CTA / 「プロを探す」 / similar button).
5. Complete the questionnaire EXACTLY in this order:
{steps_text}
6. If captcha appears or 「プロを見る」 does nothing: call report_captcha and STOP.
7. If 「前回の依頼を確認する」 and 「新しく依頼を出す」 appear,
   click 「前回の依頼を確認する」. Then call wait_one_minute.
8. For EVERY contractor in the left list:
   - click name → chat opens
   - click name at top of chat → details
   - get location; get phone/email from chat (empty string if missing)
   - call extract_current_contractor
9. Return structured result with:
   - postal_code = `{postal_code}`
   - service = 「{service_name}」
   - combination_id = `{combination_id}`
   - contractors list
Do not invent data.
"""


async def scrape_one(
    *,
    path: Path,
    service_name: str,
    service_url: str,
    combination_id: str,
    combination: dict,
    index: int,
    total: int,
) -> ScrapingResult:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Set GOOGLE_API_KEY in .env")

    browser = Browser(
        user_data_dir=str(path),
        headless=False,
        keep_alive=True,
        window_size={"width": 1440, "height": 900},
        ignore_default_args=[
            "--disable-window-activation",
            "--disable-focus-on-load",
        ],
        args=["--start-maximized"],
    )
    agent = Agent(
        task=build_task(
            service_name=service_name,
            service_url=service_url,
            combination_id=combination_id,
            combination=combination,
            index=index,
            total=total,
        ),
        llm=ChatGoogle(model=MODEL, api_key=api_key, temperature=0),
        browser=browser,
        tools=build_tools(),
        output_model_schema=ScrapingResult,
        max_actions_per_step=5,
        use_vision=True,
    )

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        result = history.structured_output
        if result is None:
            final = history.final_result()
            if not final:
                raise RuntimeError("No result (captcha or page not reached)")
            if "CAPTCHA" in str(final).upper():
                raise RuntimeError("CAPTCHA_DETECTED")
            result = ScrapingResult.model_validate_json(final)
        if not result.combination_id:
            result.combination_id = combination_id
        return result
    finally:
        await browser.kill()


def merge_unique(
    existing: list[dict],
    new_items: list[dict],
) -> list[dict]:
    seen = {
        (c.get("contractor_name", ""), c.get("location", ""))
        for c in existing
    }
    out = list(existing)
    for item in new_items:
        key = (item.get("contractor_name", ""), item.get("location", ""))
        if key[0] and key not in seen:
            seen.add(key)
            out.append(item)
    return out


async def run(
    *,
    profile: str,
    service_name: str,
    combination_keys: list[str] | None,
    limit: int | None,
    options_path: Path,
    output: Path,
) -> None:
    path = profile_path(profile)
    if not path.exists():
        raise FileNotFoundError(
            f"Profile '{profile}' not found at {path}.\n"
            f"Create it first: python login_profile.py {profile}"
        )

    options = load_options(options_path)
    if service_name not in options:
        available = ", ".join(sorted(options.keys()))
        raise KeyError(
            f"Service '{service_name}' not in options.json.\n"
            f"Available: {available}"
        )

    service_data = options[service_name]
    service_url = absolute_service_url(service_data.get("service_url", ""))
    all_combos = list_combinations(service_data)
    if not all_combos:
        raise ValueError(f"No combinations under service '{service_name}'")

    if combination_keys:
        wanted = set(combination_keys)
        selected = [(k, v) for k, v in all_combos if k in wanted]
        missing = wanted - {k for k, _ in selected}
        if missing:
            raise KeyError(
                f"Unknown combination keys for '{service_name}': "
                f"{', '.join(sorted(missing))}"
            )
    else:
        selected = all_combos

    if limit is not None:
        selected = selected[: max(0, limit)]

    if not selected:
        raise ValueError("No combinations selected to scrape.")

    print(f"Profile     : {profile} ({path.resolve()})")
    print(f"Options     : {options_path.resolve()}")
    print(f"Service     : {service_name}")
    print(f"Service URL : {service_url}")
    print(f"Combinations: {[k for k, _ in selected]}")
    print(f"Output      : {output.resolve()}")
    print("Quit Chrome using this profile before starting.")
    print("Ctrl+C to stop early.\n")

    runs: list[dict] = []
    contractors: list[dict] = []
    total = len(selected)

    for index, (combo_id, combo) in enumerate(selected, start=1):
        print("=" * 60)
        print(f"{combo_id} ({index}/{total})")
        print(f"answers: {combo.get('answers')}")
        print("=" * 60)

        try:
            result = await scrape_one(
                path=path,
                service_name=service_name,
                service_url=service_url,
                combination_id=combo_id,
                combination=combo,
                index=index,
                total=total,
            )
        except Exception as e:
            print(f"{combo_id} failed: {type(e).__name__}: {e}")
            if "CAPTCHA" in str(e).upper():
                print(
                    "Captcha hit. Stop this profile and switch account:\n"
                    f"  python login_profile.py other_name\n"
                    f"  python run_scrape_options.py other_name "
                    f"--service {service_name}"
                )
                break
            print(f"Skipping to next combination in {PAUSE_BETWEEN}s...")
            await asyncio.sleep(PAUSE_BETWEEN)
            continue

        data = result.model_dump(mode="json", exclude_none=True)
        runs.append(
            {
                "combination_id": combo_id,
                "answers": combo.get("answers", []),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "postal_code": data["postal_code"],
                "service": data["service"],
                "profile": profile,
                "contractors": data["contractors"],
            }
        )
        contractors = merge_unique(contractors, data["contractors"])
        output.write_text(
            json.dumps(
                {
                    "profile": profile,
                    "service": service_name,
                    "service_url": service_url,
                    "options_file": str(options_path),
                    "combinations_done": [r["combination_id"] for r in runs],
                    "contractors": contractors,
                    "runs": runs,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(
            f"Saved {combo_id}: "
            f"+{len(data['contractors'])} this run, "
            f"{len(contractors)} unique total"
        )

        if index < total:
            print(f"Next combination in {PAUSE_BETWEEN}s...\n")
            await asyncio.sleep(PAUSE_BETWEEN)

    print(
        f"\nDone. {len(runs)}/{total} combinations, "
        f"{len(contractors)} unique contractors → {output.resolve()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape Zehitomo using fixed combinations from options.json."
        )
    )
    parser.add_argument("profile", help="Profile name from login_profile.py")
    parser.add_argument(
        "--service",
        default="エアコンクリーニング",
        help="Service name key inside options.json",
    )
    parser.add_argument(
        "--combination",
        action="append",
        dest="combinations",
        default=None,
        help="Combination key to run (repeatable), e.g. combination1",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only run the first N selected combinations",
    )
    parser.add_argument(
        "--options",
        default=str(OPTIONS_FILE),
        help="Path to options.json",
    )
    parser.add_argument(
        "--output",
        default="zehitomo_contractors_options.json",
        help="Output JSON file",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            profile=args.profile,
            service_name=args.service,
            combination_keys=args.combinations,
            limit=args.limit,
            options_path=Path(args.options),
            output=Path(args.output),
        )
    )


if __name__ == "__main__":
    main()
