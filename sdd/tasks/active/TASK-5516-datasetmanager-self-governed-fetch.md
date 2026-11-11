# TASK-5516: DatasetManager: no wrapper, always re-fetch, no Redis, conditions forwarding (M2a)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5515
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview items 1-4 and §3 Module 2. A self-governed source authorizes itself, so DatasetManager must not wrap, cache or reuse its rows, must pass `conditions` through as fetch params, and must not mark the entry unavailable for everyone when one subject is denied.

---

## Scope

- `_make_source`: return a self-governed source unwrapped.
- `materialize`: for a self-governed source always `entry.materialize(force=True, **params)`; skip the loaded shortcut and both Redis calls; never pass `force_refresh` to the source.
- `fetch_dataset`: new branch before the TableSource branch: `params = dict(conditions or {})`, ignore `sql`; on exception, skip `_classify_fetch_failure` / `unavailable_reason` and return the correctable error dict.

**NOT in scope**: response metadata and guidance (TASK-5517); per-subject slots (TASK-5518); add_semantic (TASK-5521).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | four self-governed branches |
| `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` | MODIFY | M2a tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
from parrot.tools.dataset_manager import DatasetManager  # verified: server tests import it (test_datasets_clone.py:11)
from parrot.tools.dataset_manager.sources.base import DataSource
```

### Existing Signatures to Use
```python
# tool.py
def _make_source(self, source: "DataSource") -> "DataSource":          # line 682; InMemorySource check line 706
async def fetch_dataset(self, name, sql=None, conditions=None, force_refresh=False) -> Dict[str, Any]  # line 3415
    # source-type branches start line 3515; `elif isinstance(entry.source, TableSource):` line 3525
    # materialize call line 3678; `kind = _classify_fetch_failure(...)` line 3681
    # correctable error dict built at lines 3721-3728
async def materialize(self, name, force_refresh=False, **params) -> pd.DataFrame  # line 4270
    # `if entry.loaded and not force_refresh:` line 4307; has_builtin_cache branch 4311-4315
async def _get_cached_df(self, source)  # line 4255
async def _cache_df(self, source, df, ttl)  # line 4244
```

### Does NOT Exist
- ~~A `self_governed` branch anywhere in `tool.py`~~ — added here.
- ~~`DatasetManager.add_semantic`~~ — TASK-5521.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager._make_source",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.materialize",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetManager.fetch_dataset",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#_classify_fetch_failure"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Ordinary sources must behave exactly as before — every new branch is guarded by `source.self_governed`.
- When a dataplane guard wraps a source, `entry.source` is the wrapper; this task makes self-governed sources never wrapped, so `entry.source.self_governed` is read directly.
- The self-governed branch in `materialize` must come BEFORE the loaded shortcut at line 4307.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:4311-4315` — the has_builtin_cache branch to mirror (without `force_refresh`).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. `_make_source`: return early for self-governed — *why*: no second RLS, no fail-open (spec §2 item 1).
2. `materialize`: add the branch before line 4307 — *why*: a loaded frame belongs to a previous query.
3. `fetch_dataset`: add the params branch and the error bypass — *why*: denial is per subject.
4. Append tests; run validation.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — `_make_source`
```python
# occurrences: 1 (verified: grep -c '        if isinstance(source, InMemorySource):' tool.py)
# AFTER — insert below `        if isinstance(source, InMemorySource):` + its `return source` (verified: tool.py:706-707)
        if source.self_governed:
            # Self-governed sources enforce PBAC/RLS/masking themselves (FEAT-880).
            return source
```

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — `materialize`
```python
# occurrences: 1 (verified: grep -c '        if entry.loaded and not force_refresh:' tool.py)
# BEFORE — insert above `        # Already in memory and no refresh needed` (verified: tool.py:4306)
        if entry.source.self_governed:
            # FEAT-880: rows are query- and subject-specific — always re-fetch, never cache.
            df = await entry.materialize(force=True, **params)
            if self.generate_guide:
                self.df_guide = self._generate_dataframe_guide()
            return df
```

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — `fetch_dataset` params branch
```python
# occurrences: 1 (verified: grep -c '        elif isinstance(entry.source, TableSource):' tool.py)
# BEFORE — insert above `        elif isinstance(entry.source, TableSource):` (verified: tool.py:3525)
        elif entry.source.self_governed:
            # FEAT-880: `conditions` carries the source's query (e.g. semantic fields); sql is ignored.
            params = dict(conditions or {})
```

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — `fetch_dataset` error path
```python
# occurrences: 1 (verified: grep -c '            kind = _classify_fetch_failure(exc, getattr(entry.source, "table", None))' tool.py)
# BEFORE — insert above that line (verified: tool.py:3681), inside `except Exception as exc:`
            if entry.source.self_governed:
                # A denial is per subject: never mark the shared entry unavailable.
                message = f"Error fetching dataset '{name}': {exc}"
                return {
                    "status": "error",
                    "success": False,
                    "result": None,
                    "error": message,
                }
```

### `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` (MODIFY — append)
```python
from parrot.tools.dataset_manager import DatasetManager


@pytest.mark.asyncio
async def test_materialize_always_refetches_self_governed() -> None:
    dm = DatasetManager(generate_guide=False)
    source = _GovernedSource()
    dm.add_source(source)
    await dm.materialize("governed", metrics=["a"])
    await dm.materialize("governed", metrics=["b"])
    assert source.calls == [{"metrics": ["a"]}, {"metrics": ["b"]}]


# FILL IN: test_make_source_skips_wrapper_for_self_governed — DatasetManager(dataplane_guard=<stub object>)
#   then dm._datasets["governed"].source is source.
# FILL IN: test_materialize_skips_redis_for_self_governed — monkeypatch dm._get_cached_df/_cache_df to fail if called.
# FILL IN: test_fetch_dataset_forwards_conditions — fetch_dataset(name, sql="x", conditions={...}) → calls[-1] == conditions.
# FILL IN: test_fetch_dataset_denial_does_not_mark_unavailable — a double whose fetch raises PermissionError("permission denied");
#   assert success False and entry.unavailable_reason is None, then a second call still reaches fetch.
```

### FILL IN checklist
- [ ] four test bodies listed in the append block — bounded by spec §4 M2 rows; no Redis, no network.

---

## Acceptance Criteria

- [ ] A self-governed source is never wrapped in AuthorizingDataSource
- [ ] Two materializations with different params produce two fetch calls; no Redis read/write
- [ ] `fetch_dataset` forwards `conditions` and ignores `sql` for self-governed sources
- [ ] A denied fetch leaves `unavailable_reason` unset
- [ ] Ordinary sources unchanged (existing authz test file passes)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py -q`
- `pytest packages/ai-parrot/tests/auth/test_authorizing_data_source.py -q`

---

## Test Specification

See the append block above.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug datasetmanager-semantic-source --feature-id FEAT-880`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/datasetmanager-semantic-source.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/datasetmanager-semantic-source.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands with
   `PYTHONPATH` set to the absolute `src` dirs of every changed package (worktree rule)
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5516 datasetmanager-semantic-source verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
