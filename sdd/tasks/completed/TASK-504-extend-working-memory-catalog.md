# TASK-504: Extend WorkingMemoryCatalog for Generic Entries

**Feature**: extending-workingmemorytoolkit
**Spec**: `sdd/specs/extending-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-503
**Assigned-to**: unassigned

---

## Context

With `GenericEntry` and `EntryType` available from TASK-503, the catalog must
now support storing both `CatalogEntry` (DataFrames) and `GenericEntry`
(arbitrary data) under the same key namespace.

Implements **Module 2** from the spec.

---

## Scope

- Broaden `WorkingMemoryCatalog._store` type annotation to
  `dict[str, CatalogEntry | GenericEntry]`.
- Add `put_generic()` method that creates and stores a `GenericEntry`:
  ```python
  def put_generic(
      self, key: str, data: Any, *,
      entry_type: Optional[EntryType] = None,
      description: str = "",
      metadata: Optional[dict] = None,
      turn_id: Optional[str] = None,
  ) -> GenericEntry:
  ```
  If `entry_type` is None, auto-detect via `_detect_entry_type()`.
- Update `list_entries()` to handle both entry types — call `compact_summary()`
  on both `CatalogEntry` and `GenericEntry`, adding an `"entry_type"` field to
  each summary dict (`"dataframe"` for CatalogEntry, actual type for GenericEntry).
- Ensure `get()`, `drop()`, `keys()`, `__contains__`, `__len__` work
  unchanged with both types (they should already since they're dict operations,
  but verify type annotations).

**NOT in scope**: modifying `WorkingMemoryToolkit` tool methods or `__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/internals.py` | MODIFY | Extend `WorkingMemoryCatalog` |

---

## Implementation Notes

### Key Constraints

- `put()` remains DataFrame-only (unchanged). `put_generic()` is the new path.
- Key namespace is shared: storing a GenericEntry with a key that already holds
  a CatalogEntry **replaces** it (and vice versa). This is intentional.
- `list_entries()` must add `"entry_type": "dataframe"` to CatalogEntry summaries
  for consistency with GenericEntry summaries.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py:315-383` — current `WorkingMemoryCatalog`

---

## Acceptance Criteria

- [ ] `put_generic("key", "text data")` stores a `GenericEntry` with auto-detected type
- [ ] `put_generic("key", data, entry_type=EntryType.TEXT)` uses explicit type
- [ ] `put_generic("key", data, metadata={"tag": "v1"})` stores metadata
- [ ] `get("key")` returns `GenericEntry` when a generic was stored
- [ ] `drop("key")` removes generic entries
- [ ] `list_entries()` returns summaries for both CatalogEntry and GenericEntry
- [ ] Each summary dict includes `"entry_type"` field
- [ ] Storing generic on existing DataFrame key replaces it
- [ ] All existing tests pass: `pytest packages/ai-parrot/src/parrot/tools/working_memory/tests/ -v`

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.working_memory.internals import (
    WorkingMemoryCatalog, CatalogEntry, GenericEntry,
)
from parrot.tools.working_memory.models import EntryType


class TestCatalogGenericEntries:
    def test_put_generic_auto_detect(self):
        cat = WorkingMemoryCatalog()
        entry = cat.put_generic("note", "hello world")
        assert isinstance(entry, GenericEntry)
        assert entry.entry_type == EntryType.TEXT

    def test_put_generic_explicit_type(self):
        cat = WorkingMemoryCatalog()
        entry = cat.put_generic("data", {"a": 1}, entry_type=EntryType.JSON)
        assert entry.entry_type == EntryType.JSON

    def test_put_generic_with_metadata(self):
        cat = WorkingMemoryCatalog()
        entry = cat.put_generic("k", "text", metadata={"source": "api"})
        assert entry.metadata == {"source": "api"}

    def test_get_generic(self):
        cat = WorkingMemoryCatalog()
        cat.put_generic("k", "text")
        entry = cat.get("k")
        assert isinstance(entry, GenericEntry)

    def test_drop_generic(self):
        cat = WorkingMemoryCatalog()
        cat.put_generic("k", "text")
        assert cat.drop("k") is True
        assert "k" not in cat

    def test_list_mixed_entries(self):
        cat = WorkingMemoryCatalog()
        cat.put("df_key", pd.DataFrame({"a": [1]}))
        cat.put_generic("text_key", "hello")
        entries = cat.list_entries()
        types = {e["entry_type"] for e in entries}
        assert types == {"dataframe", "text"}

    def test_generic_replaces_dataframe(self):
        cat = WorkingMemoryCatalog()
        cat.put("k", pd.DataFrame({"a": [1]}))
        cat.put_generic("k", "replaced")
        assert isinstance(cat.get("k"), GenericEntry)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/extending-workingmemorytoolkit.spec.md` for full context
2. **Check dependencies** — TASK-503 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-504-extend-working-memory-catalog.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Implemented as specified. All 115 tests pass.

**Deviations from spec**: none
