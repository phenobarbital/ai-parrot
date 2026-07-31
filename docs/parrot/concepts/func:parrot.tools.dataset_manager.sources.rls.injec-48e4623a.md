---
type: Concept
title: inject_rls_table_source()
id: func:parrot.tools.dataset_manager.sources.rls.inject_rls_table_source
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extend a TableSource's permanent_filter with RLS conditions.
---

# inject_rls_table_source

```python
def inject_rls_table_source(source: 'TableSource', predicates: 'list[RlsPredicate]') -> 'TableSource'
```

Extend a TableSource's permanent_filter with RLS conditions.

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
