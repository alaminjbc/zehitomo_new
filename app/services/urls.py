from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

URL_RE = re.compile(r"https?://[^\s<>\"'）)」】\]}]+", re.IGNORECASE)
# Do NOT use \\s here — Japanese profile slugs can contain ideographic
# spaces (\\u3000), and \\s would truncate the URL early.
ZEHITOMO_PROFILE_RE = re.compile(
    r"https?://(?:www\.)?zehitomo\.com/profile/[^<>\"'）)」】\]?#]*",
    re.IGNORECASE,
)


def clean_url(url: str) -> str:
    return url.rstrip(".,;:!?）)」】\"]}'")


def unwrap_google_href(href: str) -> str:
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
    real = clean_url(unwrap_google_href(url))
    match = ZEHITOMO_PROFILE_RE.search(real)
    if match:
        # Decode %E9%BD%8A... so the saved URL shows Japanese characters.
        return unquote(clean_url(match.group(0)))
    try:
        parsed = urlparse(real)
        host = (parsed.hostname or "").lower()
        if host.endswith("zehitomo.com") and "/profile/" in (parsed.path or ""):
            path = unquote(parsed.path)
            return f"{parsed.scheme}://{parsed.netloc}{path}".rstrip()
    except Exception:
        pass
    return ""


def canonicalize_zehitomo_profile_url(url: str) -> str:
    """
    Prefer the base profile URL ending at /pro.

    Example:
      .../profile/foo/pro/ventilator-cleaner → .../profile/foo/pro
    """
    normalized = normalize_zehitomo_profile_url(url)
    if not normalized:
        return ""
    try:
        parsed = urlparse(normalized)
        path = unquote(parsed.path or "")
        # /profile/<id>/pro[/service...]
        m = re.search(r"(/profile/[^/]+/pro)(?:/|$)", path, flags=re.IGNORECASE)
        if m:
            base_path = m.group(1)
            return f"{parsed.scheme}://{parsed.netloc}{base_path}"
        # /profile/<id> only
        m2 = re.search(r"(/profile/[^/]+)(?:/|$)", path, flags=re.IGNORECASE)
        if m2:
            return f"{parsed.scheme}://{parsed.netloc}{m2.group(1)}/pro"
    except Exception:
        pass
    return normalized


def extract_other_website_urls(
    text: str,
    hrefs: list[str] | None = None,
) -> str:
    """Non-Zehitomo http(s) links from chat message text/anchors only."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        url = clean_url(unwrap_google_href(raw or ""))
        if not url.startswith("http"):
            return
        lower = url.lower()
        if "zehitomo.com" in lower or "google." in lower or url in seen:
            return
        seen.add(url)
        found.append(url)

    for href in hrefs or []:
        add(href)
    for match in URL_RE.finditer(text or ""):
        add(match.group(0))
    return ", ".join(found)
