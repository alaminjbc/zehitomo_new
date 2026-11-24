from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config import BASE_URL, OPTIONS_FILE


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
        match = re.search(r"(\d+)$", item[0])
        return int(match.group(1)) if match else 0

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


def _is_postal_select(select: str, label: str = "") -> bool:
    """Postal step: NNN-NNNN select, or legacy label containing 郵便番号."""
    if re.match(r"^\d{3}-\d{4}$", str(select).strip()):
        return True
    return "郵便番号" in str(label or "")


def format_steps_for_prompt(steps: list[dict]) -> str:
    """
    Label-free questionnaire instructions for the agent.

    Only step index + select values (and postal CTA). Question text is omitted
    so the same answer list can be reused across services that share options.
    """
    total = len(steps)
    lines = [
        f"There are {total} questionnaire steps. "
        "Do NOT use question labels — match each answer to the option "
        "visible on screen, in this exact order:",
    ]
    for i, step in enumerate(steps, start=1):
        label = str(step.get("label") or "")
        select = str(step.get("select") or "")
        if _is_postal_select(select, label):
            lines.append(
                f"{i}. Postal / address step:\n"
                f"   - Enter postal code `{select}`\n"
                f"   - Click 「プロを見る」"
            )
        else:
            lines.append(
                f"{i}. Select exactly: 「{select}」\n"
                f"   - Then click 「次へ」 if that button is visible "
                f"(entry-button choices may advance automatically)."
            )
    return "\n".join(lines)
