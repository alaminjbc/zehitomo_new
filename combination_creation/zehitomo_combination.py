"""
Explore Zehitomo request-form modals and save flat combinations to options.json.

Output shape:
{
  "サービス名": {
    "service_url": "/home/...",
    "combination1": {
      "steps": [
        {"label": "建物のタイプは何ですか？", "select": "戸建タイプ"},
        ...
      ],
      "postal_code": "182-0004"
    },
    "combination2": { ... }
  }
}

Usage (from repo root, with Chrome profile logged in):
    # resume by default if combinations already exist
    python combination_creation/zehitomo_combination.py

    # one service — continues from combination{N+1} if N already saved
    python combination_creation/zehitomo_combination.py --service お風呂・浴室の修理・リフォーム
    python combination_creation/zehitomo_combination.py --service リビング・居間リフォーム
    
    
    # wipe and restart from combination1
    python combination_creation/zehitomo_combination.py --service お風呂・浴室の修理・リフォーム --force
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

BASE_URL = "https://www.zehitomo.com"
USER_DATA_DIR = str(ROOT / "zehitomo-profile")
SECTIONS_FILE = ROOT / "sections.json"
OPTIONS_FILE = HERE / "options.json"

POSTAL_CODES = ["182-0004"]

CTA_SEL = "button[class*='RequestFormCTA_button']"
MODAL_SEL = "[data-test-id='request-form-modal']"
ENTRY_TITLE_SEL = "[class*='RequestFormEntry_title']"
ENTRY_BUTTON_TEXT_SEL = "[class*='form-entry-button-text']"
ADDRESS_INPUT_SEL = "#map-search-box-search-input"
NEXT_SEL = "button[data-test-id^='request-next']"
BACK_SEL = "button:has-text('戻る')"


def launch_browser(playwright):
    return playwright.chromium.launch_persistent_context(
        USER_DATA_DIR,
        channel="chrome",
        headless=False,
        viewport={"width": 1280, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )


def get_page(context):
    return context.pages[0] if context.pages else context.new_page()


def load_targets(path=SECTIONS_FILE):
    with open(path, encoding="utf-8") as f:
        sections = json.load(f)

    targets = []
    for category in sections.values():
        for section in category.get("sections", []):
            for service in section.get("services", []):
                targets.append((service["name"], service["url"]))
    return targets


def filter_targets(
    targets: list[tuple[str, str]],
    service_names: list[str] | None,
) -> list[tuple[str, str]]:
    """Keep only services whose name matches one of service_names (exact)."""
    if not service_names:
        return targets

    wanted = list(dict.fromkeys(service_names))  # preserve order, unique
    by_name = {name: url for name, url in targets}
    selected: list[tuple[str, str]] = []
    missing: list[str] = []
    for name in wanted:
        if name in by_name:
            selected.append((name, by_name[name]))
        else:
            missing.append(name)

    if missing:
        # Suggest close matches for typos / partial names
        hints: list[str] = []
        for needle in missing:
            close = [n for n, _ in targets if needle in n]
            if close:
                hints.append(f"  '{needle}' — similar: {', '.join(close[:5])}")
            else:
                hints.append(f"  '{needle}' — no similar name in sections.json")
        raise KeyError(
            "Service not found in sections.json:\n"
            + "\n".join(hints)
        )
    return selected


def load_options(path=OPTIONS_FILE):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_options(data, path=OPTIONS_FILE):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def ensure_files():
    if not OPTIONS_FILE.exists() or OPTIONS_FILE.stat().st_size == 0:
        save_options({})


def next_combination_key(service_data: dict) -> str:
    n = 1
    while f"combination{n}" in service_data:
        n += 1
    return f"combination{n}"


def combination_count(service_data: dict) -> int:
    return sum(1 for k in service_data if k.startswith("combination"))


def answers_from_steps(steps: list[dict]) -> list[str]:
    return [str(step.get("select", "")) for step in steps]


def existing_answer_tuples(service_data: dict) -> set[tuple]:
    seen: set[tuple] = set()
    for key, value in service_data.items():
        if not key.startswith("combination") or not isinstance(value, dict):
            continue
        steps = value.get("steps")
        if isinstance(steps, list) and steps:
            seen.add(tuple(answers_from_steps(steps)))
            continue
        answers = value.get("answers")
        if isinstance(answers, list):
            seen.add(tuple(answers))
    return seen


def add_combination(
    data: dict,
    service_name: str,
    steps: list[dict],
    postal_code: str,
    *,
    seen_answers: set[tuple] | None = None,
) -> str | None:
    service = data.setdefault(service_name, {})
    full_steps = list(steps) + [
        {
            "label": "郵便番号を入力して「プロを見る」",
            "select": postal_code,
        }
    ]
    answers = answers_from_steps(full_steps)
    answer_key = tuple(answers)
    if seen_answers is not None and answer_key in seen_answers:
        return None

    key = next_combination_key(service)
    service[key] = {
        "steps": full_steps,
        "postal_code": postal_code,
    }
    if seen_answers is not None:
        seen_answers.add(answer_key)
    save_options(data)
    print(f"  {key}: {' > '.join(answers)}")
    return key


def open_form(page, url):
    page.goto(f"{BASE_URL}{url}", wait_until="domcontentloaded")

    modal = page.locator(MODAL_SEL)
    if not modal.count():
        cta = page.locator(CTA_SEL)
        cta.first.scroll_into_view_if_needed()
        cta.first.click()

    page.wait_for_selector(MODAL_SEL, timeout=20000)
    page.wait_for_timeout(1000)
    return page.locator(MODAL_SEL)


def get_heading(root):
    for selector in (ENTRY_TITLE_SEL, "h2"):
        locator = root.locator(selector)
        if locator.count():
            text = locator.first.inner_text().strip()
            if text:
                return text
    return ""


def get_radio_options(root):
    options = []
    for radio in root.locator("input[type='radio']").all():
        options.append(radio.locator("xpath=ancestor::label").inner_text().strip())
    return options


def get_checkbox_options(root):
    options = []
    for checkbox in root.locator("input[type='checkbox']").all():
        options.append(checkbox.locator("xpath=parent::*//label").inner_text().strip())
    return options


def get_entry_button_options(root):
    options = []
    for text in root.locator(ENTRY_BUTTON_TEXT_SEL).all():
        options.append(text.inner_text().strip())
    return options


def get_page_options(root):
    return (
        get_radio_options(root)
        + get_checkbox_options(root)
        + get_entry_button_options(root)
    )


def get_next_button(root):
    buttons = root.locator(NEXT_SEL)
    if buttons.count():
        return buttons.last
    return None


def choose_option(root, option):
    for selector, label_selector in (
        ("input[type='radio']", "xpath=ancestor::label"),
        ("input[type='checkbox']", "xpath=parent::*//label"),
    ):
        for control in root.locator(selector).all():
            label = control.locator(label_selector)
            if label.inner_text().strip() == option:
                label.click()
                return "option"

    for text in root.locator(ENTRY_BUTTON_TEXT_SEL).all():
        if text.inner_text().strip() == option:
            text.locator("xpath=ancestor::button").first.click()
            return "button"

    return None


def is_email_step(root):
    return root.locator("button[data-test-id='request-email-step']").count() > 0


def is_address_step(root):
    field = root.locator(ADDRESS_INPUT_SEL)
    return field.count() > 0 and field.first.is_visible()


def advance_form(root, page):
    next_button = get_next_button(root)
    if next_button is not None and not next_button.is_disabled():
        next_button.click()
        page.wait_for_timeout(900)
        return True
    return False


def back(root, page):
    button = root.locator(BACK_SEL).last
    if button.count():
        button.click()
        page.wait_for_timeout(900)
        return True
    page.go_back()
    page.wait_for_timeout(2000)
    return True


def walk(
    root,
    page,
    data,
    service_name,
    steps,
    depth=0,
    *,
    resume_state: dict | None = None,
):
    """DFS all radio/button choices; at address step, record each postal as a combination."""
    if depth > 20 or is_email_step(root):
        return

    if resume_state is None:
        resume_state = {"skip_leaves": 0, "seen_answers": set()}

    options = get_page_options(root)

    if options:
        heading = get_heading(root) or f"step_{depth + 1}"
        for option in options:
            kind = choose_option(root, option)
            if kind is None:
                continue
            if kind != "button" and not advance_form(root, page):
                continue
            next_steps = steps + [{"label": heading, "select": option}]
            walk(
                root,
                page,
                data,
                service_name,
                next_steps,
                depth + 1,
                resume_state=resume_state,
            )
            back(root, page)
        return

    if is_address_step(root):
        # Record combinations only — do not submit 「プロを見る」 for every path
        for code in POSTAL_CODES:
            if resume_state["skip_leaves"] > 0:
                resume_state["skip_leaves"] -= 1
                left = resume_state["skip_leaves"]
                print(
                    f"  resume skip leaf "
                    f"({' > '.join(s['select'] for s in steps)} > {code})"
                    f" — {left} already-saved leaf(s) left to skip"
                )
                continue
            add_combination(
                data,
                service_name,
                steps,
                code,
                seen_answers=resume_state["seen_answers"],
            )
        return

    if advance_form(root, page):
        walk(
            root,
            page,
            data,
            service_name,
            steps,
            depth + 1,
            resume_state=resume_state,
        )
        back(root, page)


def explore_target(page, name, url, data, *, force: bool = False):
    """
    Explore one service form.

    force=False (default): keep existing combinations and resume DFS, skipping
    the first N address leaves already saved so new ones continue as
    combination{N+1}, combination{N+2}, ...
    force=True: wipe this service and start from combination1.
    """
    prior = 0
    if not force and isinstance(data.get(name), dict):
        prior = combination_count(data[name])

    if force or prior == 0:
        data[name] = {"service_url": url}
        skip_leaves = 0
        seen_answers: set[tuple] = set()
        if force and prior:
            print(f"  Force refresh: cleared {prior} old combinations")
        print(f"  Starting from combination1")
    else:
        data[name]["service_url"] = url
        skip_leaves = prior
        seen_answers = existing_answer_tuples(data[name])
        print(
            f"  Resuming: keeping {prior} combinations, "
            f"next new save will be combination{prior + 1}"
        )
        print(
            "  (Browser still walks earlier paths, but does not re-save them.)"
        )

    save_options(data)
    root = open_form(page, url)
    walk(
        root,
        page,
        data,
        name,
        [],
        0,
        resume_state={"skip_leaves": skip_leaves, "seen_answers": seen_answers},
    )
    save_options(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Explore Zehitomo request forms and save questionnaire "
            "combinations to options.json."
        )
    )
    parser.add_argument(
        "--service",
        action="append",
        dest="services",
        default=None,
        metavar="NAME",
        help=(
            "Only explore this service name from sections.json "
            "(repeatable). Example: "
            "--service お風呂・浴室の修理・リフォーム"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Wipe existing combinations for the service and restart "
            "from combination1 (default is resume from next)"
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    ensure_files()
    targets = load_targets()
    try:
        targets = filter_targets(targets, args.services)
    except KeyError as e:
        print(e)
        raise SystemExit(1) from e

    if not targets:
        print("No services to explore.")
        raise SystemExit(1)

    print(f"Services    : {len(targets)}")
    for name, url in targets:
        print(f"  - {name} ({url})")
    print(f"Writing to  : {OPTIONS_FILE.resolve()}")
    print(f"Force       : {args.force}")

    with sync_playwright() as p:
        context = launch_browser(p)
        page = get_page(context)

        data = load_options()
        # Drop old nested-tree shape if present (no combination1 keys)
        for service_name, payload in list(data.items()):
            if isinstance(payload, dict) and not any(
                k.startswith("combination") for k in payload
            ):
                print(f"Clearing old nested tree for: {service_name}")
                del data[service_name]
        save_options(data)

        for index, (name, url) in enumerate(targets, start=1):
            prior = (
                combination_count(data[name])
                if isinstance(data.get(name), dict)
                else 0
            )
            mode = (
                "force"
                if args.force
                else ("resume" if prior else "fresh")
            )
            print(
                f"Exploring {index}/{len(targets)} [{mode}]: "
                f"{name} ({url})"
            )
            explore_target(page, name, url, data, force=args.force)
            count = combination_count(data.get(name, {}))
            print(f"  -> {count} combinations saved for {name}")

        print(f"Done. Saved -> {OPTIONS_FILE}")
        context.close()


if __name__ == "__main__":
    main()
