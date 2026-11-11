# TASK-5518: DatasetEntry per-subject frame slots for self-governed sources (M7)

**Feature**: FEAT-880 — DatasetManager semantic source — add_semantic()
**Spec**: `sdd/specs/datasetmanager-semantic-source.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5517
**Assigned-to**: unassigned

---

## Context

Spec §2 'Per-subject frames' and §3 Module 7 (rev 0.3, owner decision 2026-11-11). On a DatasetManager shared by several users, a governed frame must be readable only by the subject that fetched it.

---

## Scope

- Turn `DatasetEntry._df` and `_column_types` into properties backed by `_frame` / `_frame_types` (ordinary sources) and an LRU dict of slots keyed by `source.current_owner()` (self-governed sources).
- Add `GOVERNED_FRAME_SLOTS = 32`.
- Make `DatasetEntry.materialize` return the fetched frame, not `self._df` (owner None stores nothing).
- `evict()` clears only the caller's slot for governed entries.
- Test at the pandas sync boundary; fix `PythonPandasTool.sync_from_manager` only if that test fails.

**NOT in scope**: server session isolation (TASK-5519); semantic source (TASK-5520).

---

## Files to Create / Modify

| File | Action | Purpose |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | properties, slots, materialize return |
| `packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py` | MODIFY | M7 tests |
| `packages/ai-parrot/src/parrot/tools/pythonpandas.py` | MODIFY | only if the sync-boundary test fails |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `254caceeb8` on `dev`. Re-verify before writing code.

### Verified Imports
```python
from collections import OrderedDict  # stdlib
from parrot.tools.dataset_manager import DatasetEntry, DatasetManager  # verified: test_datasets_clone.py:11
```

### Existing Signatures to Use
```python
# tool.py
class DatasetEntry:                                   # line 208
    self._df: Optional[pd.DataFrame] = df  # pre-load when df provided directly   # line 278
    self._column_types: Optional[Dict[str, str]] = None                         # line 279
    async def materialize(self, force=False, **params) -> pd.DataFrame          # line 337 (returns self._df, line 356)
    def evict(self) -> None                                                     # line 358
    loaded -> self._df is not None                                              # line 374
    df property/setter                                                          # lines 419-428
# `self.source` is assigned at lines 260-271, BEFORE line 278 — the setter can read it.
# pythonpandas.py: def sync_from_manager(self) -> None   # line 371, calls get_active_dataframes() line 385
```

### Does NOT Exist
- ~~`GOVERNED_FRAME_SLOTS`~~, ~~`_frame` / `_frame_slots`~~ — created here.
- ~~an owner field on DatasetEntry~~ — the owner always comes from `source.current_owner()`.

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
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/pythonpandas.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetEntry",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetEntry.materialize",
    "sym:packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py#DatasetEntry.evict",
    "sym:packages/ai-parrot/src/parrot/tools/pythonpandas.py#PythonPandasTool.sync_from_manager"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- About twenty sites read/write `entry._df`; do not edit them — the properties keep them working.
- `_clone_agent_dm` assigns `cloned_entry._df` (server `datasets.py:78`); the setter must accept it.
- Ordinary entries: identical behavior and identity of the stored object.
- Slot key comes from `self.source.current_owner()`; guard `self.source` existence during `__init__`.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py:337-365` (materialize/evict), `:374-428` (accessors).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the module constant and the four property methods on DatasetEntry — *why*: one rule for every reader.
2. Change line 278 to assign through the setter and initialise backing stores first — *why*: setter needs them.
3. `materialize`: keep the fetched frame in a local and return it — *why*: owner None stores nothing.
4. `evict`: `self._df = None; self._column_types = None` already routes to the caller's slot — verify.
5. Write the M7 tests, including the pandas sync boundary.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — DatasetEntry storage
```python
# occurrences: 1 (verified: grep -c 'class DatasetEntry:' tool.py) — module constant goes directly above it (tool.py:208)
GOVERNED_FRAME_SLOTS: int = 32  # FEAT-880: max subjects whose governed frames one entry keeps (LRU)

# occurrences: 1 each (verified: tool.py:278 and tool.py:279) — REPLACE both lines with:
        self._frame: Optional[pd.DataFrame] = None
        self._frame_types: Optional[Dict[str, str]] = None
        self._frame_slots: "OrderedDict[str, tuple[Optional[pd.DataFrame], Optional[Dict[str, str]]]]" = OrderedDict()
        self._df = df  # pre-load when df provided directly (routes through the property)
        self._column_types = None

    # ── FEAT-880: per-subject storage for self-governed sources ──
    def _governed(self) -> bool:
        source = getattr(self, "source", None)
        return bool(source is not None and getattr(source, "self_governed", False))

    def _owner(self) -> Optional[str]:
        return self.source.current_owner()

    @property
    def _df(self) -> Optional[pd.DataFrame]:
        if not self._governed():
            return self._frame
        owner = self._owner()
        if owner is None or owner not in self._frame_slots:
            return None
        self._frame_slots.move_to_end(owner)
        return self._frame_slots[owner][0]

    @_df.setter
    def _df(self, value: Optional[pd.DataFrame]) -> None:
        if not self._governed():
            self._frame = value
            return
        # FILL IN: owner None → store nothing; value None → pop the caller's slot; else set (frame, current types)
        #   and evict LRU slots beyond GOVERNED_FRAME_SLOTS — bounded by spec §3 M7.

    @property
    def _column_types(self) -> Optional[Dict[str, str]]:
        # FILL IN: same slot rule as _df, element [1]; ordinary → self._frame_types.

    @_column_types.setter
    def _column_types(self, value: Optional[Dict[str, str]]) -> None:
        # FILL IN: same slot rule as _df setter; never create a slot that has no frame.
```
**Why**: the init ordering puts backing stores in place before the first property write; `source` is already set.

### `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` (MODIFY) — `DatasetEntry.materialize`
```python
# occurrences: 1 (verified: grep -c '            self._df = await self.source.fetch(**params)' tool.py)
# REPLACE the body of the `if self._df is None or force:` block so the fetched frame is kept in a local:
        if self._df is None or force:
            frame = await self.source.fetch(**params)
            self._df = frame
            # FILL IN: apply computed columns and type detection to `frame`, then `self._df = frame` again and set
            #   self._column_types — bounded by: ordinary sources must produce exactly today's result.
            return frame
        return self._df
```

### `packages/ai-parrot/src/parrot/tools/pythonpandas.py` (MODIFY — conditional)
```python
# FILL IN: only if test_pandas_sync_has_no_foreign_governed_frame fails: in sync_from_manager (pythonpandas.py:371)
#   the bindings come from get_active_dataframes() (line 385), which now returns only the caller's frames;
#   ensure clear_dataframes() (line 382) removed the previous subject's governed variables. Otherwise leave
#   this file untouched and drop it from the commit.
```

### FILL IN checklist
- [ ] `_df` setter, `_column_types` getter/setter — bounded by spec §3 M7 bullets.
- [ ] materialize computed columns / types on the local frame — bounded by unchanged ordinary behavior.
- [ ] tests: `test_entry_frames_are_per_subject`, `test_entry_no_owner_reads_unloaded_and_stores_nothing`, `test_entry_slot_bound_lru`, `test_entry_evict_only_callers_slot`, `test_ordinary_entry_single_frame_unchanged`, `test_manager_accessors_hide_other_subjects_frames`, `test_pandas_sync_has_no_foreign_governed_frame`.

---

## Acceptance Criteria

- [ ] A governed frame fetched by subject A reads as not loaded for subject B on the same entry and manager
- [ ] Owner None: not loaded, nothing stored
- [ ] Slots bounded by GOVERNED_FRAME_SLOTS (LRU)
- [ ] `evict()` clears only the caller's slot
- [ ] Ordinary entries unchanged; all earlier tests in the core file still pass
- [ ] `get_active_dataframes`, `get_dataframe` and the DataFrame guide omit other subjects' frames

---

## Validation Commands

- `pytest packages/ai-parrot/tests/tools/test_dataset_self_governed_source.py -q`
- `pytest packages/ai-parrot-server/tests/handlers/test_datasets_clone.py -q`
- `pytest packages/ai-parrot/tests/test_pythonpandas_integration.py -q`

---

## Test Specification

Switch subject in tests by mutating `_GovernedSource.owner` between calls. For the pandas boundary, attach the manager to a `PythonPandasTool` the way `packages/ai-parrot/tests/test_pythonpandas_integration.py` does.

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
9. **Close the task** with `parrot sdd task close TASK-5518 datasetmanager-semantic-source verified`
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
