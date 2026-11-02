"""
Login once and save a Chrome profile for Zehitomo.

Usage:
    python login_profile.py alamin
    python login_profile.py alice

Profile is saved to: profiles/<name>/
Later use the same name with run_scrape.py
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

from browser_use import Browser

START_URL = "https://www.zehitomo.com/"
PROFILES_ROOT = Path(__file__).resolve().parent / "profiles"


def profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "profile"
    return PROFILES_ROOT / safe


async def login(name: str) -> None:
    path = profile_path(name)
    path.mkdir(parents=True, exist_ok=True)

    print(f"Profile name : {name}")
    print(f"Profile dir  : {path.resolve()}")
    print("Opening browser... log in to Zehitomo, then press ENTER here.\n")

    browser = Browser(
        user_data_dir=str(path),
        headless=False,
        keep_alive=True,
        window_size={"width": 1440, "height": 900},
    )
    await browser.start()

    try:
        page = await browser.get_current_page()
        await page.goto(START_URL)
        input(
            "=" * 60 + "\n"
            "1. Click 「ログイン」\n"
            "2. Sign in with this account's email\n"
            "3. When logged in, press ENTER here to save the profile\n"
            "=" * 60 + "\n"
        )
        print(f"Saved. Next run scraping with:\n  python run_scrape.py {name}")
    finally:
        await browser.kill()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python login_profile.py <profile_name>")
        print("Example: python login_profile.py alamin")
        sys.exit(1)
    asyncio.run(login(sys.argv[1]))


if __name__ == "__main__":
    main()
