---
type: Concept
title: inject_rls_postfetch()
id: func:parrot.tools.dataset_manager.sources.rls.inject_rls_postfetch
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Apply RLS predicates as post-fetch row filtering on a DataFrame.
---

# inject_rls_postfetch

```python
def inject_rls_postfetch(df: pd.DataFrame, predicates: 'list[RlsPredicate]') -> pd.DataFrame
```

Apply RLS predicates as post-fetch row filtering on a DataFrame.

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
