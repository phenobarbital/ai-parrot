# TASK-4678: Shared `request_scoped_copy` helper + request-scoped RLS injection

**Feature**: FEAT-738 — Request-scoped RLS injection and non-shared dataset sources
**Spec**: `sdd/specs/handlers-datasets-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:90cf04ce8edd`

---

## Context

`AuthorizingDataSource` injects RLS predicates by **mutating the source it wraps**.
Because the wrapper holds a long-lived reference to that object, predicates accumulate
across successive `fetch()` calls, and the mutation is visible to every other holder of
the same inner source. Combined with TASK-4679's shared-source defect this becomes a
cross-subject leak (`issue:90cf04ce8edd`, kind `vulnerability`, severity `major`).

The complete mutation surface, verified on `dev`:

| Inner source | Mutated attribute | Container |
|---|---|---|
| `SQLQuerySource` | `self._inner.sql = rewritten_sql` | `str` (rebind) |
| `TableSource` | `source._permanent_filter[col]` via `inject_rls_table_source` | shared `dict` |
| `QuerySlugSource` | `source._permanent_filter[col]` via `inject_rls_query_slug` | shared `dict` |
| `MongoSource` | `self._inner.required_filter = {...}` | rebind, reads prior value |

A shallow copy plus a fresh `_permanent_filter` dict covers all four.

## Scope

- Add `sources/scoped_copy.py` with the public `request_scoped_copy()` helper and export it.
- Make `_apply_rls` operate on, and return, a per-request copy; `fetch()` delegates to it.
- Extend the existing auth tests with non-mutation and no-accumulation coverage.

### NOT in scope

- `packages/ai-parrot-server/src/parrot/handlers/datasets.py` — that is TASK-4679.
- Post-fetch RLS for Airtable/Smartsheet (`inject_rls_postfetch`) — deferred, FEAT-228.
- Any change to predicate rendering, PBAC evaluation or `DataPlanePolicyGuard`.
- `rls.py` itself — the injectors keep mutating whatever object they are handed.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/scoped_copy.py` | CREATE |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py` | MODIFY |
| `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py` | MODIFY |
| `packages/ai-parrot/tests/auth/test_authorizing_data_source.py` | MODIFY |

## Codebase Contract

### Verified Imports

```python
from parrot.tools.dataset_manager.sources.base import DataSource
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
from parrot.tools.dataset_manager.sources.table import TableSource
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
from parrot.tools.dataset_manager.sources.rls import (
    inject_rls_sql, inject_rls_table_source, inject_rls_query_slug, inject_rls_mongo,
)
from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect
```

### Existing Signatures (verified on dev 2026-10-24)

- `sources/base.py:23` `class DataSource(ABC)`; `:46` `def __init__(self, routing_meta: Dict | None = None) -> None`
- `sources/authorizing.py:41` `class AuthorizingDataSource(DataSource)`
- `sources/authorizing.py:58` `def __init__(self, inner: DataSource, guard, pctx_provider) -> None` — sets `self._inner`, `self._guard`, `self._pctx_provider`, `self._logger`
- `sources/authorizing.py:74` `async def fetch(self, **params) -> pd.DataFrame`
- `sources/authorizing.py:153` `def _apply_rls(self, predicates, resources) -> None` ← return type becomes `DataSource`
- `sources/rls.py:72` `def inject_rls_sql(...)` → returns `(rewritten_sql, bound_params)` tuple
- `sources/rls.py:132` `def inject_rls_table_source(source, predicates) -> "TableSource"` — mutates `source._permanent_filter`
- `sources/rls.py:172` `def inject_rls_query_slug(source, predicates) -> "QuerySlugSource"` — mutates `source._permanent_filter`
- `sources/rls.py:212` `def inject_rls_mongo(source, predicates) -> dict[str, Any]`
- `sources/__init__.py` re-exports source classes with `from .<mod> import <Name>`

### Does NOT Exist (Anti-Hallucination)

- No module `sources/scoped_copy.py`; no symbol `request_scoped_copy` anywhere in the repo.
- No `DataSource.clone()`, `.copy()`, `.with_rls()` or `.__copy__()` method.
- `authorizing.py` does **not** import `copy` today.
- `SQLQuerySource` has **no** `_permanent_filter`; only `TableSource` and `QuerySlugSource` do.
- `inject_rls_sql` does **not** mutate its argument — it returns a new string.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/scoped_copy.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/auth/test_authorizing_data_source.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py#AuthorizingDataSource",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/sources/base.py#DataSource"
  ]
}
```

## Implementation Blueprint

### `sources/scoped_copy.py` — CREATE

```python
"""Request-scoped copies of :class:`DataSource` instances.

RLS injection must never mutate a source that outlives the request: the
``AuthorizingDataSource`` wrapper and the per-user ``DatasetManager`` clones both
hold long-lived references, so an in-place rewrite leaks one subject's predicates
into another subject's queries (``issue:90cf04ce8edd``).
"""

from __future__ import annotations

import copy

from .base import DataSource

__all__ = ("request_scoped_copy",)


def request_scoped_copy(source: DataSource) -> DataSource:
    """Return a copy of ``source`` that RLS injection may safely mutate.

    A shallow copy is enough for every attribute the RLS injectors rebind
    (``sql``, ``required_filter``), but ``inject_rls_table_source`` and
    ``inject_rls_query_slug`` write *into* ``_permanent_filter``, so that dict is
    replaced with a fresh one. A deep copy is deliberately avoided: sources carry
    credentials objects and cached schema, which are expensive and sometimes
    impossible to deep-copy.

    Args:
        source: The data source to isolate for the current request.

    Returns:
        A copy safe to mutate; ``source`` itself is left untouched.
    """
    scoped = copy.copy(source)
    permanent_filter = getattr(scoped, "_permanent_filter", None)
    if isinstance(permanent_filter, dict):
        scoped._permanent_filter = dict(permanent_filter)
    return scoped
```

**Why**: one function owns the mutation surface, so Module 2 cannot drift from Module 1.
`getattr` + `isinstance` rather than a type check, because only two of the five source
types have the attribute and `MongoSource` is an optional import.

### `sources/__init__.py` — MODIFY

```python
# AFTER — insert below `from .composite import CompositeDataSource, JoinSpec`
# occurrences: 1 (verified: grep -c 'from .composite import CompositeDataSource, JoinSpec')
from .scoped_copy import request_scoped_copy
```

**Why**: `handlers/datasets.py` (TASK-4679) imports it from the package, not the module.
`# FILL IN: if the file defines __all__, add "request_scoped_copy" to it — check first.`

### `sources/authorizing.py` — MODIFY

```python
# AFTER — insert below `from parrot.tools.dataset_manager.sources.dialects import driver_to_dialect`
# occurrences: 1 (verified: grep -c inside _apply_rls)
        from parrot.tools.dataset_manager.sources.scoped_copy import request_scoped_copy
```

```python
# REPLACE — fetch() step 5/6
# anchor: `        # Step 5: inject RLS if predicates were collected`
# occurrences: 1 (verified: grep -c '# Step 5: inject RLS if predicates were collected')
        # Step 5: inject RLS into a request-scoped copy, never into self._inner
        target = self._apply_rls(predicates, resources) if predicates else self._inner

        # Step 6: delegate to the (possibly RLS-filtered) per-request source
        return await target.fetch(**params)
```

```python
# REPLACE — _apply_rls signature + body head
# anchor: `    def _apply_rls(`
# occurrences: 1 (verified: grep -c '    def _apply_rls(')
    def _apply_rls(
        self,
        predicates: "list[RlsPredicate]",
        resources: "PhysicalResources",
    ) -> DataSource:
        """Return a request-scoped copy of the inner source with RLS applied.

        ``self._inner`` is never mutated: the caller fetches from the returned
        copy, so predicates cannot accumulate across requests nor leak to other
        holders of the same source (``issue:90cf04ce8edd``).

        Args:
            predicates: Rendered RLS predicates to inject.
            resources: Physical resources (provides dialect context for SQL).

        Returns:
            The copy to fetch from. Unsupported source types are returned unchanged.
        """
```

**Why**: changing the return type is what lets `fetch()` stop reading the mutated
attribute off `self._inner`. The docstring's "Strategy (Spec §2 Module 5)" text and the
existing imports inside the method are kept.

`# FILL IN: rewrite every branch body to use a local `scoped = request_scoped_copy(self._inner)``
`#          instead of `self._inner`, and `return scoped` from each branch —`
`#          bounded by AC1/AC3: the isinstance checks still test `self._inner`, the`
`#          writes and the fetch target are the copy. Four branches: SQLQuerySource,`
`#          TableSource, QuerySlugSource, and the Mongo/else branch (which must also`
`#          return the copy on its fall-through path).`

### `tests/auth/test_authorizing_data_source.py` — MODIFY

```python
# AFTER — append at end of file
# occurrences: n/a (append)
```

`# FILL IN: five tests, bounded by AC1–AC3 and the Test Specification in the spec:`
`#   test_fetch_does_not_mutate_inner_sql`
`#   test_repeated_fetch_does_not_accumulate_predicates`
`#   test_fetch_does_not_mutate_table_source_permanent_filter`
`#   test_fetch_does_not_mutate_query_slug_permanent_filter`
`#   test_rls_predicates_still_applied`
`# Reuse the module's existing guard/pctx fixtures — read the file first and match them.`

### Steps (in order)

1. Create `scoped_copy.py` exactly as blocked above — because both modules must share one
   definition of the mutation surface.
2. Export it from `sources/__init__.py` — because TASK-4679 imports from the package.
3. Change `_apply_rls`'s signature and docstring, then rewrite its four branches to write
   to the copy and return it — because the return value is what `fetch()` now delegates to.
4. Change `fetch()` steps 5/6 — do this *after* step 3 so the file never has a `None`-returning
   `_apply_rls` wired to a `target` variable.
5. Add the five tests, then run the Validation Commands.

### FILL IN checklist

- [ ] `__all__` in `sources/__init__.py` updated if present
- [ ] all four `_apply_rls` branches write to the copy and return it (incl. Mongo fall-through)
- [ ] the `pctx is None` fail-open path still returns `self._inner.fetch(**params)` unchanged
- [ ] five tests written against the module's existing fixtures

## Acceptance Criteria

- AC1. After any `fetch()`, the wrapped inner source is unchanged (`sql`, `_permanent_filter`, `required_filter`).
- AC2. Two successive `fetch()` calls send identical SQL/filters to the inner source.
- AC3. Predicates are still applied to the source actually fetched from.
- AC6. `ruff check` clean on the touched files.

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_authorizing_data_source.py -q`
- `pytest packages/ai-parrot/tests/auth/test_datasetmanager_authz_integration.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_epson_dashboard_golden.py -q`
- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_derived_sources.py -q`

## Test Specification

Unit tests only; no live database. Use the existing fake guard / `pctx` fixtures already
present in `test_authorizing_data_source.py`. Assert on object identity for the
`_permanent_filter` dict, not just equality — equality alone passes even when the original
is mutated to the same value.

## Agent Instructions

Run with `PYTHONPATH=packages/ai-parrot/src`. Do not touch `rls.py`, do not touch the
server package, do not change enforcement semantics. Read
`test_authorizing_data_source.py` before writing tests so fixture names match.

## Completion Note

_(fill in on completion)_
