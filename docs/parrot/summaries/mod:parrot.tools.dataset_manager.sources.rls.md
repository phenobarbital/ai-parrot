---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.rls
id: mod:parrot.tools.dataset_manager.sources.rls
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RLS Predicate Injection for FEAT-228 Data-Plane Authorization.
relates_to:
- concept: func:parrot.tools.dataset_manager.sources.rls.inject_rls_mongo
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.rls.inject_rls_postfetch
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.rls.inject_rls_query_slug
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.rls.inject_rls_sql
  rel: defines
- concept: func:parrot.tools.dataset_manager.sources.rls.inject_rls_table_source
  rel: defines
- concept: mod:parrot.auth.rls_registry
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.mongo
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.query_slug
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.table
  rel: references
---

# `parrot.tools.dataset_manager.sources.rls`

RLS Predicate Injection for FEAT-228 Data-Plane Authorization.

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

## Functions

- `def inject_rls_sql(sql: str, dialect: str, predicates: 'list[RlsPredicate]') -> tuple[str, dict[str, list[str]]]` — Inject RLS predicates into a SQL query via wrapping.
- `def inject_rls_table_source(source: 'TableSource', predicates: 'list[RlsPredicate]') -> 'TableSource'` — Extend a TableSource's permanent_filter with RLS conditions.
- `def inject_rls_query_slug(source: 'QuerySlugSource', predicates: 'list[RlsPredicate]') -> 'QuerySlugSource'` — Merge RLS predicates into a QuerySlugSource's permanent_filter.
- `def inject_rls_mongo(source: 'MongoSource', predicates: 'list[RlsPredicate]') -> dict[str, Any]` — Build a Mongo ``$and`` filter dict from RLS predicates.
- `def inject_rls_postfetch(df: pd.DataFrame, predicates: 'list[RlsPredicate]') -> pd.DataFrame` — Apply RLS predicates as post-fetch row filtering on a DataFrame.
