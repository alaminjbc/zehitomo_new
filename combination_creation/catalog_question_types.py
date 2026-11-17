"""
Catalog Zehitomo questionnaire *types* across services → XLSX + JSON.

For each service (one postal code, default 182-0004):
  1. Open the request-form modal chain
  2. At every question modal, record (question label, all option texts)
  3. Pick the first option to advance and discover later modals
  4. Stop at the address / postal step

A "type" is the ordered tuple of those (label, options) steps.
Services that share the same tuple get the same type_id.

Usage (from repo root, Chrome profile logged in — same as combinations):
    python combination_creation/catalog_question_types.py
    python combination_creation/catalog_question_types.py --service ハウスクリーニング
    python combination_creation/catalog_question_types.py --limit 5
    python combination_creation/catalog_question_types.py --force   # re-scan saved services
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from zehitomo_combination import (  # noqa: E402
    BASE_URL,
    MODAL_SEL,
    SECTIONS_FILE,
    advance_form,
    back,
    choose_option,
    click_page_entry_option,
    filter_targets,
    get_heading,
    get_page,
    get_page_entry_step,
    get_page_options,
    is_address_step,
    is_email_step,
    launch_browser,
    load_targets,
    open_form,
)

DEFAULT_POSTAL = "182-0004"
JSON_OUT = HERE / "question_types.json"
XLSX_OUT = HERE / "question_types.xlsx"
SUMMARY_XLSX_OUT = HERE / "question_types_summary.xlsx"


def load_catalog(path: Path = JSON_OUT) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {"postal_code": DEFAULT_POSTAL, "services": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"postal_code": DEFAULT_POSTAL, "services": {}}
    if not isinstance(data, dict):
        return {"postal_code": DEFAULT_POSTAL, "services": {}}
    data.setdefault("postal_code", DEFAULT_POSTAL)
    data.setdefault("services", {})
    if not isinstance(data["services"], dict):
        data["services"] = {}
    return data


def save_catalog(data: dict, path: Path = JSON_OUT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def persist_catalog(
    catalog: dict,
    *,
    json_out: Path = JSON_OUT,
    xlsx_out: Path = XLSX_OUT,
    summary_xlsx_out: Path = SUMMARY_XLSX_OUT,
) -> dict[str, dict]:
    """
    Recompute type_ids, then write JSON + detail XLSX + summary XLSX together.
    """
    assign_type_ids(catalog["services"])
    types = build_types_index(catalog["services"])
    catalog["types"] = {
        tid: {
            "service_count": e["service_count"],
            "question_count": e["question_count"],
            "services": e["services"],
            "steps": e["steps"],
        }
        for tid, e in types.items()
    }
    enrich_services_meta(catalog["services"])
    save_catalog(catalog, json_out)
    write_detail_xlsx(catalog, types, xlsx_out)
    write_summary_xlsx(catalog, types, summary_xlsx_out)
    return types


def load_service_meta(path: Path = SECTIONS_FILE) -> dict[str, dict]:
    """service_name → {url, category, top_category} from sections.json."""
    with open(path, encoding="utf-8") as f:
        sections = json.load(f)
    meta: dict[str, dict] = {}
    for top_name, cat in sections.items():
        if not isinstance(cat, dict):
            continue
        for section in cat.get("sections") or []:
            if not isinstance(section, dict):
                continue
            category = str(section.get("name") or "").strip()
            for service in section.get("services") or []:
                if not isinstance(service, dict):
                    continue
                name = str(service.get("name") or "").strip()
                if not name:
                    continue
                meta[name] = {
                    "url": str(service.get("url") or ""),
                    "category": category,
                    "top_category": str(top_name),
                }
    return meta


def full_service_url(service_url: str) -> str:
    path = (service_url or "").strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{BASE_URL}{path}"


def _question_steps(steps: list) -> list[dict]:
    """Drop the postal leaf from a step list for human-readable sheets."""
    return [
        s
        for s in (steps or [])
        if isinstance(s, dict) and "郵便番号" not in str(s.get("label") or "")
    ]


def _format_all_info(q_steps: list[dict], *, postal: str, type_id: str) -> str:
    """Single-cell JSON dump of the full question pattern for one service."""
    payload = {
        "type_id": type_id,
        "postal_code": postal,
        "question_count": len(q_steps),
        "questions": [
            {
                "label": str(step.get("label") or ""),
                "options": [str(o) for o in (step.get("options") or [])],
            }
            for step in q_steps
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def enrich_services_meta(services: dict, meta: dict[str, dict] | None = None) -> None:
    """Fill category / URL fields on each saved service from sections.json."""
    meta = meta if meta is not None else load_service_meta()
    for name, block in services.items():
        if not isinstance(block, dict):
            continue
        info = meta.get(name) or {}
        if info.get("category") and not block.get("category"):
            block["category"] = info["category"]
        if info.get("top_category") and not block.get("top_category"):
            block["top_category"] = info["top_category"]
        url = block.get("service_url") or info.get("url") or ""
        if url:
            block["service_url"] = url
        block["url_link"] = full_service_url(str(url))


def signature_key(steps: list[dict]) -> tuple:
    """Hashable fingerprint for a question+options chain."""
    parts: list[tuple] = []
    for step in steps:
        label = str(step.get("label") or "").strip()
        options = tuple(str(o).strip() for o in (step.get("options") or []))
        parts.append((label, options))
    return tuple(parts)


def walk_question_chain(root, page, depth: int = 0) -> list[dict]:
    """
    Linear walk: record every modal's label + all options, then choose the
    first option to reach later questions. Stops at address / email / depth.
    """
    if depth > 20 or is_email_step(root):
        return []

    if is_address_step(root):
        return []

    options = get_page_options(root)
    if options:
        heading = get_heading(root) or f"step_{depth + 1}"
        kind = choose_option(root, options[0])
        if kind is None:
            return [{"label": heading, "options": options}]
        if kind != "button" and not advance_form(root, page):
            return [{"label": heading, "options": options}]
        rest = walk_question_chain(root, page, depth + 1)
        back(root, page)
        return [{"label": heading, "options": options}] + rest

    if advance_form(root, page):
        rest = walk_question_chain(root, page, depth + 1)
        back(root, page)
        return rest

    return []


def scan_service(page, name: str, url: str, postal_code: str) -> list[dict]:
    """
    Prefer the on-page banner buttons (2–3 entry choices) as step 1 when
    present; otherwise open via CTA into the modal and walk from there.
    """
    page.goto(f"{BASE_URL}{url}", wait_until="domcontentloaded")
    page.wait_for_timeout(1200)

    steps: list[dict] = []
    entry = get_page_entry_step(page)
    if entry and entry.get("options"):
        steps.append(entry)
        print(
            f"  page entry: {entry['label']} "
            f"({len(entry['options'])} buttons)"
        )
        if not click_page_entry_option(page, entry["options"][0]):
            raise RuntimeError(f"Could not click page entry: {entry['options'][0]}")
        page.wait_for_selector(MODAL_SEL, timeout=20000)
        page.wait_for_timeout(1000)
        root = page.locator(MODAL_SEL)
    else:
        # No banner entry — same path as combination explorer (CTA → modal).
        root = open_form(page, url)

    steps.extend(walk_question_chain(root, page))
    steps.append(
        {
            "label": "郵便番号を入力して「プロを見る」",
            "options": [postal_code],
        }
    )
    return steps


def assign_type_ids(services: dict) -> dict[str, str]:
    """
    Map signature → type_1, type_2, ... (stable: first-seen order of services).
    Returns service_name → type_id.
    """
    sig_to_id: dict[tuple, str] = {}
    service_to_type: dict[str, str] = {}
    next_n = 1
    for name, block in services.items():
        if not isinstance(block, dict):
            continue
        steps = block.get("steps") or []
        if not steps:
            continue
        key = signature_key(steps)
        if key not in sig_to_id:
            sig_to_id[key] = f"type_{next_n}"
            next_n += 1
        service_to_type[name] = sig_to_id[key]
        block["type_id"] = sig_to_id[key]
        block["question_count"] = max(0, len(steps) - 1)  # exclude postal leaf
    return service_to_type


def build_types_index(services: dict) -> dict[str, dict]:
    types: dict[str, dict] = {}
    for name, block in services.items():
        if not isinstance(block, dict):
            continue
        type_id = block.get("type_id")
        steps = block.get("steps") or []
        if not type_id or not steps:
            continue
        entry = types.setdefault(
            type_id,
            {
                "type_id": type_id,
                "question_count": max(0, len(steps) - 1),
                "steps": steps,
                "services": [],
            },
        )
        entry["services"].append(name)
    for entry in types.values():
        entry["service_count"] = len(entry["services"])
    return dict(sorted(types.items(), key=lambda kv: int(kv[0].split("_")[-1])))


def _autosize(ws) -> None:
    from openpyxl.utils import get_column_letter

    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = 12
        for cell in col[:80]:
            value = "" if cell.value is None else str(cell.value)
            width = max(width, min(len(value) + 2, 60))
        ws.column_dimensions[letter].width = width


def _write_type_sheet(wb, type_id: str, q_steps: list[dict]) -> None:
    """
    Boss-style sheet per type (example: type_1):

      Amount of question |   | Type |
      1 | Q |   | <question>
        | A | Selection | <options joined by | >
    """
    from openpyxl.styles import Alignment, Font

    # Excel sheet names max 31 chars; type_N is fine.
    title = type_id[:31]
    ws = wb.create_sheet(title)
    ws.append(["Amount of question", None, "Type", None])
    ws["A1"].font = Font(bold=True)
    ws["C1"].font = Font(bold=True)

    for i, step in enumerate(q_steps, start=1):
        label = str(step.get("label") or "")
        options = " | ".join(str(o) for o in (step.get("options") or []))
        ws.append([i, "Q", None, label])
        ws.append([None, "A", "Selection", options])

    wrap = Alignment(wrap_text=True, vertical="top")
    for row in ws.iter_rows(min_row=2, max_col=4):
        for cell in row:
            cell.alignment = wrap
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 6
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 70


def write_detail_xlsx(
    catalog: dict,
    types: dict[str, dict],
    path: Path = XLSX_OUT,
) -> None:
    """
    Main sheet `question_types` (columns A–I only, matching boss layout):
      service_name | category | URL link | service_url | type_id |
      question_count | postal_code | error | all_info

    Plus one sheet per type_id (type_1, type_2, …) with Q/A layout.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment

    wb = Workbook()
    ws = wb.active
    ws.title = "question_types"

    postal = catalog.get("postal_code") or DEFAULT_POSTAL
    services = catalog.get("services") or {}

    header = [
        "service_name",
        "category",
        "URL link",
        "service_url",
        "type_id",
        "question_count",
        "postal_code",
        "error",
        "all_info",
    ]
    ws.append(header)

    wrap = Alignment(wrap_text=True, vertical="top")
    for name, block in services.items():
        if not isinstance(block, dict):
            continue
        q_steps = _question_steps(block.get("steps") or [])
        type_id = str(block.get("type_id") or "")
        service_url = str(block.get("service_url") or "")
        url_link = str(block.get("url_link") or full_service_url(service_url))
        all_info = _format_all_info(q_steps, postal=postal, type_id=type_id)
        ws.append(
            [
                name,
                block.get("category") or "",
                url_link,
                service_url,
                type_id,
                block.get("question_count") or len(q_steps),
                postal,
                block.get("error") or "",
                all_info,
            ]
        )
        ws.cell(row=ws.max_row, column=9).alignment = wrap

    ws.row_dimensions[1].height = 18
    for r in range(2, ws.max_row + 1):
        ws.row_dimensions[r].height = 90
    _autosize(ws)
    ws.column_dimensions["C"].width = 45
    ws.column_dimensions["I"].width = 55

    for type_id, entry in types.items():
        q_steps = _question_steps(entry.get("steps") or [])
        _write_type_sheet(wb, type_id, q_steps)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def write_summary_xlsx(
    catalog: dict,
    types: dict[str, dict],
    path: Path = SUMMARY_XLSX_OUT,
) -> None:
    """Separate workbook: counts + one row per type_id."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "summary"

    postal = catalog.get("postal_code") or DEFAULT_POSTAL
    services = catalog.get("services") or {}

    ws.append(["metric", "value"])
    ws.append(["postal_code", postal])
    ws.append(["services_scanned", len(services)])
    ws.append(["unique_question_types", len(types)])
    ws.append([])
    ws.append(
        [
            "type_id",
            "service_count",
            "question_count",
            "question_list",
            "services",
            "sample_all_info",
        ]
    )
    for type_id, entry in types.items():
        q_steps = _question_steps(entry.get("steps") or [])
        labels = " | ".join(str(s.get("label") or "") for s in q_steps)
        sample = _format_all_info(q_steps, postal=postal, type_id=type_id)
        ws.append(
            [
                type_id,
                entry.get("service_count", 0),
                entry.get("question_count", 0),
                labels,
                " | ".join(entry.get("services") or []),
                sample,
            ]
        )
    _autosize(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scan Zehitomo service forms and group identical "
            "question+options chains into types (XLSX + JSON)."
        )
    )
    parser.add_argument(
        "--service",
        action="append",
        dest="services",
        default=None,
        metavar="NAME",
        help="Only scan this service (repeatable)",
    )
    parser.add_argument(
        "--postal-code",
        default=DEFAULT_POSTAL,
        help=f"Postal code recorded on the final step (default {DEFAULT_POSTAL})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Scan at most N services (0 = all)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-scan services already present in question_types.json",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=JSON_OUT,
        help="Intermediate JSON path",
    )
    parser.add_argument(
        "--xlsx-out",
        type=Path,
        default=XLSX_OUT,
        help="Detail Excel path (one sheet, all info per service)",
    )
    parser.add_argument(
        "--summary-xlsx-out",
        type=Path,
        default=SUMMARY_XLSX_OUT,
        help="Summary Excel path (counts + type overview)",
    )
    parser.add_argument(
        "--xlsx-only",
        action="store_true",
        help="Rebuild XLSX files from existing JSON (no browser)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("Missing openpyxl. Install with: pip install openpyxl")
        raise SystemExit(1)

    catalog = load_catalog(args.json_out)
    catalog["postal_code"] = args.postal_code
    persist_kw = dict(
        json_out=args.json_out,
        xlsx_out=args.xlsx_out,
        summary_xlsx_out=args.summary_xlsx_out,
    )

    if args.xlsx_only:
        types = persist_catalog(catalog, **persist_kw)
        print(
            f"Rebuilt detail → {args.xlsx_out.resolve()}\n"
            f"Rebuilt summary → {args.summary_xlsx_out.resolve()} "
            f"({len(catalog['services'])} services, {len(types)} types)"
        )
        return

    targets = load_targets()
    try:
        targets = filter_targets(targets, args.services)
    except KeyError as e:
        print(e)
        raise SystemExit(1) from e

    if args.limit and args.limit > 0:
        targets = targets[: args.limit]

    if not targets:
        print("No services to scan.")
        raise SystemExit(1)

    already = set(catalog["services"])
    if not args.force:
        targets = [(n, u) for n, u in targets if n not in already]

    print(f"Postal     : {args.postal_code}")
    print(f"To scan    : {len(targets)}")
    print(f"Already    : {len(already)} in {args.json_out.name}")
    print(f"JSON       : {args.json_out.resolve()}")
    print(f"Detail XLSX: {args.xlsx_out.resolve()}")
    print(f"Summary XLSX: {args.summary_xlsx_out.resolve()}")
    print("Quit Chrome using the combination profile before starting.\n")

    if not targets:
        print("Nothing new to scan — rebuilding XLSX from saved JSON.")
        types = persist_catalog(catalog, **persist_kw)
        print(
            f"Done → {args.xlsx_out.resolve()} + "
            f"{args.summary_xlsx_out.resolve()} ({len(types)} types)"
        )
        return

    with sync_playwright() as p:
        context = launch_browser(p)
        page = get_page(context)

        for index, (name, url) in enumerate(targets, start=1):
            print(f"[{index}/{len(targets)}] {name}")
            try:
                steps = scan_service(page, name, url, args.postal_code)
            except Exception as e:
                print(f"  ERROR {type(e).__name__}: {e}")
                catalog["services"][name] = {
                    "service_url": url,
                    "url_link": full_service_url(url),
                    "steps": [],
                    "error": f"{type(e).__name__}: {e}",
                }
                types = persist_catalog(catalog, **persist_kw)
                print(
                    f"  saved JSON+XLSX "
                    f"({len(catalog['services'])} services, {len(types)} types)"
                )
                continue

            q_count = max(0, len(steps) - 1)
            labels = [s["label"] for s in steps[:-1]]
            print(f"  {q_count} questions: {' > '.join(labels)}")
            catalog["services"][name] = {
                "service_url": url,
                "url_link": full_service_url(url),
                "steps": steps,
            }
            types = persist_catalog(catalog, **persist_kw)
            print(
                f"  saved JSON+XLSX "
                f"({len(catalog['services'])} services, {len(types)} types)"
            )

        context.close()

    types = build_types_index(catalog["services"])
    print()
    print(
        f"Done. {len(catalog['services'])} services → "
        f"{len(types)} unique question types"
    )
    print(f"JSON    : {args.json_out.resolve()}")
    print(f"Detail  : {args.xlsx_out.resolve()}")
    print(f"Summary : {args.summary_xlsx_out.resolve()}")


if __name__ == "__main__":
    main()
