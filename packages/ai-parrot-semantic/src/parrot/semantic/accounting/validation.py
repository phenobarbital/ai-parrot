"""Load-time model validation (FEAT-713 M4): returns EVERY problem."""

from __future__ import annotations

import heapq
import re
from datetime import date
from typing import Mapping

from .errors import GrammarError, Problem
from .grammar import parse_assertion, parse_expr, references
from .models import AccountingModelSpec, AccountSet, ChartSnapshot, ResolvedSet

Interval = tuple[date | None, date | None]

#: Exact numeric contract (spec §2): DECIMAL(38,6) — at most 32 integer and 6 fractional digits.
_MAX_SCALE = 6
_MAX_INTEGER_DIGITS = 32
_FLOAT_MARKERS = ("float", "double", "real")
_DECIMAL_TYPE = re.compile(
    r"^\s*(?:decimal|numeric|bignumeric|bigdecimal|decimal128|decimal256)\s*"
    r"(?:\(\s*(?P<p>\d+)\s*(?:,\s*(?P<s>\d+)\s*)?\))?\s*$",
    re.IGNORECASE,
)
_INTEGER_TYPES = frozenset(
    {
        "int",
        "int2",
        "int4",
        "int8",
        "int16",
        "int32",
        "int64",
        "integer",
        "smallint",
        "tinyint",
        "bigint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "utinyint",
        "usmallint",
        "uinteger",
        "ubigint",
    }
)


def _fmt(interval: Interval) -> str:
    """Render a half-open interval for messages."""
    start = interval[0].isoformat() if interval[0] is not None else "-inf"
    end = interval[1].isoformat() if interval[1] is not None else "+inf"
    return f"[{start}, {end})"


def partition_intervals(sets: Mapping[str, AccountSet]) -> tuple[Interval, ...]:
    """Half-open intervals between every valid_from / valid_to boundary, covering (-inf, +inf).

    Args:
        sets: Account sets as written in the model.

    Returns:
        ``((None, d1), (d1, d2), ..., (dn, None))`` over the sorted distinct boundaries, or ``((None, None),)``
        when no set is dated.
    """
    boundaries = sorted(
        {bound for account_set in sets.values() for bound in (account_set.valid_from, account_set.valid_to) if bound}
    )
    points: list[date | None] = [None, *boundaries, None]
    return tuple((points[i], points[i + 1]) for i in range(len(points) - 1))


def _active(account_set: AccountSet, interval: Interval) -> bool:
    """True when the set's own ``[valid_from, valid_to)`` contains the whole *interval*."""
    start, end = interval
    if account_set.valid_from is not None and (start is None or start < account_set.valid_from):
        return False
    if account_set.valid_to is not None and (end is None or end > account_set.valid_to):
        return False
    return True


def _interval_problems(
    spec: AccountingModelSpec, resolved: Mapping[str, ResolvedSet], snapshot: ChartSnapshot
) -> list[Problem]:
    """unassigned_account, interval_gap, overlap and empty_set, evaluated per interval."""
    problems: list[Problem] = []
    members = {name: frozenset(resolved[name].accounts) if name in resolved else frozenset() for name in spec.sets}
    excluded = {account for exclusion in spec.excluded for account in exclusion.accounts}
    chart = [account.account_id for account in snapshot.accounts if account.account_id not in excluded]
    intervals = partition_intervals(spec.sets)
    active_by_interval = {
        interval: sorted(name for name, account_set in spec.sets.items() if _active(account_set, interval))
        for interval in intervals
    }
    covered_by_interval = {
        interval: frozenset().union(*(members[name] for name in active)) if active else frozenset()
        for interval, active in active_by_interval.items()
    }
    covered_anywhere = frozenset().union(*covered_by_interval.values())
    for interval in intervals:
        active = active_by_interval[interval]
        uncovered = [account for account in chart if account not in covered_by_interval[interval]]
        gaps = tuple(sorted(account for account in uncovered if account in covered_anywhere))
        unassigned = tuple(sorted(account for account in uncovered if account not in covered_anywhere))
        if unassigned:
            problems.append(
                Problem(
                    code="unassigned_account",
                    message=f"{len(unassigned)} account(s) belong to no set and are not excluded in {_fmt(interval)}",
                    interval=interval,
                    accounts=unassigned,
                )
            )
        if gaps:
            problems.append(
                Problem(
                    code="interval_gap",
                    message=(
                        f"{len(gaps)} account(s) are assigned in another interval but belong to no set "
                        f"in {_fmt(interval)}"
                    ),
                    interval=interval,
                    accounts=gaps,
                )
            )
        for index, first in enumerate(active):
            for second in active[index + 1 :]:
                shared = tuple(sorted(members[first] & members[second]))
                if not shared:
                    continue
                mutual = second in spec.sets[first].allow_overlap and first in spec.sets[second].allow_overlap
                if mutual:
                    continue
                problems.append(
                    Problem(
                        code="overlap",
                        message=f"sets {first!r} and {second!r} share {len(shared)} account(s) in {_fmt(interval)}",
                        interval=interval,
                        accounts=shared,
                    )
                )
        for name in active:
            if not members[name]:
                problems.append(
                    Problem(
                        code="empty_set",
                        message=f"set {name!r} resolves to no account in {_fmt(interval)}",
                        interval=interval,
                    )
                )
    return problems


def _selector_problems(spec: AccountingModelSpec, resolved: Mapping[str, ResolvedSet]) -> list[Problem]:
    """selector_no_match: a set whose ``select`` contributed no account beyond its explicit list."""
    problems: list[Problem] = []
    for name, account_set in spec.sets.items():
        if account_set.select is None:
            continue
        accounts = set(resolved[name].accounts) if name in resolved else set()
        if not accounts - set(account_set.accounts):
            problems.append(
                Problem(code="selector_no_match", message=f"the selector of set {name!r} matched no account")
            )
    return problems


def _metric_graph(spec: AccountingModelSpec) -> dict[str, frozenset[str]]:
    """Metric -> referenced known metrics; unparsable expressions contribute no edge."""
    graph: dict[str, frozenset[str]] = {}
    for name, metric in spec.metrics.items():
        try:
            _, refs = references(parse_expr(metric.expr))
        except GrammarError:
            refs = frozenset()
        graph[name] = frozenset(ref for ref in refs if ref in spec.metrics)
    return graph


def _cycles(graph: Mapping[str, frozenset[str]]) -> list[tuple[str, ...]]:
    """Strongly connected components that form a cycle (size > 1, or a self-reference), sorted."""
    index_of: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []
    counter = 0

    def visit(node: str) -> None:
        nonlocal counter
        index_of[node] = low[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for nxt in sorted(graph[node]):
            if nxt not in index_of:
                visit(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index_of[nxt])
        if low[node] == index_of[node]:
            component: list[str] = []
            while True:
                member = stack.pop()
                on_stack.discard(member)
                component.append(member)
                if member == node:
                    break
            if len(component) > 1 or node in graph[node]:
                components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in index_of:
            visit(node)
    return sorted(components)


def _formula_problems(spec: AccountingModelSpec) -> list[Problem]:
    """dangling_ref (syntax errors, unknown sets/metrics) and cycle."""
    problems: list[Problem] = []
    sources: list[tuple[str, str, bool]] = [(f"metric {name!r}", metric.expr, False) for name, metric in spec.metrics.items()]
    sources += [(f"assertion {index}", assertion.expr, True) for index, assertion in enumerate(spec.assertions)]
    for label, text, is_assertion in sources:
        try:
            if is_assertion:
                left, right = parse_assertion(text)
                left_sets, left_metrics = references(left)
                right_sets, right_metrics = references(right)
                sets, metrics = left_sets | right_sets, left_metrics | right_metrics
            else:
                sets, metrics = references(parse_expr(text))
        except GrammarError as exc:
            problems.append(Problem(code="dangling_ref", message=f"{label}: {exc}"))
            continue
        for set_name in sorted(sets - set(spec.sets)):
            problems.append(Problem(code="dangling_ref", message=f"{label} references unknown set {set_name!r}"))
        for metric_name in sorted(metrics - set(spec.metrics)):
            problems.append(
                Problem(code="dangling_ref", message=f"{label} references unknown metric {metric_name!r}")
            )
    for component in _cycles(_metric_graph(spec)):
        problems.append(
            Problem(
                code="cycle",
                message=f"metrics reference each other in a cycle: {', '.join(repr(m) for m in component)}",
                accounts=component,
            )
        )
    return problems


def _nature_problems(
    spec: AccountingModelSpec, resolved: Mapping[str, ResolvedSet], snapshot: ChartSnapshot
) -> list[Problem]:
    """nature_missing / nature_ambiguous for the accounts selected by any set."""
    chart = spec.chart_of_accounts
    nature = chart.nature
    if chart.amount_convention == "natural_balance":
        if nature is not None and nature.accounts is not None:
            return [
                Problem(
                    code="nature_ambiguous",
                    message="amount_convention 'natural_balance' does not take an explicit nature mapping",
                    accounts=tuple(sorted(nature.accounts)),
                )
            ]
        return []
    if nature is None:  # rejected by the ChartOfAccounts schema; kept defensive
        return []
    snapshot_natures = {account.account_id: account.nature for account in snapshot.accounts}
    selected = sorted({account for resolved_set in resolved.values() for account in resolved_set.accounts})
    problems: list[Problem] = []
    if nature.accounts is not None:
        mapping = nature.accounts
        conflicts = tuple(
            sorted(
                account
                for account, declared in mapping.items()
                if snapshot_natures.get(account) is not None and snapshot_natures[account] != declared
            )
        )
        if conflicts:
            problems.append(
                Problem(
                    code="nature_ambiguous",
                    message=f"{len(conflicts)} account(s) map to a nature that conflicts with the chart snapshot",
                    accounts=conflicts,
                )
            )
        missing = tuple(account for account in selected if account not in mapping)
    else:
        missing = tuple(account for account in selected if snapshot_natures.get(account) is None)
    if missing:
        problems.append(
            Problem(
                code="nature_missing",
                message=f"{len(missing)} selected account(s) have no nature",
                accounts=missing,
            )
        )
    return problems


def _numeric_problem(column: str, declared: str, allow_float: bool) -> Problem | None:
    """float_amount / numeric_type for one amount column against the DECIMAL(38,6) contract."""
    normalized = declared.strip().lower()
    if any(marker in normalized for marker in _FLOAT_MARKERS):
        if allow_float:
            return None
        return Problem(
            code="float_amount",
            message=f"amount column {column!r} is floating point ({declared!r}); set allow_float to accept it",
        )
    if normalized in _INTEGER_TYPES:
        return None
    match = _DECIMAL_TYPE.match(normalized)
    if match is None:
        return Problem(code="numeric_type", message=f"amount column {column!r} has non-numeric type {declared!r}")
    if match.group("p") is None:
        return None  # unparameterised: precision is enforced on actual values at execution
    precision = int(match.group("p"))
    scale = int(match.group("s") or 0)
    if scale > _MAX_SCALE or precision - scale > _MAX_INTEGER_DIGITS:
        return Problem(
            code="numeric_type",
            message=(
                f"amount column {column!r} type {declared!r} does not fit DECIMAL(38,6) "
                f"(at most {_MAX_INTEGER_DIGITS} integer and {_MAX_SCALE} fractional digits)"
            ),
        )
    return None


def _column_problems(spec: AccountingModelSpec, columns: Mapping[str, str]) -> list[Problem]:
    """column_missing, float_amount and numeric_type over the declared journal columns."""
    chart = spec.chart_of_accounts
    declared = {name.lower(): (name, kind) for name, kind in columns.items()}
    amount_columns = [name for name in (chart.amount, chart.debit, chart.credit) if name]
    required = [chart.account_key, chart.posting_date, *amount_columns, *chart.dimensions]
    problems: list[Problem] = []
    for name in dict.fromkeys(required):
        if name.lower() not in declared:
            problems.append(Problem(code="column_missing", message=f"journal column {name!r} does not exist"))
    for name in amount_columns:
        entry = declared.get(name.lower())
        if entry is None:
            continue
        problem = _numeric_problem(name, entry[1], chart.allow_float)
        if problem is not None:
            problems.append(problem)
    return problems


def validate(
    spec: AccountingModelSpec,
    resolved: Mapping[str, ResolvedSet],
    snapshot: ChartSnapshot,
    columns: Mapping[str, str] | None,
) -> list[Problem]:
    """Every invariant of spec §3 M4; never stops at the first problem.

    Args:
        spec: The model as written.
        resolved: Every set with its selectors resolved against *snapshot*.
        snapshot: The chart of accounts the model is validated against.
        columns: Journal column name -> declared type; None skips the column checks.

    Returns:
        Every problem, sorted by code, interval and accounts.
    """
    problems: list[Problem] = []
    problems += _interval_problems(spec, resolved, snapshot)
    problems += _selector_problems(spec, resolved)
    problems += _formula_problems(spec)
    problems += _nature_problems(spec, resolved, snapshot)
    if columns is not None:
        problems += _column_problems(spec, columns)
    return sorted(problems, key=lambda p: (p.code, str(p.interval), p.accounts, p.message))


def metric_order(spec: AccountingModelSpec) -> tuple[str, ...]:
    """Deterministic topological order of metrics; members of a cycle are appended last in name order.

    Args:
        spec: The model as written.

    Returns:
        Every metric name, each after the metrics it references (except inside cycles).
    """
    graph = _metric_graph(spec)
    pending = {name: len(deps) for name, deps in graph.items()}
    dependents: dict[str, list[str]] = {name: [] for name in graph}
    for name, deps in graph.items():
        for dep in deps:
            dependents[dep].append(name)
    ready = [name for name, count in pending.items() if count == 0]
    heapq.heapify(ready)
    order: list[str] = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for dependent in dependents[name]:
            pending[dependent] -= 1
            if pending[dependent] == 0:
                heapq.heappush(ready, dependent)
    placed = set(order)
    return tuple(order + sorted(name for name in graph if name not in placed))
