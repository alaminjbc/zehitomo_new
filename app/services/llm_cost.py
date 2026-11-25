"""Measure actual Gemini LLM cost for one scrape combination run.

browser-use tracks token usage when Agent(..., calculate_cost=True).
If the library has no price for our model name, we fall back to rates from
env / defaults (same ballpark as ceo_full_cost_estimate.md).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


def _rate_per_million(env_key: str, default: float) -> float:
    raw = os.getenv(env_key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# USD per 1M tokens — override via .env if Google changes list price.
INPUT_USD_PER_1M = _rate_per_million("GEMINI_INPUT_USD_PER_1M", 0.75)
OUTPUT_USD_PER_1M = _rate_per_million("GEMINI_OUTPUT_USD_PER_1M", 3.75)


@dataclass
class RunLlmCost:
    model: str
    steps: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    llm_calls: int
    cost_usd: float
    cost_source: str  # "browser_use" | "estimate_rates"

    @property
    def cost_per_step_usd(self) -> float | None:
        if self.steps <= 0:
            return None
        return self.cost_usd / self.steps


def estimate_cost_usd(*, prompt_tokens: int, completion_tokens: int) -> float:
    """Apply configured $/1M rates to measured token counts."""
    return (
        prompt_tokens * INPUT_USD_PER_1M / 1_000_000
        + completion_tokens * OUTPUT_USD_PER_1M / 1_000_000
    )


def _usage_numbers(usage: Any) -> tuple[int, int, int, int, float]:
    """Extract token totals and library cost from history.usage / UsageSummary."""
    prompt = int(getattr(usage, "total_prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "total_completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
    calls = int(getattr(usage, "entry_count", 0) or 0)
    cost = float(getattr(usage, "total_cost", 0) or 0)
    return prompt, completion, total, calls, cost


def summarize_run_cost(
    history: Any,
    *,
    model: str,
) -> RunLlmCost | None:
    """Build a RunLlmCost from one Agent.run() history, or None if no usage."""
    usage = getattr(history, "usage", None)
    if usage is None:
        return None

    prompt, completion, total, calls, lib_cost = _usage_numbers(usage)
    if prompt == 0 and completion == 0 and total == 0:
        return None

    try:
        steps = int(history.number_of_steps())
    except Exception:
        steps = 0

    if lib_cost > 0:
        cost_usd = lib_cost
        source = "browser_use"
    else:
        cost_usd = estimate_cost_usd(
            prompt_tokens=prompt,
            completion_tokens=completion,
        )
        source = "estimate_rates"

    return RunLlmCost(
        model=model,
        steps=steps,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        llm_calls=calls,
        cost_usd=round(cost_usd, 6),
        cost_source=source,
    )


def format_run_cost(cost: RunLlmCost) -> str:
    per_step = cost.cost_per_step_usd
    per_step_s = f"${per_step:.4f}/step" if per_step is not None else "n/a"
    return (
        f"LLM cost: ${cost.cost_usd:.4f} "
        f"({cost.steps} steps, {cost.total_tokens:,} tokens, "
        f"{cost.llm_calls} calls, {per_step_s}, source={cost.cost_source})"
    )


def run_cost_dict(cost: RunLlmCost | None) -> dict[str, Any] | None:
    if cost is None:
        return None
    data = asdict(cost)
    per_step = cost.cost_per_step_usd
    data["cost_per_step_usd"] = (
        round(per_step, 6) if per_step is not None else None
    )
    return data
