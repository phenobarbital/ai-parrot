"""Accounting compiler (FEAT-713 M5): planning, SQL rendering, self-check, hashing and lineage.

Imports nothing from parrot.semantic outside the accounting package.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import sqlglot
from pydantic import TypeAdapter
from sqlglot import exp

from .errors import AccountingError, PeriodSpansMembershipChange, RequestValidationError
from .grammar import BinOp, Expr, Neg, Num, Ref, Sum, parse_assertion, parse_expr, references
from .models import (
    AccountingModel,
    AccountingRequest,
    AssertionRequest,
    CompiledMetricQuery,
    Lineage,
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


# --- Rendering (TASK-5531) ---------------------------------------------------------------------------------------

_EXACT_TYPE = {"duckdb": "DECIMAL(38, 6)", "postgres": "NUMERIC(38, 6)", "bigquery": "BIGNUMERIC"}
_GRAIN_UNIT = {"day": "DAY", "week": "WEEK", "month": "MONTH", "quarter": "QUARTER", "year": "YEAR"}
_WINDOW_UNIT = {"mtd": "MONTH", "qtd": "QUARTER", "ytd": "YEAR"}
_BUCKET = "bucket"
_SCAN_ALIAS = "scan"
_WINDOW_ALIAS = "windowed"


def _check_dialect(dialect: str) -> None:
    """Raise AccountingError for a dialect without an exact decimal type."""
    if dialect not in _EXACT_TYPE:
        raise AccountingError(f"unsupported dialect {dialect!r}; expected one of {', '.join(sorted(_EXACT_TYPE))}")


def _ident(name: str) -> exp.Identifier:
    """Identifier node for *name*; sqlglot quotes (and escapes) it whenever it is not a safe bare identifier."""
    return exp.to_identifier(name)


def _col(name: str) -> exp.Column:
    """Unqualified column reference built from a model-supplied name (never parsed)."""
    return exp.Column(this=_ident(name))


def _table_parts(table: str) -> tuple[str, ...]:
    """Split a ``catalog.db.table`` name into its non-empty parts (at most three).

    Raises:
        AccountingError: Empty name or more than three parts.
    """
    parts = tuple(table.split("."))
    if not table or any(not part for part in parts) or len(parts) > 3:
        raise AccountingError(f"invalid journal table name {table!r}")
    return parts


def _table(table: str) -> exp.Table:
    """Table node built from identifiers (the name is never parsed as SQL)."""
    parts = _table_parts(table)
    kwargs: dict[str, exp.Identifier] = {"this": _ident(parts[-1])}
    if len(parts) >= 2:
        kwargs["db"] = _ident(parts[-2])
    if len(parts) == 3:
        kwargs["catalog"] = _ident(parts[0])
    return exp.Table(**kwargs)


def _literal(value: str | int) -> exp.Expression:
    """SQL literal for a filter or account value; strings are quoted and escaped by sqlglot."""
    if isinstance(value, bool):
        raise AccountingError("boolean filter values are not supported")
    if isinstance(value, int):
        return exp.Literal.number(value)
    return exp.Literal.string(value)


def _in(column: str, values: tuple[str | int, ...]) -> exp.In:
    """``column IN (<literals>)`` with values in the given (already sorted) order."""
    return exp.In(this=_col(column), expressions=[_literal(value) for value in values])


def _date(value: date) -> exp.Cast:
    """``CAST('YYYY-MM-DD' AS DATE)`` — a literal, never a bind parameter."""
    return exp.cast(exp.Literal.string(value.isoformat()), "DATE")


def _trunc(unit: str, this: exp.Expression, dialect: str) -> exp.Cast:
    """``CAST(DATE_TRUNC(<unit>, this) AS DATE)``; BigQuery weeks use ISOWEEK to match DuckDB/Postgres (Monday)."""
    if dialect == "bigquery" and unit == "WEEK":
        unit = "ISOWEEK"
    return exp.cast(exp.DateTrunc(this=this, unit=exp.var(unit)), "DATE")


def _exact(column: str, dialect: str) -> exp.Cast:
    """``CAST(column AS <exact decimal type of dialect>)``."""
    return exp.cast(_col(column), exp.DataType.build(_EXACT_TYPE[dialect], dialect=dialect))


def _amount_expr(plan: MetricPlan, dialect: str) -> exp.Expression:
    """Normalised, exactly-cast amount for one posting (spec §2 sign table).

    Every account becomes positive in its natural balance. Each nature gets an explicit ``CASE`` arm listing its
    accounts (sorted); an account with no recorded nature matches no arm and contributes NULL, never a guessed sign.

    Args:
        plan: The metric plan (natures, convention and amount columns are read from it).
        dialect: Target dialect.

    Returns:
        The normalised amount expression.

    Raises:
        AccountingError: Unknown dialect, missing amount columns, or no natures for a nature-dependent convention.
    """
    _check_dialect(dialect)
    convention = plan.amount_convention
    if convention == "debit_credit_columns":
        if not plan.debit or not plan.credit:
            raise AccountingError("amount_convention 'debit_credit_columns' requires 'debit' and 'credit' columns")
        zero = exp.Literal.number(0)
        debit = exp.Coalesce(this=_exact(plan.debit, dialect), expressions=[zero])
        credit = exp.Coalesce(this=_exact(plan.credit, dialect), expressions=[zero.copy()])
        positive = {"debit": exp.Sub(this=debit, expression=credit)}
        positive["credit"] = exp.Sub(this=credit.copy(), expression=debit.copy())
    else:
        if not plan.amount:
            raise AccountingError(f"amount_convention {convention!r} requires an 'amount' column")
        amount = _exact(plan.amount, dialect)
        if convention == "natural_balance":
            return amount
        natural = "debit" if convention == "debit_positive" else "credit"
        positive = {
            natural: amount,
            ("credit" if natural == "debit" else "debit"): exp.Neg(this=amount.copy()),
        }
    case = exp.Case()
    for nature in ("debit", "credit"):
        accounts = tuple(account for account, value in plan.natures if value == nature)
        if accounts:
            case = case.when(_in(plan.account_key, accounts), positive[nature])
    if not case.args.get("ifs"):
        raise AccountingError(f"amount_convention {convention!r} needs account natures, but the plan has none")
    return case


def _set_column(plan_set: PlanSet, plan: MetricPlan, dialect: str) -> exp.Alias:
    """``COALESCE(SUM(CASE WHEN account IN (...) THEN <normalised amount> END), 0) AS set_<name>``.

    The normalised amount only lists the natures of this set's own accounts, so the SQL grows with the set sizes
    rather than with the size of the whole chart.
    """
    members = set(plan_set.accounts)
    scoped = plan.model_copy(update={"natures": tuple(pair for pair in plan.natures if pair[0] in members)})
    amount = _amount_expr(scoped, dialect)
    case = exp.Case().when(_in(plan.account_key, plan_set.accounts), amount)
    total = exp.Coalesce(this=exp.Sum(this=case), expressions=[exp.Literal.number(0)])
    return exp.alias_(total, _ident(plan_set.alias))


def _scan(plan: MetricPlan, dialect: str) -> exp.Select:
    """Inner scan: bucket, dimensions and one exact aggregate per set, grouped by bucket + dimensions."""
    projections: list[exp.Expression] = []
    group: list[exp.Expression] = []
    if plan.grain is not None:
        bucket = _trunc(_GRAIN_UNIT[plan.grain], _col(plan.posting_date), dialect)
        projections.append(exp.alias_(bucket, _ident(_BUCKET)))
        group.append(bucket.copy())
    for dimension in plan.dimensions:
        projections.append(_col(dimension))
        group.append(_col(dimension))
    projections.extend(_set_column(plan_set, plan, dialect) for plan_set in plan.sets)
    if not projections:
        raise AccountingError("plan has no grain, dimensions or account sets to select")

    conditions: list[exp.Expression] = [
        exp.GTE(this=_col(plan.posting_date), expression=_date(plan.scan_from)),
        exp.LT(this=_col(plan.posting_date), expression=_date(plan.to_exclusive)),
    ]
    conditions.extend(_in(column, values) for column, values in plan.filters)

    select = exp.Select(expressions=projections).from_(_table(plan.table), copy=False)
    select = select.where(exp.and_(*conditions), copy=False)
    if group:
        select = select.group_by(*group, copy=False)
    return select


def _ascending(column: str, dialect: str) -> exp.Ordered:
    """Ascending sort key with the dialect's own default NULL placement (rendered without a NULLS clause)."""
    nulls_small = sqlglot.Dialect.get_or_raise(dialect).NULL_ORDERING == "nulls_are_small"
    return exp.Ordered(this=_col(column), nulls_first=nulls_small)


def _output_keys(plan: MetricPlan) -> list[str]:
    """Bucket (when grained) followed by the requested dimensions."""
    return ([_BUCKET] if plan.grain is not None else []) + list(plan.dimensions)


def render_plan(plan: MetricPlan, dialect: str) -> str:
    """Render *plan* to SQL for *dialect*; deterministic; never returns SQL that fails the self-check.

    The SQL returns exact per-set aggregates (cumulative sums for period-to-date requests) and never evaluates
    metric arithmetic; ``plan.columns`` is applied afterwards by the shared evaluator.

    Args:
        plan: The portable plan; nothing else is consulted.
        dialect: ``"duckdb"``, ``"postgres"`` or ``"bigquery"``.

    Returns:
        The rendered SQL text.

    Raises:
        AccountingError: Unknown dialect, inconsistent plan, or SQL failing the self-check.
    """
    _check_dialect(dialect)
    if plan.cumulative is not None and (plan.grain is None or plan.grain == "week"):
        raise RequestValidationError(f"cumulative {plan.cumulative!r} requires a day/month/quarter/year grain")
    keys = _output_keys(plan)
    aliases = [plan_set.alias for plan_set in plan.sets]
    scan = _scan(plan, dialect).subquery(_SCAN_ALIAS, copy=False)

    if plan.cumulative is None:
        source: exp.Expression = scan
        where: exp.Expression | None = None
    else:
        window_key = _trunc(_WINDOW_UNIT[plan.cumulative], _col(_BUCKET), dialect)
        partition = [window_key] + [_col(dimension) for dimension in plan.dimensions]
        running = [
            exp.alias_(
                exp.Window(
                    this=exp.Sum(this=_col(alias)),
                    partition_by=[part.copy() for part in partition],
                    order=exp.Order(expressions=[_ascending(_BUCKET, dialect)]),
                ),
                _ident(alias),
            )
            for alias in aliases
        ]
        windowed = exp.Select(expressions=[_col(key) for key in keys] + running).from_(scan, copy=False)
        source = windowed.subquery(_WINDOW_ALIAS, copy=False)
        where = exp.GTE(
            this=_col(_BUCKET),
            expression=_trunc(_GRAIN_UNIT[plan.grain], _date(plan.output_from), dialect),  # type: ignore[index]
        )

    outer = exp.Select(expressions=[_col(name) for name in keys + aliases]).from_(source, copy=False)
    if where is not None:
        outer = outer.where(where, copy=False)
    if keys:
        outer = outer.order_by(*(_ascending(key, dialect) for key in keys), copy=False)
    sql = outer.sql(dialect=dialect, pretty=False, identify=False)

    declared = {plan.account_key, plan.posting_date, *plan.dimensions, *(column for column, _ in plan.filters)}
    declared |= {column for column in (plan.amount, plan.debit, plan.credit) if column}
    self_check(sql, dialect, table=plan.table, columns=frozenset(declared))
    return sql


def self_check(sql: str, dialect: str, *, table: str, columns: frozenset[str]) -> None:
    """Re-parse and assert referenced tables/columns ⊆ declared; raise AccountingError otherwise.

    Output aliases are accepted only for the names the renderer produces (``bucket`` and ``set_<name>``) and only
    when the SQL itself defines them; ``*`` projections, table functions and any other table are rejected.

    Args:
        sql: Rendered SQL.
        dialect: Dialect to parse with.
        table: The declared journal table (``[catalog.][db.]table``).
        columns: Declared journal columns.

    Raises:
        AccountingError: Unparseable SQL, more than one statement, or a reference outside the allowlist.
    """
    try:
        statements = [statement for statement in sqlglot.parse(sql, read=dialect) if statement is not None]
    except sqlglot.errors.SqlglotError as exc:
        raise AccountingError(f"self-check could not parse the rendered SQL: {exc}") from exc
    if len(statements) != 1:
        raise AccountingError(f"self-check expected exactly one statement, found {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise AccountingError(f"self-check expected a SELECT, found {type(tree).__name__}")

    expected = _table_parts(table)
    for node in tree.find_all(exp.Table):
        found = tuple(part.name for part in node.parts) if isinstance(node.this, exp.Identifier) else ()
        if found != expected:
            raise AccountingError(f"self-check: SQL references table {node.sql(dialect=dialect)!r}, not {table!r}")
    if any(True for _ in tree.find_all(exp.Star)):
        raise AccountingError("self-check: SQL selects '*'")

    defined = {alias.alias for alias in tree.find_all(exp.Alias)}
    allowed_aliases = {name for name in defined if name == _BUCKET or name.startswith("set_")}
    for column in tree.find_all(exp.Column):
        if column.table:
            raise AccountingError(f"self-check: qualified column {column.sql(dialect=dialect)!r} is not allowed")
        if column.name not in columns and column.name not in allowed_aliases:
            raise AccountingError(f"self-check: SQL references undeclared column {column.name!r}")


def _metric_closure(model: AccountingModel, names: frozenset[str]) -> frozenset[str]:
    """*names* plus every metric they reference, transitively."""
    closure: set[str] = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in closure or name not in model.spec.metrics:
            continue
        closure.add(name)
        pending.extend(references(parse_expr(model.spec.metrics[name].expr))[1])
    return frozenset(closure)


def _has_div(expr: PlanExpr) -> bool:
    """True when *expr* contains a division anywhere."""
    return expr.op == "div" or any(_has_div(arg) for arg in expr.args)


def _lineage(
    model: AccountingModel,
    plan: MetricPlan,
    *,
    metric: str | None,
    assertion_index: int | None,
    formula: str,
) -> Lineage:
    """Lineage for a metric or assertion plan: sets used, related assertions and warnings.

    Args:
        model: The loaded model.
        plan: The plan being compiled.
        metric: Metric name, or ``None`` for an assertion.
        assertion_index: Assertion index, or ``None`` for a metric.
        formula: The expression as written in the model.

    Returns:
        The ``Lineage``. For a metric, ``assertions`` lists every model assertion that references the metric or
        any metric it depends on; for an assertion, it is that assertion's expression.
    """
    by_alias = {_set_alias(name): resolved for name, resolved in model.sets.items()}
    sets = tuple(by_alias[plan_set.alias] for plan_set in plan.sets)
    if metric is None:
        assertions: tuple[str, ...] = (model.spec.assertions[assertion_index].expr,) if assertion_index is not None else ()
    else:
        related = _metric_closure(model, frozenset({metric}))
        found: list[str] = []
        for assertion in model.spec.assertions:
            left, right = parse_assertion(assertion.expr)
            touched = _metric_closure(model, references(left)[1] | references(right)[1])
            if touched & related:
                found.append(assertion.expr)
        assertions = tuple(found)
    warnings: list[str] = []
    if any(_has_div(expr) for _, expr in plan.columns):
        warnings.append("division_by_zero_possible")
    if plan.cast_decimal:
        warnings.append("float_cast")
    return Lineage(
        metric=metric,
        assertion_index=assertion_index,
        formula=formula,
        sets=sets,
        assertions=assertions,
        warnings=tuple(warnings),
    )


def _compiled(
    model: AccountingModel,
    request: MetricRequest | AssertionRequest,
    plan: MetricPlan,
    dialect: str,
    lineage: Lineage,
) -> CompiledMetricQuery:
    """Render *plan* and wrap it with its hashes, request and lineage."""
    sql = render_plan(plan, dialect)
    return CompiledMetricQuery(
        sql=sql,
        dialect=dialect,
        sql_hash=hashlib.sha256(f"{dialect}\n{sql}".encode()).hexdigest(),
        model_hash=model.model_hash,
        plan_hash=plan.plan_hash,
        plan=plan,
        request=request,
        lineage=lineage,
    )


def compile_metric(model: AccountingModel, request: MetricRequest, dialect: str) -> CompiledMetricQuery:
    """plan_metric + render_plan. Same (model_hash, canonical request, dialect) ⇒ byte-identical sql.

    Args:
        model: The loaded model.
        request: The metric request.
        dialect: Target dialect.

    Returns:
        The compiled query with plan, hashes and lineage.
    """
    plan = plan_metric(model, request)
    lineage = _lineage(
        model, plan, metric=request.metric, assertion_index=None, formula=model.spec.metrics[request.metric].expr
    )
    return _compiled(model, request, plan, dialect, lineage)


def compile_assertion(model: AccountingModel, request: AssertionRequest, dialect: str) -> CompiledMetricQuery:
    """plan_assertion + render_plan; lineage carries metric=None and the assertion index.

    Args:
        model: The loaded model.
        request: The assertion request.
        dialect: Target dialect.

    Returns:
        The compiled assertion query.
    """
    plan = plan_assertion(model, request)
    lineage = _lineage(
        model,
        plan,
        metric=None,
        assertion_index=request.assertion_index,
        formula=model.spec.assertions[request.assertion_index].expr,
    )
    return _compiled(model, request, plan, dialect, lineage)
