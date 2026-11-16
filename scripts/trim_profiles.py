"""One-shot trim of regenerable Chrome caches under profiles/.

Usage (from repo root, Chrome fully quit):
    python scripts/trim_profiles.py
    python scripts/trim_profiles.py alamin azimon
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import PROFILES_ROOT  # noqa: E402
from app.services.browser import profile_path, trim_profile_logged  # noqa: E402


def main() -> None:
    names = sys.argv[1:]
    if names:
        paths = [profile_path(name) for name in names]
    else:
        if not PROFILES_ROOT.is_dir():
            print(f"No profiles dir: {PROFILES_ROOT}")
            raise SystemExit(1)
        paths = sorted(p for p in PROFILES_ROOT.iterdir() if p.is_dir())

    if not paths:
        print("No profiles to trim.")
        raise SystemExit(0)

    print("Quit Chrome for these profiles before trimming (Cmd+Q).")
    for path in paths:
        if not path.is_dir():
            print(f"Missing: {path}")
            continue
        trim_profile_logged(path)


if __name__ == "__main__":
    main()
