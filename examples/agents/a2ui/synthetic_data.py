"""Deterministic synthetic data for the A2UI dashboard walkthrough.

Everything here is generated from a fixed seed, so the walkthrough produces a
byte-identical A2UI envelope on every run — which is what makes it usable as a
smoke test for the wire format (FEAT-470) as well as a teaching example.

No external services, no network, no LLM: just ``numpy`` + ``pandas``.
"""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

#: Fixed seed — the whole point is that the dashboard is reproducible.
SEED = 20260828

#: Fictional company the synthetic numbers describe.
COMPANY = "Northwind Cloud"

_MONTHS: List[str] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

_PLANS: List[str] = ["Starter", "Team", "Business", "Enterprise"]

#: Monthly seat price per plan, in USD.
_PLAN_PRICE: Dict[str, float] = {
    "Starter": 12.0,
    "Team": 29.0,
    "Business": 79.0,
    "Enterprise": 240.0,
}


def build_monthly_metrics(*, seed: int = SEED) -> pd.DataFrame:
    """Build a 12-month SaaS revenue-operations series.

    The series is intentionally *shaped* rather than pure noise: MRR grows
    month over month, churn trends down, and NPS drifts up — so the resulting
    charts have something to actually show.

    Args:
        seed: Seed for the random generator. The default keeps the output
            stable across runs.

    Returns:
        A 12-row DataFrame with columns ``month``, ``mrr``, ``new_mrr``,
        ``churned_mrr``, ``churn_rate``, ``active_accounts`` and ``nps``.
    """
    rng = np.random.default_rng(seed)

    base_mrr = 780_000.0
    growth = np.cumprod(1.0 + rng.normal(loc=0.038, scale=0.011, size=12))
    mrr = np.round(base_mrr * growth, 2)

    churn_rate = np.round(np.clip(np.linspace(2.9, 1.6, 12) + rng.normal(0, 0.12, 12), 0.5, 6.0), 2)
    churned_mrr = np.round(mrr * churn_rate / 100.0, 2)
    new_mrr = np.round(np.diff(mrr, prepend=base_mrr) + churned_mrr, 2)

    active_accounts = np.round(mrr / rng.uniform(390, 430, size=12)).astype(int)
    nps = np.round(np.clip(np.linspace(31, 47, 12) + rng.normal(0, 2.1, 12), 0, 100)).astype(int)

    return pd.DataFrame(
        {
            "month": _MONTHS,
            "mrr": mrr,
            "new_mrr": new_mrr,
            "churned_mrr": churned_mrr,
            "churn_rate": churn_rate,
            "active_accounts": active_accounts,
            "nps": nps,
        }
    )


def build_plan_mix(monthly: pd.DataFrame, *, seed: int = SEED) -> pd.DataFrame:
    """Break the closing month's MRR down by plan tier.

    Args:
        monthly: The frame returned by :func:`build_monthly_metrics`; only its
            final row is used, so the breakdown always reconciles to the MRR
            the KPI card reports.
        seed: Seed for the random generator.

    Returns:
        A 4-row DataFrame with columns ``plan``, ``accounts``, ``mrr`` and
        ``share_pct``. ``mrr`` sums to the closing month's MRR.
    """
    rng = np.random.default_rng(seed + 1)
    closing_mrr = float(monthly["mrr"].iloc[-1])

    # Dirichlet gives a share vector that sums to exactly 1.0 — so the plan
    # breakdown reconciles to total MRR instead of drifting off it.
    shares = rng.dirichlet(np.array([3.0, 5.0, 4.0, 2.0]))
    plan_mrr = np.round(closing_mrr * shares, 2)
    # Absorb the rounding residue into the largest tier so the sum is exact.
    plan_mrr[int(np.argmax(plan_mrr))] += round(closing_mrr - float(plan_mrr.sum()), 2)

    accounts = np.array(
        [max(1, int(round(m / _PLAN_PRICE[p]))) for m, p in zip(plan_mrr, _PLANS)]
    )

    return pd.DataFrame(
        {
            "plan": _PLANS,
            "accounts": accounts,
            "mrr": np.round(plan_mrr, 2),
            "share_pct": np.round(shares * 100.0, 1),
        }
    )


def build_goals(monthly: pd.DataFrame) -> List[Dict[str, Any]]:
    """Derive goal-completion percentages from the synthetic series.

    Args:
        monthly: The frame returned by :func:`build_monthly_metrics`.

    Returns:
        A list of ``{"label", "value"}`` dicts, each ``value`` a 0-100
        percentage — the shape ``ProgressBlock.items`` expects.
    """
    closing = monthly.iloc[-1]
    arr_target = 16_000_000.0
    return [
        {
            "label": "ARR target",
            "value": round(min(100.0, float(closing["mrr"]) * 12 / arr_target * 100), 1),
        },
        {
            "label": "Churn under 2.0%",
            "value": round(min(100.0, 2.0 / max(float(closing["churn_rate"]), 0.01) * 100), 1),
        },
        {
            "label": "NPS 50 target",
            "value": round(min(100.0, float(closing["nps"]) / 50.0 * 100), 1),
        },
    ]


def as_money(value: float) -> str:
    """Format a USD amount compactly (``$1.2M`` / ``$780.5K``).

    Args:
        value: The amount in USD.

    Returns:
        A short human-readable string for a KPI card face.
    """
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"
