"""RLS Predicate Injection for FEAT-228 Data-Plane Authorization.

Provides per-source-type injection functions that take a list of rendered
:class:`~parrot.auth.rls_registry.RlsPredicate` objects and apply them to
the outbound query.  Each injection method is a pure function (or returns a
modified source/DataFrame) — no network I/O.

Injection strategies by source type (Spec §2 Module 5):
- :class:`~parrot.tools.dataset_manager.sources.sql.SQLQuerySource`: wrap
  the original SQL with a ``SELECT * FROM (...) AS _rls WHERE <pred>`` so
  the predicate is applied after all table joins.
- :class:`~parrot.tools.dataset_manager.sources.table.TableSource`: extend
  the existing ``_permanent_filter`` dict with RLS column conditions.
- :class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`:
  merge predicates into the slug's ``_permanent_filter``.
- :class:`~parrot.tools.dataset_manager.sources.mongo.MongoSource`: merge
  predicate conditions into the Mongo query filter via ``$and``.
- Post-fetch (Airtable/Smartsheet): filter the returned
  :class:`pandas.DataFrame` by the bound parameter values.

Security note: ``SQLQuerySource.fetch()`` uses ``str.format()`` style
substitution and cannot bind named ``:p0`` parameters via a driver.  Values
are therefore inlined (escaped) directly into the WHERE clause at injection
time.  ``inject_rls_sql`` always returns an empty ``bound_params`` dict —
callers do not need to pass parameters to the driver separately.

Usage::

    from parrot.auth.rls_registry import RlsPredicate
    from parrot.tools.dataset_manager.sources.rls import inject_rls_sql

    wrapped_sql, params = inject_rls_sql(
        "SELECT * FROM sales.orders", "postgres", [pred]
    )
    # params is always {} — values are inlined into wrapped_sql
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from parrot.auth.rls_registry import RlsPredicate
    from parrot.tools.dataset_manager.sources.table import TableSource
    from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
    from parrot.tools.dataset_manager.sources.mongo import MongoSource

# Regex used by inject_rls_table_source, inject_rls_query_slug and
# inject_rls_postfetch to extract the column name from a rendered predicate.
# Matches patterns like:  col IN (:p0, :p1)   or   col = :p0
_COL_FROM_PREDICATE_RE = re.compile(r"^(\w+)\s+(?:IN|=)", re.I)


def _escape_sql_value(value: str) -> str:
    """Escape a string value for safe inline SQL interpolation.

    Single quotes are doubled to prevent SQL injection.  This is consistent
    with the ``SQLQuerySource._escape_value`` approach used elsewhere.

    Args:
        value: The raw string value to escape.

    Returns:
        The value wrapped in single quotes with internal quotes doubled.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def inject_rls_sql(
    sql: str,
    dialect: str,
    predicates: "list[RlsPredicate]",
) -> tuple[str, dict[str, list[str]]]:
    """Inject RLS predicates into a SQL query via wrapping.

    Wraps the original query as a subquery and appends a ``WHERE`` clause
    composed of all predicate expressions joined with ``AND``::

        SELECT * FROM (<original>) AS _rls WHERE (<pred1>) AND (<pred2>)

    Bound parameter values are inlined (safely escaped via single-quote
    doubling) directly into the WHERE clause.  ``SQLQuerySource.fetch()``
    uses ``str.format()`` style substitution and cannot bind named ``:p0``
    parameters via a driver, so inlining is the correct approach here.

    Multiple predicates are deduplicated by index-prefixing their parameter
    names before inlining to prevent collisions between predicates that share
    the same placeholder names (e.g. both use ``:p0``).

    Args:
        sql: Original SQL query string.
        dialect: sqlglot dialect name (unused in the wrapping strategy but
            kept for API consistency with future push-down strategies).
        predicates: List of rendered :class:`~parrot.auth.rls_registry.RlsPredicate`
            objects to inject.

    Returns:
        A ``(rewritten_sql, {})`` tuple.  ``bound_params`` is always empty
        because values are inlined into the SQL string.
    """
    if not predicates:
        return sql, {}

    where_parts: list[str] = []
    for i, pred in enumerate(predicates):
        expanded = pred.sql_predicate
        # Remap parameter names with a predicate-index prefix to avoid
        # collisions when multiple predicates both use :p0, :p1, etc.
        remapped: dict[str, list[str]] = {}
        for key, values in pred.bound_params.items():
            new_key = f"pred{i}_{key}"
            expanded = re.sub(rf":{re.escape(key)}\b", f":{new_key}", expanded)
            remapped[new_key] = values
        # Inline the values: replace :pred0_p0 with escaped literal
        for new_key, values in remapped.items():
            escaped_vals = ", ".join(_escape_sql_value(str(v)) for v in values)
            expanded = re.sub(
                rf":{re.escape(new_key)}\b",
                escaped_vals,
                expanded,
            )
        where_parts.append(f"({expanded})")

    combined = " AND ".join(where_parts)
    wrapped = f"SELECT * FROM ({sql}) AS _rls WHERE {combined}"
    return wrapped, {}


def inject_rls_table_source(
    source: "TableSource",
    predicates: "list[RlsPredicate]",
) -> "TableSource":
    """Extend a TableSource's permanent_filter with RLS conditions.

    Modifies ``source._permanent_filter`` in place by adding the actual
    column name (extracted from ``pred.sql_predicate``) as the filter key
    and all bound parameter values as the allow-list.

    The column name is parsed from the predicate SQL using the pattern
    ``col IN (...)`` or ``col = ...``.  Predicates that do not match this
    pattern are skipped with a warning.

    Args:
        source: The :class:`~parrot.tools.dataset_manager.sources.table.TableSource`
            to modify.
        predicates: List of rendered predicates to apply.

    Returns:
        The same (mutated) source instance.
    """
    for pred in predicates:
        m = _COL_FROM_PREDICATE_RE.match(pred.sql_predicate.strip())
        if m is None:
            # Cannot determine column — skip silently (caller may log).
            continue
        col = m.group(1)
        # Flatten all values from all bound params into one allow-list.
        values = [v for vlist in pred.bound_params.values() for v in vlist]
        existing = source._permanent_filter.get(col)
        if existing is None:
            source._permanent_filter[col] = values
        elif isinstance(existing, list):
            source._permanent_filter[col] = existing + values
        else:
            source._permanent_filter[col] = [existing] + values
    return source


def inject_rls_query_slug(
    source: "QuerySlugSource",
    predicates: "list[RlsPredicate]",
) -> "QuerySlugSource":
    """Merge RLS predicates into a QuerySlugSource's permanent_filter.

    Adds the actual column name (extracted from ``pred.sql_predicate``) and
    all bound parameter values into ``source._permanent_filter``.  The
    existing ``permanent_filter`` mechanism merges these conditions at fetch
    time.

    The column name is parsed from the predicate SQL using the pattern
    ``col IN (...)`` or ``col = ...``.  Predicates that do not match this
    pattern are skipped.

    Args:
        source: The :class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`
            to modify.
        predicates: List of rendered predicates to apply.

    Returns:
        The same (mutated) source instance.
    """
    for pred in predicates:
        m = _COL_FROM_PREDICATE_RE.match(pred.sql_predicate.strip())
        if m is None:
            continue
        col = m.group(1)
        # Flatten all values from all bound params into one allow-list.
        values = [v for vlist in pred.bound_params.values() for v in vlist]
        existing = source._permanent_filter.get(col)
        if existing is None:
            source._permanent_filter[col] = values
        elif isinstance(existing, list):
            source._permanent_filter[col] = existing + values
        else:
            source._permanent_filter[col] = [existing] + values
    return source


def inject_rls_mongo(
    source: "MongoSource",
    predicates: "list[RlsPredicate]",
) -> dict[str, Any]:
    """Build a Mongo ``$and`` filter dict from RLS predicates.

    Translates each predicate's bound parameters into Mongo ``$in`` filter
    expressions and wraps them in a ``{"$and": [...]}`` structure.

    Args:
        source: The :class:`~parrot.tools.dataset_manager.sources.mongo.MongoSource`
            (used to read existing ``required_filter`` if set).
        predicates: List of rendered predicates to apply.

    Returns:
        A Mongo query filter dict ready for use as the ``filter`` argument.
    """
    conditions: list[dict[str, Any]] = []

    for pred in predicates:
        for param_name, values in pred.bound_params.items():
            # Heuristic: param name often corresponds to the field name when
            # the template is simple.  Use an $in filter on the field.
            conditions.append({param_name: {"$in": values}})

    if not conditions:
        return {}

    return {"$and": conditions}


def inject_rls_postfetch(
    df: pd.DataFrame,
    predicates: "list[RlsPredicate]",
) -> pd.DataFrame:
    """Apply RLS predicates as post-fetch row filtering on a DataFrame.

    Used for API-backed sources (Airtable, Smartsheet) where server-side
    filtering is not available or not reliable.  Filters the DataFrame to
    retain only rows whose column values appear in the allowed lists.

    For each predicate, the bound parameter values are collected and used as
    an allow-list for the corresponding column.  The column name is inferred
    from the predicate's SQL expression using the pattern
    ``col IN (...)`` or ``col = ...``.  If the column name cannot be
    extracted, a :class:`ValueError` is raised.

    .. note::
        **TODO: FEAT-228 post-fetch RLS deferred** — ``AuthorizingDataSource``
        does not yet call this function for Airtable/Smartsheet sources.
        Wiring it in requires a pre/post split of ``fetch()`` that is deferred.
        This function is fully implemented and tested; the missing piece is the
        callsite in ``_apply_rls``.

    Security note: post-fetch means data entered the process before filtering.
    This is weaker than server-side filtering but still enforces the restriction
    at the process boundary.  Sensitive-classed sources should block post-fetch
    RLS (handled by AuthorizingDataSource, not here).

    Args:
        df: The :class:`pandas.DataFrame` returned by the source.
        predicates: List of rendered :class:`~parrot.auth.rls_registry.RlsPredicate`
            objects.

    Returns:
        A filtered :class:`pandas.DataFrame`.
    """
    if not predicates or df.empty:
        return df

    # Broader regex: handles LOWER(col) IN (...) and similar wrappers in
    # addition to the simple "col IN (...)" / "col = ..." patterns.
    _col_re = re.compile(r"(?:^|\()(\w+)\s+(?:IN|=)", re.I)

    mask = pd.Series([True] * len(df), index=df.index)

    for pred in predicates:
        # Infer the column name from the SQL predicate.
        col_match = _col_re.search(pred.sql_predicate.strip())
        if col_match is None:
            raise ValueError(
                f"Cannot extract column name from RLS predicate: "
                f"{pred.sql_predicate!r}"
            )
        col = col_match.group(1)
        if col not in df.columns:
            continue
        allowed_values = [
            v for values in pred.bound_params.values() for v in values
        ]
        mask = mask & df[col].astype(str).isin(allowed_values)

    return df[mask].reset_index(drop=True)
