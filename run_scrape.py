"""
Scrape Zehitomo contractors using one saved Chrome profile.

Runs several questionnaire combinations (default 5) on that profile,
then stops. Switch to another profile if captcha starts appearing.

Usage:
    # first login (one time per email)
    python login_profile.py alamin

    # then scrape 5 combinations with that profile
    python run_scrape.py alamin

    # custom options
    python run_scrape.py alamin --combinations 4 --postal-code 182-0004

Requires .env:
    GOOGLE_API_KEY=...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from browser_use import ActionResult, Agent, Browser, ChatGoogle, Tools
from browser_use.tools.views import NoParamsAction

load_dotenv()

PROFILES_ROOT = Path(__file__).resolve().parent / "profiles"
START_URL = "https://www.zehitomo.com/"
SERVICE_URL = "https://www.zehitomo.com/service-list"
AIRCON_URL = (
    "https://www.zehitomo.com/home/cleaning/"
    "electronics-cleaning/air-conditioner-cleaner"
)
SERVICE_NAME = "エアコンクリーニング"
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
    contractors: list[Contractor]


def profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "profile"
    return PROFILES_ROOT / safe


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
        input(
            "\nNot logged in. Log in manually in the browser, then press ENTER.\n"
        )
        return ActionResult(extracted_content="Manual login completed.")

    @tools.action(
        "Pick a random zero-based index for a questionnaire step. "
        "Pass num_options = number of visible radio options."
    )
    async def pick_random_option(num_options: int) -> ActionResult:
        index = random.randrange(max(1, int(num_options)))
        return ActionResult(extracted_content=str(index))

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


def build_task(postal_code: str, combination: int, total: int) -> str:
    return f"""
You are scraping Zehitomo with a saved Chrome profile (already logged in earlier).
This is combination {combination}/{total} (use different random answers than before).

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

Steps:
1. Go to {START_URL}.
2. Check login using the TOP-RIGHT profile circle rule above.
3. Prefer going directly to the service page:
   {AIRCON_URL}
   (You may use {SERVICE_URL} and click 「{SERVICE_NAME}」 if needed.)
4. Click 「戸建タイプ」.
5. Questionnaire modal: until 「スキップ」 appears:
   - count radio options
   - call pick_random_option
   - select that index
   - click 「次へ」
6. Click 「スキップ」 when it appears.
7. Enter postal code `{postal_code}`, click 「プロを見る」.
8. If captcha appears or 「プロを見る」 does nothing: call report_captcha and STOP.
9. If 「前回の依頼を確認する」 and 「新しく依頼を出す」 appear,
    click 「前回の依頼を確認する」. Then call wait_one_minute.
10. For EVERY contractor in the left list:
    - click name → chat opens
    - click name at top of chat → details
    - get location; get phone/email from chat (empty string if missing)
    - call extract_current_contractor
11. Return structured result for postal `{postal_code}` and service 「{SERVICE_NAME}」.
Do not invent data.
"""


async def scrape_one(
    *,
    path: Path,
    postal_code: str,
    combination: int,
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
    )
    agent = Agent(
        task=build_task(postal_code, combination, total),
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
    name: str,
    combinations: int,
    postal_code: str,
    output: Path,
) -> None:
    path = profile_path(name)
    if not path.exists():
        raise FileNotFoundError(
            f"Profile '{name}' not found at {path}.\n"
            f"Create it first: python login_profile.py {name}"
        )

    print(f"Profile      : {name} ({path.resolve()})")
    print(f"Postal code  : {postal_code}")
    print(f"Combinations : {combinations}")
    print(f"Output       : {output.resolve()}")
    print("Ctrl+C to stop early.\n")

    runs: list[dict] = []
    contractors: list[dict] = []

    for i in range(1, combinations + 1):
        print("=" * 60)
        print(f"COMBINATION {i}/{combinations} (new random answers)")
        print("=" * 60)

        try:
            result = await scrape_one(
                path=path,
                postal_code=postal_code,
                combination=i,
                total=combinations,
            )
        except Exception as e:
            print(f"Combination {i} failed: {type(e).__name__}: {e}")
            if "CAPTCHA" in str(e).upper():
                print(
                    "Captcha hit. Stop this profile and switch account:\n"
                    f"  python login_profile.py other_name\n"
                    f"  python run_scrape.py other_name"
                )
                break
            print(f"Skipping to next combination in {PAUSE_BETWEEN}s...")
            await asyncio.sleep(PAUSE_BETWEEN)
            continue

        data = result.model_dump(mode="json", exclude_none=True)
        runs.append(
            {
                "combination": i,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "postal_code": data["postal_code"],
                "service": data["service"],
                "profile": name,
                "contractors": data["contractors"],
            }
        )
        contractors = merge_unique(contractors, data["contractors"])
        output.write_text(
            json.dumps(
                {
                    "profile": name,
                    "service": SERVICE_NAME,
                    "postal_code": postal_code,
                    "combinations_done": len(runs),
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
            f"Saved combination {i}: "
            f"+{len(data['contractors'])} this run, "
            f"{len(contractors)} unique total"
        )

        if i < combinations:
            print(f"Next combination in {PAUSE_BETWEEN}s...\n")
            await asyncio.sleep(PAUSE_BETWEEN)

    print(
        f"\nDone. {len(runs)}/{combinations} combinations, "
        f"{len(contractors)} unique contractors → {output.resolve()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Zehitomo with one saved profile (4-5 combinations)."
    )
    parser.add_argument("profile", help="Profile name from login_profile.py")
    parser.add_argument(
        "--combinations",
        type=int,
        default=5,
        help="How many questionnaire combinations to run (default: 5)",
    )
    parser.add_argument("--postal-code", default="182-0004")
    parser.add_argument(
        "--output",
        default="zehitomo_contractors.json",
        help="Output JSON file",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            name=args.profile,
            combinations=args.combinations,
            postal_code=args.postal_code,
            output=Path(args.output),
        )
    )


if __name__ == "__main__":
    main()
