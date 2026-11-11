"""Manually push local scrape artifacts to Google Drive.

Usage (from repo root):
    python scripts/sync_drive.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import (  # noqa: E402
    DRIVE_FOLDER_ID,
    DRIVE_SYNC_ENABLED,
    GOOGLE_DRIVE_CREDENTIALS,
)
from app.services.drive import drive_configured, sync_scrape_artifacts  # noqa: E402


def main() -> None:
    print(f"DRIVE_SYNC_ENABLED : {DRIVE_SYNC_ENABLED}")
    print(f"DRIVE_FOLDER_ID    : {DRIVE_FOLDER_ID}")
    print(f"CREDENTIALS        : {GOOGLE_DRIVE_CREDENTIALS}")
    print(f"configured         : {drive_configured()}")
    if not DRIVE_SYNC_ENABLED:
        print("Set GOOGLE_DRIVE_SYNC=1 in .env")
        raise SystemExit(1)
    if not drive_configured():
        print("Missing credentials file or folder id.")
        raise SystemExit(1)
    sync_scrape_artifacts()
    print("Done.")


if __name__ == "__main__":
    main()
