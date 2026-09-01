"""Unit tests for `agents/flex_dashboard/transformers.py` (FEAT-491 TASK-2694)."""

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest
from parrot.outputs.a2ui.recipes.transformers import transformer_registry

# Same worktree-safe file-path loading technique as
# `test_finance_reporter_descriptors.py::_load_finance_reporter` and
# `test_flex_dashboard_normalize.py::_load_normalize`. `transformers.py`
# additionally does `from agents.flex_dashboard.normalize import ...` (an
# absolute, real package import) — to make that resolve deterministically
# from THIS worktree's files (and not risk crossing into a different
# worktree's `agents/` via ambient sys.path state), the full package chain
# ("agents" -> "agents.flex_dashboard" -> "...normalize" -> "...transformers")
# is pre-registered in `sys.modules` in dependency order before exec'ing
# transformers.py, so its internal import resolves purely from cache.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_AGENTS_DIR = _REPO_ROOT / "agents"
_FLEX_DIR = _AGENTS_DIR / "flex_dashboard"


def _load_package(name: str, init_path: Path, search_dir: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, init_path, submodule_search_locations=[str(search_dir)])
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load package {name!r} from {init_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_module(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _load_flex_transformers():
    _load_package("agents", _AGENTS_DIR / "__init__.py", _AGENTS_DIR)
    _load_package("agents.flex_dashboard", _FLEX_DIR / "__init__.py", _FLEX_DIR)
    _load_module("agents.flex_dashboard.normalize", _FLEX_DIR / "normalize.py")
    return _load_module("agents.flex_dashboard.transformers", _FLEX_DIR / "transformers.py")


@pytest.fixture(scope="module")
def loaded_flex_transformers():
    return _load_flex_transformers()


_EXPECTED_TRANSFORMERS = [
    "payroll_hero",
    "worked_hours_by_month",
    "payroll_by_month",
    "revenue_by_month",
    "payroll_pct_by_month",
    "pay_code_hours",
    "pay_code_allocation",
    "rep_utilization_by_region",
    "proximity_staffing",
    "flex_narrative_facts",
]


def test_transformers_registered(loaded_flex_transformers):
    for name in _EXPECTED_TRANSFORMERS:
        assert transformer_registry.get(name) is not None


class TestPayrollHero:
    def test_payroll_hero_totals(self, loaded_flex_transformers, flex_frames):
        payroll_hero = loaded_flex_transformers.payroll_hero
        out = payroll_hero({"hours": flex_frames["hours"], "finance": flex_frames["finance"]}, {})

        expected_hours = flex_frames["hours"]["hours"].sum()
        assert out["worked_hours_total"] == pytest.approx(expected_hours, abs=0.01)
        assert out["payroll_total"] == pytest.approx(18000.0 + 20682.27, abs=0.01)
        assert out["revenue_total"] == pytest.approx(120000.0 + 137456.85, abs=0.01)

    def test_payroll_pct_denominator(self, loaded_flex_transformers, flex_frames):
        """Regression pin: denominator is Revenue ALONE, not Revenue + PC Revenue."""
        payroll_hero = loaded_flex_transformers.payroll_hero
        out = payroll_hero({"hours": flex_frames["hours"], "finance": flex_frames["finance"]}, {})

        payroll_total = 18000.0 + 20682.27
        revenue_total = 120000.0 + 137456.85
        pc_revenue_total = 40000.0 + 51229.85

        assert out["payroll_pct"] == pytest.approx(payroll_total / revenue_total, rel=1e-6)
        # NOT payroll / (revenue + pc_revenue)
        wrong_pct = payroll_total / (revenue_total + pc_revenue_total)
        assert out["payroll_pct"] != pytest.approx(wrong_pct, rel=1e-6)

    def test_payroll_hero_reflects_active_filters(self, loaded_flex_transformers, flex_frames):
        """Code-review finding (adopted): the hero row must narrow with the
        SAME filters as the rest of the dashboard — a month-filtered replay
        must not show all-time totals in the hero cards."""
        payroll_hero = loaded_flex_transformers.payroll_hero
        unfiltered = payroll_hero({"hours": flex_frames["hours"], "finance": flex_frames["finance"]}, {})
        filtered = payroll_hero(
            {"hours": flex_frames["hours"], "finance": flex_frames["finance"]},
            {"month": "2025-10"},
        )

        assert filtered["worked_hours_total"] == pytest.approx(30.199996 + 1900.0)
        assert filtered["payroll_total"] == pytest.approx(20682.27)
        assert filtered["revenue_total"] == pytest.approx(137456.85)
        assert filtered["worked_hours_total"] != pytest.approx(unfiltered["worked_hours_total"])

    def test_payroll_hero_pay_code_filter(self, loaded_flex_transformers, flex_frames):
        payroll_hero = loaded_flex_transformers.payroll_hero
        out = payroll_hero(
            {"hours": flex_frames["hours"], "finance": flex_frames["finance"]},
            {"pay_code": "Admin Time"},
        )
        # Only Admin Time hours narrow; finance has no pay_code column, so
        # its totals stay at the full (unfiltered) amount.
        assert out["worked_hours_total"] == pytest.approx(25.0 + 30.199996)
        assert out["payroll_total"] == pytest.approx(18000.0 + 20682.27)


class TestMonthSeriesTransformers:
    def test_worked_hours_by_month(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.worked_hours_by_month({"hours": flex_frames["hours"]}, {})
        series = {row["month"]: row["worked_hours"] for row in out["series"]}
        assert series["2025-09"] == pytest.approx(25.0 + 1800.0)
        assert series["2025-10"] == pytest.approx(30.199996 + 1900.0)

    def test_payroll_by_month(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.payroll_by_month({"finance": flex_frames["finance"]}, {})
        series = {row["month"]: row["payroll"] for row in out["series"]}
        assert series["2025-09"] == pytest.approx(18000.0)
        assert series["2025-10"] == pytest.approx(20682.27)

    def test_revenue_by_month(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.revenue_by_month({"finance": flex_frames["finance"]}, {})
        series = {row["month"]: row["revenue"] for row in out["series"]}
        assert series["2025-09"] == pytest.approx(120000.0)
        assert series["2025-10"] == pytest.approx(137456.85)

    def test_payroll_pct_by_month(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.payroll_pct_by_month({"finance": flex_frames["finance"]}, {})
        series = {row["month"]: row["payroll_pct"] for row in out["series"]}
        assert series["2025-09"] == pytest.approx(18000.0 / 120000.0, rel=1e-6)
        assert series["2025-10"] == pytest.approx(20682.27 / 137456.85, rel=1e-6)

    def test_month_filter_narrows_series(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.payroll_by_month({"finance": flex_frames["finance"]}, {"month": "2025-10"})
        assert [row["month"] for row in out["series"]] == ["2025-10"]


class TestPayCodeSections:
    def test_pay_code_hours(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.pay_code_hours({"hours": flex_frames["hours"]}, {})
        records = {row["pay_code"]: row["hours"] for row in out["records"]}
        assert records["Admin Time"] == pytest.approx(25.0 + 30.199996)
        assert records["Field Time"] == pytest.approx(1800.0 + 1900.0)

    def test_pay_code_hours_respects_pay_code_param(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.pay_code_hours({"hours": flex_frames["hours"]}, {"pay_code": "Admin Time"})
        assert [r["pay_code"] for r in out["records"]] == ["Admin Time"]

    def test_pay_code_allocation(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.pay_code_allocation({"hours": flex_frames["hours"]}, {})
        shares = {row["pay_code"]: row["share_pct"] for row in out["records"]}
        assert sum(shares.values()) == pytest.approx(100.0, abs=0.01)

    def test_pay_code_allocation_honors_pay_code_filter(self, loaded_flex_transformers, flex_frames):
        """Code-review finding (adopted): consistent with the sibling
        pay_code_hours table — a pay_code filter narrows the allocation
        base too (trivially 100% for the one selected code)."""
        out = loaded_flex_transformers.pay_code_allocation({"hours": flex_frames["hours"]}, {"pay_code": "Admin Time"})
        assert [r["pay_code"] for r in out["records"]] == ["Admin Time"]
        assert out["records"][0]["share_pct"] == pytest.approx(100.0)
        assert out["total_hours"] == pytest.approx(25.0 + 30.199996)

    def test_per_section_filters(self, loaded_flex_transformers, flex_frames):
        """A flex_type param must never reach/alter a finance-only transformer."""
        baseline = loaded_flex_transformers.payroll_by_month({"finance": flex_frames["finance"]}, {})
        with_bogus_filter = loaded_flex_transformers.payroll_by_month(
            {"finance": flex_frames["finance"]}, {"flex_type": "Flex"}
        )
        assert baseline == with_bogus_filter


class TestRepUtilization:
    def test_rep_utilization_formula(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.rep_utilization_by_region(
            {
                "rep_utilization": flex_frames["rep_utilization"],
                "region_utilization": flex_frames["region_utilization"],
            },
            {},
        )
        by_region_month = {(r["region"], r["month"]): r for r in out["records"]}

        rep_ca = by_region_month[("CA", "2026-05")]
        assert rep_ca["utilization"] == pytest.approx(12 / 63, rel=1e-6)
        # region_utilization has no CA row for 2026-05 -> no cross-check available.
        assert rep_ca["cross_check_utilization"] is None

        rep_il = by_region_month[("IL", "2026-06")]
        assert rep_il["utilization"] == pytest.approx(10 / 50, rel=1e-6)

    def test_rep_utilization_cross_check_when_available(self, loaded_flex_transformers):
        """When region/category/month line up, the precomputed column is attached."""
        rep_df = pd.DataFrame(
            [
                {
                    "bop_date": "2026-03-01",
                    "eop_date": "2026-03-31",
                    "region": "CA",
                    "state": "CA",
                    "catagory": "Flex",
                    "hours_worked": 100.0,
                    "work_shifts": 10,
                    "employees_worked": 11,
                    "average_active": 75.5,
                }
            ]
        )
        region_df = pd.DataFrame(
            [
                {
                    "BOP Date": "2026-03-01",
                    "EOP Date": "2026-03-31",
                    "FM Region": "CA",
                    "State Code": "CA",
                    "State": "California",
                    "Category": "Flex",
                    "Employees Worked": 11,
                    "Average Active Employees": 75.5,
                    "Flex Employees": 68,
                    "Employee Utilization": 0.145695364238411,
                }
            ]
        )
        out = loaded_flex_transformers.rep_utilization_by_region(
            {"rep_utilization": rep_df, "region_utilization": region_df}, {}
        )
        record = out["records"][0]
        assert record["utilization"] == pytest.approx(11 / 75.5, rel=1e-6)
        assert record["cross_check_utilization"] == pytest.approx(0.145695364238411, rel=1e-6)


class TestProximityStaffing:
    def test_proximity_staffing(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.proximity_staffing(
            {"msl": flex_frames["msl"], "employees": flex_frames["employees"]}, {}
        )
        assert len(out["store_layer"]) == 3
        assert len(out["employee_layer"]) == 3
        assert out["radius_miles"] == 50
        assert out["nearest_n"] == 3

        coverage = {row["store_name"]: row for row in out["coverage"]}
        norridge = coverage["T-Mobile 3SFD Norridge IL"]
        # Jordan Reyes is seeded a few miles from the Norridge store.
        nearest_names = [e["display_name"] for e in norridge["nearest_employees"]]
        assert nearest_names[0] == "Jordan Reyes"
        assert norridge["nearest_employees"][0]["distance_miles"] < 5.0
        assert norridge["employees_within_radius"] >= 1

    def test_proximity_staffing_radius_and_nearest_n_params(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.proximity_staffing(
            {"msl": flex_frames["msl"], "employees": flex_frames["employees"]},
            {"radius_miles": 1, "nearest_n": 1},
        )
        assert out["radius_miles"] == 1
        assert out["nearest_n"] == 1
        for row in out["coverage"]:
            assert len(row["nearest_employees"]) <= 1

    def test_proximity_staffing_flex_type_filter(self, loaded_flex_transformers, flex_frames):
        out = loaded_flex_transformers.proximity_staffing(
            {"msl": flex_frames["msl"], "employees": flex_frames["employees"]},
            {"flex_type": "Core"},
        )
        assert len(out["employee_layer"]) == 1
        assert out["employee_layer"][0]["display_name"] == "Casey Kim"


class TestNarrativeFacts:
    def test_narrative_facts_consumes_prior_outputs(self, loaded_flex_transformers, flex_frames):
        hero = loaded_flex_transformers.payroll_hero(
            {"hours": flex_frames["hours"], "finance": flex_frames["finance"]}, {}
        )
        worked_hours = loaded_flex_transformers.worked_hours_by_month({"hours": flex_frames["hours"]}, {})
        utilization = loaded_flex_transformers.rep_utilization_by_region(
            {
                "rep_utilization": flex_frames["rep_utilization"],
                "region_utilization": flex_frames["region_utilization"],
            },
            {},
        )
        out = loaded_flex_transformers.flex_narrative_facts(
            {
                "payroll_hero": hero,
                "worked_hours_by_month": worked_hours,
                "rep_utilization_by_region": utilization,
            },
            {},
        )
        assert out["worked_hours_total"] == hero["worked_hours_total"]
        assert out["payroll_pct"] == hero["payroll_pct"]
        assert out["worked_hours_trend"] == "increasing"
        assert out["regions_tracked"] == ["CA", "IL"]
