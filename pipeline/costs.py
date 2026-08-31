"""Cost accounting with hard ceilings.

Rates are list prices as of Aug 2026 and WILL drift. Verify against your own
invoices monthly; `python -m pipeline.cli costs` prints what the pipeline
thinks it is spending so you can reconcile.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import EPISODES

RATES = {
    # Claude, per million tokens (Opus-class scripting run).
    "claude_input_per_mtok": 5.00,
    "claude_output_per_mtok": 25.00,
    # Replicate FLUX.
    "flux_schnell_per_image": 0.003,
    "flux_dev_per_image": 0.025,
}


def month_chars(prefix: str) -> int:
    """Characters sent to TTS this calendar month, across all episodes."""
    total = 0
    for p in EPISODES.glob("ep*/manifest.json"):
        try:
            with open(p) as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not data.get("created_at", "").startswith(prefix):
            continue
        if data.get("dry_run"):
            continue
        total += data.get("narration_chars", 0)
    return total


def voice_spend(chars: int, plan: dict) -> tuple[float, float]:
    """(credits used, overage USD) for `chars` on this plan.

    Inside the allowance the marginal cost is zero -- the subscription is sunk
    -- so the number worth reporting is the overage, not a pro-rata share of
    the monthly fee. A pro-rata share makes a light month look expensive and
    a heavy one look cheap, which is backwards."""
    credits = chars * plan.get("credits_per_char", 1.0)
    over = max(0.0, credits - plan["monthly_credits"])
    return credits, over / 1000 * plan.get("overage_usd_per_1k", 0.30)


def month_total(prefix: str = "") -> float:
    total = 0.0
    for p in EPISODES.glob("ep*/manifest.json"):
        try:
            with open(p) as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if prefix and not data.get("created_at", "").startswith(prefix):
            continue
        total += data.get("costs", {}).get("total", 0.0)
    return round(total, 2)


def check_ceilings(manifest, cfg: dict) -> None:
    ceil = cfg["cost_ceilings"]
    ep = manifest.data.get("costs", {}).get("total", 0.0)
    if ep > ceil["per_episode_usd"]:
        raise SystemExit(
            f"ABORT: episode cost ${ep:.2f} exceeded ceiling "
            f"${ceil['per_episode_usd']:.2f}. Raise it in config/pipeline.yaml "
            f"if this is intentional."
        )
    month = month_total(manifest.data.get("created_at", "")[:7])
    if month > ceil["per_month_usd"]:
        raise SystemExit(
            f"ABORT: month-to-date variable spend ${month:.2f} exceeded ceiling "
            f"${ceil['per_month_usd']:.2f}."
        )
