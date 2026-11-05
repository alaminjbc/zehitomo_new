"""Append scraped contractors to zehitomo_main.csv.

Row 2 of the sheet is the English field map:

    date, company_or_contractor_name, address, phone_number, mail_address,
    url_to_access_to_contractor, other_contractor_website_url,
    type_of_industry, memo, , , combination, , timestamp
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from app.config import MAIN_SHEET


def strip_san(name: str) -> str:
    """Sheet note: 企業名 must drop the trailing 「さん」."""
    name = (name or "").strip()
    if name.endswith("さん"):
        return name[:-2].strip()
    return name


def sheet_date(finished_at: str = "") -> str:
    """Match existing rows: 2026/11/05."""
    if finished_at:
        try:
            moment = datetime.fromisoformat(finished_at)
            if moment.tzinfo is not None:
                moment = moment.astimezone()
            return moment.strftime("%Y/%m/%d")
        except ValueError:
            pass
    return datetime.now(timezone.utc).astimezone().strftime("%Y/%m/%d")


def _existing_keys(path: Path) -> set[tuple[str, str, str]]:
    """name + zehitomo url + combination already written."""
    keys: set[tuple[str, str, str]] = set()
    if not path.exists() or path.stat().st_size == 0:
        return keys
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 12:
                continue
            name = strip_san(row[1])
            url = (row[5] or "").strip()
            combination = (row[11] or "").strip()
            if name:
                keys.add((name, url, combination))
    return keys


def append_contractors(
    contractors: list[dict],
    *,
    service_name: str,
    combination_id: str,
    finished_at: str = "",
    sheet_path: Path = MAIN_SHEET,
) -> int:
    """Append one row per contractor. Skip rows already on the sheet."""
    if not contractors:
        return 0

    seen = _existing_keys(sheet_path)
    date = sheet_date(finished_at)
    rows: list[list[str]] = []
    for contractor in contractors:
        name = strip_san(contractor.get("contractor_name", ""))
        if not name:
            continue
        url = (contractor.get("url_to_access_to_contractor") or "").strip()
        key = (name, url, combination_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            [
                date,
                name,
                (contractor.get("location") or "").strip(),
                (contractor.get("phone_number") or "").strip(),
                (contractor.get("email") or "").strip(),
                url,
                (contractor.get("other_contractor_website_url") or "").strip(),
                service_name,
                "",
                "",
                "",
                combination_id,
                "",
                finished_at,
            ]
        )

    if not rows:
        return 0

    needs_newline = False
    if sheet_path.exists() and sheet_path.stat().st_size:
        with sheet_path.open("rb") as handle:
            handle.seek(-1, 2)
            needs_newline = handle.read(1) not in (b"\n", b"\r")

    with sheet_path.open("a", encoding="utf-8", newline="") as handle:
        if needs_newline:
            handle.write("\n")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)
    return len(rows)
