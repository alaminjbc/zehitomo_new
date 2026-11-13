"""Track Chrome-profile captcha cooldowns in scripts/profile_status.json."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import DEFAULT_PROFILE_COOLDOWN_DAYS, PROFILE_STATUS_FILE


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _empty_status() -> dict[str, Any]:
    return {
        "cooldown_days": DEFAULT_PROFILE_COOLDOWN_DAYS,
        "profiles": {},
    }


def load_status(path: Path = PROFILE_STATUS_FILE) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return _empty_status()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_status()
    if not isinstance(data, dict):
        return _empty_status()

    cooldown_days = data.get("cooldown_days", DEFAULT_PROFILE_COOLDOWN_DAYS)
    try:
        cooldown_days = int(cooldown_days)
    except (TypeError, ValueError):
        cooldown_days = DEFAULT_PROFILE_COOLDOWN_DAYS
    if cooldown_days < 1:
        cooldown_days = DEFAULT_PROFILE_COOLDOWN_DAYS

    profiles = data.get("profiles")
    if not isinstance(profiles, dict):
        profiles = {}

    return {
        "cooldown_days": cooldown_days,
        "profiles": profiles,
    }


def save_status(data: dict[str, Any], path: Path = PROFILE_STATUS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "cooldown_days": int(
            data.get("cooldown_days") or DEFAULT_PROFILE_COOLDOWN_DAYS
        ),
        "profiles": data.get("profiles") if isinstance(data.get("profiles"), dict) else {},
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _profile_entry(data: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = data.setdefault("profiles", {})
    entry = profiles.get(profile)
    if not isinstance(entry, dict):
        entry = {}
        profiles[profile] = entry
    return entry


def _lazy_reactivate(entry: dict[str, Any], *, now: datetime | None = None) -> bool:
    """If cooldown expired, flip status to active. Returns True if eligible."""
    now = now or _now()
    status = str(entry.get("status") or "active").strip().lower()
    if status != "cooldown":
        return True

    eligible_after = _parse_iso(entry.get("eligible_after"))
    if eligible_after is None or now >= eligible_after:
        entry["status"] = "active"
        entry.pop("eligible_after", None)
        return True
    return False


def is_eligible(profile: str, *, path: Path = PROFILE_STATUS_FILE) -> bool:
    return profile in list_eligible([profile], path=path)


def list_eligible(
    profiles: list[str],
    *,
    path: Path = PROFILE_STATUS_FILE,
) -> list[str]:
    data = load_status(path)
    changed = False
    eligible: list[str] = []
    now = _now()
    for name in profiles:
        name = (name or "").strip()
        if not name:
            continue
        entry = data.get("profiles", {}).get(name)
        if not isinstance(entry, dict):
            eligible.append(name)
            continue
        before = str(entry.get("status") or "").lower()
        if _lazy_reactivate(entry, now=now):
            eligible.append(name)
            if before == "cooldown" and str(entry.get("status") or "").lower() == "active":
                changed = True
    if changed:
        save_status(data, path)
    return eligible


def mark_captcha(
    profile: str,
    *,
    service: str = "",
    combination_id: str = "",
    path: Path = PROFILE_STATUS_FILE,
) -> dict[str, Any]:
    """Put profile on cooldown until now + cooldown_days."""
    profile = (profile or "").strip()
    if not profile:
        raise ValueError("profile name is required")

    data = load_status(path)
    days = int(data.get("cooldown_days") or DEFAULT_PROFILE_COOLDOWN_DAYS)
    now = _now()
    eligible_after = now + timedelta(days=days)
    entry = _profile_entry(data, profile)
    entry["status"] = "cooldown"
    entry["last_captcha_at"] = now.isoformat()
    entry["eligible_after"] = eligible_after.isoformat()
    if service:
        entry["last_service"] = service
    if combination_id:
        entry["last_combination"] = combination_id
    save_status(data, path)
    print(
        f"[profile-status] {profile} → cooldown until "
        f"{eligible_after.isoformat()} ({days} day(s))"
    )
    return entry


def mark_success(
    profile: str,
    *,
    path: Path = PROFILE_STATUS_FILE,
) -> dict[str, Any]:
    """Mark profile active after a successful combination scrape."""
    profile = (profile or "").strip()
    if not profile:
        raise ValueError("profile name is required")

    data = load_status(path)
    entry = _profile_entry(data, profile)
    entry["status"] = "active"
    entry["last_success_at"] = _now().isoformat()
    entry.pop("eligible_after", None)
    save_status(data, path)
    return entry


def cooldown_summary(
    profiles: list[str],
    *,
    path: Path = PROFILE_STATUS_FILE,
) -> str:
    """Human-readable lines about which profiles are on cooldown."""
    data = load_status(path)
    now = _now()
    lines: list[str] = []
    for name in profiles:
        name = (name or "").strip()
        if not name:
            continue
        entry = data.get("profiles", {}).get(name)
        if not isinstance(entry, dict):
            lines.append(f"  {name}: active (no status entry)")
            continue
        if _lazy_reactivate(entry, now=now):
            lines.append(f"  {name}: active")
            continue
        eligible_after = entry.get("eligible_after") or "?"
        lines.append(f"  {name}: cooldown until {eligible_after}")
    save_status(data, path)
    return "\n".join(lines)
