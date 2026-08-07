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


@pytest.fixture
def upstream_outputs():
    """The three prior-step outputs `narrative_facts` consumes.

    Shaped to exercise every `division_reads` branch:
      - 'Retail'   : net negative with one project < -5000   -> concentrated
      - 'Wholesale': net positive despite a negative project -> offset_by
      - 'Services' : net positive, nothing material           -> on_track
      - 'Thin'     : net negative, nothing material           -> spread
    """
    return {
        "variance_analysis": {
            "first_snapshot": "20260701",
            "last_snapshot": "20260703",
            "first_totals": {},
            "last_totals": {},
            "rev_pct_change": 1.5,
            "ebitda_dollar_change": -20000.0,
            "rev_direction": "narrowing",
            "ebitda_direction": "worsened",
            "rev_state": "behind",
            "n_snapshots": 3,
        },
        "top_movers": {
            "worst": [
                {"division": "Retail", "project": "Alpha", "ebitda_variance": -42000.0, "trend": -8000.0}
            ],
            "best": [
                {"division": "Wholesale", "project": "Zeta", "ebitda_variance": 31000.0, "trend": None}
            ],
        },
        "division_breakdown": {
            "Retail": {
                "ebitda_variance": -6000.0,
                "projects": [
                    {"name": "Alpha", "rev_variance": -1000.0, "ebitda_variance": -42000.0},
                    {"name": "Beta", "rev_variance": 500.0, "ebitda_variance": 36000.0},
                ],
            },
            "Wholesale": {
                "ebitda_variance": 22000.0,
                "projects": [
                    {"name": "Gamma", "rev_variance": -300.0, "ebitda_variance": -9000.0},
                    {"name": "Zeta", "rev_variance": 700.0, "ebitda_variance": 31000.0},
                ],
            },
            "Services": {
                "ebitda_variance": 1000.0,
                "projects": [
                    {"name": "Delta", "rev_variance": 100.0, "ebitda_variance": 2000.0},
                    {"name": "Epsilon", "rev_variance": -50.0, "ebitda_variance": -1000.0},
                ],
            },
            "Thin": {
                "ebitda_variance": -2500.0,
                "projects": [
                    {"name": "Iota", "rev_variance": -20.0, "ebitda_variance": -2000.0},
                    {"name": "Kappa", "rev_variance": -10.0, "ebitda_variance": -500.0},
                ],
            },
        },
    }


class TestNarrativeFacts:
    """Tests for the `narrative_facts` transformer (FEAT-420 Module 1)."""

    def test_registered_with_no_column_requirements(self):
        """Prior-step dict inputs must not be column-gated."""
        assert transformer_registry.manifest("narrative_facts").requires_columns == {}

    def test_headline_flags_reuse_upstream_directions(self, upstream_outputs):
        """rev_direction/ebitda_direction/rev_state come from variance_analysis."""
        fn = transformer_registry.get("narrative_facts").func
        out = fn(upstream_outputs, {})
        assert out["headline"]["rev_direction"] == "narrowing"
        assert out["headline"]["ebitda_direction"] == "worsened"
        assert out["headline"]["rev_state"] == "behind"
        assert out["headline"]["diverging"] is True
        assert out["headline"]["both_improving"] is False
        assert out["headline"]["both_worsening"] is False
        assert out["headline"]["first_label"] == "20260701"
        assert out["headline"]["last_label"] == "20260703"

    def test_division_read_kinds(self, upstream_outputs):
        """All four kinds are produced per the reference decision order."""
        fn = transformer_registry.get("narrative_facts").func
        out = fn(upstream_outputs, {})
        kinds = {d["division"]: d["kind"] for d in out["division_reads"]}
        assert kinds == {
            "Retail": "concentrated",
            "Wholesale": "offset_by",
            "Services": "on_track",
            "Thin": "spread",
        }

    def test_offsetter_only_for_offset_by(self, upstream_outputs):
        fn = transformer_registry.get("narrative_facts").func
        out = fn(upstream_outputs, {})
        for read in out["division_reads"]:
            if read["kind"] == "offset_by":
                assert read["offsetter"] == "Zeta"
            else:
                assert read["offsetter"] is None

    def test_materiality_threshold_and_cap(self):
        """Only < -5000 projects are named, capped at max_named_per_division."""
        fn = transformer_registry.get("narrative_facts").func
        inputs = {
            "variance_analysis": {
                "first_snapshot": "a", "last_snapshot": "b", "first_totals": {},
                "last_totals": {}, "rev_pct_change": 0.0, "ebitda_dollar_change": 0.0,
                "rev_direction": "flat", "ebitda_direction": "held_steady",
                "rev_state": "behind", "n_snapshots": 1,
            },
            "top_movers": {"worst": [], "best": []},
            "division_breakdown": {
                "MultiNeg": {
                    "ebitda_variance": -80000.0,
                    "projects": [
                        {"name": "P1", "ebitda_variance": -10000.0},
                        {"name": "P2", "ebitda_variance": -60000.0},
                        {"name": "P3", "ebitda_variance": -20000.0},
                    ],
                }
            },
        }
        out = fn(inputs, {})
        read = out["division_reads"][0]
        assert read["kind"] == "concentrated"
        assert len(read["named"]) == 2
        assert set(read["named"]) == {"P2", "P3"}  # the two most negative

    def test_urgency_branches(self):
        """trend<0 -> immediate; >0 -> confirm_trend; None/0 -> check_timing."""
        fn = transformer_registry.get("narrative_facts").func
        base = {
            "variance_analysis": {
                "first_snapshot": "a", "last_snapshot": "b", "first_totals": {},
                "last_totals": {}, "rev_pct_change": 0.0, "ebitda_dollar_change": 0.0,
                "rev_direction": "flat", "ebitda_direction": "held_steady",
                "rev_state": "behind", "n_snapshots": 2,
            },
            "division_breakdown": {},
        }
        for trend, expected in ((-8000.0, "immediate"), (5000.0, "confirm_trend"),
                                 (0.0, "check_timing"), (None, "check_timing")):
            inputs = {
                **base,
                "top_movers": {
                    "worst": [
                        {"division": "D", "project": "P", "ebitda_variance": -1000.0, "trend": trend}
                    ],
                    "best": [],
                },
            }
            out = fn(inputs, {})
            assert out["top_driver"]["urgency"] == expected

    def test_top_driver_none_when_no_negative_project(self):
        """No negative project -> top_driver is None."""
        fn = transformer_registry.get("narrative_facts").func
        inputs = {
            "variance_analysis": {
                "first_snapshot": "a", "last_snapshot": "b", "first_totals": {},
                "last_totals": {}, "rev_pct_change": 1.0, "ebitda_dollar_change": 1.0,
                "rev_direction": "narrowing", "ebitda_direction": "improved",
                "rev_state": "ahead", "n_snapshots": 2,
            },
            "top_movers": {"worst": [], "best": []},
            "division_breakdown": {},
        }
        out = fn(inputs, {})
        assert out["top_driver"] is None

    def test_single_snapshot_claims_no_trend(self):
        """n_snapshots == 1 -> pass-through flat/held_steady, trend labels are new_this_period."""
        fn = transformer_registry.get("narrative_facts").func
        inputs = {
            "variance_analysis": {
                "first_snapshot": "20260701", "last_snapshot": "20260701", "first_totals": {},
                "last_totals": {}, "rev_pct_change": 0.0, "ebitda_dollar_change": 0.0,
                "rev_direction": "flat", "ebitda_direction": "held_steady",
                "rev_state": "behind", "n_snapshots": 1,
            },
            "top_movers": {
                "worst": [{"division": "D", "project": "P", "ebitda_variance": -1000.0, "trend": None}],
                "best": [{"division": "D", "project": "Q", "ebitda_variance": 500.0, "trend": None}],
            },
            "division_breakdown": {},
        }
        out = fn(inputs, {})
        assert out["headline"]["rev_direction"] == "flat"
        assert out["headline"]["ebitda_direction"] == "held_steady"
        assert out["n_snapshots"] == 1
        assert out["watch"][0]["trend_basis"] == "new_this_period"
        assert out["bright"][0]["trend_basis"] == "new_this_period"

    def test_zero_budget_division_does_not_raise(self):
        """Mirrors the library.py:98 division-by-zero guard — no division here at all."""
        fn = transformer_registry.get("narrative_facts").func
        inputs = {
            "variance_analysis": {
                "first_snapshot": "a", "last_snapshot": "b", "first_totals": {},
                "last_totals": {}, "rev_pct_change": 0.0, "ebitda_dollar_change": 0.0,
                "rev_direction": "flat", "ebitda_direction": "held_steady",
                "rev_state": "behind", "n_snapshots": 1,
            },
            "top_movers": {"worst": [], "best": []},
            "division_breakdown": {
                "ZeroBudget": {
                    "ebitda_variance": 0.0,
                    "projects": [{"name": "Z", "ebitda_variance": 0.0}],
                },
            },
        }
        out = fn(inputs, {})
        assert out["division_reads"][0]["kind"] == "on_track"

    def test_emits_no_prose(self, upstream_outputs):
        """No output value may read as an English sentence."""
        import re

        fn = transformer_registry.get("narrative_facts").func
        out = fn(upstream_outputs, {})

        def walk(v):
            if isinstance(v, str):
                assert not re.search(r"\s\w+\s\w+\s\w+\s", v), f"prose leaked: {v!r}"
            elif isinstance(v, dict):
                for i in v.values():
                    walk(i)
            elif isinstance(v, list):
                for i in v:
                    walk(i)

        walk(out)

    def test_pure_and_deterministic(self, upstream_outputs):
        fn = transformer_registry.get("narrative_facts").func
        assert fn(upstream_outputs, {}) == fn(upstream_outputs, {})
