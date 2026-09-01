"""Unit tests for `agents/flex_dashboard/normalize.py` (FEAT-491 TASK-2693)."""

import importlib.util
import math
import sys
from pathlib import Path

import pytest

# `agents/` is a local, gitignored-by-default directory (`/agents/` in
# .gitignore; individual agent files/packages must be `git add -f`'d to
# ship — see CLAUDE.md's "Heads-up" note on the equivalent `sdd/templates/`
# pattern). Some `parrot` submodule imports also trigger a settings
# bootstrap (`navconfig.conf`) that `os.chdir()`s to the MAIN repo checkout,
# which can make a plain `import agents.flex_dashboard.normalize` resolve
# inconsistently when tests run from a git worktree. Load the module
# directly from this worktree's own file path instead — same technique as
# `test_finance_reporter_descriptors.py::_load_finance_reporter`.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_NORMALIZE_PATH = _REPO_ROOT / "agents" / "flex_dashboard" / "normalize.py"


def _load_normalize():
    module_name = "agents.flex_dashboard.normalize"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, _NORMALIZE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {_NORMALIZE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture(scope="module")
def normalize():
    return _load_normalize()


class TestParseCurrency:
    def test_parse_currency(self, normalize):
        assert normalize.parse_currency("$137,456.85") == pytest.approx(137456.85)
        assert normalize.parse_currency("-$44,621.24") == pytest.approx(-44621.24)
        assert normalize.parse_currency("$0.00") == pytest.approx(0.0)

    def test_parse_currency_passthrough_numeric(self, normalize):
        assert normalize.parse_currency(42) == pytest.approx(42.0)
        assert normalize.parse_currency(3.14) == pytest.approx(3.14)

    def test_parse_currency_nan_safe(self, normalize):
        assert math.isnan(normalize.parse_currency(None))
        assert math.isnan(normalize.parse_currency(float("nan")))
        assert math.isnan(normalize.parse_currency(""))
        assert math.isnan(normalize.parse_currency("not-a-number"))

    def test_normalize_currency_columns(self, normalize, flex_frames):
        finance = flex_frames["finance"]
        currency_columns = [
            "Revenue",
            "PC Revenue",
            "EBITDA",
            "Payroll",
            "Travel and Expenses",
            "Program Overhead Allocation",
            "Other Related Expenses",
        ]
        out = normalize.normalize_currency_columns(finance, currency_columns)
        # Original frame is untouched (pure function, never mutate in place).
        assert finance["Revenue"].iloc[1] == "$137,456.85"
        assert out["Revenue"].iloc[1] == pytest.approx(137456.85)
        assert out["Other Related Expenses"].iloc[1] == pytest.approx(-44621.24)


class TestMonthAlignment:
    def test_month_alignment(self, normalize, flex_frames):
        finance_out = normalize.month_period(flex_frames["finance"], source="finance")
        assert finance_out["month"].iloc[1] == "2025-10"

        hours_out = normalize.month_period(flex_frames["hours"], source="hours")
        assert hours_out["month"].iloc[2] == "2025-10"

        region_out = normalize.month_period(flex_frames["region_utilization"], source="fm")
        assert region_out["month"].iloc[0] == "2026-03"

        rep_out = normalize.month_period(flex_frames["rep_utilization"], source="fm")
        assert rep_out["month"].iloc[0] == "2026-05"

    def test_month_period_does_not_mutate_input(self, normalize, flex_frames):
        # finance's own date column is already named "month" (spec §2); the
        # mutation check is that its RAW string values survive untouched.
        finance = flex_frames["finance"]
        normalize.month_period(finance, source="finance")
        assert finance["month"].iloc[0] == "2025-09-30"

        hours = flex_frames["hours"]
        normalize.month_period(hours, source="hours")
        assert "month" not in hours.columns

    def test_month_period_unknown_source_raises(self, normalize, flex_frames):
        with pytest.raises(ValueError):
            normalize.month_period(flex_frames["finance"], source="bogus")

    def test_month_period_missing_column_raises(self, normalize, flex_frames):
        with pytest.raises(KeyError):
            normalize.month_period(flex_frames["msl"], source="finance")


class TestColumnCanonicalization:
    def test_column_canonicalization(self, normalize, flex_frames):
        rep_out = normalize.canonicalize_columns(flex_frames["rep_utilization"], source="rep_utilization")
        assert "category" in rep_out.columns
        assert "catagory" not in rep_out.columns
        assert rep_out["category"].iloc[0] == "Flex"

        region_out = normalize.canonicalize_columns(flex_frames["region_utilization"], source="region_utilization")
        assert "region" in region_out.columns
        assert "state" in region_out.columns
        assert "employees_worked" in region_out.columns
        assert "average_active" in region_out.columns
        assert "employee_utilization" in region_out.columns
        assert "FM Region" not in region_out.columns

    def test_canonicalize_columns_does_not_mutate_input(self, normalize, flex_frames):
        rep = flex_frames["rep_utilization"]
        normalize.canonicalize_columns(rep, source="rep_utilization")
        assert "catagory" in rep.columns

    def test_canonicalize_columns_unknown_source_raises(self, normalize, flex_frames):
        with pytest.raises(ValueError):
            normalize.canonicalize_columns(flex_frames["msl"], source="bogus")
