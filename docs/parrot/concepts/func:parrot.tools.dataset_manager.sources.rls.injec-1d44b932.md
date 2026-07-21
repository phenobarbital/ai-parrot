---
type: Concept
title: inject_rls_query_slug()
id: func:parrot.tools.dataset_manager.sources.rls.inject_rls_query_slug
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Merge RLS predicates into a QuerySlugSource's permanent_filter.
---

# inject_rls_query_slug

```python
def inject_rls_query_slug(source: 'QuerySlugSource', predicates: 'list[RlsPredicate]') -> 'QuerySlugSource'
```

Merge RLS predicates into a QuerySlugSource's permanent_filter.

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
