"""Golden-file tests for FEAT-324 Module 3 (`parrot.outputs.a2ui.recipes.library`).

Fixture derived from `sdd/artifacts/executive_summary.py`'s compact row format
(division, project, rev_actual, rev_budget, ebitda_actual, ebitda_budget),
extended with a `snapshot` column combining two snapshot days into one frame
(the "one frame + snapshot_col param" convention documented in
`parrot.outputs.a2ui.recipes.library`).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from parrot.outputs.a2ui.recipes.transformers import transformer_registry

GOLDEN = Path(__file__).parent / "golden"

_ROWS = [
    # snapshot,      division, project, rev_actual, rev_budget, ebitda_actual, ebitda_budget
    ("2026-06-01", "Sales", "Alpha", 100000.0, 90000.0, 20000.0, 18000.0),
    ("2026-06-01", "Sales", "Beta", 50000.0, 60000.0, 5000.0, 8000.0),
    ("2026-06-01", "Ops", "Gamma", 30000.0, 30000.0, 4000.0, 4000.0),
    ("2026-07-22", "Sales", "Alpha", 120000.0, 110000.0, 25000.0, 22000.0),
    ("2026-07-22", "Sales", "Beta", 55000.0, 70000.0, 4000.0, 9000.0),
    ("2026-07-22", "Ops", "Gamma", 32000.0, 31000.0, 4500.0, 4200.0),
    ("2026-07-22", "Ops", "Delta", 10000.0, 12000.0, -1000.0, 500.0),
]

_COLUMNS = [
    "snapshot",
    "division",
    "project",
    "rev_actual",
    "rev_budget",
    "ebitda_actual",
    "ebitda_budget",
]


@pytest.fixture
def budget_variance_frames() -> pd.DataFrame:
    """Two-snapshot combined DataFrame reproducing the reference dashboard shape."""
    return pd.DataFrame(_ROWS, columns=_COLUMNS)


def _golden(name: str):
    with open(GOLDEN / f"{name}.json") as f:
        return json.load(f)


def test_library_golden_day_totals(budget_variance_frames):
    fn = transformer_registry.get("day_totals").func
    out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot"})
    assert out == _golden("day_totals")


def test_library_golden_division_breakdown(budget_variance_frames):
    fn = transformer_registry.get("division_breakdown").func
    out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot"})
    assert out == _golden("division_breakdown")


def test_library_golden_variance_analysis(budget_variance_frames):
    fn = transformer_registry.get("variance_analysis").func
    out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot"})
    assert out == _golden("variance_analysis")


def test_library_golden_top_movers(budget_variance_frames):
    fn = transformer_registry.get("top_movers").func
    out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot"})
    assert out == _golden("top_movers")


def test_day_totals_without_snapshot_column_is_single_record():
    df = pd.DataFrame(
        [(100.0, 90.0, 20.0, 18.0)],
        columns=["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"],
    )
    fn = transformer_registry.get("day_totals").func
    out = fn({"snapshots": df}, {})
    assert out == {
        "rev_actual": 100.0,
        "rev_budget": 90.0,
        "rev_variance": 10.0,
        "rev_variance_pct": pytest.approx(11.11, rel=1e-2),
        "ebitda_actual": 20.0,
        "ebitda_budget": 18.0,
        "ebitda_variance": 2.0,
    }


def test_variance_pct_zero_budget_guard():
    df = pd.DataFrame(
        [("2026-01-01", 0.0, 0.0, 0.0, 0.0)],
        columns=["snapshot", "rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"],
    )
    fn = transformer_registry.get("day_totals").func
    out = fn({"snapshots": df}, {"snapshot_col": "snapshot"})
    assert out["2026-01-01"]["rev_variance_pct"] == 0.0


def test_variance_analysis_requires_snapshot_column():
    df = pd.DataFrame(
        [(100.0, 90.0, 20.0, 18.0)],
        columns=["rev_actual", "rev_budget", "ebitda_actual", "ebitda_budget"],
    )
    fn = transformer_registry.get("variance_analysis").func
    with pytest.raises(ValueError, match="requires a"):
        fn({"snapshots": df}, {})


def test_top_movers_respects_n(budget_variance_frames):
    fn = transformer_registry.get("top_movers").func
    out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot", "n": 1})
    assert len(out["worst"]) == 1
    assert len(out["best"]) == 1
    assert out["worst"][0]["project"] == "Beta"
    assert out["best"][0]["project"] == "Alpha"


def test_groupby_aggregate():
    df = pd.DataFrame(
        {
            "division": ["Sales", "Sales", "Ops"],
            "rev_actual": [100.0, 200.0, 50.0],
        }
    )
    fn = transformer_registry.get("groupby_aggregate").func
    out = fn(
        {"df": df},
        {"by": ["division"], "aggs": {"total_rev": {"column": "rev_actual", "func": "sum"}}},
    )
    rows = {row["division"]: row["total_rev"] for row in out["rows"]}
    assert rows == {"Sales": 300.0, "Ops": 50.0}


def test_groupby_aggregate_rejects_unsafe_func_name():
    df = pd.DataFrame({"division": ["Sales"], "rev_actual": [100.0]})
    fn = transformer_registry.get("groupby_aggregate").func
    with pytest.raises(ValueError, match="Unsupported aggregation function"):
        fn(
            {"df": df},
            {"by": ["division"], "aggs": {"x": {"column": "rev_actual", "func": "__class__"}}},
        )


def test_pivot():
    df = pd.DataFrame(
        {
            "division": ["Sales", "Sales", "Ops"],
            "metric": ["rev", "ebitda", "rev"],
            "value": [100.0, 20.0, 50.0],
        }
    )
    fn = transformer_registry.get("pivot").func
    out = fn(
        {"df": df},
        {"index": "division", "columns": "metric", "values": "value", "aggfunc": "sum"},
    )
    rows = {row["division"]: row for row in out["rows"]}
    assert rows["Sales"]["rev"] == 100.0
    assert rows["Sales"]["ebitda"] == 20.0
    assert rows["Ops"]["rev"] == 50.0


def test_pivot_rejects_unsafe_aggfunc_name():
    df = pd.DataFrame({"division": ["Sales"], "metric": ["rev"], "value": [100.0]})
    fn = transformer_registry.get("pivot").func
    with pytest.raises(ValueError, match="Unsupported aggregation function"):
        fn(
            {"df": df},
            {"index": "division", "columns": "metric", "values": "value", "aggfunc": "eval"},
        )


def test_latest_vs_baseline():
    baseline = pd.DataFrame({"project": ["Alpha", "Beta"], "ebitda": [18.0, 8.0]})
    latest = pd.DataFrame({"project": ["Alpha", "Beta"], "ebitda": [25.0, 4.0]})
    fn = transformer_registry.get("latest_vs_baseline").func
    out = fn(
        {"baseline": baseline, "latest": latest},
        {"on": ["project"], "value_cols": ["ebitda"]},
    )
    rows = {row["project"]: row for row in out["rows"]}
    assert rows["Alpha"]["ebitda_delta"] == 7.0
    assert rows["Beta"]["ebitda_delta"] == -4.0


def test_all_seven_transformers_registered():
    expected = {
        "day_totals",
        "division_breakdown",
        "variance_analysis",
        "top_movers",
        "groupby_aggregate",
        "pivot",
        "latest_vs_baseline",
    }
    registered = {m.name for m in transformer_registry.list()}
    assert expected <= registered


def test_outputs_are_json_serializable(budget_variance_frames):
    for name in ("day_totals", "division_breakdown", "variance_analysis", "top_movers"):
        fn = transformer_registry.get(name).func
        out = fn({"snapshots": budget_variance_frames}, {"snapshot_col": "snapshot"})
        json.dumps(out)  # must not raise
