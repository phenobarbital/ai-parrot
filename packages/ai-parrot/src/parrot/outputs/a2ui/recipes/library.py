"""Built-in transformer library (Module 3, FEAT-324).

Ports the analysis routines of ``sdd/artifacts/executive_summary.py`` (a
gitignored, non-package reference artifact — its MATH is ported here, never
imported) into registered, pure ``@infographic_transformer`` functions, plus
generic tabular helpers. These are the seed vocabulary recipes reference in
``TransformStep.transformer``.

Row/frame convention: the finance-domain transformers (``day_totals``,
``division_breakdown``, ``variance_analysis``, ``top_movers``) operate on a
DataFrame with columns ``division, project, rev_actual, rev_budget,
ebitda_actual, ebitda_budget`` and an OPTIONAL snapshot column (default name
``"snapshot"``, overridable via the ``snapshot_col`` param) carrying a
date-like value when multiple days are combined into one frame — this is the
"one frame + snapshot_col param" convention (as opposed to per-day framing
or a snapshot-discovery transformer, both explicitly out of scope).

Money-metric outputs are rounded to 2 decimal places (matching the reference
artifact's display conventions); the generic tabular helpers preserve full
float precision since they have no notion of "money".

Importing this module registers all 7 transformers on the shared
:data:`~parrot.outputs.a2ui.recipes.transformers.transformer_registry` as an
import side effect — mirrored by ``recipes/__init__.py`` importing this
module.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from parrot.outputs.a2ui.recipes.transformers import infographic_transformer

__all__: list[str] = []  # registration is by import side effect, not re-export

_MONEY_COLUMNS = ["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"]


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to a JSON-safe list of records.

    Routes through ``DataFrame.to_json`` so numpy scalar dtypes (int64,
    float64, ...) and NaN become native JSON types (NaN -> ``null``) rather
    than raising ``TypeError`` on naive ``json.dumps``.
    """
    return json.loads(df.to_json(orient="records"))


def _day_totals_for(df: pd.DataFrame) -> dict[str, Any]:
    """Compute revenue/EBITDA totals + variance for a single snapshot's rows.

    Direct port of ``executive_summary.day_totals`` (spec §Codebase Contract),
    generalized from a row-list to a DataFrame. ``rev_variance_pct`` guards
    division-by-zero exactly like the original (line 48: ``... if rev_b else 0``).
    """
    rev_a = float(df["rev_actual"].sum())
    rev_b = float(df["rev_budget"].sum())
    eb_a = float(df["ebitda_actual"].sum())
    eb_b = float(df["ebitda_budget"].sum())
    rev_variance = rev_a - rev_b
    return {
        "rev_actual": round(rev_a, 2),
        "rev_budget": round(rev_b, 2),
        "rev_variance": round(rev_variance, 2),
        "rev_variance_pct": round(rev_variance / rev_b * 100, 2) if rev_b else 0.0,
        "ebitda_actual": round(eb_a, 2),
        "ebitda_budget": round(eb_b, 2),
        "ebitda_variance": round(eb_a - eb_b, 2),
    }


@infographic_transformer(
    "day_totals",
    requires_columns={"snapshots": _MONEY_COLUMNS},
    description=(
        "Per-snapshot revenue/EBITDA totals and variances vs budget "
        "(port of executive_summary.day_totals). If the input carries a "
        "snapshot column (see 'snapshot_col' param, default 'snapshot'), "
        "returns one totals record per distinct snapshot value keyed by its "
        "string value; otherwise returns a single totals record for the "
        "whole frame."
    ),
    params_schema={
        "snapshot_col": {"type": "string", "default": "snapshot"},
    },
)
def day_totals(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = inputs["snapshots"]
    snapshot_col = params.get("snapshot_col", "snapshot")
    if snapshot_col in df.columns:
        return {
            str(key): _day_totals_for(group)
            for key, group in sorted(df.groupby(snapshot_col), key=lambda kv: str(kv[0]))
        }
    return _day_totals_for(df)


@infographic_transformer(
    "division_breakdown",
    requires_columns={"snapshots": ["division", "project", *_MONEY_COLUMNS]},
    description=(
        "Per-division rollup + per-project variances for a single snapshot "
        "(port of executive_summary.division_breakdown). If the input "
        "carries multiple snapshot values (see 'snapshot_col' param), the "
        "LATEST snapshot is used — matching the reference artifact, which "
        "only ever calls division_breakdown on the latest day's rows."
    ),
    params_schema={
        "snapshot_col": {"type": "string", "default": "snapshot"},
    },
)
def division_breakdown(
    inputs: dict[str, pd.DataFrame], params: dict[str, Any]
) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = inputs["snapshots"]
    snapshot_col = params.get("snapshot_col", "snapshot")
    if snapshot_col in df.columns:
        latest = df[snapshot_col].max()
        df = df[df[snapshot_col] == latest]

    divisions: dict[str, dict[str, Any]] = {}
    for row in df.itertuples(index=False):
        d = divisions.setdefault(
            row.division,
            {
                "rev_actual": 0.0,
                "rev_budget": 0.0,
                "ebitda_actual": 0.0,
                "ebitda_budget": 0.0,
                "projects": [],
            },
        )
        d["rev_actual"] += float(row.rev_actual)
        d["rev_budget"] += float(row.rev_budget)
        d["ebitda_actual"] += float(row.ebitda_actual)
        d["ebitda_budget"] += float(row.ebitda_budget)
        d["projects"].append(
            {
                "name": row.project,
                "rev_variance": round(float(row.rev_actual - row.rev_budget), 2),
                "ebitda_variance": round(float(row.ebitda_actual - row.ebitda_budget), 2),
            }
        )

    for d in divisions.values():
        d["rev_actual"] = round(d["rev_actual"], 2)
        d["rev_budget"] = round(d["rev_budget"], 2)
        d["ebitda_actual"] = round(d["ebitda_actual"], 2)
        d["ebitda_budget"] = round(d["ebitda_budget"], 2)
        d["rev_variance"] = round(d["rev_actual"] - d["rev_budget"], 2)
        d["ebitda_variance"] = round(d["ebitda_actual"] - d["ebitda_budget"], 2)

    return divisions


@infographic_transformer(
    "variance_analysis",
    requires_columns={"snapshots": _MONEY_COLUMNS},
    description=(
        "First-vs-latest comparison across N snapshots: pct-point change, "
        "EBITDA dollar change, and direction flags — narrowing/widening/flat "
        "for revenue, improved/worsened/held_steady for EBITDA, ahead/behind "
        "for the latest revenue state (port of the cross-day math in "
        "executive_summary.analyze / headline_text, WITHOUT any narrative "
        "sentence generation, which is a renderer/layout concern). Requires "
        "a snapshot column (default 'snapshot'); with a single distinct "
        "snapshot value, first and last totals are identical and both "
        "changes are 0."
    ),
    params_schema={
        "snapshot_col": {"type": "string", "default": "snapshot"},
    },
)
def variance_analysis(
    inputs: dict[str, pd.DataFrame], params: dict[str, Any]
) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = inputs["snapshots"]
    snapshot_col = params.get("snapshot_col", "snapshot")
    if snapshot_col not in df.columns:
        raise ValueError(f"variance_analysis requires a {snapshot_col!r} column")

    snapshots_sorted = sorted(df[snapshot_col].unique())
    first_key, last_key = snapshots_sorted[0], snapshots_sorted[-1]
    first_totals = _day_totals_for(df[df[snapshot_col] == first_key])
    last_totals = _day_totals_for(df[df[snapshot_col] == last_key])

    rev_pct_change = round(
        abs(first_totals["rev_variance_pct"]) - abs(last_totals["rev_variance_pct"]), 2
    )
    ebitda_dollar_change = round(
        last_totals["ebitda_variance"] - first_totals["ebitda_variance"], 2
    )
    rev_direction = (
        "narrowing" if rev_pct_change > 0 else "widening" if rev_pct_change < 0 else "flat"
    )
    ebitda_direction = (
        "improved"
        if ebitda_dollar_change > 0
        else "worsened" if ebitda_dollar_change < 0 else "held_steady"
    )
    rev_state = "behind" if last_totals["rev_variance"] < 0 else "ahead"

    return {
        "first_snapshot": str(first_key),
        "last_snapshot": str(last_key),
        "first_totals": first_totals,
        "last_totals": last_totals,
        "rev_pct_change": rev_pct_change,
        "ebitda_dollar_change": ebitda_dollar_change,
        "rev_direction": rev_direction,
        "ebitda_direction": ebitda_direction,
        "rev_state": rev_state,
        "n_snapshots": len(snapshots_sorted),
    }


@infographic_transformer(
    "top_movers",
    requires_columns={"snapshots": ["division", "project", "ebitda_actual", "ebitda_budget"]},
    description=(
        "Worst/best N projects by EBITDA variance (actual - budget) at the "
        "latest snapshot (port of the worst/best selection in "
        "executive_summary.analyze). If the input carries multiple snapshot "
        "values, each project also gets a 'trend' field: the change in its "
        "EBITDA variance from the first to the latest snapshot (null if the "
        "project is new at the latest snapshot, or if only one snapshot is "
        "present)."
    ),
    params_schema={
        "n": {"type": "integer", "default": 3},
        "snapshot_col": {"type": "string", "default": "snapshot"},
    },
)
def top_movers(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = inputs["snapshots"]
    n = int(params.get("n", 3))
    snapshot_col = params.get("snapshot_col", "snapshot")

    first_df: pd.DataFrame | None = None
    if snapshot_col in df.columns:
        snapshots_sorted = sorted(df[snapshot_col].unique())
        latest_key, first_key = snapshots_sorted[-1], snapshots_sorted[0]
        latest_df = df[df[snapshot_col] == latest_key]
        if first_key != latest_key:
            first_df = df[df[snapshot_col] == first_key]
    else:
        latest_df = df

    def _variance_lookup(frame: pd.DataFrame) -> dict[tuple[str, str], float]:
        return {
            (row.division, row.project): float(row.ebitda_actual - row.ebitda_budget)
            for row in frame.itertuples(index=False)
        }

    latest_variances = _variance_lookup(latest_df)
    first_variances = _variance_lookup(first_df) if first_df is not None else {}

    entries = []
    for (division, project), variance in latest_variances.items():
        entry: dict[str, Any] = {
            "division": division,
            "project": project,
            "ebitda_variance": round(variance, 2),
        }
        if first_df is not None:
            prior = first_variances.get((division, project))
            entry["trend"] = round(variance - prior, 2) if prior is not None else None
        else:
            entry["trend"] = None
        entries.append(entry)

    worst = sorted(
        (e for e in entries if e["ebitda_variance"] < 0), key=lambda e: e["ebitda_variance"]
    )[:n]
    best = sorted(
        (e for e in entries if e["ebitda_variance"] > 0), key=lambda e: -e["ebitda_variance"]
    )[:n]
    return {"worst": worst, "best": best}


@infographic_transformer(
    "groupby_aggregate",
    requires_columns={},  # columns depend on runtime 'by'/'aggs' params, not statically known
    description=(
        "Generic group-by + named aggregation. 'by' is a list of grouping "
        "columns; 'aggs' maps output column name -> {'column': ..., "
        "'func': 'sum'|'mean'|'count'|'min'|'max'|...}. Returns a list of "
        "records (full float precision, no assumed rounding)."
    ),
    params_schema={
        "by": {"type": "array", "items": {"type": "string"}},
        "aggs": {"type": "object"},
    },
)
def groupby_aggregate(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = inputs["df"]
    by = params["by"]
    aggs = params["aggs"]
    named_aggs = {
        out_name: pd.NamedAgg(column=spec["column"], aggfunc=spec["func"])
        for out_name, spec in aggs.items()
    }
    grouped = df.groupby(by, dropna=False).agg(**named_aggs).reset_index()
    return {"rows": _records(grouped)}


@infographic_transformer(
    "pivot",
    requires_columns={},  # columns depend on runtime 'index'/'columns'/'values' params
    description=(
        "Generic pivot table: 'index', 'columns', 'values' column names "
        "plus 'aggfunc' (default 'sum'). Returns a list of records with the "
        "pivoted columns flattened (full float precision)."
    ),
    params_schema={
        "index": {"type": "string"},
        "columns": {"type": "string"},
        "values": {"type": "string"},
        "aggfunc": {"type": "string", "default": "sum"},
    },
)
def pivot(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    df = inputs["df"]
    table = df.pivot_table(
        index=params["index"],
        columns=params["columns"],
        values=params["values"],
        aggfunc=params.get("aggfunc", "sum"),
    ).reset_index()
    table.columns = [str(c) for c in table.columns]
    return {"rows": _records(table)}


@infographic_transformer(
    "latest_vs_baseline",
    requires_columns={},  # 'baseline'/'latest' shape depends on runtime 'on'/'value_cols'
    description=(
        "Joins a 'baseline' and a 'latest' frame on 'on' key columns and "
        "computes '<col>_delta' = latest - baseline for each of "
        "'value_cols' (missing values on either side treated as 0). Returns "
        "a list of records (full float precision)."
    ),
    params_schema={
        "on": {"type": "array", "items": {"type": "string"}},
        "value_cols": {"type": "array", "items": {"type": "string"}},
    },
)
def latest_vs_baseline(inputs: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict[str, Any]:
    """See the ``@infographic_transformer`` description above."""
    baseline = inputs["baseline"]
    latest = inputs["latest"]
    on = params["on"]
    value_cols = params["value_cols"]

    merged = latest.merge(baseline, on=on, suffixes=("_latest", "_baseline"), how="outer")
    records = []
    for row in merged.itertuples(index=False):
        row_dict = row._asdict()
        record: dict[str, Any] = {key: row_dict[key] for key in on}
        for col in value_cols:
            latest_val = row_dict.get(f"{col}_latest", row_dict.get(col))
            baseline_val = row_dict.get(f"{col}_baseline", row_dict.get(col))
            latest_val = 0.0 if latest_val is None or pd.isna(latest_val) else float(latest_val)
            baseline_val = (
                0.0 if baseline_val is None or pd.isna(baseline_val) else float(baseline_val)
            )
            record[f"{col}_latest"] = round(latest_val, 2)
            record[f"{col}_baseline"] = round(baseline_val, 2)
            record[f"{col}_delta"] = round(latest_val - baseline_val, 2)
        records.append(record)
    return {"rows": records}
