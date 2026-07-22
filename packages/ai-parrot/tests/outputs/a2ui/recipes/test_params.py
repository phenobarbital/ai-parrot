"""Substitution + resolver tests for FEAT-324 Module 1 (`parrot.outputs.a2ui.recipes.params`)."""

from datetime import datetime, timezone

import pytest

from parrot.outputs.a2ui.recipes.models import RecipeParam
from parrot.outputs.a2ui.recipes.params import resolve_date, resolve_params, substitute

_NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)  # a Wednesday, mid-July


def test_resolver_current_month():
    assert resolve_date("current_month", now=_NOW) == "2026-07"


def test_resolver_previous_month():
    assert resolve_date("previous_month", now=_NOW) == "2026-06"


def test_resolver_previous_month_crosses_year_boundary():
    jan = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert resolve_date("previous_month", now=jan) == "2025-12"


def test_resolver_today():
    assert resolve_date("today", now=_NOW) == "2026-07-22"


def test_resolver_yesterday():
    assert resolve_date("yesterday", now=_NOW) == "2026-07-21"


def test_resolver_first_of_month():
    assert resolve_date("first_of_month", now=_NOW) == "2026-07-01"


def test_resolver_unknown_name_raises():
    with pytest.raises(ValueError, match="Unknown date resolver"):
        resolve_date("next_quarter", now=_NOW)


def test_resolver_respects_timezone():
    # 2026-07-22T23:30 UTC is already 2026-07-23 in UTC+1
    late_utc = datetime(2026, 7, 22, 23, 30, tzinfo=timezone.utc)
    assert resolve_date("today", tz="UTC", now=late_utc) == "2026-07-22"


def test_resolve_params_uses_default_resolver():
    declared = [RecipeParam(name="month", default="current_month")]
    resolved = resolve_params(declared, now=_NOW)
    assert resolved == {"month": "2026-07"}


def test_resolve_params_literal_default():
    declared = [RecipeParam(name="division", default="all")]
    resolved = resolve_params(declared)
    assert resolved == {"division": "all"}


def test_resolve_params_override_wins():
    declared = [RecipeParam(name="month", default="current_month")]
    resolved = resolve_params(declared, overrides={"month": "2026-01"}, now=_NOW)
    assert resolved == {"month": "2026-01"}


def test_resolve_params_missing_default_and_override_raises():
    declared = [RecipeParam(name="month", default=None)]
    with pytest.raises(ValueError, match="no default"):
        resolve_params(declared)


def test_undeclared_override_rejected():
    declared = [RecipeParam(name="month", default="current_month")]
    with pytest.raises(ValueError, match="not declared"):
        resolve_params(declared, overrides={"typo_param": "x"})


def test_substitute_leaves_no_placeholders():
    assert substitute("WHERE month = '{month}'", {"month": "2026-07"}) == "WHERE month = '2026-07'"


def test_substitute_multiple_placeholders():
    result = substitute("{division}/{month}", {"division": "sales", "month": "2026-07"})
    assert result == "sales/2026-07"


def test_substitute_unknown_placeholder_raises():
    with pytest.raises(ValueError, match="no resolved value"):
        substitute("{typo}", {"month": "2026-07"})
