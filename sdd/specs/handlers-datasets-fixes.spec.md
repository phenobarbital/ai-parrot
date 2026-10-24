---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [security, rls, pbac, dataset-manager, dataplane]
---

# Feature Specification: Request-scoped RLS injection and non-shared dataset sources

**Feature ID**: FEAT-738
**Date**: 2026-10-24
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.3.0
**Source**: `issue:90cf04ce8edd` (ledger, kind `vulnerability`, severity `major`,
discovered from `spec:FEAT-704`)

---

## 1. Motivation & Business Requirements

### Problem Statement

`AuthorizingDataSource` enforces PBAC and injects row-level-security predicates before
delegating to the wrapped source. It performs that injection **by mutating the wrapped
source object in place**, and the HTTP dataset handlers **share one source object across
per-user `DatasetManager` clones**. Together these two facts make one subject's RLS
predicates observable by another subject.

Two independent defects, both verified in source on `dev`:

1. **In-place RLS mutation** —
   `packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`,
   `AuthorizingDataSource._apply_rls()` mutates `self._inner` on every branch:

   | Inner source | Mutated attribute | Container |
   |---|---|---|
   | `SQLQuerySource` | `self._inner.sql = rewritten_sql` | `str` (rebind) |
   | `TableSource` | `source._permanent_filter[col]` via `inject_rls_table_source` | shared `dict` |
   | `QuerySlugSource` | `source._permanent_filter[col]` via `inject_rls_query_slug` | shared `dict` |
   | `MongoSource` | `self._inner.required_filter = {...}` | rebind, reads prior value |

   Because the wrapper holds a long-lived reference, predicates **accumulate across
   successive requests** on the same wrapper, and the mutation is visible to every other
   holder of the same inner object.

2. **Shared source across user-scoped managers** —
   `packages/ai-parrot-server/src/parrot/handlers/datasets.py`, `_clone_agent_dm()`
   builds per-user `DatasetEntry` clones with `source=entry.source`. It deep-copies the
   DataFrame (`entry.df.copy(deep=True)`) and the metadata/column-type dicts, but passes
   the **same `DataSource` instance** to every user's manager.

Defect 2 turns defect 1 from a per-session accumulation bug into a **cross-subject
leak**: subject A's RLS rewrite lands on an object subject B's manager also points at.

The semantic layer (FEAT-704) is unaffected — it clones the AST per request and hands off
DataFrames only — but it does not touch these code paths and is itself not started, so it
neither fixes nor shields `DatasetManager` users.

### Goals

- G1. RLS injection is **request-scoped**: a `fetch()` call never mutates `self._inner`.
- G2. Repeated `fetch()` calls on one `AuthorizingDataSource` produce the same predicates,
  never an accumulation.
- G3. Per-user `DatasetManager` clones never share a mutable `DataSource` instance.
- G4. The existing enforcement semantics are unchanged: same predicates, same denials,
  same fail-open on `pctx is None`, same fail-closed on sensitive drivers.

### Non-Goals (explicitly out of scope)

- Post-fetch RLS for Airtable/Smartsheet (`inject_rls_postfetch`) — still deferred (FEAT-228).
- Any change to predicate rendering, PBAC evaluation, or `DataPlanePolicyGuard`.
- The other fields `_clone_agent_dm` currently drops (`description`, `computed_columns`,
  `usage_guidance`, `protected`, `no_cache`) — a separate tidy-up, not a security defect.
- The semantic layer (FEAT-704) in any form.

---

## 2. Architectural Design

### Overview

`_apply_rls` changes from a mutator returning `None` into a **factory returning the source
to fetch from**. `fetch()` binds the result to a local and delegates to that local, so the
wrapper's own `_inner` stays pristine for the next request.

The copy is a `copy.copy()` (shallow) plus an explicit fresh `dict` for the one mutable
container the injectors write into (`_permanent_filter`). A full `deepcopy` is deliberately
avoided: `TableSource` caches `_schema` and `_row_count_estimate`, and sources may hold
credentials objects — a shallow copy with targeted container isolation is both cheaper and
narrower.

### Integration Points

- `AuthorizingDataSource.fetch()` — step 5/6 delegate to the per-request source.
- `DatasetManager._make_source()` (`tool.py:599`) wraps sources in `AuthorizingDataSource`;
  unchanged, it only ever sees the wrapper.
- `_clone_agent_dm()` (`handlers/datasets.py:47`) — the only caller is line 130.

### Data Models

No new models. No signature change to any public API; `_apply_rls` is private.

---

## 3. Module Breakdown

### Module 1: Request-scoped RLS injection (`ai-parrot`)

`packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py`

- Add `import copy` at module scope.
- Add a private helper `_request_scoped_copy(inner: DataSource) -> DataSource` that returns
  `copy.copy(inner)` and, when the copy exposes a `_permanent_filter` dict, rebinds it to
  `dict(inner._permanent_filter)` so the injectors cannot reach the original.
- Change `_apply_rls(self, predicates, resources) -> DataSource`: it operates on the copy,
  never on `self._inner`, and returns the copy. Every branch that currently writes to
  `self._inner` writes to the local copy instead. The unsupported-source branch returns the
  copy unchanged.
- Change `fetch()` step 5/6 to:
  `target = self._apply_rls(predicates, resources) if predicates else self._inner`, then
  `return await target.fetch(**params)`.
- Logging messages and levels are unchanged.

### Module 2: Non-shared source in per-user clones (`ai-parrot-server`)

`packages/ai-parrot-server/src/parrot/handlers/datasets.py`

- `_clone_agent_dm()` passes an isolated source to each `DatasetEntry` rather than
  `entry.source`, using the same shallow-copy-plus-container-isolation rule so a per-user
  manager can never write through to the agent's catalog object.
- The existing `try/except Exception` per entry keeps its behaviour: a source that cannot be
  copied logs the existing warning and that entry is skipped, never silently shared.

---

## 4. Test Specification

### Unit Tests

`packages/ai-parrot/tests/auth/test_authorizing_data_source.py` (extend):

- `test_fetch_does_not_mutate_inner_sql` — a `SQLQuerySource` wrapper with one predicate:
  after `fetch()`, `inner.sql` is byte-identical to the original.
- `test_repeated_fetch_does_not_accumulate_predicates` — two successive `fetch()` calls
  produce the same SQL handed to the inner fetch; the second is not doubly-filtered.
- `test_fetch_does_not_mutate_table_source_permanent_filter` — `TableSource._permanent_filter`
  is unchanged after `fetch()`, and the dict object identity differs from the one the
  injector wrote into.
- `test_fetch_does_not_mutate_query_slug_permanent_filter` — same for `QuerySlugSource`.
- `test_rls_predicates_still_applied` — the source actually fetched from carries the
  predicates (guards against "fixed the leak by dropping enforcement").

`packages/ai-parrot-server/tests/handlers/test_datasets_clone.py` (new):

- `test_clone_agent_dm_does_not_share_source` — the cloned entry's `source` is not the same
  object as the agent entry's source.
- `test_clone_agent_dm_isolates_mutation` — mutating the clone's source leaves the agent's
  source untouched.
- `test_clone_agent_dm_skips_uncopyable_source` — a source whose copy raises is skipped with
  the existing warning rather than shared.

### Validation Contract

```bash
PYTHONPATH=packages/ai-parrot/src python -m pytest packages/ai-parrot/tests/auth/ -q
PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src python -m pytest packages/ai-parrot-server/tests/handlers/ -q
PYTHONPATH=packages/ai-parrot/src python -m pytest packages/ai-parrot/tests/outputs/a2ui/linked/ -q
ruff check packages/ai-parrot/src/parrot/tools/dataset_manager/sources/authorizing.py packages/ai-parrot-server/src/parrot/handlers/datasets.py
```

---

## 5. Acceptance Criteria

- AC1. After any `fetch()` on an `AuthorizingDataSource`, the wrapped inner source is
  attribute-for-attribute unchanged (`sql`, `_permanent_filter`, `required_filter`).
- AC2. Two successive `fetch()` calls with the same `PermissionContext` send identical SQL
  / filters to the inner source — no accumulation.
- AC3. The predicates are still applied to the source actually fetched from.
- AC4. `_clone_agent_dm` yields entries whose `source` is not the agent's source object, and
  mutating the clone's source does not affect the agent's.
- AC5. `packages/ai-parrot/tests/auth/` and the a2ui linked golden tests pass unchanged.
- AC6. `ruff check` clean on both touched files.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.tools.dataset_manager.sources.authorizing import AuthorizingDataSource
from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
from parrot.tools.dataset_manager.sources.table import TableSource
from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
from parrot.tools.dataset_manager.sources.rls import (
    inject_rls_sql, inject_rls_table_source, inject_rls_query_slug, inject_rls_mongo,
)
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetManager
```

### Existing Signatures (verified on dev 2026-10-24)

- `authorizing.py:41` `class AuthorizingDataSource(DataSource)`
- `authorizing.py:58` `def __init__(self, inner: DataSource, guard: "DataPlanePolicyGuard", pctx_provider: Callable[[], Optional["PermissionContext"]]) -> None`
- `authorizing.py:74` `async def fetch(self, **params) -> pd.DataFrame`
- `authorizing.py:153` `def _apply_rls(self, predicates: "list[RlsPredicate]", resources: "PhysicalResources") -> None` ← return type changes to `DataSource`
- `rls.py:72` `def inject_rls_sql(...)` → returns `(rewritten_sql, bound_params)`
- `rls.py:132` `def inject_rls_table_source(source, predicates) -> "TableSource"` (mutates `source._permanent_filter`)
- `rls.py:172` `def inject_rls_query_slug(source, predicates) -> "QuerySlugSource"` (mutates `source._permanent_filter`)
- `rls.py:212` `def inject_rls_mongo(source, predicates) -> dict[str, Any]`
- `handlers/datasets.py:47` `def _clone_agent_dm(agent: object, logger: object) -> DatasetManager | None` (sole caller: line 130)
- `tool.py:129` `class DatasetEntry`, `__init__(self, name, description=None, source=None, metadata=None, is_active=True, auto_detect_types=True, cache_ttl=3600, no_cache=False, df=None, query_slug=None, computed_columns=None, usage_guidance=None, protected=False)`
- `tool.py:599` `def DatasetManager._make_source(self, source: "DataSource") -> "DataSource"`

### Does NOT Exist (Anti-Hallucination)

- There is **no** `DataSource.clone()`, `.copy()` or `.with_rls()` method — the copy must be
  built with `copy.copy` in the caller.
- There is **no** existing test file `packages/ai-parrot-server/tests/handlers/test_datasets_clone.py`.
- `_clone_agent_dm` has **no** test coverage anywhere today.
- `authorizing.py` does **not** currently import `copy`.
- `SQLQuerySource` has no `_permanent_filter`; only `TableSource` and `QuerySlugSource` do.

### Edit Sites (Blueprint Anchors)

- `authorizing.py` — `# Step 5: inject RLS if predicates were collected` (fetch)
- `authorizing.py` — `# Mutate the sql attribute so the inner fetch uses the rewritten SQL.`
- `authorizing.py` — `elif isinstance(self._inner, TableSource):`
- `authorizing.py` — `elif isinstance(self._inner, QuerySlugSource):`
- `handlers/datasets.py` — `cloned_entry = DatasetEntry(`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first; no blocking calls added. `copy.copy` is cheap and synchronous.
- No new dependency. `copy` is stdlib.
- Google-style docstrings, full type hints, 120 columns, `black` + `ruff`.

### Known Risks / Gotchas

- **Do not use `copy.deepcopy`.** Sources carry `_credentials` and cached `_schema` /
  `_row_count_estimate`; a deep copy is expensive per request and may fail on
  non-copyable credential objects. Shallow copy + fresh `_permanent_filter` dict is the
  whole mutation surface (table above).
- `MongoSource` is imported lazily inside `_apply_rls` and may be absent — keep the existing
  `try/ImportError` shape.
- The `pctx is None` fail-open path returns before step 5 and must keep returning
  `self._inner.fetch(...)` directly.
- `cache_key` / `has_builtin_cache` delegate to `self._inner`; since `_inner` is no longer
  mutated, cache keys stop drifting between requests — this is the intended behaviour, but
  check the a2ui linked golden tests, which assert on cached dashboards.

---

## 8. Open Questions

None. Both halves and the copy strategy are settled by the mutation table in §1.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-10-24 | Jesus Lara | Initial spec from `issue:90cf04ce8edd` |
