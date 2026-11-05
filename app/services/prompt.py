from __future__ import annotations

import json

from app.config import START_URL
from app.services.options import answers_from_steps, format_steps_for_prompt


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
