# TASK-215: QuerySlugSource + MultiQuerySlugSource

**Feature**: DatasetManager Lazy Data Sources (FEAT-030)
**Spec**: `sdd/specs/datasetmanager-datasources.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-213
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Replaces the inline `_call_qs()` / `_call_multiquery()` logic currently living in
> `DatasetManager`. Wraps the existing QuerySource (`QS`) and multi-query patterns as proper
> `DataSource` implementations. Backward compat for `add_query()` depends on this task.

---

## Scope

Implement `QuerySlugSource` and `MultiQuerySlugSource` at `parrot/tools/dataset_manager/sources/query_slug.py`.

### `QuerySlugSource`

- Constructor: `slug: str`, `prefetch_schema_enabled: bool = True`
- `cache_key`: `f"qs:{self.slug}"`
- `fetch(**params)`: calls `QS(slug=self.slug, conditions=params)` (or equivalent existing pattern from `DatasetManager._call_qs()`). Returns `pd.DataFrame`.
- `prefetch_schema()`: if `prefetch_schema_enabled`, calls `QS(slug=self.slug, conditions={"querylimit": 1})` to fetch one row and infer columns+dtypes. Returns `{}` if call fails.
- `describe()`: returns `f"QuerySource slug '{self.slug}'"`

### `MultiQuerySlugSource`

- Constructor: `slugs: List[str]`, merged results across slugs.
- `cache_key`: `f"multiqs:{':'.join(sorted(self.slugs))}"`
- `fetch(**params)`: calls the existing multi-query pattern (`_call_multiquery`) for each slug and concatenates results.
- `prefetch_schema()`: runs one-row prefetch on each slug, merges schema dicts.
- `describe()`: returns `f"Multi-QuerySource slugs: {', '.join(self.slugs)}"`

### Key implementation detail

Copy the QS call logic from the existing `DatasetManager._call_qs()` and `_call_multiquery()` methods into these source classes — do not leave duplicated logic in `DatasetManager` (that cleanup happens in TASK-219).

Export both classes from `parrot/tools/dataset_manager/sources/__init__.py`.

**NOT in scope**: Changes to `DatasetManager.add_query()` (TASK-219). Removal of `_call_qs` from tool.py (TASK-219).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/sources/query_slug.py` | CREATE | QuerySlugSource + MultiQuerySlugSource |
| `parrot/tools/dataset_manager/sources/__init__.py` | MODIFY | Export both classes |

---

## Implementation Notes

- Look at the existing `_call_qs()` and `_call_multiquery()` in `parrot/tools/dataset_manager/tool.py` for the exact QS invocation pattern.
- `prefetch_schema` must silently handle QS failures (return `{}`) — schema is optional for query slugs.
- `conditions=params` — all kwargs passed to `fetch()` become the `conditions` dict.

### References in Codebase
- `parrot/tools/dataset_manager/tool.py` — `_call_qs()`, `_call_multiquery()` to extract logic from
- QuerySource import pattern (look for `QS` / `MultiQS` imports in existing tool.py)

---

## Acceptance Criteria

- [ ] `QuerySlugSource` at `parrot/tools/dataset_manager/sources/query_slug.py`
- [ ] `MultiQuerySlugSource` at same file
- [ ] `fetch()` passes `**params` as `conditions=` to QS call
- [ ] `prefetch_schema()` calls QS with `querylimit: 1` and returns inferred schema
- [ ] `prefetch_schema()` returns `{}` without raising on QS failure
- [ ] `cache_key` format: `qs:{slug}` / `multiqs:{slugs_sorted}`
- [ ] Both classes exported from `sources/__init__.py`
- [ ] Unit tests pass: `pytest tests/tools/test_datasources.py::TestQuerySlugSource -v`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-datasources.spec.md` for full context
2. **Check dependencies** — verify TASK-213 is in `sdd/tasks/completed/`
3. **Read** `parrot/tools/dataset_manager/tool.py` to extract `_call_qs()` / `_call_multiquery()` logic
4. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-215-queryslug-source.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**: Implemented `QuerySlugSource` and `MultiQuerySlugSource` in
`parrot/tools/dataset_manager/sources/query_slug.py`. Used a module-level
conditional import of `QS` (with `try/except ImportError`) so the name is
patchable in tests. All 21 new unit tests pass (30 total in the file).

**Deviations from spec**: None. Module-level import pattern chosen over lazy
per-function import to enable test mocking — behaviour is identical at runtime.
