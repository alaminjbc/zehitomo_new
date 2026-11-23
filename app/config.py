"""Paths and runtime settings. Repo root is the parent of this package.

File paths can be overridden by:
  1. Environment variables (set by scripts/rotate_config.json → lib_rotate.sh)
  2. apply_path_overrides() / CLI flags on `python -m app.main`

If unset, the defaults below are kept.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def resolve_path(raw: str | Path | None, default: Path) -> Path:
    """Absolute path as-is; relative paths are under the repo root."""
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    path = Path(text)
    return path if path.is_absolute() else (ROOT / path)


# Env keys used by rotate scripts (and optional manual exports).
_ENV_OPTIONS = "ZEHITOMO_OPTIONS"
_ENV_OUTPUT = "ZEHITOMO_OUTPUT"
_ENV_SHEET = "ZEHITOMO_SHEET"
_ENV_PROFILE_STATUS = "ZEHITOMO_PROFILE_STATUS"

PROFILES_ROOT = ROOT / "profiles"
OPTIONS_FILE = resolve_path(
    os.getenv(_ENV_OPTIONS),
    ROOT / "combination_creation" / "options.json",
)
OUTPUT_FILE = resolve_path(os.getenv(_ENV_OUTPUT), ROOT / "output.json")
MAIN_SHEET = resolve_path(os.getenv(_ENV_SHEET), ROOT / "zehitomo_main.csv")
PROFILE_STATUS_FILE = resolve_path(
    os.getenv(_ENV_PROFILE_STATUS),
    ROOT / "scripts" / "profile_status.json",
)
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


def apply_path_overrides(
    *,
    options: str | Path | None = None,
    output: str | Path | None = None,
    sheet: str | Path | None = None,
    profile_status: str | Path | None = None,
) -> None:
    """Override path constants for this process (CLI / rotate)."""
    global OPTIONS_FILE, OUTPUT_FILE, MAIN_SHEET, PROFILE_STATUS_FILE

    if options is not None and str(options).strip():
        OPTIONS_FILE = resolve_path(options, OPTIONS_FILE)
        os.environ[_ENV_OPTIONS] = str(OPTIONS_FILE)
    if output is not None and str(output).strip():
        OUTPUT_FILE = resolve_path(output, OUTPUT_FILE)
        os.environ[_ENV_OUTPUT] = str(OUTPUT_FILE)
    if sheet is not None and str(sheet).strip():
        MAIN_SHEET = resolve_path(sheet, MAIN_SHEET)
        os.environ[_ENV_SHEET] = str(MAIN_SHEET)
    if profile_status is not None and str(profile_status).strip():
        PROFILE_STATUS_FILE = resolve_path(profile_status, PROFILE_STATUS_FILE)
        os.environ[_ENV_PROFILE_STATUS] = str(PROFILE_STATUS_FILE)


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
