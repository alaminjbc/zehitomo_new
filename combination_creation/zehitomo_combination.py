"""
Explore Zehitomo request-form modals and save flat combinations to options.json.

Output shape:
{
  "サービス名": {
    "service_url": "/home/...",
    "combination1": {
      "answers": ["戸建タイプ", "...", "182-0004"],
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
    python combination_creation/zehitomo_combination.py
"""

from __future__ import annotations

import json
import time
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


def add_combination(data: dict, service_name: str, steps: list[dict], postal_code: str):
    service = data.setdefault(service_name, {})
    key = next_combination_key(service)
    answers = [s["select"] for s in steps] + [postal_code]
    full_steps = list(steps) + [
        {
            "label": "郵便番号を入力して「プロを見る」",
            "select": postal_code,
        }
    ]
    service[key] = {
        "answers": answers,
        "steps": full_steps,
        "postal_code": postal_code,
    }
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


def walk(root, page, data, service_name, steps, depth=0):
    """DFS all radio/button choices; at address step, record each postal as a combination."""
    if depth > 20 or is_email_step(root):
        return

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
            walk(root, page, data, service_name, next_steps, depth + 1)
            back(root, page)
        return

    if is_address_step(root):
        # Record combinations only — do not submit 「プロを見る」 for every path
        for code in POSTAL_CODES:
            add_combination(data, service_name, steps, code)
        return

    if advance_form(root, page):
        walk(root, page, data, service_name, steps, depth + 1)
        back(root, page)


def explore_target(page, name, url, data):
    # Fresh list for this service (keeps other services already saved)
    data[name] = {"service_url": url}
    root = open_form(page, url)
    walk(root, page, data, name, [], 0)
    save_options(data)


def main():
    ensure_files()
    targets = load_targets()
    print(f"Loaded {len(targets)} services from {SECTIONS_FILE}")
    print(f"Writing combinations to {OPTIONS_FILE}")

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
            if name in data and any(
                k.startswith("combination") for k in data[name]
            ):
                print(f"Skip {index}/{len(targets)} (already done): {name}")
                continue
            print(f"Exploring {index}/{len(targets)}: {name} ({url})")
            explore_target(page, name, url, data)
            count = sum(
                1 for k in data.get(name, {}) if k.startswith("combination")
            )
            print(f"  -> {count} combinations saved for {name}")

        print(f"Done. Saved -> {OPTIONS_FILE}")
        context.close()


if __name__ == "__main__":
    main()
