"""
Build options.json-style combinations from the management sheet
`combination_type_5` tab (type_5 = 民泊清掃).

Sheet rules:
  - Columns Q1–Q4 + location (+ prefecture/city/town).
  - A blank Q cell means “same as the previous row” (fill-forward).
  - `location` is a numeric area id; postal is derived as 7-digit NNNNNNN → NNN-NNNN
    (e.g. 10010 → 001-0010), matching the sample value in column M.

Usage (from repo root):
    python combination_creation/build_options_from_type5.py
    python combination_creation/build_options_from_type5.py --locations 20
    python combination_creation/build_options_from_type5.py \\
        --xlsx "combination_creation/[AI Zehitomo] management sheet.xlsx" \\
        --output combination_creation/options_type_5.json
    # also merge into main options.json under 民泊清掃
    python combination_creation/build_options_from_type5.py --merge-options

    # Boss block-test sheet: 12 rows, same location (10010 → 001-0010), vary Q1–Q4
    python combination_creation/build_options_from_type5.py --test
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUTPUT_DIR = HERE / "Output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
INPUT_DIR = HERE / "Input"
INPUT_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_XLSX = INPUT_DIR / "[AI Zehitomo] management sheet_tokyo.xlsx"
DEFAULT_SHEET = "combination_type_5_tokyo"

DEFAULT_OUTPUT = OUTPUT_DIR / "options_type_5_tokyo.json"
TEST_SHEET = "test_combination_type_5_tokyo"
TEST_OUTPUT = OUTPUT_DIR / "options_test_type_5_tokyo.json"
QUESTION_TYPES = INPUT_DIR / "question_types_tokyo.json"
MAIN_OPTIONS = OUTPUT_DIR / "options_tokyo.json"

SERVICE_NAME = "民泊清掃"
DEFAULT_SERVICE_URL = "/home/cleaning/other-cleaning/airbnb-cleaner"
DEFAULT_LOCATION_LIMIT = 10
# Boss test sheet: 12 Q-rows, one shared location code.
TEST_LOCATION_LIMIT = 1


def location_to_postal(location: Any) -> str:
    """10010 → '001-0010'."""
    raw = str(location).strip()
    if not raw:
        raise ValueError("empty location")
    # Excel may give 10010.0
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise ValueError(f"location has no digits: {location!r}")
    padded = digits.zfill(7)
    if len(padded) > 7:
        padded = padded[-7:]
    return f"{padded[:3]}-{padded[3:]}"


def load_type5_meta(
    path: Path = QUESTION_TYPES,
) -> tuple[str, list[str]]:
    """Return (service_url, question labels for Q1..Q4) from catalog."""
    service_url = DEFAULT_SERVICE_URL
    labels = [
        "どちらで民泊清掃をご希望ですか？",
        "いつ頃実施したいですか？",
        "間取りを教えてください",
        "駐車スペースはございますか？",
    ]
    if not path.exists() or path.stat().st_size == 0:
        return service_url, labels

    data = json.loads(path.read_text(encoding="utf-8"))
    services = data.get("services") or {}
    block = services.get(SERVICE_NAME) if isinstance(services, dict) else None
    if isinstance(block, dict):
        if block.get("service_url"):
            service_url = str(block["service_url"])
        steps = block.get("steps") or []
        q_labels = [
            str(s.get("label") or "").strip()
            for s in steps
            if isinstance(s, dict) and "郵便番号" not in str(s.get("label") or "")
        ]
        if len(q_labels) >= 4:
            labels = q_labels[:4]
    return service_url, labels


def _cell_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def read_type5_rows(
    xlsx: Path,
    *,
    sheet_name: str = DEFAULT_SHEET,
    location_limit: int = DEFAULT_LOCATION_LIMIT,
    max_rows: int | None = None,
    require_explicit_q: bool = False,
) -> list[dict[str, Any]]:
    """
    Read a type_5 combination sheet with Q fill-forward.

    Keep rows until `location_limit` unique location ids are collected.
    If `max_rows` is set, stop after that many combinations.
    If `require_explicit_q` is True, skip rows where all Q1–Q4 cells are blank
    (used for test_combination_type_5 so trailing location junk is ignored).
    """
    from openpyxl import load_workbook

    if not xlsx.exists():
        raise FileNotFoundError(f"Excel not found: {xlsx}")

    wb = load_workbook(xlsx, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise KeyError(
            f"Sheet {sheet_name!r} not in {xlsx.name}. "
            f"Available: {', '.join(wb.sheetnames)}"
        )
    ws = wb[sheet_name]

    prev_q = [None, None, None, None]
    seen_locations: list[str] = []
    seen_set: set[str] = set()
    rows: list[dict[str, Any]] = []

    for row in ws.iter_rows(min_row=2, max_col=10, values_only=True):
        q_raw = [_cell_str(row[i]) if i < len(row) else None for i in range(4)]
        explicit_any = any(v is not None for v in q_raw)
        if require_explicit_q and not explicit_any:
            # Test sheet: stop at the blank block after the 12 boss rows.
            if rows:
                break
            continue

        for i in range(4):
            if q_raw[i] is None:
                q_raw[i] = prev_q[i]
            else:
                prev_q[i] = q_raw[i]

        if any(v is None for v in q_raw):
            # Still missing a Q before the first filled row — skip.
            continue

        loc_val = row[4] if len(row) > 4 else None
        loc_key = _cell_str(loc_val)
        if loc_key is None:
            continue
        if loc_key.endswith(".0"):
            loc_key = loc_key[:-2]

        if loc_key not in seen_set:
            # New location beyond the first N → stop (sheet is location-ordered).
            if len(seen_locations) >= location_limit:
                break
            seen_set.add(loc_key)
            seen_locations.append(loc_key)

        try:
            postal = location_to_postal(loc_key)
        except ValueError:
            continue

        rows.append(
            {
                "answers": list(q_raw),
                "location_id": loc_key,
                "postal_code": postal,
            }
        )
        if max_rows is not None and len(rows) >= max_rows:
            break

    wb.close()
    return rows


def build_options(
    rows: list[dict[str, Any]],
    *,
    service_url: str,
    labels: list[str],
) -> dict[str, Any]:
    service: dict[str, Any] = {"service_url": service_url}
    for index, row in enumerate(rows, start=1):
        steps = [
            {"label": labels[i], "select": row["answers"][i]}
            for i in range(4)
        ]
        steps.append(
            {
                "label": "郵便番号を入力して「プロを見る」",
                "select": row["postal_code"],
            }
        )
        service[f"combination{index}"] = {
            "steps": steps,
            "postal_code": row["postal_code"],
        }
    return {SERVICE_NAME: service}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build options.json combinations for type_5 (民泊清掃) "
            "from the management sheet, using the first N locations."
        )
    )
    parser.add_argument(
        "--xlsx",
        type=Path,
        default=DEFAULT_XLSX,
        help="Path to [AI Zehitomo] management sheet.xlsx",
    )
    parser.add_argument(
        "--sheet",
        default=None,
        help="Sheet name (default: combination_type_5, or test sheet with --test)",
    )
    parser.add_argument(
        "--locations",
        type=int,
        default=None,
        help="How many unique locations to take from the top (default: 20, or 1 with --test)",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional hard cap on combination rows",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help=(
            "Boss block-test mode: sheet test_combination_type_5, "
            "one location (10010), first 12 Q-rows → options_test_type_5.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write standalone options JSON here",
    )
    parser.add_argument(
        "--merge-options",
        action="store_true",
        help=f"Also merge {SERVICE_NAME} into {MAIN_OPTIONS.name}",
    )
    return parser.parse_args()


def _ensure_openpyxl_or_reexec() -> None:
    """
    Homebrew python often wins over conda on PATH. If openpyxl is missing,
    re-exec with the zehitomo conda interpreter when available.
    """
    try:
        import openpyxl  # noqa: F401
        return
    except ImportError:
        pass

    import os
    import sys

    candidates = [
        Path("/opt/miniconda3/envs/zehitomo/bin/python"),
        Path(os.environ["CONDA_PREFIX"]) / "bin" / "python"
        if os.environ.get("CONDA_PREFIX")
        else None,
    ]
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        if candidate.resolve() == Path(sys.executable).resolve():
            continue
        print(f"openpyxl missing in {sys.executable}")
        print(f"Re-running with {candidate}", flush=True)
        os.execv(str(candidate), [str(candidate), *sys.argv])

    print("Missing openpyxl for this Python interpreter.")
    print(f"  python : {sys.executable}")
    print("Install into THIS env, then re-run:")
    print(f"  {sys.executable} -m pip install openpyxl")
    print("Or run explicitly:")
    print(
        "  /opt/miniconda3/envs/zehitomo/bin/python "
        "combination_creation/build_options_from_type5.py"
    )
    raise SystemExit(1)


def main() -> None:
    _ensure_openpyxl_or_reexec()

    args = parse_args()

    sheet = args.sheet
    locations = args.locations
    output = args.output
    max_rows = args.max_rows
    require_explicit_q = False

    if args.test:
        sheet = sheet or TEST_SHEET
        locations = TEST_LOCATION_LIMIT if locations is None else locations
        output = output or TEST_OUTPUT
        # Boss added exactly 12 Q-rows; ignore the huge location tail on that tab.
        max_rows = 12 if max_rows is None else max_rows
        require_explicit_q = True
    else:
        sheet = sheet or DEFAULT_SHEET
        locations = DEFAULT_LOCATION_LIMIT if locations is None else locations
        output = output or DEFAULT_OUTPUT

    if locations < 1:
        raise SystemExit("--locations must be >= 1")

    service_url, labels = load_type5_meta()
    print(f"Service   : {SERVICE_NAME}")
    print(f"URL       : {service_url}")
    print(f"Labels    : {labels}")
    print(f"Sheet     : {sheet} @ {args.xlsx}")
    print(f"Locations : first {locations} unique")
    if max_rows is not None:
        print(f"Max rows  : {max_rows}")
    if args.test:
        print("Mode      : TEST (same location, vary Q1–Q4, one-account block check)")

    rows = read_type5_rows(
        args.xlsx,
        sheet_name=sheet,
        location_limit=locations,
        max_rows=max_rows,
        require_explicit_q=require_explicit_q,
    )
    if not rows:
        raise SystemExit("No rows parsed — check sheet name / fill-forward data.")

    unique_locs = list(dict.fromkeys(r["location_id"] for r in rows))
    print(f"Parsed    : {len(rows)} combinations, {len(unique_locs)} locations")
    for index, row in enumerate(rows, start=1):
        print(
            f"  combination{index}: loc {row['location_id']} → "
            f"{row['postal_code']} | {' > '.join(row['answers'])}"
        )

    payload = build_options(rows, service_url=service_url, labels=labels)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote     : {output.resolve()}")

    if args.merge_options:
        existing: dict[str, Any] = {}
        if MAIN_OPTIONS.exists() and MAIN_OPTIONS.stat().st_size:
            try:
                existing = json.loads(MAIN_OPTIONS.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
            if not isinstance(existing, dict):
                existing = {}
        existing[SERVICE_NAME] = payload[SERVICE_NAME]
        MAIN_OPTIONS.write_text(
            json.dumps(existing, ensure_ascii=False, indent=4) + "\n",
            encoding="utf-8",
        )
        print(f"Merged    : {MAIN_OPTIONS.resolve()} ← {SERVICE_NAME}")


if __name__ == "__main__":
    main()
