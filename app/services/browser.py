from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from app.config import PROFILE_LOCK_NAMES, PROFILES_ROOT

# Organic Google results + any zehitomo profile links visible on the SERP.
# Tuned for current Google SERP DOM (h3 / div.g / /url?q= / cite lines).
GOOGLE_TOP_RESULTS_JS = """
() => {
  const root =
    document.querySelector('#search') ||
    document.querySelector('#rso') ||
    document.querySelector('#center_col') ||
    document.body;

  const pageText = ((document.body && document.body.innerText) || '').slice(0, 2000);
  const blocked =
    /unusual traffic|自動送信|captcha|detected unusual|当社のシステム|ロボットではない|通常と異なるトラフィック|google\\.com\\/sorry/i.test(
      pageText + ' ' + (location.href || '')
    );
  const hasSearchRoot = !!(
    document.querySelector('#search') ||
    document.querySelector('#rso') ||
    document.querySelector('#center_col')
  );

  const unwrap = (href) => {
    try {
      const u = new URL(href);
      if (u.hostname.includes('google.') && u.pathname.includes('/url')) {
        return u.searchParams.get('q') || u.searchParams.get('url') || href;
      }
    } catch (e) {}
    return href;
  };

  const skipHref = (href) => {
    const lower = (href || '').toLowerCase();
    if (!href) return true;
    // Relative Google redirects are OK (resolved via <a>.href in the browser).
    if (!(href.startsWith('http') || href.startsWith('/url') || href.startsWith('/goto'))) {
      return true;
    }
    if (lower.includes('accounts.google')) return true;
    if (lower.includes('support.google')) return true;
    if (lower.includes('policies.google')) return true;
    if (lower.includes('webcache.googleusercontent')) return true;
    // Keep Google redirect wrappers:
    //   /url?q=https://zehitomo.com/...   (classic)
    //   /goto?url=CAES...                 (new opaque redirect — must OPEN to resolve)
    // Drop other google.* chrome links (settings, maps appstore, etc.).
    if (lower.includes('google.')) {
      const isRedirect =
        lower.includes('/url?') ||
        lower.includes('/goto?') ||
        lower.includes('zehitomo.com');
      if (!isRedirect) return true;
    }
    return false;
  };

  const looksZehitomoProfile = (href) => {
    const real = (unwrap(href) || '').toLowerCase();
    return real.includes('zehitomo.com/profile/');
  };

  const results = [];
  const seen = new Set();

  const pushResult = (title, href) => {
    const cleanHref = (href || '').trim();
    if (skipHref(cleanHref) || seen.has(cleanHref)) return;
    seen.add(cleanHref);
    results.push({
      title: (title || '').trim().slice(0, 160),
      href: cleanHref,
      unwrapped: unwrap(cleanHref),
    });
  };

  // 1) Classic organic: h3 title + nearby anchor.
  for (const h3 of root.querySelectorAll('h3')) {
    if (results.length >= 10) break;
    let a = h3.closest('a[href]') || h3.querySelector('a[href]');
    if (!a) {
      let p = h3.parentElement;
      for (let i = 0; i < 8 && p && !a; i++) {
        a = p.querySelector('a[href]');
        if (a) break;
        p = p.parentElement;
      }
    }
    if (!a) continue;
    pushResult(h3.innerText || '', a.href || '');
  }

  // 2) Modern cards: div.g / data-sokoban-container.
  for (const card of root.querySelectorAll('div.g, div[data-sokoban-container]')) {
    if (results.length >= 10) break;
    const h3 = card.querySelector('h3');
    const a =
      (h3 && (h3.closest('a[href]') || h3.querySelector('a[href]'))) ||
      card.querySelector('a[href]');
    if (!a) continue;
    pushResult((h3 && h3.innerText) || a.innerText || '', a.href || '');
  }

  // 3) Fallback: any non-google http link under #search (automation-safe scrape).
  if (results.length === 0) {
    for (const a of root.querySelectorAll('a[href]')) {
      if (results.length >= 10) break;
      const href = (a.href || '').trim();
      if (skipHref(href)) continue;
      const title = (a.innerText || a.textContent || '').trim();
      if (!title) continue;
      pushResult(title.slice(0, 160), href);
    }
  }

  // Direct profile links anywhere on the SERP (blue link / cite / redirect).
  const profiles = [];
  const seenProfile = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = (a.href || '').trim();
    if (!href || !looksZehitomoProfile(href)) continue;
    const key = unwrap(href);
    if (seenProfile.has(key)) continue;
    seenProfile.add(key);
    let title = (a.innerText || a.textContent || '').trim();
    if (!title) {
      const h3 = a.querySelector('h3') || (a.closest('div') || a).querySelector('h3');
      title = (h3 && h3.innerText) || '';
    }
    profiles.push({
      title: title.slice(0, 160),
      href: href,
      unwrapped: key,
    });
    if (profiles.length >= 10) break;
  }

  // Also promote organic rows that already unwrap to a profile URL.
  for (const r of results) {
    if (!looksZehitomoProfile(r.href) && !looksZehitomoProfile(r.unwrapped || '')) {
      continue;
    }
    const key = r.unwrapped || r.href;
    if (seenProfile.has(key)) continue;
    seenProfile.add(key);
    profiles.push({
      title: r.title || '',
      href: r.href,
      unwrapped: key,
    });
  }

  return {
    count: results.length,
    results: results,
    profiles: profiles,
    url: location.href,
    title: document.title || '',
    serp_ok: hasSearchRoot && !blocked && (results.length > 0 || profiles.length > 0),
    blocked: blocked,
    has_search_root: hasSearchRoot,
    preview: pageText.slice(0, 240),
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


def linux_chrome_args() -> list[str]:
    """
    Extra Chrome flags needed on Linux / Docker. Empty on macOS / Windows.

    --password-store=basic: encrypt cookies with Chrome's built-in key instead
      of the desktop keyring (GNOME/KWallet). login_profile.py and the scraper
      must agree, otherwise the scraper cannot decrypt the login cookies and
      Zehitomo shows you as logged out. Docker has no keyring at all.
    --no-sandbox: Chrome refuses to start as root (the Docker container user)
      unless the sandbox is disabled.
    """
    if not sys.platform.startswith("linux"):
        return []
    args = ["--password-store=basic"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.append("--no-sandbox")
    return args


def clear_stale_profile_locks(path: Path) -> list[str]:
    """Remove Singleton* leftovers from a crashed Chrome launch."""
    removed: list[str] = []
    for name in PROFILE_LOCK_NAMES:
        lock = path / name
        if lock.exists() or lock.is_symlink():
            lock.unlink(missing_ok=True)
            removed.append(name)
    return removed


# Regenerable Chrome junk only. Never include Cookies / Login Data /
# Preferences / Local Storage / Session Storage / IndexedDB.
_TRIM_RELATIVE_PATHS = (
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnWebGPUCache",
    "Default/DawnGraphiteCache",
    "Default/Service Worker",
    "Default/History",
    "Default/History-journal",
    "Default/Sessions",
    "Default/Sessions_Encrypted",
    "GraphiteDawnCache",
    "GPUPersistentCache",
    "ShaderCache",
    "GrShaderCache",
    "optimization_guide_model_store",
    "component_crx_cache",
    "extensions_crx_cache",
    "WasmTtsEngine",
    "Safe Browsing",
    "OnDeviceHeadSuggestModel",
    "BrowserMetrics",
    "DeferredBrowserMetrics",
    "CertificateRevocation",
    "ZxcvbnData",
    "ActorSafetyLists",
    "OptimizationHints",
    "Subresource Filter",
    "PKIMetadata",
    "Crowd Deny",
    "SafetyTips",
    "MEIPreload",
    "FileTypePolicies",
    "FirstPartySetsPreloaded",
    "PrivacySandboxAttestationsPreloaded",
    "AmountExtractionHeuristicRegexes",
    "CaptchaProviders",
    "OptimizationGuideModelsManifest",
    "segmentation_platform",
    "OriginTrials",
    "SSLErrorAssistant",
)


def _path_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file() or path.is_symlink():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def trim_profile(path: Path) -> dict[str, int | list[str]]:
    """
    Delete regenerable Chrome caches under a user-data-dir.
    Keeps login session files. Chrome must be fully quit first.
    """
    path = Path(path)
    before = _path_size(path)
    removed: list[str] = []
    freed = 0

    if not path.is_dir():
        return {"before": before, "after": before, "freed": 0, "removed": removed}

    for rel in _TRIM_RELATIVE_PATHS:
        target = path / rel
        if not target.exists() and not target.is_symlink():
            continue
        size = _path_size(target)
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target, ignore_errors=False)
            else:
                target.unlink(missing_ok=True)
            removed.append(rel)
            freed += size
        except OSError as e:
            print(f"[trim] skip {rel}: {e}")

    after = _path_size(path)
    return {
        "before": before,
        "after": after,
        "freed": max(freed, before - after),
        "removed": removed,
    }


def format_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{n}B"


def trim_profile_logged(path: Path) -> dict[str, int | list[str]]:
    """Trim and print a short before/after summary."""
    result = trim_profile(path)
    removed = result.get("removed") or []
    print(
        f"[trim] {path.name}: "
        f"{format_bytes(int(result['before']))} → "
        f"{format_bytes(int(result['after']))} "
        f"(freed {format_bytes(int(result['freed']))}, "
        f"{len(removed)} paths)"
    )
    return result


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


def strip_san_for_search(name: str) -> str:
    """Drop trailing 「さん」 for Google query variants only."""
    text = (name or "").strip()
    if text.endswith("さん"):
        return text[:-2].strip()
    return text


def google_profile_search_queries(contractor_name: str) -> list[str]:
    """
    Queries to try for Zehitomo profile lookup (same style as manual search).

    First query keeps the display name (including さん if present).
    Short/generic names get extra quoted / プロフィール variants.
    """
    name = (contractor_name or "").strip()
    if not name:
        return []
    bare = strip_san_for_search(name)
    queries = [f"{name} ゼヒトモ"]
    if bare and bare != name:
        queries.append(f"{bare} ゼヒトモ")
    if bare:
        queries.append(f'"{bare}" ゼヒトモ')
    # Short names (本田 / 久保 / 山本) are noisy on Google — tighten further.
    if bare and len(bare) <= 3:
        queries.extend(
            [
                f"{bare} ゼヒトモ プロフィール",
                f'"{bare}" site:zehitomo.com/profile',
            ]
        )
    elif bare:
        queries.append(f"{bare} site:zehitomo.com/profile")
    # de-dupe, keep order
    out: list[str] = []
    seen: set[str] = set()
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def google_search_url(
    query: str,
    *,
    host: str = "www.google.co.jp",
    basic_html: bool = True,
) -> str:
    """
    Build a Google search URL.

    ``basic_html=True`` adds ``gbv=1`` so Google returns the classic HTML SERP
    with real ``/url?q=https://...`` links. The new AI SERP often uses opaque
    ``/goto?url=CAES...`` redirects that hide zehitomo.com until clicked.
    """
    from urllib.parse import quote_plus

    host = (host or "www.google.co.jp").strip() or "www.google.co.jp"
    url = f"https://{host}/search?hl=ja&gl=jp&q=" + quote_plus(query)
    if basic_html:
        url += "&gbv=1"
    return url


def _name_tokens_for_match(name: str) -> list[str]:
    bare = strip_san_for_search(name)
    # Split on spaces / middle dots; keep tokens with length >= 2.
    parts = re.split(r"[\s　・/|/]+", bare)
    return [p for p in parts if len(p) >= 2]


def name_matches_text(name: str, *texts: str) -> bool:
    """
    True if the contractor name matches title/URL text.

    Short JP names (本田 / 久保) must not match longer names like 大久保 —
    prefer `/profile/{name}-...` slug or a title boundary match.
    """
    bare = strip_san_for_search(name)
    if not bare:
        return False

    # Strongest signal: zehitomo profile path slug.
    for text in texts:
        lower = (text or "")
        if "/profile/" not in lower:
            continue
        try:
            from urllib.parse import unquote, urlparse

            path = unquote(urlparse(lower).path or "")
        except Exception:
            path = lower
        # /profile/本田-宙治-xxx/pro  or  /profile/ctkサポート-xxx/pro
        slug = path.split("/profile/", 1)[-1].split("/pro", 1)[0]
        slug_norm = slug.replace("　", "").replace(" ", "").lower()
        bare_norm = bare.replace("　", "").replace(" ", "").lower()
        if slug_norm == bare_norm or slug_norm.startswith(bare_norm + "-"):
            return True
        # Reject short-name substring hits inside a longer slug (久保 ⊂ 大久保建築).
        if len(bare_norm) <= 3 and bare_norm in slug_norm and not slug_norm.startswith(
            bare_norm
        ):
            return False

    blob = " ".join(t or "" for t in texts)
    if not blob:
        return False

    if len(bare) <= 3:
        # Title like "本田 義人 | 滋賀県..." or "CTKサポート | 北海道..."
        return (
            re.search(
                rf"(^|[\s　]){re.escape(bare)}([\s　|\-:]|$)",
                blob,
            )
            is not None
        )

    tokens = _name_tokens_for_match(name)
    return any(tok in blob for tok in tokens)


def score_serp_candidate(name: str, title: str, href: str = "") -> int:
    """Higher = open sooner. Used to rank organic rows before clicking."""
    title = title or ""
    href = href or ""
    score = 0
    bare = strip_san_for_search(name)
    if bare and bare in title:
        score += 20
    if name_matches_text(name, title, href):
        score += 30
    if "ゼヒトモ" in title or "zehitomo" in title.lower():
        score += 8
    if "|" in title:  # typical Zehitomo card: "Name | 都道府県"
        score += 6
    if "profile" in href.lower() or "zehitomo.com" in href.lower():
        score += 10
    if "AI モード" in title or "Zehitomo Lab" in title or "ゼヒトモラボ" in title:
        score -= 50
    if "求人" in title or "採用" in title:
        score -= 20
    return score


def pick_zehitomo_profile_from_serp(
    serp: dict[str, Any] | None,
    contractor_name: str,
) -> dict[str, Any]:
    """
    Choose the best zehitomo.com/profile URL from a GOOGLE_TOP_RESULTS_JS payload.

    Preference:
      1) SERP profile links whose title matches the name
      2) Any SERP profile link
      3) Organic results that unwrap to a profile URL (name match first)
    """
    from app.services.urls import (
        canonicalize_zehitomo_profile_url,
        normalize_zehitomo_profile_url,
    )

    empty = {
        "url": "",
        "how": "",
        "title": "",
        "href": "",
        "serp_ok": False,
        "blocked": False,
    }
    if not isinstance(serp, dict):
        return empty

    empty["serp_ok"] = bool(serp.get("serp_ok"))
    empty["blocked"] = bool(serp.get("blocked"))

    profiles = [p for p in (serp.get("profiles") or []) if isinstance(p, dict)]
    results = [r for r in (serp.get("results") or []) if isinstance(r, dict)]

    def try_rows(rows: list[dict], how: str, *, require_name: bool) -> dict[str, Any] | None:
        for row in rows:
            title = str(row.get("title") or "")
            href = str(row.get("href") or row.get("unwrapped") or "")
            if require_name and not name_matches_text(contractor_name, title, href):
                continue
            matched = canonicalize_zehitomo_profile_url(
                normalize_zehitomo_profile_url(href)
            )
            if matched:
                return {
                    "url": matched,
                    "how": how,
                    "title": title,
                    "href": href,
                    "serp_ok": empty["serp_ok"],
                    "blocked": empty["blocked"],
                }
        return None

    for require_name, suffix in ((True, "_name_match"), (False, "")):
        hit = try_rows(profiles, f"serp_profile{suffix}", require_name=require_name)
        if hit:
            return hit
        # Organic rows that already point at /profile/
        organic_profiles = [
            r
            for r in results
            if "zehitomo.com/profile" in str(r.get("unwrapped") or r.get("href") or "").lower()
        ]
        hit = try_rows(
            organic_profiles,
            f"serp_organic_profile{suffix}",
            require_name=require_name,
        )
        if hit:
            return hit

    return empty


# Manual-style settle time after loading a Google SERP (user: wait 4–5s).
GOOGLE_SERP_SETTLE_S = 4.5
# Pause between contractor names when batch-testing (reduces /sorry).
GOOGLE_BETWEEN_NAMES_S = 12.0
# Pause between query fallbacks for the same name.
GOOGLE_BETWEEN_QUERIES_S = 8.0
# Written into url_to_access_to_contractor when Google /sorry blocks search.
GOOGLE_CAPTCHA_BLOCKED_MSG = (
    "google search is not possible due to captcha from this account"
)


def is_google_blocked(serp: dict[str, Any] | None = None, url: str = "") -> bool:
    """True when Google shows the unusual-traffic /sorry / captcha page."""
    if isinstance(serp, dict):
        if serp.get("blocked"):
            return True
        url = str(serp.get("url") or url or "")
    lower = (url or "").lower()
    return "google.com/sorry" in lower or "/sorry/" in lower


def is_noise_serp_title(title: str) -> bool:
    """Skip AI boxes / images / lab / job ads when ranking organics to open."""
    t = (title or "").strip()
    if not t:
        return True
    if t in {"すべての画像", "画像", "Videos", "Images", "よくある質問"}:
        return True
    if "AI モードの回答" in t:
        return True
    if "Zehitomo Lab" in t or "ゼヒトモラボ" in t:
        return True
    if "求人" in t or "中途採用" in t:
        return True
    return False


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


async def _dismiss_google_consent(page) -> None:
    try:
        consent = await page_eval(page, GOOGLE_DISMISS_CONSENT_JS)
        if isinstance(consent, dict) and consent.get("clicked"):
            print(f"[profile-url] dismissed Google consent: {consent}")
            await asyncio.sleep(1.5)
    except Exception:
        pass


async def google_search_like_human(page, query: str) -> dict[str, Any]:
    """
    Manual-style Google search (same flow as the standalone tester):
      open google.co.jp → type query in the box → Enter → wait ~4.5s → parse SERP.

    Falls back to a direct /search URL if the search box is missing.
    Returns the GOOGLE_TOP_RESULTS_JS payload (may have blocked=True).
    """
    print(f"[profile-url] search: {query!r}")
    await page_goto(page, "https://www.google.co.jp/", settle_s=1.2)
    await _dismiss_google_consent(page)

    page_url = ""
    try:
        page_url = await page.get_url()
    except Exception:
        pass
    if is_google_blocked(url=page_url):
        print(f"[profile-url] Google /sorry on homepage: {page_url}")
        return {
            "count": 0,
            "results": [],
            "profiles": [],
            "url": page_url,
            "serp_ok": False,
            "blocked": True,
        }

    typed = False
    for selector in (
        'textarea[name="q"]',
        'input[name="q"]',
        'textarea[aria-label*="検索"]',
        'input[aria-label*="検索"]',
    ):
        try:
            els = await page.get_elements_by_css_selector(selector)
            if not els:
                continue
            box = els[0]
            await box.click()
            await asyncio.sleep(0.25)
            await box.fill(query, clear=True)
            await asyncio.sleep(0.35)
            await page.press("Enter")
            typed = True
            break
        except Exception:
            continue

    if not typed:
        print("[profile-url] search box missing — falling back to direct URL")
        await page_goto(
            page,
            google_search_url(query, basic_html=False),
            settle_s=1.0,
        )

    await _dismiss_google_consent(page)
    print(f"[profile-url] waiting {GOOGLE_SERP_SETTLE_S}s for SERP…")
    await asyncio.sleep(GOOGLE_SERP_SETTLE_S)

    serp = await page_eval(page, GOOGLE_TOP_RESULTS_JS)
    if not isinstance(serp, dict):
        serp = {}
    try:
        serp.setdefault("url", await page.get_url())
    except Exception:
        pass
    return serp


async def _open_ranked_serp_results(
    page,
    browser_session,
    name: str,
    serp: dict[str, Any],
    *,
    search_url_fallback: str = "",
) -> dict[str, Any]:
    """
    Prefer a name-matched SERP profile link; else open top ranked organics
    (manual: open first 1–2 links) and accept a matching /profile URL.
    """
    from app.services.urls import canonicalize_zehitomo_profile_url

    picked = pick_zehitomo_profile_from_serp(serp, name)
    if picked.get("url") and name_matches_text(
        name, picked.get("title") or "", picked.get("url") or ""
    ):
        return {**picked, "opened": []}

    results = [r for r in (serp.get("results") or []) if isinstance(r, dict)]
    ranked: list[tuple[int, int, dict]] = []
    for idx, row in enumerate(results):
        title = str(row.get("title") or "")
        href = str(row.get("href") or "")
        if is_noise_serp_title(title):
            continue
        ranked.append((score_serp_candidate(name, title, href), idx, row))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    bare = strip_san_for_search(name)
    limit = 4 if len(bare) <= 3 else 2
    opened: list[dict[str, Any]] = []

    for rank_i, (score, _idx, row) in enumerate(ranked[:limit], start=1):
        href = str(row.get("href") or "").strip()
        title = str(row.get("title") or "")
        if not (
            href.startswith("http")
            or href.startswith("/url")
            or href.startswith("/goto")
        ):
            continue
        print(f"[profile-url] open #{rank_i} (score={score}): {title!r}")
        try:
            await page_goto(page, href, settle_s=2.5)
        except Exception as e:
            opened.append(
                {
                    "rank": rank_i,
                    "title": title,
                    "href": href,
                    "ok": False,
                    "reason": f"goto_failed:{type(e).__name__}",
                }
            )
            if search_url_fallback:
                try:
                    await page_goto(page, search_url_fallback, settle_s=1.5)
                except Exception:
                    pass
            continue

        final = await current_url(browser_session, page)
        matched = canonicalize_zehitomo_profile_url(final)
        name_ok = bool(matched) and name_matches_text(name, title, matched, final)
        opened.append(
            {
                "rank": rank_i,
                "title": title,
                "href": href,
                "final": final,
                "matched": matched,
                "name_ok": name_ok,
            }
        )
        print(
            f"[profile-url] #{rank_i} final={final!r} "
            f"matched={matched or '(no)'} name_ok={name_ok}"
        )
        if matched and name_ok:
            return {
                "url": matched,
                "how": f"opened_organic_{rank_i}",
                "title": title,
                "href": href,
                "opened": opened,
                "serp_ok": bool(serp.get("serp_ok")),
                "blocked": bool(serp.get("blocked")),
            }
        # Back to SERP for next try.
        try:
            await page.go_back()
            await asyncio.sleep(1.5)
        except Exception:
            if search_url_fallback:
                try:
                    await page_goto(page, search_url_fallback, settle_s=1.5)
                except Exception:
                    pass

    # Last resort: any SERP profile URL even without strict name match
    # (better than empty for unique company names that still failed match).
    if picked.get("url"):
        return {**picked, "opened": opened, "how": picked.get("how") or "serp_profile"}

    return {
        "url": "",
        "how": "",
        "title": "",
        "href": "",
        "opened": opened,
        "serp_ok": bool(serp.get("serp_ok")),
        "blocked": bool(serp.get("blocked")),
    }


async def lookup_zehitomo_profile_url(
    page,
    browser_session,
    contractor_name: str,
    *,
    max_queries: int = 2,
) -> dict[str, Any]:
    """
    Find a zehitomo.com/profile URL for ``contractor_name`` via Google.

    Uses the same human-like search + name/slug matching that the standalone
    tester validated. Stops early on Google /sorry (does not raise — caller
    keeps scraping Zehitomo; profile URL is just left empty).
    """
    name = (contractor_name or "").strip()
    empty = {
        "url": "",
        "how": "",
        "query": "",
        "queries": [],
        "opened": [],
        "blocked": False,
        "serp_ok": False,
    }
    if not name:
        return empty

    queries = google_profile_search_queries(name)[: max(1, max_queries)]
    last = dict(empty)

    for qi, query in enumerate(queries):
        if qi > 0:
            print(
                f"[profile-url] pause {GOOGLE_BETWEEN_QUERIES_S}s before next query…"
            )
            await asyncio.sleep(GOOGLE_BETWEEN_QUERIES_S)

        serp = await google_search_like_human(page, query)
        print(
            f"[profile-url] SERP count={serp.get('count')} "
            f"profiles={len(serp.get('profiles') or [])} "
            f"serp_ok={serp.get('serp_ok')} blocked={serp.get('blocked')}"
        )

        if is_google_blocked(serp):
            print(
                f"[profile-url] Google bot-check /sorry — skip remaining queries. "
                f"url={serp.get('url')}"
            )
            last = {
                **empty,
                "blocked": True,
                "query": query,
                "queries": (last.get("queries") or []) + [query],
                "serp_ok": False,
            }
            return last

        found = await _open_ranked_serp_results(
            page,
            browser_session,
            name,
            serp,
            search_url_fallback=google_search_url(query, basic_html=False),
        )
        last = {
            **found,
            "query": query,
            "queries": (last.get("queries") or []) + [query],
        }
        if found.get("url"):
            return last

    return last
