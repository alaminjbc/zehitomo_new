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
