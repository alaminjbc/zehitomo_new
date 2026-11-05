"""
Login once and save a Chrome profile for Zehitomo.

Opens **real Google Chrome** (not Playwright/automation). Google blocks sign-in
in automated browsers ("This browser or app may not be secure").

Usage:
    python login_profile.py alamin
    python login_profile.py alice

Profile is saved to: profiles/<name>/
Later use the same name with: python -m app.main <name>
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from pathlib import Path

START_URL = "https://www.zehitomo.com/"
PROFILES_ROOT = Path(__file__).resolve().parent / "profiles"


def profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "profile"
    return PROFILES_ROOT / safe


def find_google_chrome() -> Path | None:
    """Path to a normal Google Chrome binary (not Playwright Chromium)."""
    if sys.platform == "darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path(
                "/Applications/Google Chrome Canary.app/Contents/MacOS/"
                "Google Chrome Canary"
            ),
        ]
    elif sys.platform == "win32":
        local = Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"
        candidates = [
            local,
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = []
        for name in (
            "google-chrome",
            "google-chrome-stable",
            "chrome",
            "chromium",
            "chromium-browser",
        ):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for path in candidates:
        if path.is_file():
            return path
    return None


def launch_chrome(user_data_dir: Path, url: str) -> None:
    chrome = find_google_chrome()
    if chrome is None:
        raise FileNotFoundError(
            "Google Chrome not found. Install Chrome from https://www.google.com/chrome/\n"
            "Playwright/Chromium cannot be used for Google login (Google blocks it)."
        )

    # No remote debugging or automation flags — required for Google sign-in.
    subprocess.Popen(
        [
            str(chrome),
            f"--user-data-dir={user_data_dir.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


async def wait_for_enter(prompt: str) -> None:
    await asyncio.to_thread(input, prompt)


async def login(name: str) -> None:
    path = profile_path(name)
    path.mkdir(parents=True, exist_ok=True)

    print(f"Profile name : {name}")
    print(f"Profile dir  : {path.resolve()}")
    print("Opening Google Chrome (normal browser, not automation)...\n")

    launch_chrome(path, START_URL)

    print(f"Loaded in Chrome: {START_URL}")
    print("=" * 60)
    print("1. Click 「ログイン」 in the Chrome window")
    print("2. Sign in with Google / email (should NOT show 'not secure' now)")
    print("3. Confirm you are logged in on Zehitomo")
    print("4. Quit Chrome completely (macOS: Cmd+Q)")
    print("5. Return here and press ENTER once")
    print("=" * 60)
    await wait_for_enter("\nPress ENTER after you quit Chrome: ")
    print(f"Profile saved under {path.resolve()}")
    print(f"Next: python -m app.main {name} --service <service> --limit 1")
    print(
        "\nImportant: Always quit Chrome before python -m app.main "
        "(same profile folder cannot be open in two browsers)."
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python login_profile.py <profile_name>")
        print("Example: python login_profile.py alamin")
        sys.exit(1)
    try:
        asyncio.run(login(sys.argv[1]))
    except FileNotFoundError as e:
        print(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
