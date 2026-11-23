"""
Standalone test for Google → Zehitomo profile URL lookup.

Mirrors the manual check:
  search "{name} ゼヒトモ" → wait ~4.5s → read SERP → optionally open top links.

Uses helpers from app.services.browser (GOOGLE_TOP_RESULTS_JS + pick_*).

Usage (from repo root, Chrome quit for that profile):
    # names that previously failed in the scraper
    python scripts/test_google_profile_url.py --profile azimon \\
        --name 本田 --name CTKサポート --name 久保

    # names from zehitomo_main.csv (skip header/meta rows)
    python scripts/test_google_profile_url.py --profile azimon --from-csv --limit 8

    # expected URL check
    python scripts/test_google_profile_url.py --profile azimon \\
        --name 本田 --expect 'https://www.zehitomo.com/profile/本田-宙治-SUF24XMs7/pro'
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.browser import (  # noqa: E402
    GOOGLE_BETWEEN_NAMES_S,
    GOOGLE_BETWEEN_QUERIES_S,
    GOOGLE_DISMISS_CONSENT_JS,
    GOOGLE_SERP_SETTLE_S,
    GOOGLE_TOP_RESULTS_JS,
    clear_stale_profile_locks,
    find_google_chrome,
    google_profile_search_queries,
    google_search_url,
    is_google_blocked,
    pick_zehitomo_profile_from_serp,
    profile_path,
    trim_profile_logged,
)
from app.services.urls import (  # noqa: E402
    canonicalize_zehitomo_profile_url,
    normalize_zehitomo_profile_url,
)


DEFAULT_FAILING_NAMES = [
    "本田",
    "CTKサポート",
    "久保",
    "クリーンパートナー",
    "合同会社OFFICESK",
    "キャメルフィッシュ",
]

EXPECTED = {
    "本田": "https://www.zehitomo.com/profile/本田-宙治-SUF24XMs7/pro",
    "CTKサポート": "https://www.zehitomo.com/profile/ctkサポート-EZz0G2eR0/pro",
    "久保": "https://www.zehitomo.com/profile/久保-貴幸-a85viQatA/pro",
    "クリーンパートナー": "https://www.zehitomo.com/profile/井上-慎也/pro",
    "合同会社OFFICESK": "https://www.zehitomo.com/profile/合同会社officesk-npaSZkhdY/pro",
    "キャメルフィッシュ": "https://www.zehitomo.com/profile/キャメルフィッシュ-u9NseQQEl/pro",
}


def load_csv_names(path: Path, *, limit: int = 0) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for i, row in enumerate(reader):
            if i < 3:  # JP header, EN header, 必須 row
                continue
            if len(row) < 2:
                continue
            name = (row[1] or "").strip()
            if not name or name in seen:
                continue
            # skip junk rows
            if name in {"必須：「さん」はカット", "company_or_contractor_name"}:
                continue
            seen.add(name)
            names.append(name)
            if limit and len(names) >= limit:
                break
    return names


def _is_noise_serp_title(title: str) -> bool:
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


def resolve_profile_from_serp_and_opens(page, name: str, serp: dict) -> dict:
    """Match manual flow: prefer SERP profile link, else open top organics."""
    from app.services.browser import name_matches_text

    picked = pick_zehitomo_profile_from_serp(serp, name)
    # Only accept SERP pick when the name actually matches (avoid wrong pros).
    if picked.get("url") and name_matches_text(
        name, picked.get("title") or "", picked.get("url") or ""
    ):
        return picked

    from app.services.browser import score_serp_candidate

    opened: list[dict] = []
    results = [r for r in (serp.get("results") or []) if isinstance(r, dict)]
    ranked: list[tuple[int, int, dict]] = []
    for idx, row in enumerate(results):
        title = str(row.get("title") or "")
        href = str(row.get("href") or "")
        if _is_noise_serp_title(title):
            continue
        ranked.append((score_serp_candidate(name, title, href), idx, row))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    bare = name.replace("さん", "").strip()
    limit = 6 if len(bare) <= 3 else 4

    for rank_i, (score, _idx, row) in enumerate(ranked[:limit], start=1):
        href = str(row.get("href") or "").strip()
        title = str(row.get("title") or "")
        if not (href.startswith("http") or href.startswith("/url") or href.startswith("/goto")):
            continue
        print(f"    open #{rank_i} (score={score}): {title!r} → {href[:90]}")
        try:
            clicked = False
            try:
                loc = page.locator(f'a[href="{href}"]').first
                if loc.count():
                    loc.click(timeout=5000)
                    clicked = True
            except Exception:
                clicked = False
            if not clicked:
                page.goto(href, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2.5)
        except Exception as e:
            opened.append({"rank": rank_i, "ok": False, "error": str(e)})
            continue
        final = page.url
        matched = canonicalize_zehitomo_profile_url(
            normalize_zehitomo_profile_url(final)
        )
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
            f"    final=#{rank_i}: {final!r} matched={matched or '(no)'} "
            f"name_ok={name_ok}"
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
        if "google." not in final.lower():
            try:
                page.go_back(wait_until="domcontentloaded", timeout=15000)
                time.sleep(1.5)
            except Exception:
                pass

    return {
        "url": "",
        "how": "",
        "title": "",
        "href": "",
        "opened": opened,
        "serp_ok": bool(serp.get("serp_ok")),
        "blocked": bool(serp.get("blocked")),
    }


class GoogleBlockedError(RuntimeError):
    """Raised when Google shows /sorry or captcha — stop the whole batch."""


def _save_debug(page, name: str, suffix: str = "") -> None:
    safe = "".join(ch if ch.isalnum() else "_" for ch in name)[:40]
    out_dir = ROOT / "scripts" / "google_serp_debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{safe}{suffix}"
    try:
        page.screenshot(path=str(out_dir / f"{tag}.png"), full_page=True)
        (out_dir / f"{tag}.html").write_text(page.content(), encoding="utf-8")
        print(f"  saved debug → {out_dir / tag}.png / .html")
    except Exception as e:
        print(f"  debug save failed: {e}")


def _dismiss_consent(page) -> None:
    try:
        consent = page.evaluate(GOOGLE_DISMISS_CONSENT_JS)
        if isinstance(consent, dict) and consent.get("clicked"):
            print(f"  consent dismissed: {consent}")
            time.sleep(1.5)
    except Exception:
        pass


def _read_serp(page) -> dict:
    serp = page.evaluate(GOOGLE_TOP_RESULTS_JS)
    return serp if isinstance(serp, dict) else {}


def _wait_for_user_captcha(page, *, prompt: str) -> None:
    print()
    print("!" * 60)
    print(prompt)
    print("Solve the captcha in the Chrome window, then press Enter here.")
    print("!" * 60)
    try:
        input()
    except EOFError:
        time.sleep(30)
    time.sleep(1.0)
    # If still blocked after user action, leave page as-is for caller to re-check.


def google_search_like_human(page, query: str, *, wait_captcha: bool) -> dict:
    """
    Manual-style search: open google.co.jp → type query → Enter → wait 4.5s.
    Falls back to direct /search URL only if the search box is missing.
    """
    print(f"  query: {query!r}")
    page.goto("https://www.google.co.jp/", wait_until="domcontentloaded", timeout=60000)
    time.sleep(1.2)
    _dismiss_consent(page)

    if is_google_blocked(url=page.url):
        _save_debug(page, query[:20], "_sorry")
        if wait_captcha:
            _wait_for_user_captcha(
                page,
                prompt="Google /sorry on homepage — solve captcha, then continue.",
            )
            page.goto("https://www.google.co.jp/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(1.2)
        if is_google_blocked(url=page.url):
            raise GoogleBlockedError(page.url)

    typed = False
    for selector in (
        'textarea[name="q"]',
        'input[name="q"]',
        'textarea[aria-label*="検索"]',
        'input[aria-label*="検索"]',
    ):
        try:
            box = page.locator(selector).first
            if not box.count():
                continue
            box.click(timeout=4000)
            time.sleep(0.3)
            # Clear any leftover text, then type like a person.
            page.keyboard.press("Meta+a")
            page.keyboard.press("Backspace")
            box.type(query, delay=45)
            time.sleep(0.4)
            page.keyboard.press("Enter")
            typed = True
            break
        except Exception:
            continue

    if not typed:
        print("  (search box missing — falling back to direct URL)")
        page.goto(
            google_search_url(query, basic_html=False),
            wait_until="domcontentloaded",
            timeout=60000,
        )

    time.sleep(1.0)
    _dismiss_consent(page)
    print(f"  waiting {GOOGLE_SERP_SETTLE_S}s for SERP…")
    time.sleep(GOOGLE_SERP_SETTLE_S)

    serp = _read_serp(page)
    if is_google_blocked(serp, page.url):
        _save_debug(page, query[:20], "_sorry")
        if wait_captcha:
            _wait_for_user_captcha(
                page,
                prompt="Google captcha on SERP — solve it, wait for results, then Enter.",
            )
            time.sleep(GOOGLE_SERP_SETTLE_S)
            serp = _read_serp(page)
        if is_google_blocked(serp, page.url):
            raise GoogleBlockedError(str(serp.get("url") or page.url))
    return serp


def lookup_one(page, name: str, *, wait_captcha: bool = False) -> dict:
    """Try query fallbacks until a profile URL is found."""
    last: dict = {"url": "", "queries": []}
    for qi, query in enumerate(google_profile_search_queries(name)):
        if qi > 0:
            print(f"  pause {GOOGLE_BETWEEN_QUERIES_S}s before next query…")
            time.sleep(GOOGLE_BETWEEN_QUERIES_S)

        serp = google_search_like_human(page, query, wait_captcha=wait_captcha)
        print(
            f"  SERP count={serp.get('count')} profiles={len(serp.get('profiles') or [])} "
            f"serp_ok={serp.get('serp_ok')} blocked={serp.get('blocked')} "
            f"title={serp.get('title')!r}"
        )

        if not serp.get("serp_ok"):
            print(f"  page url: {serp.get('url')}")
            print(f"  preview : {str(serp.get('preview') or '')[:200]!r}")
            _save_debug(page, name)

        for i, p in enumerate((serp.get("profiles") or [])[:3], start=1):
            print(
                f"    profile#{i}: {p.get('title')!r} → "
                f"{str(p.get('unwrapped') or p.get('href'))[:90]}"
            )
        for i, r in enumerate((serp.get("results") or [])[:3], start=1):
            print(f"    organic#{i}: {r.get('title')!r} → {str(r.get('href'))[:90]}")

        found = resolve_profile_from_serp_and_opens(page, name, serp)
        last = {
            **found,
            "query": query,
            "queries": (last.get("queries") or []) + [query],
            "serp": {
                "count": serp.get("count"),
                "profiles": len(serp.get("profiles") or []),
                "serp_ok": serp.get("serp_ok"),
                "blocked": serp.get("blocked"),
            },
        }
        if found.get("url"):
            return last
    return last


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Test Google → Zehitomo profile URL lookup")
    p.add_argument(
        "--profile",
        default="azimon",
        help="Chrome user-data profile under profiles/ (default: azimon)",
    )
    p.add_argument(
        "--name",
        action="append",
        dest="names",
        default=None,
        help="Contractor name to search (repeatable)",
    )
    p.add_argument(
        "--from-csv",
        action="store_true",
        help="Load unique names from zehitomo_main.csv",
    )
    p.add_argument(
        "--csv",
        type=Path,
        default=ROOT / "zehitomo_main.csv",
        help="CSV path for --from-csv",
    )
    p.add_argument("--limit", type=int, default=0, help="Max names when using --from-csv")
    p.add_argument(
        "--expect",
        default="",
        help="Optional expected URL when testing a single --name",
    )
    p.add_argument(
        "--failing-defaults",
        action="store_true",
        help="Use the known failing names from the boss check",
    )
    p.add_argument(
        "--wait-captcha",
        action="store_true",
        help="If Google /sorry appears, pause so you can solve it in Chrome, then continue",
    )
    p.add_argument(
        "--pause-between",
        type=float,
        default=GOOGLE_BETWEEN_NAMES_S,
        help=f"Seconds between names (default {GOOGLE_BETWEEN_NAMES_S})",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    names = list(args.names or [])
    if args.from_csv:
        names.extend(load_csv_names(args.csv, limit=args.limit))
    if args.failing_defaults or not names:
        names = list(dict.fromkeys([*names, *DEFAULT_FAILING_NAMES]))

    names = list(dict.fromkeys(n.strip() for n in names if n and n.strip()))
    if not names:
        raise SystemExit("No names to test.")

    chrome = find_google_chrome()
    path = profile_path(args.profile)
    path.mkdir(parents=True, exist_ok=True)
    clear_stale_profile_locks(path)
    try:
        trim_profile_logged(path)
    except Exception:
        pass

    print(f"Chrome  : {chrome}")
    print(f"Profile : {args.profile} ({path})")
    print(f"Names   : {len(names)}")
    print(f"Mode    : human-type search, pause {args.pause_between}s between names")
    if args.wait_captcha:
        print("Captcha : will pause for you to solve in Chrome")
    print("Quit Chrome for this profile before starting (Cmd+Q).\n")
    print(
        "NOTE: if this profile just hit Zehitomo/Google captcha, use another "
        "profile (tasnia/mustakim) or wait before retrying azimon.\n"
    )

    from playwright.sync_api import sync_playwright

    ok = 0
    rows: list[tuple[str, str, str]] = []
    stopped_by_captcha = False

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(path),
            channel="chrome",
            headless=False,
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args=["--enable-automation"],
            executable_path=str(chrome) if chrome else None,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # Warm up on Google homepage (less bot-like than jumping straight to /search).
        try:
            page.goto("https://www.google.co.jp/", wait_until="domcontentloaded", timeout=60000)
            time.sleep(2.0)
            if is_google_blocked(url=page.url):
                _save_debug(page, "warmup", "_sorry")
                if args.wait_captcha:
                    _wait_for_user_captcha(
                        page,
                        prompt="Google already blocked this profile on warmup.",
                    )
                if is_google_blocked(url=page.url):
                    raise GoogleBlockedError(page.url)
        except GoogleBlockedError as e:
            print(f"\nGoogle captcha/blocked — aborting whole run.\n  {e}")
            print(
                "Fix: solve captcha once with --wait-captcha, or switch profile:\n"
                "  python scripts/test_google_profile_url.py --profile tasnia "
                "--failing-defaults --wait-captcha"
            )
            context.close()
            raise SystemExit(2)

        for index, name in enumerate(names, start=1):
            if index > 1 and args.pause_between > 0:
                print(f"\n… pausing {args.pause_between}s between names …\n")
                time.sleep(args.pause_between)

            print("=" * 60)
            print(f"[{index}/{len(names)}] {name}")
            try:
                result = lookup_one(page, name, wait_captcha=args.wait_captcha)
            except GoogleBlockedError as e:
                print(f"  Google bot-check /sorry — aborting remaining names.")
                print(f"  page url: {e}")
                rows.append((name, "", "CAPTCHA"))
                stopped_by_captcha = True
                break
            except Exception as e:
                print(f"  ERROR {type(e).__name__}: {e}")
                rows.append((name, "", f"ERROR:{type(e).__name__}"))
                continue

            got = result.get("url") or ""
            expect = ""
            if args.expect and len(names) == 1:
                expect = canonicalize_zehitomo_profile_url(args.expect)
            elif name in EXPECTED:
                expect = EXPECTED[name]

            status = "FOUND" if got else "MISS"
            if expect:
                status = "OK" if got == expect else ("WRONG" if got else "MISS")
            if status in {"OK", "FOUND"}:
                ok += 1

            print(f"  → {status}: {got or '(none)'}  how={result.get('how')!r}")
            if expect and got != expect:
                print(f"  expected: {expect}")
            rows.append((name, got, status))

        context.close()

    print()
    print("=" * 60)
    print(f"Summary: {ok}/{len(rows)} with a profile URL")
    for name, got, status in rows:
        print(f"  [{status}] {name}: {got or '(none)'}")
    if stopped_by_captcha:
        print(
            "\nStopped early because of Google captcha. Do NOT keep retrying the "
            "same hot profile — wait, or use --wait-captcha / another profile."
        )
        raise SystemExit(2)


if __name__ == "__main__":
    main()
