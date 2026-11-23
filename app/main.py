"""CLI entry for the Zehitomo scraper."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import (
    MAIN_SHEET,
    OPTIONS_FILE,
    OUTPUT_FILE,
    PROFILE_STATUS_FILE,
    apply_path_overrides,
)
from app.services.scraper import CAPTCHA_EXIT_CODE, CaptchaDetected, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape Zehitomo using fixed combinations from options.json."
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
        help="Path to options.json (or options_type_5.json)",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_FILE),
        help="Output JSON file",
    )
    parser.add_argument(
        "--sheet",
        default=str(MAIN_SHEET),
        help="CSV sheet path (zehitomo_main.csv)",
    )
    parser.add_argument(
        "--profile-status",
        default=str(PROFILE_STATUS_FILE),
        help="Profile cooldown status JSON",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Re-scrape combinations even if already present in the output file",
    )
    args = parser.parse_args()

    apply_path_overrides(
        options=args.options,
        output=args.output,
        sheet=args.sheet,
        profile_status=args.profile_status,
    )

    try:
        asyncio.run(
            run(
                profile=args.profile,
                service_name=args.service,
                combination_keys=args.combinations,
                limit=args.limit,
                options_path=Path(args.options),
                output=Path(args.output),
                sheet_path=Path(args.sheet),
                profile_status_path=Path(args.profile_status),
                rerun=args.rerun,
            )
        )
    except CaptchaDetected:
        sys.exit(CAPTCHA_EXIT_CODE)


if __name__ == "__main__":
    main()
