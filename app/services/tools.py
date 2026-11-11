from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import quote_plus

from browser_use import ActionResult, Tools
from browser_use.tools.views import NoParamsAction

from app.config import START_URL
from app.services.browser import (
    CHAT_CONTENT_JS,
    GOOGLE_DISMISS_CONSENT_JS,
    GOOGLE_TOP_RESULTS_JS,
    current_url,
    page_eval,
    page_goto,
)
from app.services.urls import (
    extract_other_website_urls,
    normalize_zehitomo_profile_url,
    unwrap_google_href,
)


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

        scan_text = chat_text
        if not str(scan_text).strip():
            scan_text = await page_eval(
                page, "() => (document.body && document.body.innerText) || ''"
            )
            scan_text = (
                scan_text if isinstance(scan_text, str) else str(scan_text or "")
            )

        email_match = re.search(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            scan_text,
        )
        phone_match = re.search(
            r"(?<!\d)(?:0\d{1,4}[-−]\d{1,4}[-−]\d{3,4}|0\d{9,10})(?!\d)",
            scan_text,
        )
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
        "Google-search \"{contractor_name} ゼヒトモ\", open the first two "
        "organic result links, and return url_to_access_to_contractor if a "
        "page is https://www.zehitomo.com/profile/... "
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
        search_url = "https://www.google.com/search?hl=ja&gl=jp&q=" + quote_plus(
            query
        )

        print(f"[profile-url] search: {query!r}")
        await page_goto(page, search_url, settle_s=2.5)
        consent = await page_eval(page, GOOGLE_DISMISS_CONSENT_JS)
        if isinstance(consent, dict) and consent.get("clicked"):
            print(f"[profile-url] dismissed Google consent: {consent}")
            await asyncio.sleep(1.5)

        serp = await page_eval(page, GOOGLE_TOP_RESULTS_JS)
        results: list[dict] = []
        serp_profiles: list[dict] = []
        if isinstance(serp, dict):
            raw = serp.get("results") or []
            if isinstance(raw, list):
                results = [r for r in raw if isinstance(r, dict)]
            raw_profiles = serp.get("profiles") or []
            if isinstance(raw_profiles, list):
                serp_profiles = [r for r in raw_profiles if isinstance(r, dict)]
            print(
                f"[profile-url] SERP count={serp.get('count')} "
                f"profiles_on_serp={len(serp_profiles)} "
                f"titles={[r.get('title') for r in results[:2]]}"
            )
        else:
            print(f"[profile-url] SERP parse failed: {serp!r}")

        profile_url = ""
        opened: list[dict[str, str]] = []

        # Prefer a zehitomo profile link already visible on the SERP
        # (e.g. クリーンデイ → /profile/三田村-様/pro).
        for i, result in enumerate(serp_profiles[:3], start=1):
            title = str(result.get("title") or "")
            href = unwrap_google_href(str(result.get("href") or "").strip())
            matched = normalize_zehitomo_profile_url(href)
            if not matched:
                continue
            opened.append(
                {
                    "rank": str(i),
                    "title": title,
                    "href": href,
                    "final": href,
                    "matched": matched,
                    "how": "serp_profile_link",
                }
            )
            print(
                f"[profile-url] SERP profile link #{i}: {matched}"
            )
            profile_url = matched
            break

        # Otherwise open the first two organic results and verify the URL.
        if not profile_url:
            for i, result in enumerate(results[:2], start=1):
                title = str(result.get("title") or "")
                href = unwrap_google_href(str(result.get("href") or "").strip())
                matched = normalize_zehitomo_profile_url(href)
                if matched:
                    opened.append(
                        {
                            "rank": str(i),
                            "title": title,
                            "href": href,
                            "final": href,
                            "matched": matched,
                            "how": "serp_href",
                        }
                    )
                    print(
                        f"[profile-url] #{i} SERP href already profile: {matched}"
                    )
                    profile_url = matched
                    break

                if not href.startswith("http"):
                    opened.append(
                        {
                            "rank": str(i),
                            "title": title,
                            "ok": "false",
                            "reason": "bad_href",
                            "href": href,
                        }
                    )
                    continue

                print(f"[profile-url] #{i} open title={title!r} href={href!r}")
                try:
                    await page_goto(page, href, settle_s=2.5)
                except Exception as e:
                    opened.append(
                        {
                            "rank": str(i),
                            "title": title,
                            "href": href,
                            "ok": "false",
                            "reason": f"goto_failed:{type(e).__name__}",
                        }
                    )
                    print(f"[profile-url] #{i} goto failed: {e}")
                    await page_goto(page, search_url, settle_s=1.5)
                    continue

                final_url = await current_url(browser_session, page)
                matched = normalize_zehitomo_profile_url(final_url)
                opened.append(
                    {
                        "rank": str(i),
                        "title": title,
                        "href": href,
                        "final": final_url,
                        "matched": matched,
                        "how": "opened",
                    }
                )
                print(
                    f"[profile-url] #{i} final={final_url!r} "
                    f"matched={matched or '(no)'}"
                )
                if matched:
                    profile_url = matched
                    break

                # Back to SERP before trying the next result.
                await page_goto(page, search_url, settle_s=1.5)

        try:
            await page_goto(page, return_url, settle_s=1.5)
        except Exception:
            try:
                await browser_session.navigate_to(return_url)
                await asyncio.sleep(1.5)
            except Exception:
                pass

        print(f"[profile-url] done query={query!r} → {profile_url or '(none)'}")
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
