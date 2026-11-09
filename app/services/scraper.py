from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from browser_use import Agent, Browser, ChatGoogle

from app.config import MAX_STEPS, MODEL, PAUSE_BETWEEN
from app.models import ScrapingResult
from app.services.browser import clear_stale_profile_locks, find_google_chrome, profile_path
from app.services.options import (
    absolute_service_url,
    answers_from_steps,
    list_combinations,
    load_options,
)
from app.services.prompt import build_task
from app.services.sheet import append_contractors
from app.services.tools import build_tools

# Exit code used by rotation scripts when postal-code captcha blocks a profile.
CAPTCHA_EXIT_CODE = 2


class CaptchaDetected(RuntimeError):
    """Raised when Zehitomo shows captcha; scripts should switch profile."""


def load_combinations_done(output: Path, service_name: str) -> dict[str, Any]:
    """Keep prior combinations for the same service across profile switches."""
    if not output.exists() or output.stat().st_size == 0:
        return {}
    try:
        data = json.loads(output.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if data.get("service") != service_name:
        return {}
    done = data.get("combinations_done") or {}
    return done if isinstance(done, dict) else {}


def write_output(
    output: Path,
    *,
    profile: str,
    service_name: str,
    service_url: str,
    options_path: Path,
    combinations_done: dict[str, Any],
) -> None:
    output.write_text(
        json.dumps(
            {
                "profile": profile,
                "service": service_name,
                "service_url": service_url,
                "options_file": str(options_path),
                "combinations_done": combinations_done,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


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

    chrome = find_google_chrome()
    if chrome is None:
        raise FileNotFoundError(
            "Google Chrome not found. Profiles from login_profile.py require "
            "real Chrome (Playwright Chromium crashes on those profiles).\n"
            "Install Chrome: https://www.google.com/chrome/"
        )

    removed = clear_stale_profile_locks(path)
    if removed:
        print(f"Cleared stale profile locks: {', '.join(removed)}")

    # Must use real Google Chrome — login_profile.py wrote this user-data-dir
    # with Chrome. browser-use defaults to Playwright Chromium, which then
    # exits immediately → CDP ReadError / RemoteProtocolError.
    browser = Browser(
        executable_path=str(chrome),
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


async def run(
    *,
    profile: str,
    service_name: str,
    combination_keys: list[str] | None,
    limit: int | None,
    options_path: Path,
    output: Path,
    rerun: bool = False,
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

    combinations_done = load_combinations_done(output, service_name)
    if not rerun and combinations_done:
        before = len(selected)
        selected = [(k, v) for k, v in selected if k not in combinations_done]
        skipped = before - len(selected)
        if skipped:
            print(f"Skipping {skipped} combination(s) already in {output.name}")

    if not selected:
        print(f"Nothing left to scrape for '{service_name}' → {output.resolve()}")
        return

    chrome = find_google_chrome()
    print(f"Profile     : {profile} ({path.resolve()})")
    print(f"Chrome      : {chrome.resolve() if chrome else '(missing!)'}")
    print(f"Options     : {options_path.resolve()}")
    print(f"Service     : {service_name}")
    print(f"Service URL : {service_url}")
    print(f"Combinations: {[k for k, _ in selected]}")
    print(f"Output      : {output.resolve()}")
    print("Quit Chrome using this profile before starting (Cmd+Q).")
    print("Ctrl+C to stop early.\n")

    total = len(selected)
    captcha_hit = False

    for index, (combo_id, combo) in enumerate(selected, start=1):
        print("=" * 60)
        print(f"{combo_id} ({index}/{total})")
        print(f"answers: {answers_from_steps(combo.get('steps') or [])}")
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
                    f"  python -m app.main other_name "
                    f"--service {service_name}"
                )
                captcha_hit = True
                break
            print(f"Skipping to next combination in {PAUSE_BETWEEN}s...")
            await asyncio.sleep(PAUSE_BETWEEN)
            continue

        data = result.model_dump(mode="json", exclude_none=True)
        finished_at = datetime.now(timezone.utc).isoformat()
        combinations_done[combo_id] = {
            "steps": combo.get("steps") or [],
            "postal_code": combo.get("postal_code", data.get("postal_code", "")),
            "finished_at": finished_at,
            "profile": profile,
            "extracted_contractors": data["contractors"],
        }
        write_output(
            output,
            profile=profile,
            service_name=service_name,
            service_url=service_url,
            options_path=options_path,
            combinations_done=combinations_done,
        )
        added = append_contractors(
            data["contractors"],
            service_name=service_name,
            combination_id=combo_id,
            profile=profile,
            finished_at=finished_at,
        )
        print(
            f"Saved {combo_id}: {len(data['contractors'])} contractors, "
            f"{added} new rows in zehitomo_main.csv"
        )

        if index < total:
            print(f"Next combination in {PAUSE_BETWEEN}s...\n")
            await asyncio.sleep(PAUSE_BETWEEN)

    contractor_count = sum(
        len(item.get("extracted_contractors") or [])
        for item in combinations_done.values()
    )
    print(
        f"\nDone. {len(combinations_done)} combinations saved, "
        f"{contractor_count} contractors → {output.resolve()}"
    )
    if captcha_hit:
        raise CaptchaDetected("CAPTCHA_DETECTED")
