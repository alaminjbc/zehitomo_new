from __future__ import annotations

import asyncio
import json
import re

from browser_use import ActionResult, Tools
from browser_use.tools.views import NoParamsAction

from app.config import START_URL
from app.services.browser import (
    CHAT_CONTENT_JS,
    GOOGLE_CAPTCHA_BLOCKED_MSG,
    current_url,
    lookup_zehitomo_profile_url,
    page_eval,
    page_goto,
)
from app.services.urls import (
    extract_other_website_urls,
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

        result = await lookup_zehitomo_profile_url(
            page, browser_session, name, max_queries=2
        )
        profile_url = result.get("url") or ""
        if result.get("blocked") and not profile_url:
            profile_url = GOOGLE_CAPTCHA_BLOCKED_MSG
        query = result.get("query") or f"{name} ゼヒトモ"

        try:
            await page_goto(page, return_url, settle_s=1.5)
        except Exception:
            try:
                await browser_session.navigate_to(return_url)
                await asyncio.sleep(1.5)
            except Exception:
                pass

        print(
            f"[profile-url] done query={query!r} → {profile_url or '(none)'} "
            f"how={result.get('how')!r} blocked={result.get('blocked')}"
        )
        return ActionResult(
            extracted_content=json.dumps(
                {
                    "contractor_name": name,
                    "search_query": query,
                    "queries_tried": result.get("queries") or [],
                    "how": result.get("how") or "",
                    "opened_results": result.get("opened") or [],
                    "google_blocked": bool(result.get("blocked")),
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
