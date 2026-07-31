---
type: Concept
title: inject_rls_sql()
id: func:parrot.tools.dataset_manager.sources.rls.inject_rls_sql
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Inject RLS predicates into a SQL query via wrapping.
---

# inject_rls_sql

```python
def inject_rls_sql(sql: str, dialect: str, predicates: 'list[RlsPredicate]') -> tuple[str, dict[str, list[str]]]
```

Inject RLS predicates into a SQL query via wrapping.

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
