"""Shared exact formula evaluation (FEAT-713, spec numeric contract rev 0.3). Standard library only."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Mapping, Sequence

from .errors import AccountingExecutionError
from .models import MetricPlan, PlanExpr

_SCALE = 10**6
_MAX_INPUT_INTEGER = 10**32
_MAX_SCALED = 10**38


def _decimal_to_fraction(value: Decimal, *, column: str) -> Fraction:
    """Validate a Decimal against DECIMAL(38,6) and return it as an exact Fraction."""
    if not value.is_finite():
        raise AccountingExecutionError(f"aggregate {column!r} is not finite: {value!r}")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -6 and value != value.quantize(Decimal(1).scaleb(-6)):
        raise AccountingExecutionError(f"aggregate {column!r} exceeds scale 6: {value!r}")
    fraction = Fraction(value)
    if abs(fraction) >= _MAX_INPUT_INTEGER:
        raise AccountingExecutionError(f"aggregate {column!r} exceeds DECIMAL(38,6): {value!r}")
    return fraction


def _to_fraction(value: Any, *, column: str) -> Fraction:
    """Exact Fraction for one aggregate value; None => 0.

    Raises:
        AccountingExecutionError: float/bool/NaN/inf/malformed string, or a value outside DECIMAL(38,6).
    """
    if value is None:
        return Fraction(0)
    if isinstance(value, bool):
        raise AccountingExecutionError(f"aggregate {column!r} is a bool, expected an exact number")
    if isinstance(value, Decimal):
        return _decimal_to_fraction(value, column=column)
    if isinstance(value, int):
        return _decimal_to_fraction(Decimal(value), column=column)
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation as exc:
            raise AccountingExecutionError(f"aggregate {column!r} is a malformed number: {value!r}") from exc
        return _decimal_to_fraction(parsed, column=column)
    raise AccountingExecutionError(f"aggregate {column!r} has unsupported type {type(value).__name__}")


def _eval(expr: PlanExpr, sets: Mapping[str, Fraction]) -> Fraction | None:
    """Exact evaluation; division by zero yields None, which propagates."""
    op = expr.op
    if op == "set":
        return sets[expr.alias]  # type: ignore[index]
    if op == "num":
        return Fraction(Decimal(expr.value))  # type: ignore[arg-type]
    values = [_eval(arg, sets) for arg in expr.args]
    if any(v is None for v in values):
        return None
    if op == "neg":
        return -values[0]  # type: ignore[operator]
    left, right = values[0], values[1]
    if op == "add":
        return left + right  # type: ignore[operator]
    if op == "sub":
        return left - right  # type: ignore[operator]
    if op == "mul":
        return left * right  # type: ignore[operator]
    if op == "div":
        if right == 0:
            return None
        return left / right  # type: ignore[operator]
    raise AccountingExecutionError(f"unknown plan operator {op!r}")


def _quantize(value: Fraction) -> Decimal:
    """Round once to scale 6, half-even, with integer arithmetic only; overflow => AccountingExecutionError."""
    scaled = value * _SCALE
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    twice = 2 * remainder
    if twice > scaled.denominator or (twice == scaled.denominator and quotient % 2 == 1):
        quotient += 1
    if abs(quotient) >= _MAX_SCALED:
        raise AccountingExecutionError("result exceeds DECIMAL(38,6)")
    sign = 1 if quotient < 0 else 0
    return Decimal((sign, tuple(int(d) for d in str(abs(quotient))), -6))


def evaluate_rows(plan: MetricPlan, rows: Sequence[Mapping[str, Any]]) -> tuple[dict, ...]:
    """Validate exact aggregates, evaluate formulas and round final columns once; preserve grain/dimensions.

    Raises:
        AccountingExecutionError: floats, malformed aggregates or precision/scale overflow.
    """
    aliases = [s.alias for s in plan.sets]
    out: list[dict] = []
    for row in rows:
        sets = {alias: _to_fraction(row.get(alias), column=alias) for alias in aliases}
        result = {key: value for key, value in row.items() if key not in sets}
        for name, expr in plan.columns:
            value = _eval(expr, sets)
            result[name] = None if value is None else _quantize(value)
        out.append(result)
    return tuple(out)
