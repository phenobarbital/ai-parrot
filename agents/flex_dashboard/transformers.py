"""Flex dashboard transformers (FEAT-491 TASK-2694, spec §3 Module 2).

Registered, PURE ``@infographic_transformer`` functions ``(inputs, params)
-> dict`` over the six frozen Flex dataset aliases (spec §2): ``msl``,
``finance``, ``hours``, ``employees``, ``region_utilization``,
``rep_utilization``. Every number a Flex dashboard section shows comes from
one of these — never from replaying LLM-generated code (FEAT-324 G1).

All input cleaning goes through :mod:`agents.flex_dashboard.normalize`
(TASK-2693) — no inline currency/date/column-name handling here (spec §7
Known Risks).

**Pinned formulas (spec §2, resolved Q&A — do NOT deviate):**

- Payroll % to Revenue = ``sum(Payroll) / sum(Revenue)`` from ``finance``
  (denominator is Revenue ALONE, never ``Revenue + PC Revenue``).
- Worked Hours = ``sum(hours)`` from ``hours``; ``finance["Total Hours"]``
  is never used here (FTE cross-check only, out of this module's scope).
- Rep Utilization = ``employees_worked / average_active`` recomputed from
  ``rep_utilization``; the ``region_utilization`` precomputed
  ``Employee Utilization`` column is surfaced only as a cross-check value,
  never as the source of truth.
- Proximity Staffing = per-store nearest-N employees by haversine distance
  (implemented with numpy — no new dependency), plus a coverage count
  within a configurable radius (default 50 miles).

``flex_narrative_facts`` consumes the OTHER transformers' output dict keys,
not dataset aliases, and must be the LAST section in any published recipe
(mirrors ``agents/finance_reporter.py``'s ``narrative_facts`` pattern).

.. note::

   Registered as ``flex_narrative_facts``, NOT the generic ``narrative_facts``
   FinanceReporter uses: ``parrot.outputs.a2ui.recipes`` unconditionally
   imports ``library.py`` as an import side effect (its own ``__init__.py``),
   which registers a DIFFERENT, finance-specific ``narrative_facts`` function
   on the same process-wide ``transformer_registry`` the moment anything
   imports ``infographic_transformer`` — before this module's own decorators
   even run. Two different functions can never share one registry name
   (``TransformerRegistry.register`` raises), so the Flex narrative step
   needs its own name (discovered empirically via TASK-2694's own tests;
   see the Completion Note).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from parrot.outputs.a2ui.recipes.transformers import infographic_transformer

from agents.flex_dashboard.normalize import (
    canonicalize_columns,
    month_period,
    normalize_currency_columns,
)

__all__: list[str] = []  # registration is by import side effect, not re-export

#: Earth radius in miles, used by the haversine distance calculation.
_EARTH_RADIUS_MILES = 3958.8


def _apply_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    """Apply zero or more equality filters to *df*.

    Args:
        df: Input frame.
        filters: Column -> value. A falsy value (``None`` OR ``""``) means
            "no filter" and is skipped (per-section filter rule: an absent
            param never narrows a transformer's own dataset). Empty string
            is ALSO treated as unset (not just ``None``) because a published
            recipe's declared ``RecipeParam`` for an optional filter MUST
            have a concrete, non-``None`` default (`resolve_params` raises
            otherwise — see `agents/flex_dashboard.py`'s `recipe_params()`,
            TASK-2697) — ``""`` is that sentinel "no value" default.

    Returns:
        The filtered frame (a view/copy per pandas boolean indexing).
    """
    for column, value in filters.items():
        if value:
            df = df[df[column] == value]
    return df


def _haversine_miles(lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    """Great-circle distance in miles between two (arrays of) coordinates.

    Pure numpy implementation (spec §7 External Dependencies: no new
    ``haversine`` package dependency).

    Args:
        lat1: Latitude(s) of the first point(s), in degrees.
        lon1: Longitude(s) of the first point(s), in degrees.
        lat2: Latitude(s) of the second point(s), in degrees.
        lon2: Longitude(s) of the second point(s), in degrees.

    Returns:
        Distance(s) in miles, broadcast per numpy rules.
    """
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2.0) ** 2
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return _EARTH_RADIUS_MILES * c


# ═══════════════════════════════════════════════════════════════════════════
# Payroll Contribution
# ═══════════════════════════════════════════════════════════════════════════


@infographic_transformer(
    "payroll_hero",
    requires_columns={"hours": ["month_start", "hours"], "finance": ["month", "Payroll", "Revenue"]},
    description=(
        "Hero-row totals: Worked Hours (sum of hours.hours), Payroll and "
        "Revenue totals (sum of finance.Payroll / finance.Revenue), and "
        "Payroll % to Revenue = payroll_total / revenue_total (Revenue "
        "ALONE as denominator — spec §2 resolved Q&A). Reflects the SAME "
        "active filters as the rest of the dashboard."
    ),
    params_schema={
        "month": {"type": "string", "description": "YYYY-MM filter."},
        "pay_code": {"type": "string"},
        "cost_center": {"type": "string"},
    },
)
def payroll_hero(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    # Code-review finding (external `codex` review, adopted): the hero row
    # must reflect the SAME active filters as the rest of the dashboard —
    # otherwise a month/pay_code-filtered replay shows all-time totals in
    # the hero cards next to a filtered month-series chart, an internally
    # inconsistent dashboard. `month`/`pay_code`/`cost_center` narrow
    # `hours`; `month` narrows `finance` (finance has no pay_code/
    # cost_center column, so those two are naturally no-ops there).
    hours = month_period(inputs["hours"], source="hours")
    hours = _apply_filters(
        hours,
        {
            "month": params.get("month"),
            "pay_code": params.get("pay_code"),
            "cost_center": params.get("cost_center"),
        },
    )
    finance = month_period(inputs["finance"], source="finance")
    finance = normalize_currency_columns(finance, ["Payroll", "Revenue"])
    finance = _apply_filters(finance, {"month": params.get("month")})

    worked_hours_total = float(hours["hours"].sum())
    payroll_total = float(finance["Payroll"].sum())
    revenue_total = float(finance["Revenue"].sum())
    payroll_pct = (payroll_total / revenue_total) if revenue_total else 0.0

    return {
        "worked_hours_total": round(worked_hours_total, 2),
        "payroll_total": round(payroll_total, 2),
        "revenue_total": round(revenue_total, 2),
        # Ratio, not money — kept at full float precision (no rounding),
        # same convention as library.py's generic tabular helpers.
        "payroll_pct": payroll_pct,
    }


@infographic_transformer(
    "worked_hours_by_month",
    requires_columns={"hours": ["month_start", "hours"]},
    description="Worked Hours (sum of hours.hours) by month.",
    params_schema={
        "month": {"type": "string", "description": "YYYY-MM filter."},
        "pay_code": {"type": "string"},
        "cost_center": {"type": "string"},
    },
)
def worked_hours_by_month(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = month_period(inputs["hours"], source="hours")
    df = _apply_filters(
        df,
        {
            "month": params.get("month"),
            "pay_code": params.get("pay_code"),
            "cost_center": params.get("cost_center"),
        },
    )
    grouped = df.groupby("month", as_index=False)["hours"].sum().sort_values("month")
    series = [
        {"month": row.month, "worked_hours": round(float(row.hours), 2)} for row in grouped.itertuples(index=False)
    ]
    return {"series": series}


@infographic_transformer(
    "payroll_by_month",
    requires_columns={"finance": ["month", "Payroll"]},
    description="Payroll total (sum of finance.Payroll) by month.",
    params_schema={"month": {"type": "string", "description": "YYYY-MM filter."}},
)
def payroll_by_month(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = month_period(inputs["finance"], source="finance")
    df = normalize_currency_columns(df, ["Payroll"])
    df = _apply_filters(df, {"month": params.get("month")})
    grouped = df.groupby("month", as_index=False)["Payroll"].sum().sort_values("month")
    series = [{"month": row.month, "payroll": round(float(row.Payroll), 2)} for row in grouped.itertuples(index=False)]
    return {"series": series}


@infographic_transformer(
    "revenue_by_month",
    requires_columns={"finance": ["month", "Revenue"]},
    description="P&L Revenue total (sum of finance.Revenue) by month.",
    params_schema={"month": {"type": "string", "description": "YYYY-MM filter."}},
)
def revenue_by_month(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = month_period(inputs["finance"], source="finance")
    df = normalize_currency_columns(df, ["Revenue"])
    df = _apply_filters(df, {"month": params.get("month")})
    grouped = df.groupby("month", as_index=False)["Revenue"].sum().sort_values("month")
    series = [{"month": row.month, "revenue": round(float(row.Revenue), 2)} for row in grouped.itertuples(index=False)]
    return {"series": series}


@infographic_transformer(
    "payroll_pct_by_month",
    requires_columns={"finance": ["month", "Payroll", "Revenue"]},
    description=(
        "Payroll % to Revenue by month = sum(Payroll) / sum(Revenue) per "
        "month (Revenue ALONE as denominator — spec §2 resolved Q&A)."
    ),
    params_schema={"month": {"type": "string", "description": "YYYY-MM filter."}},
)
def payroll_pct_by_month(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = month_period(inputs["finance"], source="finance")
    df = normalize_currency_columns(df, ["Payroll", "Revenue"])
    df = _apply_filters(df, {"month": params.get("month")})
    grouped = df.groupby("month", as_index=False)[["Payroll", "Revenue"]].sum().sort_values("month")
    series = [
        {
            "month": row.month,
            # Ratio, not money — full float precision, no rounding.
            "payroll_pct": (row.Payroll / row.Revenue) if row.Revenue else 0.0,
        }
        for row in grouped.itertuples(index=False)
    ]
    return {"series": series}


@infographic_transformer(
    "pay_code_hours",
    requires_columns={"hours": ["pay_code", "hours"]},
    description="Worked Hours (sum of hours.hours) by pay_code.",
    params_schema={
        "month": {"type": "string", "description": "YYYY-MM filter."},
        "pay_code": {"type": "string"},
        "cost_center": {"type": "string"},
    },
)
def pay_code_hours(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = month_period(inputs["hours"], source="hours")
    df = _apply_filters(
        df,
        {
            "month": params.get("month"),
            "pay_code": params.get("pay_code"),
            "cost_center": params.get("cost_center"),
        },
    )
    grouped = df.groupby("pay_code", as_index=False)["hours"].sum().sort_values("pay_code")
    records = [
        {"pay_code": row.pay_code, "hours": round(float(row.hours), 2)} for row in grouped.itertuples(index=False)
    ]
    return {"records": records}


@infographic_transformer(
    "pay_code_allocation",
    requires_columns={"hours": ["pay_code", "hours"]},
    description=(
        "Worked Hours by Pay Code Allocation: each pay_code's share (%) of "
        "total worked hours. A pay_code filter narrows the allocation base "
        "itself (consistent with the sibling pay_code_hours table) — with "
        "one pay_code selected, its share is trivially 100%, same as "
        "filtering any breakdown to a single category."
    ),
    params_schema={
        "month": {"type": "string", "description": "YYYY-MM filter."},
        "pay_code": {"type": "string"},
        "cost_center": {"type": "string"},
    },
)
def pay_code_allocation(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = month_period(inputs["hours"], source="hours")
    df = _apply_filters(
        df,
        {
            "month": params.get("month"),
            "pay_code": params.get("pay_code"),
            "cost_center": params.get("cost_center"),
        },
    )
    total_hours = float(df["hours"].sum())
    grouped = df.groupby("pay_code", as_index=False)["hours"].sum().sort_values("pay_code")
    records = [
        {
            "pay_code": row.pay_code,
            "hours": round(float(row.hours), 2),
            "share_pct": round((float(row.hours) / total_hours * 100.0) if total_hours else 0.0, 2),
        }
        for row in grouped.itertuples(index=False)
    ]
    return {"total_hours": round(total_hours, 2), "records": records}


# ═══════════════════════════════════════════════════════════════════════════
# Rep (Representative) Utilization
# ═══════════════════════════════════════════════════════════════════════════


@infographic_transformer(
    "rep_utilization_by_region",
    requires_columns={
        "rep_utilization": ["bop_date", "region", "catagory", "employees_worked", "average_active"],
        "region_utilization": ["BOP Date", "FM Region", "Category", "Employee Utilization"],
    },
    description=(
        "Rep Utilization by region/category/month = employees_worked / "
        "average_active, RECOMPUTED from rep_utilization (spec §2 resolved "
        "Q&A). The region_utilization precomputed Employee Utilization "
        "column is attached only as cross_check_utilization, never as the "
        "source of truth."
    ),
    params_schema={
        "month": {"type": "string", "description": "YYYY-MM filter."},
        "category": {"type": "string"},
    },
)
def rep_utilization_by_region(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    rep = canonicalize_columns(inputs["rep_utilization"], source="rep_utilization")
    rep = month_period(rep, source="fm")
    rep = _apply_filters(rep, {"month": params.get("month"), "category": params.get("category")})
    rep_grouped = (
        rep.groupby(["region", "category", "month"], as_index=False)[["employees_worked", "average_active"]]
        .sum()
        .sort_values(["region", "month"])
    )

    cross = canonicalize_columns(inputs["region_utilization"], source="region_utilization")
    cross = month_period(cross, source="fm")
    cross = _apply_filters(cross, {"month": params.get("month"), "category": params.get("category")})
    cross_grouped = cross.groupby(["region", "category", "month"], as_index=False)["employee_utilization"].mean()
    cross_lookup = {
        (row.region, row.category, row.month): float(row.employee_utilization)
        for row in cross_grouped.itertuples(index=False)
    }

    records = []
    for row in rep_grouped.itertuples(index=False):
        utilization = float(row.employees_worked) / float(row.average_active) if row.average_active else 0.0
        key = (row.region, row.category, row.month)
        records.append(
            {
                "region": row.region,
                "category": row.category,
                "month": row.month,
                # Ratios, not money — full float precision, no rounding.
                "utilization": utilization,
                "cross_check_utilization": cross_lookup.get(key),
            }
        )
    return {"records": records}


# ═══════════════════════════════════════════════════════════════════════════
# Proximity Staffing
# ═══════════════════════════════════════════════════════════════════════════


@infographic_transformer(
    "proximity_staffing",
    requires_columns={
        "msl": ["store_name", "latitude", "longitude"],
        "employees": ["display_name", "latitude", "longitude"],
    },
    description=(
        "Per-store nearest-N employees by haversine distance, plus a "
        "coverage count of employees within a configurable radius. Returns "
        "a store map layer, an employee map layer, and a per-store "
        "coverage table."
    ),
    params_schema={
        "radius_miles": {"type": "number", "default": 50},
        "nearest_n": {"type": "integer", "default": 3},
        "flex_type": {"type": "string"},
    },
)
def proximity_staffing(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    radius_miles = float(params.get("radius_miles") or 50)
    nearest_n = int(params.get("nearest_n") or 3)

    stores = inputs["msl"].sort_values("store_name").reset_index(drop=True)
    employees = canonicalize_columns(inputs["employees"], source="employees")
    employees = _apply_filters(employees, {"flex_type": params.get("flex_type")})
    employees = employees.sort_values("display_name").reset_index(drop=True)

    store_layer = [
        {
            "store_name": row.store_name,
            "latitude": float(row.latitude),
            "longitude": float(row.longitude),
            "region_name": getattr(row, "region_name", None),
            "state_code": getattr(row, "state_code", None),
        }
        for row in stores.itertuples(index=False)
    ]
    employee_layer = [
        {
            "display_name": row.display_name,
            "latitude": float(row.latitude),
            "longitude": float(row.longitude),
            "flex_type": getattr(row, "flex_type", None),
        }
        for row in employees.itertuples(index=False)
    ]

    coverage = []
    emp_lat = employees["latitude"].to_numpy(dtype=float)
    emp_lon = employees["longitude"].to_numpy(dtype=float)
    emp_names = employees["display_name"].to_numpy()

    for store in stores.itertuples(index=False):
        if len(employees) == 0:
            coverage.append(
                {
                    "store_name": store.store_name,
                    "nearest_employees": [],
                    "employees_within_radius": 0,
                }
            )
            continue

        distances = _haversine_miles(float(store.latitude), float(store.longitude), emp_lat, emp_lon)
        order = np.argsort(distances, kind="stable")
        nearest = [
            {
                "display_name": str(emp_names[i]),
                "distance_miles": round(float(distances[i]), 2),
            }
            for i in order[:nearest_n]
        ]
        within_radius = int(np.sum(distances <= radius_miles))
        coverage.append(
            {
                "store_name": store.store_name,
                "nearest_employees": nearest,
                "employees_within_radius": within_radius,
            }
        )

    return {
        "store_layer": store_layer,
        "employee_layer": employee_layer,
        "coverage": coverage,
        "radius_miles": radius_miles,
        "nearest_n": nearest_n,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Narrative facts — MUST be the last section (consumes prior step outputs)
# ═══════════════════════════════════════════════════════════════════════════


def _series_trend(series: list[dict[str, Any]], value_key: str) -> str:
    """Classify a month series' first-vs-last direction.

    Args:
        series: A ``[{"month": ..., value_key: ...}, ...]`` list, already
            sorted by month.
        value_key: The numeric field to compare.

    Returns:
        ``"increasing"``, ``"decreasing"``, or ``"flat"`` (also ``"flat"``
        for fewer than two points).
    """
    if len(series) < 2:
        return "flat"
    first, last = series[0][value_key], series[-1][value_key]
    if last > first:
        return "increasing"
    if last < first:
        return "decreasing"
    return "flat"


@infographic_transformer(
    "flex_narrative_facts",
    requires_columns={},  # inputs are prior-step dict outputs, not frames
    description=(
        "Structured narrative facts derived from payroll_hero, "
        "worked_hours_by_month and rep_utilization_by_region's outputs — "
        "no English sentence generation (a downstream skill renders these "
        "as prose). MUST be the last section in any recipe that includes "
        "it (FinanceReporter pattern)."
    ),
)
def flex_narrative_facts(inputs: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    hero = inputs["payroll_hero"]
    worked_hours_series = inputs["worked_hours_by_month"]["series"]
    utilization_records = inputs["rep_utilization_by_region"]["records"]

    return {
        "worked_hours_total": hero["worked_hours_total"],
        "payroll_total": hero["payroll_total"],
        "revenue_total": hero["revenue_total"],
        "payroll_pct": hero["payroll_pct"],
        "worked_hours_trend": _series_trend(worked_hours_series, "worked_hours"),
        "regions_tracked": sorted({r["region"] for r in utilization_records}),
    }
