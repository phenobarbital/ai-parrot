"""FEAT-713 — exact evaluation, rounding and rejection."""

from __future__ import annotations

from decimal import Decimal

import pytest

from parrot.semantic.accounting.errors import AccountingExecutionError
from parrot.semantic.accounting.evaluation import evaluate_rows
from parrot.semantic.accounting.models import MetricPlan, PlanExpr, PlanSet


def _s(alias: str) -> PlanExpr:
    return PlanExpr(op="set", alias=alias)


def _n(value: str) -> PlanExpr:
    return PlanExpr(op="num", value=value)


def _op(op: str, *args: PlanExpr) -> PlanExpr:
    return PlanExpr(op=op, args=tuple(args))


def _plan(columns: dict[str, PlanExpr]) -> MetricPlan:
    return MetricPlan.model_construct(
        sets=tuple(PlanSet(alias=a, accounts=("1",)) for a in ("a", "b", "c")),
        columns=tuple(columns.items()),
        grain=None,
        dimensions=("region",),
    )


def test_exact_formula_evaluation() -> None:
    plan = _plan(
        {
            "big": _op("div", _s("a"), _n("1")),
            "third": _op("div", _n("1"), _n("3")),
            "cancel": _op("mul", _op("sub", _op("add", _s("a"), _s("b")), _s("b")), _s("c")),
        }
    )
    rows = [{"region": "x", "a": 9007199254740993, "b": "0.1", "c": Decimal("2")}]
    (out,) = evaluate_rows(plan, rows)
    assert out["big"] == Decimal("9007199254740993.000000")
    assert out["third"] == Decimal("0.333333")
    assert out["cancel"] == Decimal("18014398509481986.000000")
    assert out["region"] == "x"
    assert "a" not in out


def test_rounding_and_overflow() -> None:
    plan = _plan({"v": _op("mul", _s("a"), _n("1"))})
    half = _plan({"v": _op("div", _s("a"), _n("10"))})
    # ties go half-even at scale 6 (a/10 with a = 0.000005 -> 0.0000005)
    assert evaluate_rows(half, [{"a": "0.000005"}])[0]["v"] == Decimal("0.000000")
    assert evaluate_rows(half, [{"a": "0.000015"}])[0]["v"] == Decimal("0.000002")
    assert evaluate_rows(half, [{"a": "-0.000015"}])[0]["v"] == Decimal("-0.000002")
    assert evaluate_rows(half, [{"a": "0.000025"}])[0]["v"] == Decimal("0.000002")
    neg = _plan({"v": _op("div", _s("a"), _n("-3"))})
    assert evaluate_rows(neg, [{"a": "1"}])[0]["v"] == Decimal("-0.333333")
    big = Decimal("9" * 32 + "." + "9" * 6)
    assert evaluate_rows(plan, [{"a": big}])[0]["v"] == big
    with pytest.raises(AccountingExecutionError):
        evaluate_rows(plan, [{"a": Decimal(10**32)}])
    grow = _plan({"v": _op("mul", _s("a"), _n("10"))})
    with pytest.raises(AccountingExecutionError):
        evaluate_rows(grow, [{"a": big}])
    wide = _plan({"v": _op("sub", _op("mul", _s("a"), _s("a")), _op("mul", _s("a"), _s("a")))})
    assert evaluate_rows(wide, [{"a": big}])[0]["v"] == Decimal("0.000000")


@pytest.mark.parametrize("bad", [1.5, float("nan"), float("inf"), "1e3x", True, Decimal("NaN"), Decimal("0.0000001")])
def test_invalid_aggregate_values(bad) -> None:
    plan = _plan({"v": _s("a")})
    with pytest.raises(AccountingExecutionError):
        evaluate_rows(plan, [{"a": bad}])
    zero = _plan({"v": _op("add", _op("div", _s("a"), _s("b")), _n("1"))})
    assert evaluate_rows(zero, [{"a": 1, "b": 0}])[0]["v"] is None
    assert evaluate_rows(zero, [{"a": None, "b": None}])[0]["v"] is None
