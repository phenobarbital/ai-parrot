"""FEAT-713 M5 — planning."""

from __future__ import annotations

import copy
import json
from datetime import date
from decimal import Decimal

import pytest
import yaml

from parrot.semantic.accounting.compiler import canonical_request, plan_assertion, plan_metric
from parrot.semantic.accounting.errors import PeriodSpansMembershipChange, RequestValidationError
from parrot.semantic.accounting.loader import load_model
from parrot.semantic.accounting.models import AssertionRequest, MetricPlan, MetricRequest, PlanExpr, PlanSet

_PLAIN = (dict, list, tuple, str, int, bool, float, Decimal, date, type(None))


def _request(**kwargs) -> MetricRequest:
    period = kwargs.pop("period")
    return MetricRequest.model_validate({**kwargs, "period": period})


def _walk(value: object) -> None:
    assert isinstance(value, _PLAIN), f"non-plain value in plan: {type(value)!r}"
    assert not type(value).__module__.startswith("sqlglot")
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk(item)


def _data(path) -> dict:
    return copy.deepcopy(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_plan_is_plain_json(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    request = _request(
        metric="gross_margin",
        grain="month",
        dimensions=("entity",),
        filters={"product_line": ("pokemon", "magic"), "cost_center": "CC100"},
        period={"from": "2025-02-15", "to": "2025-06-30"},
    )
    plan = plan_metric(model, request)
    _walk(plan.model_dump())
    assert MetricPlan.model_validate_json(plan.model_dump_json()) == plan
    assert json.loads(plan.model_dump_json())["schema_version"] == 1
    assert plan_metric(model, request).plan_hash == plan.plan_hash

    assert plan.table == "journal"
    assert plan.cast_decimal is False
    assert plan.scan_from == plan.output_from == date(2025, 2, 15)
    assert plan.to_exclusive == date(2025, 7, 1)
    assert [alias for alias, _ in plan.filters] == ["cost_center", "product_line"]
    assert dict(plan.filters)["product_line"] == ("magic", "pokemon")
    assert [s.alias for s in plan.sets] == ["set_cost_of_sales", "set_product_sales", "set_returns"]
    for plan_set in plan.sets:
        assert list(plan_set.accounts) == sorted(plan_set.accounts)
    used = {a for s in plan.sets for a in s.accounts}
    assert {a for a, _ in plan.natures} == used
    assert plan.columns[0][0] == "m_gross_margin"
    revenue = PlanExpr(
        op="sub", args=(PlanExpr(op="set", alias="set_product_sales"), PlanExpr(op="set", alias="set_returns"))
    )
    assert plan.columns[0][1] == PlanExpr(op="sub", args=(revenue, PlanExpr(op="set", alias="set_cost_of_sales")))

    key_request = json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))
    assert canonical_request(request) == key_request

    ytd = plan_metric(
        model,
        _request(
            metric="revenue", grain="month", period={"from": "2025-05-10", "to": "2025-06-30", "cumulative": "ytd"}
        ),
    )
    assert ytd.scan_from == date(2025, 1, 1)
    assert ytd.output_from == date(2025, 5, 10)
    assert ytd.cumulative == "ytd"
    qtd = plan_metric(
        model,
        _request(metric="revenue", grain="day", period={"from": "2025-05-10", "to": "2025-06-30", "cumulative": "qtd"}),
    )
    assert qtd.scan_from == date(2025, 4, 1)
    mtd = plan_metric(
        model,
        _request(metric="revenue", grain="day", period={"from": "2025-05-10", "to": "2025-05-30", "cumulative": "mtd"}),
    )
    assert mtd.scan_from == date(2025, 5, 1)


def test_refuse_membership_change(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    with pytest.raises(PeriodSpansMembershipChange) as info:
        plan_metric(model, _request(metric="revenue", period={"from": "2024-12-01", "to": "2025-01-31"}))
    assert info.value.boundary == date(2025, 1, 1)
    assert "2024-12-01..2024-12-31" in info.value.suggestion
    assert "2025-01-01..2025-01-31" in info.value.suggestion

    with pytest.raises(PeriodSpansMembershipChange) as info:
        plan_metric(
            model,
            _request(
                metric="revenue", grain="month", period={"from": "2024-12-01", "to": "2025-02-28", "cumulative": "ytd"}
            ),
        )
    assert info.value.boundary == date(2025, 1, 1)

    # Periods ending on / starting at the boundary do not cross it.
    plan_metric(model, _request(metric="revenue", period={"from": "2024-12-01", "to": "2024-12-31"}))
    plan_metric(model, _request(metric="revenue", period={"from": "2025-01-01", "to": "2025-01-31"}))

    # Widened ytd window crossing a mid-year boundary while the period itself does not.
    data = _data(troc_pnl_yaml)
    data["sets"]["d_and_a"]["valid_from"] = "2025-04-01"
    data["sets"]["d_and_a_legacy"]["valid_to"] = "2025-04-01"
    shifted = load_model(data, chart_snapshot)
    period = {"from": "2025-05-01", "to": "2025-05-31"}
    assert plan_metric(shifted, _request(metric="revenue", grain="month", period=period)).scan_from == date(2025, 5, 1)
    with pytest.raises(PeriodSpansMembershipChange) as info:
        plan_metric(shifted, _request(metric="revenue", grain="month", period={**period, "cumulative": "ytd"}))
    assert info.value.boundary == date(2025, 4, 1)
    assert "2025-01-01..2025-03-31" in info.value.suggestion
    assert "2025-04-01..2025-05-31" in info.value.suggestion
    qtd = plan_metric(shifted, _request(metric="revenue", grain="month", period={**period, "cumulative": "qtd"}))
    assert qtd.scan_from == date(2025, 4, 1)


def test_request_validation_errors(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="no_such_metric", period=period))
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="revenue", dimensions=("region",), period=period))
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="revenue", filters={"account_id": "4000"}, period=period))
    with pytest.raises(RequestValidationError):
        plan_metric(model, _request(metric="revenue", filters={"entity": ()}, period=period))

    data = _data(troc_pnl_yaml)
    data["metrics"]["revenue"]["dimensions"] = ["entity"]
    data["metrics"]["depreciation"] = {"expr": "sum(d_and_a)"}
    restricted = load_model(data, chart_snapshot)
    with pytest.raises(RequestValidationError):
        plan_metric(restricted, _request(metric="revenue", dimensions=("product_line",), period=period))
    plan_metric(restricted, _request(metric="revenue", dimensions=("entity",), period=period))
    with pytest.raises(RequestValidationError) as info:
        plan_metric(restricted, _request(metric="depreciation", period={"from": "2024-02-01", "to": "2024-02-28"}))
    assert not isinstance(info.value, PeriodSpansMembershipChange)
    plan = plan_metric(restricted, _request(metric="depreciation", period=period))
    assert plan.sets == (PlanSet(alias="set_d_and_a", accounts=("6810", "6820")),)


def test_plan_assertion_index(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    plan = plan_assertion(model, AssertionRequest.model_validate({"assertion_index": 0, "period": period}))
    assert [name for name, _ in plan.columns] == ["lhs", "rhs"]
    assert plan.columns[0][1] == plan.columns[1][1]
    assert plan.grain is None and plan.dimensions == () and plan.filters == () and plan.cumulative is None
    assert plan.scan_from == plan.output_from == date(2025, 2, 1)
    assert [s.alias for s in plan.sets] == ["set_cost_of_sales", "set_product_sales", "set_returns"]
    with pytest.raises(RequestValidationError):
        plan_assertion(model, AssertionRequest.model_validate({"assertion_index": 1, "period": period}))
    with pytest.raises(PeriodSpansMembershipChange):
        plan_assertion(
            model,
            AssertionRequest.model_validate(
                {"assertion_index": 0, "period": {"from": "2024-12-01", "to": "2025-01-31"}}
            ),
        )


def test_plan_hash_formula_identity(troc_pnl_yaml, chart_snapshot) -> None:
    model = load_model(troc_pnl_yaml, chart_snapshot)
    period = {"from": "2025-02-01", "to": "2025-02-28"}
    margin = plan_metric(model, _request(metric="gross_margin", grain="month", period=period))
    ratio = plan_metric(model, _request(metric="gross_margin_pct", grain="month", period=period))
    assert margin.sets == ratio.sets
    assert margin.natures == ratio.natures
    assert margin.plan_hash != ratio.plan_hash
    assert (
        plan_metric(model, _request(metric="gross_margin", grain="month", period=period)).plan_hash == margin.plan_hash
    )
