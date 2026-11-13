"""Paths and runtime settings. Repo root is the parent of this package."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PROFILES_ROOT = ROOT / "profiles"
OPTIONS_FILE = ROOT / "combination_creation" / "options.json"
OUTPUT_FILE = ROOT / "output.json"
MAIN_SHEET = ROOT / "zehitomo_main.csv"
PROFILE_STATUS_FILE = ROOT / "scripts" / "profile_status.json"
DEFAULT_PROFILE_COOLDOWN_DAYS = 3
BASE_URL = "https://www.zehitomo.com"
START_URL = f"{BASE_URL}/"
MODEL = os.getenv("GOOGLE_MODEL", "gemini-3.6-flash")
MAX_STEPS = 250
PAUSE_BETWEEN = 15
PROFILE_LOCK_NAMES = (
    "SingletonLock",
    "SingletonCookie",
    "SingletonSocket",
    "RunningChromeVersion",
)

# Google Drive sync (service account). Separate from GOOGLE_API_KEY (Gemini).
DRIVE_SYNC_ENABLED = os.getenv("GOOGLE_DRIVE_SYNC", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_drive_creds = os.getenv("GOOGLE_DRIVE_CREDENTIALS", "").strip()
GOOGLE_DRIVE_CREDENTIALS = (
    Path(_drive_creds)
    if _drive_creds and Path(_drive_creds).is_absolute()
    else (ROOT / _drive_creds if _drive_creds else ROOT / "credentials" / "google-drive-service-account.json")
)
DRIVE_FOLDER_ID = os.getenv(
    "GOOGLE_DRIVE_FOLDER_ID",
    "1DAMVhfiyQj8AK890CO87v0Z1omunyrPY",
).strip()
