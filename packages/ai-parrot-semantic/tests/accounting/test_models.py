"""FEAT-713 M2 — model-definition contract validators."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from parrot.semantic.accounting.models import (
    AccountingModel,
    AccountingModelSpec,
    AccountingRequest,
    AccountSet,
    AssertionRequest,
    ChartOfAccounts,
    JournalSource,
    MetricPlan,
    MetricRequest,
    NatureSpec,
    PlanExpr,
)

_FRAME = {"dataframe": "journal"}
_NATURE = {"from_column": "nature"}


def _chart(**overrides: Any) -> ChartOfAccounts:
    payload: dict[str, Any] = {"source": _FRAME, "account_key": "account_id", "posting_date": "posting_date"}
    payload.update(overrides)
    return ChartOfAccounts.model_validate(payload)


def _spec_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": "troc_pnl",
        "version": "2026.10",
        "tenant": "troc",
        "chart_of_accounts": {
            "source": _FRAME,
            "account_key": "account_id",
            "posting_date": "posting_date",
            "amount_convention": "debit_positive",
            "amount": "amount",
            "nature": _NATURE,
        },
        "sets": {"sales": {"accounts": ["4000"]}},
        "metrics": {"revenue": {"expr": "sum(sales)"}},
    }
    payload.update(overrides)
    return payload


def test_amount_convention_required() -> None:
    with pytest.raises(ValidationError):
        _chart(amount="amount", nature=_NATURE)

    # Single-amount conventions need `amount` and `nature`.
    for convention in ("debit_positive", "credit_positive"):
        assert _chart(amount_convention=convention, amount="amount", nature=_NATURE).amount == "amount"
        with pytest.raises(ValidationError):
            _chart(amount_convention=convention, nature=_NATURE)
        with pytest.raises(ValidationError):
            _chart(amount_convention=convention, amount="amount")

    # debit_credit_columns needs debit + credit, no amount, and nature.
    chart = _chart(amount_convention="debit_credit_columns", debit="dr", credit="cr", nature=_NATURE)
    assert (chart.debit, chart.credit, chart.amount) == ("dr", "cr", None)
    with pytest.raises(ValidationError):
        _chart(amount_convention="debit_credit_columns", debit="dr", nature=_NATURE)
    with pytest.raises(ValidationError):
        _chart(amount_convention="debit_credit_columns", credit="cr", nature=_NATURE)
    with pytest.raises(ValidationError):
        _chart(amount_convention="debit_credit_columns", debit="dr", credit="cr", amount="amount", nature=_NATURE)
    with pytest.raises(ValidationError):
        _chart(amount_convention="debit_credit_columns", debit="dr", credit="cr")

    # natural_balance needs `amount`; nature is optional.
    assert _chart(amount_convention="natural_balance", amount="amount").nature is None
    with pytest.raises(ValidationError):
        _chart(amount_convention="natural_balance")

    with pytest.raises(ValidationError):
        _chart(amount_convention="signed", amount="amount", nature=_NATURE)

    # nature: from_column XOR accounts.
    assert NatureSpec(accounts={"4000": "credit"}).accounts == {"4000": "credit"}
    with pytest.raises(ValidationError):
        NatureSpec()
    with pytest.raises(ValidationError):
        NatureSpec(from_column="nature", accounts={"4000": "credit"})


def test_journal_source_rules() -> None:
    assert JournalSource(dataframe="journal").dataframe == "journal"
    table = JournalSource(table="gl.journal", connection="finance", driver="pg")
    assert table.table == "gl.journal"

    with pytest.raises(ValidationError):
        JournalSource()
    with pytest.raises(ValidationError):
        JournalSource(table="gl.journal", dataframe="journal", connection="finance", driver="pg")
    with pytest.raises(ValidationError):
        JournalSource(table="gl.journal", driver="pg")
    with pytest.raises(ValidationError):
        JournalSource(table="gl.journal", connection="finance")


def test_account_set_rules() -> None:
    account_set = AccountSet.model_validate({"select": {"prefix": "5"}, "except": ["5900"]})
    assert account_set.except_ == ("5900",)
    assert AccountSet(accounts=("4000",), except_=("4010",)).except_ == ("4010",)

    with pytest.raises(ValidationError):
        AccountSet()
    with pytest.raises(ValidationError):
        AccountSet(accounts=("6810",), valid_from=date(2025, 1, 1), valid_to=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        AccountSet(accounts=("6810",), valid_from=date(2025, 2, 1), valid_to=date(2025, 1, 1))


def test_reserved_metric_name_rejected() -> None:
    assert AccountingModelSpec.model_validate(_spec_payload()).metrics["revenue"].expr == "sum(sales)"
    with pytest.raises(ValidationError, match="__validate__"):
        AccountingModelSpec.model_validate(_spec_payload(metrics={"__validate__": {"expr": "sum(sales)"}}))


def test_natures_sorted_unique() -> None:
    spec = AccountingModelSpec.model_validate(_spec_payload())
    base: dict[str, Any] = {
        "spec": spec,
        "snapshot_hash": "s" * 64,
        "intervals": ((None, date(2025, 1, 1)), (date(2025, 1, 1), None)),
        "sets": {"sales": {"name": "sales", "accounts": ("4000",), "valid_from": None, "valid_to": None}},
        "model_hash": "m" * 64,
    }

    with pytest.raises(ValidationError):
        AccountingModel(**base, natures=(("5000", "debit"), ("4000", "credit")))
    with pytest.raises(ValidationError):
        AccountingModel(**base, natures=(("4000", "credit"), ("4000", "debit")))

    model = AccountingModel(**base, natures=(("4000", "credit"), ("5000", "debit")))
    restored = AccountingModel.model_validate_json(model.model_dump_json())
    assert restored == model
    assert restored.natures == (("4000", "credit"), ("5000", "debit"))
    assert isinstance(restored.natures, tuple) and all(isinstance(pair, tuple) for pair in restored.natures)
    assert isinstance(restored.intervals[0], tuple)
    assert hash(restored.natures) == hash(model.natures)


_PERIOD = {"from": "2025-01-01", "to": "2025-03-31"}


def test_request_cumulative_fits_grain() -> None:
    allowed = {
        "mtd": {"day", "month"},
        "qtd": {"day", "month", "quarter"},
        "ytd": {"day", "month", "quarter", "year"},
    }
    for cumulative, grains in allowed.items():
        for grain in ("day", "week", "month", "quarter", "year", None):
            payload = {"metric": "revenue", "grain": grain, "period": {**_PERIOD, "cumulative": cumulative}}
            if grain in grains:
                assert MetricRequest.model_validate(payload).period.cumulative == cumulative
            else:
                with pytest.raises(ValidationError):
                    MetricRequest.model_validate(payload)

    # Non-cumulative requests accept any grain, week and None included.
    for grain in ("day", "week", "month", "quarter", "year", None):
        assert MetricRequest.model_validate({"metric": "revenue", "grain": grain, "period": _PERIOD}).grain == grain

    # Period ordering: from <= to (equal is a valid single day).
    assert MetricRequest.model_validate(
        {"metric": "revenue", "period": {"from": "2025-01-01", "to": "2025-01-01"}}
    ).period.from_ == date(2025, 1, 1)
    with pytest.raises(ValidationError):
        MetricRequest.model_validate({"metric": "revenue", "period": {"from": "2025-02-01", "to": "2025-01-31"}})


def test_accounting_request_discriminates() -> None:
    adapter: TypeAdapter[Any] = TypeAdapter(AccountingRequest)

    metric = adapter.validate_json('{"kind": "metric", "metric": "revenue", "grain": "month", "period": %s}'
                                   % '{"from": "2025-01-01", "to": "2025-03-31", "cumulative": "ytd"}')
    assert isinstance(metric, MetricRequest)
    assert metric.metric == "revenue"

    assertion = adapter.validate_json('{"kind": "assertion", "assertion_index": 0, '
                                      '"period": {"from": "2025-01-01", "to": "2025-03-31"}}')
    assert isinstance(assertion, AssertionRequest)
    assert assertion.assertion_index == 0

    with pytest.raises(ValidationError):
        adapter.validate_json('{"kind": "assertion", "assertion_index": 0, '
                              '"period": {"from": "2025-01-01", "to": "2025-03-31", "cumulative": "mtd"}}')
    with pytest.raises(ValidationError):
        adapter.validate_json('{"kind": "assertion", "assertion_index": -1, '
                              '"period": {"from": "2025-01-01", "to": "2025-03-31"}}')
    with pytest.raises(ValidationError):
        adapter.validate_json('{"kind": "report", "period": {"from": "2025-01-01", "to": "2025-03-31"}}')


def _plan(formula: PlanExpr, **overrides: Any) -> MetricPlan:
    payload: dict[str, Any] = {
        "table": "gl.journal",
        "account_key": "account_id",
        "posting_date": "posting_date",
        "amount_convention": "debit_positive",
        "amount": "amount",
        "debit": None,
        "credit": None,
        "natures": (("4000", "credit"), ("5000", "debit")),
        "cast_decimal": True,
        "sets": ({"alias": "s0", "accounts": ("4000",)}, {"alias": "s1", "accounts": ("5000",)}),
        "columns": (("gross_margin", formula),),
        "grain": "month",
        "dimensions": ("store_id",),
        "filters": (("store_id", ("A", 7)),),
        "scan_from": date(2025, 1, 1),
        "output_from": date(2025, 1, 1),
        "to_exclusive": date(2025, 4, 1),
        "cumulative": "ytd",
    }
    payload.update(overrides)
    return MetricPlan.model_validate(payload)


def test_plan_round_trips_json() -> None:
    formula = PlanExpr(op="sub", args=(PlanExpr(op="set", alias="s0"), PlanExpr(op="set", alias="s1")))
    plan = _plan(formula)

    restored = MetricPlan.model_validate_json(plan.model_dump_json())
    assert restored == plan
    assert restored.columns[0][1].args[0].alias == "s0"
    assert restored.plan_hash == plan.plan_hash
    assert len(plan.plan_hash) == 64
    assert _plan(formula).plan_hash == plan.plan_hash

    other = PlanExpr(op="add", args=(PlanExpr(op="set", alias="s0"), PlanExpr(op="num", value="1.5")))
    assert _plan(other).plan_hash != plan.plan_hash
    assert _plan(formula, cast_decimal=False).plan_hash != plan.plan_hash
    assert _plan(formula, cumulative=None).plan_hash != plan.plan_hash
    assert {"result_scale", "rounding", "arithmetic_version"} <= set(plan.model_dump(mode="json"))
