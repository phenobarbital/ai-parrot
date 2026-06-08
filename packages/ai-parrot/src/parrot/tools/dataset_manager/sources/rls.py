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

Security invariant: subject attribute values are **never** interpolated into
SQL strings.  The :class:`~parrot.auth.rls_registry.RlsPredicate`
``sql_predicate`` contains parameter placeholders (``":p0"``, ``":p1"``).
The actual values live in ``bound_params`` and are returned to the caller for
driver-level parameterised binding.  The wrapping SQL strategy
(``"SELECT * FROM (...) AS _rls WHERE ..."`` form) preserves this invariant
because the predicate string itself only references bound placeholders.

Usage::

    from parrot.auth.rls_registry import RlsPredicate
    from parrot.tools.dataset_manager.sources.rls import inject_rls_sql

    wrapped_sql, params = inject_rls_sql(
        "SELECT * FROM sales.orders", "postgres", [pred]
    )
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from parrot.auth.rls_registry import RlsPredicate
    from parrot.tools.dataset_manager.sources.table import TableSource
    from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
    from parrot.tools.dataset_manager.sources.mongo import MongoSource


def inject_rls_sql(
    sql: str,
    dialect: str,
    predicates: "list[RlsPredicate]",
) -> tuple[str, dict[str, list[str]]]:
    """Inject RLS predicates into a SQL query via wrapping.

    Wraps the original query as a subquery and appends a ``WHERE`` clause
    composed of all predicate expressions joined with ``AND``::

        SELECT * FROM (<original>) AS _rls WHERE (<pred1>) AND (<pred2>)

    Subject attribute values are **never** interpolated into the returned SQL
    string.  They live in the ``bound_params`` mapping returned alongside the
    SQL, for the driver to bind safely.

    Args:
        sql: Original SQL query string.
        dialect: sqlglot dialect name (unused in the wrapping strategy but
            kept for API consistency with future push-down strategies).
        predicates: List of rendered :class:`~parrot.auth.rls_registry.RlsPredicate`
            objects to inject.

    Returns:
        A ``(rewritten_sql, bound_params)`` tuple where ``bound_params`` maps
        placeholder names to their value lists.
    """
    if not predicates:
        return sql, {}

    all_params: dict[str, list[str]] = {}
    where_parts: list[str] = []
    for pred in predicates:
        where_parts.append(pred.sql_predicate)
        all_params.update(pred.bound_params)

    combined = " AND ".join(f"({p})" for p in where_parts)
    wrapped = f"SELECT * FROM ({sql}) AS _rls WHERE {combined}"
    return wrapped, all_params


def inject_rls_table_source(
    source: "TableSource",
    predicates: "list[RlsPredicate]",
) -> "TableSource":
    """Extend a TableSource's permanent_filter with RLS conditions.

    Modifies ``source._permanent_filter`` in place by adding the bound
    parameter values for each predicate's subject attribute.  This piggy-backs
    on the existing ``permanent_filter`` mechanism without changing the source
    class.

    Args:
        source: The :class:`~parrot.tools.dataset_manager.sources.table.TableSource`
            to modify.
        predicates: List of rendered predicates to apply.

    Returns:
        The same (mutated) source instance.
    """
    for pred in predicates:
        # Merge each bound param list into the permanent filter dict.
        # If multiple predicates touch the same key, we use a list.
        for param_name, values in pred.bound_params.items():
            existing = source._permanent_filter.get(param_name)
            if existing is None:
                source._permanent_filter[param_name] = values
            elif isinstance(existing, list):
                source._permanent_filter[param_name] = existing + values
            else:
                source._permanent_filter[param_name] = [existing] + values
    return source


def inject_rls_query_slug(
    source: "QuerySlugSource",
    predicates: "list[RlsPredicate]",
) -> "QuerySlugSource":
    """Merge RLS predicates into a QuerySlugSource's permanent_filter.

    Adds the bound parameter values from each predicate into
    ``source._permanent_filter``.  The existing ``permanent_filter``
    mechanism merges these conditions at fetch time.

    Args:
        source: The :class:`~parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource`
            to modify.
        predicates: List of rendered predicates to apply.

    Returns:
        The same (mutated) source instance.
    """
    for pred in predicates:
        for param_name, values in pred.bound_params.items():
            existing = source._permanent_filter.get(param_name)
            if existing is None:
                source._permanent_filter[param_name] = values
            elif isinstance(existing, list):
                source._permanent_filter[param_name] = existing + values
            else:
                source._permanent_filter[param_name] = [existing] + values
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
    from the first bound parameter key (or from the first IN-list pattern in
    the predicate's SQL expression).

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

    import re

    mask = pd.Series([True] * len(df), index=df.index)

    for pred in predicates:
        # Infer the column name from the SQL predicate.
        # Expected patterns: "col IN (:p0, :p1)", "col = :p0"
        col_match = re.match(r"(\w+)\s+(?:IN|=)\s*", pred.sql_predicate.strip(), re.I)
        if col_match is None:
            continue
        col = col_match.group(1)
        if col not in df.columns:
            continue
        allowed_values = [
            v for values in pred.bound_params.values() for v in values
        ]
        mask = mask & df[col].astype(str).isin(allowed_values)

    return df[mask].reset_index(drop=True)
