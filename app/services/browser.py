from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from app.config import PROFILE_LOCK_NAMES, PROFILES_ROOT

# Organic Google results + any zehitomo profile links visible on the SERP.
GOOGLE_TOP_RESULTS_JS = """
() => {
  const root =
    document.querySelector('#search') ||
    document.querySelector('#rso') ||
    document.querySelector('#center_col') ||
    document.body;

  const skipHref = (href) => {
    const lower = (href || '').toLowerCase();
    if (!href || !href.startsWith('http')) return true;
    if (lower.includes('accounts.google')) return true;
    if (lower.includes('support.google')) return true;
    if (lower.includes('google.') && !lower.includes('/url?') && !lower.includes('zehitomo.com')) {
      return true;
    }
    return false;
  };

  const results = [];
  const seen = new Set();

  // Classic organic: h3 title with a nearby / parent / child anchor.
  for (const h3 of root.querySelectorAll('h3')) {
    let a = h3.closest('a[href]') || h3.querySelector('a[href]');
    if (!a) {
      let p = h3.parentElement;
      for (let i = 0; i < 6 && p && !a; i++) {
        a = p.querySelector('a[href]');
        if (a) break;
        p = p.parentElement;
      }
    }
    if (!a) continue;
    const href = (a.href || '').trim();
    if (skipHref(href) || seen.has(href)) continue;
    seen.add(href);
    results.push({
      title: (h3.innerText || '').trim().slice(0, 160),
      href: href,
    });
    if (results.length >= 5) break;
  }

  // Direct profile links on the SERP (cite / blue link / redirect).
  const profiles = [];
  const seenProfile = new Set();
  for (const a of root.querySelectorAll('a[href]')) {
    const href = (a.href || '').trim();
    if (!href) continue;
    const lower = href.toLowerCase();
    const looksProfile =
      lower.includes('zehitomo.com/profile/') ||
      (lower.includes('google.') && lower.includes('/url?') && lower.includes('zehitomo.com'));
    if (!looksProfile) continue;
    if (seenProfile.has(href)) continue;
    seenProfile.add(href);
    profiles.push({
      title: (a.innerText || a.textContent || '').trim().slice(0, 160),
      href: href,
    });
    if (profiles.length >= 5) break;
  }

  return {
    count: results.length,
    results: results,
    profiles: profiles,
    url: location.href,
  };
}
"""

GOOGLE_DISMISS_CONSENT_JS = """
() => {
  const texts = ['同意する', 'すべて承認', 'I agree', 'Accept all', 'Accept'];
  const buttons = Array.from(document.querySelectorAll('button, input[type="submit"]'));
  for (const text of texts) {
    const btn = buttons.find((el) => (el.innerText || el.value || '').includes(text));
    if (btn) {
      btn.click();
      return { clicked: true, text: text };
    }
  }
  return { clicked: false };
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


def profile_path(name: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", name).strip("_") or "profile"
    return PROFILES_ROOT / safe


def find_google_chrome() -> Path | None:
    """Real Google Chrome, not Playwright Chromium."""
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
        for name in ("google-chrome", "google-chrome-stable", "chrome"):
            found = shutil.which(name)
            if found:
                candidates.append(Path(found))

    for path in candidates:
        if path.is_file():
            return path
    return None


def clear_stale_profile_locks(path: Path) -> list[str]:
    """Remove Singleton* leftovers from a crashed Chrome launch."""
    removed: list[str] = []
    for name in PROFILE_LOCK_NAMES:
        lock = path / name
        if lock.exists() or lock.is_symlink():
            lock.unlink(missing_ok=True)
            removed.append(name)
    return removed


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
