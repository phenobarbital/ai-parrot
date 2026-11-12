"""Accounting compiler (FEAT-713 M5). Planning half; rendering is appended by TASK-5531.

Imports nothing from parrot.semantic outside the accounting package.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from pydantic import TypeAdapter

from .errors import PeriodSpansMembershipChange, RequestValidationError
from .grammar import BinOp, Expr, Neg, Num, Ref, Sum, parse_assertion, parse_expr
from .models import (
    AccountingModel,
    AccountingRequest,
    AssertionRequest,
    MetricPlan,
    MetricRequest,
    PlanExpr,
    PlanSet,
)
from .validation import metric_order

_REQUEST = TypeAdapter(AccountingRequest)

_BINOPS: dict[str, str] = {"+": "add", "-": "sub", "*": "mul", "/": "div"}
_ONE_DAY = timedelta(days=1)

Interval = tuple[date | None, date | None]


def canonical_request(request: MetricRequest | AssertionRequest) -> str:
    """Sorted-key compact JSON of the request, by alias — the cache-key and audit form.

    Args:
        request: A metric or assertion request.

    Returns:
        The exact ``<request JSON>`` string embedded in ``CompiledMetricQuery.cache_key``.
    """
    return json.dumps(request.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":"))


def _window_start(day: date, cumulative: str | None) -> date:
    """Start of the natural month / quarter / year containing *day*; *day* itself when not cumulative.

    Args:
        day: Any calendar day.
        cumulative: ``"mtd"``, ``"qtd"``, ``"ytd"`` or ``None``.

    Returns:
        The first day of the natural window, or *day* when *cumulative* is ``None``.
    """
    if cumulative == "mtd":
        return day.replace(day=1)
    if cumulative == "qtd":
        return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    if cumulative == "ytd":
        return date(day.year, 1, 1)
    return day


def _set_alias(name: str) -> str:
    """Plan alias of an account set."""
    return f"set_{name}"


def _lower(expr: Expr, model: AccountingModel, seen: frozenset[str] = frozenset()) -> PlanExpr:
    """Lower an AST to PlanExpr, inlining metric references (cycles were rejected at load).

    Args:
        expr: Parsed metric expression.
        model: The loaded model whose sets and metrics the expression refers to.
        seen: Metrics already being inlined on the current path (defensive cycle guard).

    Returns:
        The equivalent plan expression over ``set_<name>`` aliases.

    Raises:
        RequestValidationError: Unknown set or metric, or a reference cycle.
    """
    if isinstance(expr, Sum):
        if expr.set_name not in model.sets:
            raise RequestValidationError(f"unknown account set {expr.set_name!r}")
        return PlanExpr(op="set", alias=_set_alias(expr.set_name))
    if isinstance(expr, Num):
        return PlanExpr(op="num", value=str(expr.value))
    if isinstance(expr, Neg):
        return PlanExpr(op="neg", args=(_lower(expr.operand, model, seen),))
    if isinstance(expr, BinOp):
        return PlanExpr(
            op=_BINOPS[expr.op],  # type: ignore[arg-type]
            args=(_lower(expr.left, model, seen), _lower(expr.right, model, seen)),
        )
    if isinstance(expr, Ref):
        if expr.metric in seen:
            raise RequestValidationError(f"metric {expr.metric!r} references itself")
        metric = model.spec.metrics.get(expr.metric)
        if metric is None:
            raise RequestValidationError(f"unknown metric {expr.metric!r}")
        return _lower(parse_expr(metric.expr), model, seen | {expr.metric})
    raise RequestValidationError(f"unsupported expression node {type(expr).__name__}")


def _aliases(expr: PlanExpr) -> set[str]:
    """Every set alias referenced by *expr*."""
    found = {expr.alias} if expr.op == "set" and expr.alias is not None else set()
    for arg in expr.args:
        found |= _aliases(arg)
    return found


def _interval_for(model: AccountingModel, start: date, end_exclusive: date) -> tuple[date | None, date | None]:
    """The single membership interval containing [start, end_exclusive); else PeriodSpansMembershipChange.

    Args:
        model: The loaded model.
        start: First day of the scanned window.
        end_exclusive: Day after the last day of the window.

    Returns:
        The ``(start, end)`` half-open membership interval holding the whole window.

    Raises:
        PeriodSpansMembershipChange: A membership boundary falls strictly inside the window; the first such
            boundary is reported with the two sub-periods to request instead.
    """
    boundaries = sorted(
        {
            bound
            for interval in model.intervals
            for bound in interval
            if bound is not None and start < bound < end_exclusive
        }
    )
    if boundaries:
        boundary = boundaries[0]
        last = end_exclusive - _ONE_DAY
        raise PeriodSpansMembershipChange(
            boundary,
            (
                f"request {start.isoformat()}..{(boundary - _ONE_DAY).isoformat()} and "
                f"{boundary.isoformat()}..{last.isoformat()} as separate periods"
            ),
        )
    for low, high in model.intervals:
        if (low is None or low <= start) and (high is None or high >= end_exclusive):
            return low, high
    return None, None


def _active(valid_from: date | None, valid_to: date | None, interval: Interval) -> bool:
    """True when ``[valid_from, valid_to)`` contains the whole half-open *interval*."""
    low, high = interval
    if valid_from is not None and (low is None or low < valid_from):
        return False
    if valid_to is not None and (high is None or high > valid_to):
        return False
    return True


def _plan_sets(
    model: AccountingModel, columns: tuple[tuple[str, PlanExpr], ...], interval: Interval
) -> tuple[PlanSet, ...]:
    """Deduplicated, alias-sorted plan sets referenced by *columns*, each checked active in *interval*.

    Raises:
        RequestValidationError: A referenced set is not active for the whole membership interval.
    """
    aliases = set().union(*(_aliases(expr) for _, expr in columns)) if columns else set()
    by_alias = {_set_alias(name): resolved for name, resolved in model.sets.items()}
    plan_sets: list[PlanSet] = []
    for alias in sorted(aliases):
        resolved = by_alias[alias]
        if not _active(resolved.valid_from, resolved.valid_to, interval):
            raise RequestValidationError(
                f"account set {resolved.name!r} is not active over the requested period "
                f"(valid from {resolved.valid_from} to {resolved.valid_to})"
            )
        plan_sets.append(PlanSet(alias=alias, accounts=tuple(sorted(resolved.accounts))))
    return tuple(plan_sets)


def _filter_key(value: str | int) -> tuple[bool, str | int]:
    """Deterministic ordering for mixed int / str filter values (ints first)."""
    return isinstance(value, str), value


def _filters(model: AccountingModel, request: MetricRequest) -> tuple[tuple[str, tuple[str | int, ...]], ...]:
    """Validated filters, sorted by column with sorted, unique values.

    Raises:
        RequestValidationError: Filter on an undeclared column, or an empty value list.
    """
    declared = set(model.spec.chart_of_accounts.dimensions)
    result: list[tuple[str, tuple[str | int, ...]]] = []
    for column in sorted(request.filters):
        if column not in declared:
            raise RequestValidationError(f"filter on undeclared dimension {column!r}")
        raw = request.filters[column]
        values = raw if isinstance(raw, tuple) else (raw,)
        if not values:
            raise RequestValidationError(f"filter on {column!r} has no values")
        result.append((column, tuple(sorted(set(values), key=_filter_key))))
    return tuple(result)


def _natures_for(model: AccountingModel, sets: tuple[PlanSet, ...]) -> tuple[tuple[str, str], ...]:
    """The sorted subset of ``model.natures`` covering the accounts of *sets*."""
    used = {account for plan_set in sets for account in plan_set.accounts}
    return tuple(pair for pair in model.natures if pair[0] in used)


def _base_fields(model: AccountingModel) -> dict[str, object]:
    """Journal-layout fields shared by metric and assertion plans."""
    chart = model.spec.chart_of_accounts
    return {
        "table": chart.source.table or chart.source.dataframe or "",
        "account_key": chart.account_key,
        "posting_date": chart.posting_date,
        "amount_convention": chart.amount_convention,
        "amount": chart.amount,
        "debit": chart.debit,
        "credit": chart.credit,
        "cast_decimal": chart.allow_float,
    }


def plan_metric(model: AccountingModel, request: MetricRequest) -> MetricPlan:
    """Dialect-independent, JSON-serialisable plan. Raises RequestValidationError / PeriodSpansMembershipChange.

    Args:
        model: The loaded, validated model.
        request: The metric request (cumulative/grain combinations already checked by the model).

    Returns:
        The portable ``MetricPlan``.

    Raises:
        RequestValidationError: Unknown metric or dimension, undeclared filter, inactive set.
        PeriodSpansMembershipChange: The period, or the widened cumulative window, crosses a membership change.
    """
    if request.metric not in metric_order(model.spec):
        raise RequestValidationError(f"unknown metric {request.metric!r}")
    metric = model.spec.metrics[request.metric]
    chart = model.spec.chart_of_accounts
    allowed = metric.dimensions if metric.dimensions is not None else chart.dimensions
    if len(set(request.dimensions)) != len(request.dimensions):
        raise RequestValidationError("duplicate dimension in request")
    for dimension in request.dimensions:
        if dimension not in allowed:
            raise RequestValidationError(f"dimension {dimension!r} is not available for metric {request.metric!r}")
    filters = _filters(model, request)

    period = request.period
    to_exclusive = period.to + _ONE_DAY
    output_from = period.from_
    scan_from = _window_start(period.from_, period.cumulative)
    try:
        interval = _interval_for(model, scan_from, to_exclusive)
    except PeriodSpansMembershipChange as exc:
        if period.cumulative is None:
            raise
        first_start = output_from if exc.boundary > output_from else scan_from
        raise PeriodSpansMembershipChange(
            exc.boundary,
            (
                f"the {period.cumulative} window starts {scan_from.isoformat()}, before the change; request "
                f"{first_start.isoformat()}..{(exc.boundary - _ONE_DAY).isoformat()} and "
                f"{exc.boundary.isoformat()}..{period.to.isoformat()} as separate non-cumulative periods"
            ),
        ) from exc

    columns = ((f"m_{request.metric}", _lower(parse_expr(metric.expr), model, frozenset({request.metric}))),)
    sets = _plan_sets(model, columns, interval)
    return MetricPlan(
        **_base_fields(model),
        natures=_natures_for(model, sets),
        sets=sets,
        columns=columns,
        grain=request.grain,
        dimensions=request.dimensions,
        filters=filters,
        scan_from=scan_from,
        output_from=output_from,
        to_exclusive=to_exclusive,
        cumulative=period.cumulative,
    )


def plan_assertion(model: AccountingModel, request: AssertionRequest) -> MetricPlan:
    """Plan both sides of model.spec.assertions[request.assertion_index] over request.period (no grain).

    Args:
        model: The loaded, validated model.
        request: The assertion request (never cumulative).

    Returns:
        A ``MetricPlan`` whose ``columns`` are ``("lhs", …)`` and ``("rhs", …)``.

    Raises:
        RequestValidationError: Index out of range or an inactive set.
        PeriodSpansMembershipChange: The period crosses a membership change.
    """
    assertions = model.spec.assertions
    if request.assertion_index >= len(assertions):
        raise RequestValidationError(
            f"assertion index {request.assertion_index} out of range (model has {len(assertions)} assertion(s))"
        )
    left, right = parse_assertion(assertions[request.assertion_index].expr)
    period = request.period
    to_exclusive = period.to + _ONE_DAY
    interval = _interval_for(model, period.from_, to_exclusive)
    columns = (("lhs", _lower(left, model)), ("rhs", _lower(right, model)))
    sets = _plan_sets(model, columns, interval)
    return MetricPlan(
        **_base_fields(model),
        natures=_natures_for(model, sets),
        sets=sets,
        columns=columns,
        grain=None,
        dimensions=(),
        filters=(),
        scan_from=period.from_,
        output_from=period.from_,
        to_exclusive=to_exclusive,
        cumulative=None,
    )
