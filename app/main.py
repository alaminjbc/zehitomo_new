"""CLI entry for the Zehitomo scraper."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.config import OPTIONS_FILE, OUTPUT_FILE
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
        help="Path to options.json",
    )
    parser.add_argument(
        "--output",
        default=str(OUTPUT_FILE),
        help="Output JSON file",
    )
    parser.add_argument(
        "--rerun",
        action="store_true",
        help="Re-scrape combinations even if already present in the output file",
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            run(
                profile=args.profile,
                service_name=args.service,
                combination_keys=args.combinations,
                limit=args.limit,
                options_path=Path(args.options),
                output=Path(args.output),
                rerun=args.rerun,
            )
        )
    except CaptchaDetected:
        sys.exit(CAPTCHA_EXIT_CODE)


if __name__ == "__main__":
    main()
