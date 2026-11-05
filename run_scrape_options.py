"""
Scrape Zehitomo contractors using exact questionnaire combinations from options.json.

Usage:
    # login once
    python login_profile.py azimon

    # scrape first combination of エアコンクリーニング
    python run_scrape_options.py alamin --service エアコンクリーニング --limit 1
    

    # scrape combination1 and combination2 only
    python run_scrape_options.py azimon --service エアコンクリーニング --combination combination1 --combination combination2

    # scrape all combinations for a service
    python run_scrape_options.py azimon --service エアコンクリーニング

Requires .env:
    GOOGLE_API_KEY=...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from browser_use import ActionResult, Agent, Browser, ChatGoogle, Tools
from browser_use.tools.views import NoParamsAction

load_dotenv()

ROOT = Path(__file__).resolve().parent
PROFILES_ROOT = ROOT / "profiles"
OPTIONS_FILE = ROOT / "combination_creation" / "options.json"
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

URL_RE = re.compile(r"https?://[^\s<>\"'）)」】\]}]+", re.IGNORECASE)
ZEHITOMO_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?zehitomo\.com/profile/[^\s<>\"'）)」】\]?#]*",
    re.IGNORECASE,
)
# Click Google result title #index (0 = first, 1 = second).
GOOGLE_CLICK_RESULT_JS = """
(index) => {
  const h3s = Array.from(document.querySelectorAll('h3'));
  if (index < 0 || index >= h3s.length) {
    return { ok: false, reason: 'no_result', count: h3s.length };
  }
  const h3 = h3s[index];
  let a = h3.querySelector('a[href]') || h3.closest('a');
  if (!a) {
    let p = h3.parentElement;
    for (let i = 0; i < 5 && p; i++) {
      a = p.querySelector('a[href]');
      if (a) break;
      p = p.parentElement;
    }
  }
  if (!a) return { ok: false, reason: 'no_link', text: (h3.innerText || '').trim() };
  try { a.setAttribute('target', '_self'); } catch (e) {}
  a.click();
  return { ok: true, text: (h3.innerText || '').trim().slice(0, 120) };
}
"""

CHAT_CONTENT_JS = """
() => {
  const selectors = [
    '[class*="ChatMessage"]',
    '[class*="chat-message"]',
    '[class*="MessageBubble"]',
    '[class*="message-bubble"]',
    '[class*="MessageBody"]',
    '[class*="message-body"]',
    '[class*="MessageContent"]',
    '[data-test-id*="message"]',
    '[class*="Conversation"] [class*="Message"]',
    '[class*="ChatThread"]',
    '[class*="chat-thread"]',
  ];
  const texts = [];
  const hrefs = [];
  const seenEl = new Set();

  const collect = (root) => {
    if (!root || seenEl.has(root)) return;
    seenEl.add(root);
    const t = (root.innerText || '').trim();
    if (t) texts.push(t);
    for (const a of root.querySelectorAll('a[href]')) {
      if (a.href) hrefs.push(a.href);
    }
  };

  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) collect(el);
  }

  // Fallback: right-hand chat / conversation panel if nothing matched
  if (!texts.length) {
    const fallbacks = [
      '[class*="ChatPanel"]',
      '[class*="chat-panel"]',
      '[class*="ConversationPanel"]',
      '[class*="MessageList"]',
      'main',
    ];
    for (const sel of fallbacks) {
      const el = document.querySelector(sel);
      if (el) {
        collect(el);
        break;
      }
    }
  }

  return { text: texts.join('\\n'), hrefs };
}
"""


def _clean_url(url: str) -> str:
    return url.rstrip(".,;:!?）)」】\"]}'")


def _unwrap_google_href(href: str) -> str:
    """Resolve Google redirect (/url?q=...) to the real destination URL."""
    if "google." in href and "/url?" in href:
        qs = parse_qs(urlparse(href).query)
        if "q" in qs and qs["q"]:
            return unquote(qs["q"][0])
        if "url" in qs and qs["url"]:
            return unquote(qs["url"][0])
    return href


def normalize_zehitomo_profile_url(url: str) -> str:
    """Return cleaned zehitomo.com/profile/... URL, or "" if not a profile page."""
    if not url:
        return ""
    real = _clean_url(_unwrap_google_href(url))
    m = ZEHITOMO_PROFILE_RE.search(real)
    if m:
        # Decode %E9%BD%8A... so the saved URL shows Japanese characters.
        return unquote(_clean_url(m.group(0)))
    # Also accept final browser URL path even if regex is picky
    try:
        parsed = urlparse(real)
        host = (parsed.hostname or "").lower()
        if host.endswith("zehitomo.com") and "/profile/" in (parsed.path or ""):
            path = unquote(parsed.path)
            return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip()
    except Exception:
        pass
    return ""


def extract_other_website_urls(
    text: str,
    hrefs: list[str] | None = None,
) -> str:
    """Non-Zehitomo http(s) links from chat message text/anchors only."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        url = _clean_url(_unwrap_google_href(raw or ""))
        if not url.startswith("http"):
            return
        lower = url.lower()
        if "zehitomo.com" in lower:
            return
        if "google." in lower:
            return
        if url in seen:
            return
        seen.add(url)
        found.append(url)

    for href in hrefs or []:
        add(href)
    for match in URL_RE.finditer(text or ""):
        add(match.group(0))
    return ", ".join(found)


def parse_evaluate_result(raw: Any) -> Any:
    """browser-use Page.evaluate() always returns a string (JSON for objects)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


async def page_eval(page, js: str, *args: Any) -> Any:
    return parse_evaluate_result(await page.evaluate(js, *args))


async def page_goto(page, url: str, *, settle_s: float = 1.2) -> None:
    """Navigate with browser-use Page (no Playwright wait_for_load_state)."""
    await page.goto(url)
    await asyncio.sleep(settle_s)


async def current_url(browser_session, page=None) -> str:
    try:
        url = await browser_session.get_current_page_url()
        if url:
            return url
    except Exception:
        pass
    if page is not None:
        try:
            return await page.get_url()
        except Exception:
            pass
    return ""


class Contractor(BaseModel):
    contractor_name: str = Field(description="Name at top of chat box")
    location: str = Field(description="Location from details/map")
    phone_number: str = Field(default="", description="Phone or empty")
    email: str = Field(default="", description="Email or empty")
    url_to_access_to_contractor: str = Field(
        default="",
        description=(
            "Zehitomo public profile URL "
            "(https://www.zehitomo.com/profile/...) found by Google-searching "
            "contractor_name + ' ゼヒトモ', opening the top 1-2 result links, "
            "and verifying the final page URL"
        ),
    )
    other_contractor_website_url: str = Field(
        default="",
        description=(
            "Non-Zehitomo website/URL taken only from contractor chat "
            "messages (empty if none)"
        ),
    )


class ScrapingResult(BaseModel):
    postal_code: str
    service: str
    combination_id: str = ""
    contractors: list[Contractor]


def profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "profile"
    return PROFILES_ROOT / safe


def find_google_chrome() -> Path | None:
    """Same real Chrome binary used by login_profile.py (not Playwright Chromium)."""
    if sys.platform == "darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path(
                "/Applications/Google Chrome Canary.app/Contents/MacOS/"
                "Google Chrome Canary"
            ),
        ]
    elif sys.platform == "win32":
        local = Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe"
        candidates = [
            local,
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
    else:
        candidates = []
        for name in (
            "google-chrome",
            "google-chrome-stable",
            "chrome",
        ):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for path in candidates:
        if path.is_file():
            return path
    return None


def clear_stale_profile_locks(path: Path) -> list[str]:
    """
    Remove Singleton* leftovers from a crashed Chrome/Chromium launch.
    Safe when no process is using this user-data-dir.
    """
    removed: list[str] = []
    for name in PROFILE_LOCK_NAMES:
        lock = path / name
        if lock.exists() or lock.is_symlink():
            lock.unlink(missing_ok=True)
            removed.append(name)
    return removed


def load_options(path: Path = OPTIONS_FILE) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(
            f"options.json not found or empty: {path}\n"
            "Run: python combination_creation/zehitomo_combination.py"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        raise ValueError(f"No services in {path}")
    return data


def list_combinations(service_data: dict[str, Any]) -> list[tuple[str, dict]]:
    items: list[tuple[str, dict]] = []
    for key, value in service_data.items():
        if key.startswith("combination") and isinstance(value, dict):
            items.append((key, value))

    def sort_key(item: tuple[str, dict]) -> int:
        m = re.search(r"(\d+)$", item[0])
        return int(m.group(1)) if m else 0

    return sorted(items, key=sort_key)


def absolute_service_url(service_url: str) -> str:
    service_url = (service_url or "").strip()
    if service_url.startswith("http"):
        return service_url
    if not service_url.startswith("/"):
        service_url = "/" + service_url
    return BASE_URL + service_url


def answers_from_steps(steps: list[dict]) -> list[str]:
    """Selected values already live on each step; no separate answers list."""
    return [str(step.get("select", "")) for step in steps]


def format_steps_for_prompt(steps: list[dict]) -> str:
    lines: list[str] = []
    for i, step in enumerate(steps, start=1):
        label = step.get("label", "")
        select = step.get("select", "")
        if "郵便番号" in label or re.match(r"\d{3}-\d{4}", str(select)):
            lines.append(
                f"{i}. Postal / address step「{label}」:\n"
                f"   - Enter postal code `{select}`\n"
                f"   - Click 「プロを見る」"
            )
        else:
            lines.append(
                f"{i}. Question「{label}」:\n"
                f"   - Select exactly: 「{select}」\n"
                f"   - Then click 「次へ」 if that button is visible "
                f"(entry-button choices may advance automatically)."
            )
    return "\n".join(lines)


def build_tools() -> Tools:
    tools = Tools()

    @tools.action(
        "Wait for the user to manually complete login, then continue. "
        "ONLY call this when there is NO circular profile/avatar button "
        "in the TOP-RIGHT of the header. Seeing the word 「ログイン」 "
        "somewhere else on the page does NOT mean logged out.",
        param_model=NoParamsAction,
    )
    async def wait_for_manual_login(_: NoParamsAction) -> ActionResult:
        print(
            "\nNot logged in. Log in manually in the browser, then press ENTER here."
        )
        await asyncio.to_thread(input, "Press ENTER when login is complete: ")
        return ActionResult(extracted_content="Manual login completed.")

    @tools.action(
        "Wait 60 seconds for contractor list to load.",
        param_model=NoParamsAction,
    )
    async def wait_one_minute(_: NoParamsAction) -> ActionResult:
        print("Waiting 60 seconds...")
        await asyncio.sleep(60)
        return ActionResult(extracted_content="Finished waiting 60 seconds.")

    @tools.action(
        "If captcha appears or 「プロを見る」 does nothing, call this and stop. "
        "Pass reason describing what you saw."
    )
    async def report_captcha(reason: str = "") -> ActionResult:
        print(f"[CAPTCHA] {reason or 'blocked'}")
        return ActionResult(
            extracted_content="CAPTCHA_DETECTED. Stop now.",
            error="CAPTCHA_DETECTED",
        )

    @tools.action(
        "Extract phone, email, and any non-Zehitomo website URLs "
        "from the contractor CHAT MESSAGES only (not the whole page). "
        "Call this while the chat/details for that contractor are open. "
        "This action takes no arguments.",
        param_model=NoParamsAction,
    )
    async def extract_current_contractor(
        _: NoParamsAction,
        browser_session,
    ) -> ActionResult:
        page = await browser_session.get_current_page()
        chat = await page_eval(page, CHAT_CONTENT_JS)
        if not isinstance(chat, dict):
            chat = {}
        chat_text = chat.get("text") or ""
        chat_hrefs = chat.get("hrefs") or []

        # Phone/email: prefer chat text; fall back to body if chat empty
        scan_text = chat_text
        if not str(scan_text).strip():
            scan_text = await page_eval(
                page, "() => (document.body && document.body.innerText) || ''"
            )
            scan_text = scan_text if isinstance(scan_text, str) else str(scan_text or "")

        email_match = re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            scan_text,
        )
        phone_match = re.search(
            r"(?<!\d)(?:0\d{1,4}[-−]\d{1,4}[-−]\d{3,4}|0\d{9,10})(?!\d)",
            scan_text,
        )
        # Website URL: chat messages / chat anchors only (never whole page)
        other_url = extract_other_website_urls(str(chat_text), list(chat_hrefs))
        return ActionResult(
            extracted_content=json.dumps(
                {
                    "phone_number": (
                        phone_match.group(0).replace("−", "-")
                        if phone_match
                        else ""
                    ),
                    "email": email_match.group(0) if email_match else "",
                    "other_contractor_website_url": other_url,
                    "chat_text_preview": str(chat_text)[:3000],
                },
                ensure_ascii=False,
            )
        )

    @tools.action(
        "Google-search \"{contractor_name} ゼヒトモ\", click the first two "
        "result links, and return url_to_access_to_contractor if a page is "
        "https://www.zehitomo.com/profile/... "
        "Pass the exact contractor_name shown on Zehitomo. "
        "This tool returns to the Zehitomo request page when done — "
        "do NOT use go_back afterward."
    )
    async def find_url_to_access_to_contractor(
        contractor_name: str,
        browser_session,
    ) -> ActionResult:
        name = (contractor_name or "").strip()
        if not name:
            return ActionResult(
                extracted_content=json.dumps(
                    {
                        "contractor_name": "",
                        "url_to_access_to_contractor": "",
                        "reason": "empty contractor_name",
                    },
                    ensure_ascii=False,
                )
            )

        page = await browser_session.get_current_page()
        return_url = await current_url(browser_session, page)
        if "zehitomo.com" not in return_url.lower():
            return_url = return_url or START_URL

        query = f"{name} ゼヒトモ"
        search_url = (
            "https://www.google.com/search?hl=ja&q=" + quote_plus(query)
        )

        # 1) Google search
        print(f"[profile-url] search: {query!r}")
        await page_goto(page, search_url, settle_s=2.0)

        # 2) Click first two result titles; keep first zehitomo profile URL
        profile_url = ""
        opened: list[dict[str, str]] = []
        for i in range(2):
            await page_goto(page, search_url, settle_s=1.5)
            click = await page_eval(page, GOOGLE_CLICK_RESULT_JS, i)
            if not isinstance(click, dict) or not click.get("ok"):
                print(f"[profile-url] click #{i + 1} failed: {click}")
                opened.append(
                    {
                        "rank": str(i + 1),
                        "ok": "false",
                        "detail": str(click),
                    }
                )
                continue

            await asyncio.sleep(2.0)
            final_url = await current_url(browser_session, page)
            matched = normalize_zehitomo_profile_url(final_url)
            opened.append(
                {
                    "rank": str(i + 1),
                    "text": str(click.get("text") or ""),
                    "final": final_url,
                    "matched": matched,
                }
            )
            print(
                f"[profile-url] #{i + 1} text={click.get('text')!r} "
                f"final={final_url!r} matched={matched or '(no)'}"
            )
            if matched:
                profile_url = matched
                break

        # 3) Go back to Zehitomo contractor/request page
        try:
            await page_goto(page, return_url, settle_s=1.5)
        except Exception:
            try:
                await browser_session.navigate_to(return_url)
                await asyncio.sleep(1.5)
            except Exception:
                pass

        print(
            f"[profile-url] done query={query!r} → "
            f"{profile_url or '(none)'}"
        )
        return ActionResult(
            extracted_content=json.dumps(
                {
                    "contractor_name": name,
                    "search_query": query,
                    "opened_results": opened,
                    "url_to_access_to_contractor": profile_url,
                    "return_url": return_url,
                    "instruction": (
                        "Already back on Zehitomo request page. "
                        "Do NOT go_back. Continue with next contractor."
                    ),
                },
                ensure_ascii=False,
            )
        )

    return tools


def build_task(
    *,
    service_name: str,
    service_url: str,
    combination_id: str,
    combination: dict,
    index: int,
    total: int,
) -> str:
    postal_code = combination.get("postal_code", "")
    steps = combination.get("steps") or []
    answers = answers_from_steps(steps)
    steps_text = format_steps_for_prompt(steps)

    return f"""
You are scraping Zehitomo with a saved Chrome profile (already logged in earlier).
This is {combination_id} ({index}/{total}) for service 「{service_name}」.

You MUST follow the fixed questionnaire answers below. Do NOT pick random options.
Do NOT skip steps. Do NOT invent answers.

Exact answers list: {json.dumps(answers, ensure_ascii=False)}

LOGIN CHECK (important — do not get this wrong):
- LOGGED IN = a circular profile / avatar button is visible in the TOP-RIGHT
  corner of the site header.
- LOGGED OUT = that top-right profile circle is missing, and the header shows
  「ログイン」 / 「新規登録」 as header buttons instead.
- The word 「ログイン」 may still appear elsewhere on the page (footer, banners,
  marketing). IGNORE that. Only look at the TOP-RIGHT header.
- If the top-right profile circle is present: you ARE logged in.
  Do NOT call wait_for_manual_login.
- Only call wait_for_manual_login when the top-right profile circle is missing.

Flow:
1. Go to {START_URL}.
2. Check login using the TOP-RIGHT profile circle rule above.
3. Go directly to the service page:
   {service_url}
4. Open the request form if needed (CTA / 「プロを探す」 / similar button).
5. Complete the questionnaire EXACTLY in this order:
{steps_text}
6. If captcha appears or 「プロを見る」 does nothing: call report_captcha and STOP.
7. If 「前回の依頼を確認する」 and 「新しく依頼を出す」 appear,
   click 「前回の依頼を確認する」. Then call wait_one_minute.
8. For EVERY contractor in the left list:
   - click name → chat opens
   - click name at top of chat → details
   - get location; get phone/email from chat (empty string if missing)
   - call extract_current_contractor
     → use its phone_number, email, and other_contractor_website_url
       (other_contractor_website_url = ONLY links from chat messages,
        not sidebar/header/footer; "" if none)
   - call find_url_to_access_to_contractor with that contractor_name
     → searches Google for: `{{contractor_name}} ゼヒトモ`
     → clicks the first two Google result links and checks for
       zehitomo.com/profile/...
     → use its url_to_access_to_contractor ("" if none match)
     → tool already returns to the Zehitomo request page.
       Do NOT use go_back. Do NOT open the homepage.
       Continue with the NEXT contractor on the left list.
9. Return structured result with:
   - postal_code = `{postal_code}`
   - service = 「{service_name}」
   - combination_id = `{combination_id}`
   - contractors list, each with:
     contractor_name, location, phone_number, email,
     url_to_access_to_contractor, other_contractor_website_url
Do not invent data. Use "" when a field is missing.
"""


async def scrape_one(
    *,
    path: Path,
    service_name: str,
    service_url: str,
    combination_id: str,
    combination: dict,
    index: int,
    total: int,
) -> ScrapingResult:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("Set GOOGLE_API_KEY in .env")

    chrome = find_google_chrome()
    if chrome is None:
        raise FileNotFoundError(
            "Google Chrome not found. Profiles from login_profile.py require "
            "real Chrome (Playwright Chromium crashes on those profiles).\n"
            "Install Chrome: https://www.google.com/chrome/"
        )

    removed = clear_stale_profile_locks(path)
    if removed:
        print(f"Cleared stale profile locks: {', '.join(removed)}")

    # Must use real Google Chrome — login_profile.py wrote this user-data-dir
    # with Chrome. browser-use defaults to Playwright Chromium, which then
    # exits immediately → CDP ReadError / RemoteProtocolError.
    browser = Browser(
        executable_path=str(chrome),
        user_data_dir=str(path),
        headless=False,
        keep_alive=True,
        window_size={"width": 1440, "height": 900},
        ignore_default_args=[
            "--disable-window-activation",
            "--disable-focus-on-load",
        ],
        args=["--start-maximized"],
    )
    agent = Agent(
        task=build_task(
            service_name=service_name,
            service_url=service_url,
            combination_id=combination_id,
            combination=combination,
            index=index,
            total=total,
        ),
        llm=ChatGoogle(model=MODEL, api_key=api_key, temperature=0),
        browser=browser,
        tools=build_tools(),
        output_model_schema=ScrapingResult,
        max_actions_per_step=5,
        use_vision=True,
    )

    try:
        history = await agent.run(max_steps=MAX_STEPS)
        result = history.structured_output
        if result is None:
            final = history.final_result()
            if not final:
                raise RuntimeError("No result (captcha or page not reached)")
            if "CAPTCHA" in str(final).upper():
                raise RuntimeError("CAPTCHA_DETECTED")
            result = ScrapingResult.model_validate_json(final)
        if not result.combination_id:
            result.combination_id = combination_id
        return result
    finally:
        await browser.kill()


def write_output(
    output: Path,
    *,
    profile: str,
    service_name: str,
    service_url: str,
    options_path: Path,
    combinations_done: dict[str, Any],
) -> None:
    output.write_text(
        json.dumps(
            {
                "profile": profile,
                "service": service_name,
                "service_url": service_url,
                "options_file": str(options_path),
                "combinations_done": combinations_done,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


async def run(
    *,
    profile: str,
    service_name: str,
    combination_keys: list[str] | None,
    limit: int | None,
    options_path: Path,
    output: Path,
) -> None:
    path = profile_path(profile)
    if not path.exists():
        raise FileNotFoundError(
            f"Profile '{profile}' not found at {path}.\n"
            f"Create it first: python login_profile.py {profile}"
        )

    options = load_options(options_path)
    if service_name not in options:
        available = ", ".join(sorted(options.keys()))
        raise KeyError(
            f"Service '{service_name}' not in options.json.\n"
            f"Available: {available}"
        )

    service_data = options[service_name]
    service_url = absolute_service_url(service_data.get("service_url", ""))
    all_combos = list_combinations(service_data)
    if not all_combos:
        raise ValueError(f"No combinations under service '{service_name}'")

    if combination_keys:
        wanted = set(combination_keys)
        selected = [(k, v) for k, v in all_combos if k in wanted]
        missing = wanted - {k for k, _ in selected}
        if missing:
            raise KeyError(
                f"Unknown combination keys for '{service_name}': "
                f"{', '.join(sorted(missing))}"
            )
    else:
        selected = all_combos

    if limit is not None:
        selected = selected[: max(0, limit)]

    if not selected:
        raise ValueError("No combinations selected to scrape.")

    chrome = find_google_chrome()
    print(f"Profile     : {profile} ({path.resolve()})")
    print(f"Chrome      : {chrome.resolve() if chrome else '(missing!)'}")
    print(f"Options     : {options_path.resolve()}")
    print(f"Service     : {service_name}")
    print(f"Service URL : {service_url}")
    print(f"Combinations: {[k for k, _ in selected]}")
    print(f"Output      : {output.resolve()}")
    print("Quit Chrome using this profile before starting (Cmd+Q).")
    print("Ctrl+C to stop early.\n")

    combinations_done: dict[str, Any] = {}
    total = len(selected)

    for index, (combo_id, combo) in enumerate(selected, start=1):
        print("=" * 60)
        print(f"{combo_id} ({index}/{total})")
        print(f"answers: {answers_from_steps(combo.get('steps') or [])}")
        print("=" * 60)

        try:
            result = await scrape_one(
                path=path,
                service_name=service_name,
                service_url=service_url,
                combination_id=combo_id,
                combination=combo,
                index=index,
                total=total,
            )
        except Exception as e:
            print(f"{combo_id} failed: {type(e).__name__}: {e}")
            if "CAPTCHA" in str(e).upper():
                print(
                    "Captcha hit. Stop this profile and switch account:\n"
                    f"  python login_profile.py other_name\n"
                    f"  python run_scrape_options.py other_name "
                    f"--service {service_name}"
                )
                break
            print(f"Skipping to next combination in {PAUSE_BETWEEN}s...")
            await asyncio.sleep(PAUSE_BETWEEN)
            continue

        data = result.model_dump(mode="json", exclude_none=True)
        # Full combination from options.json, plus the contractors found for it.
        # `runs` is not written: it repeated this same combination and contractor list.
        combinations_done[combo_id] = {
            "steps": combo.get("steps") or [],
            "postal_code": combo.get("postal_code", data.get("postal_code", "")),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "extracted_contractors": data["contractors"],
        }
        write_output(
            output,
            profile=profile,
            service_name=service_name,
            service_url=service_url,
            options_path=options_path,
            combinations_done=combinations_done,
        )
        print(
            f"Saved {combo_id}: "
            f"{len(data['contractors'])} contractors"
        )

        if index < total:
            print(f"Next combination in {PAUSE_BETWEEN}s...\n")
            await asyncio.sleep(PAUSE_BETWEEN)

    contractor_count = sum(
        len(item.get("extracted_contractors") or [])
        for item in combinations_done.values()
    )
    print(
        f"\nDone. {len(combinations_done)}/{total} combinations, "
        f"{contractor_count} contractors → {output.resolve()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Scrape Zehitomo using fixed combinations from options.json."
        )
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
        default="output.json",
        help="Output JSON file",
    )
    args = parser.parse_args()

    asyncio.run(
        run(
            profile=args.profile,
            service_name=args.service,
            combination_keys=args.combinations,
            limit=args.limit,
            options_path=Path(args.options),
            output=Path(args.output),
        )
    )


if __name__ == "__main__":
    main()
