# TASK-505: Add Generic Tool Methods (store_result, get_result, search_stored)

**Feature**: extending-workingmemorytoolkit
**Spec**: `sdd/specs/extending-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-503, TASK-504
**Assigned-to**: unassigned

---

## Context

With the catalog extended for generic entries, this task adds the new tool
methods that let the LLM store and retrieve arbitrary data. Also adds
`search_stored()` (resolved open question) and extends existing `drop_stored()`
and `list_stored()` to handle both entry types.

Implements **Module 3** from the spec.

---

## Scope

- Add `store_result()` async tool method:
  - Accepts `key`, `data` (Any), `data_type` (str, default "auto"),
    `description`, `metadata` (optional dict), `turn_id`.
  - Uses `_catalog.put_generic()`.
  - Returns summary with `entry_type` field.

- Add `get_result()` async tool method:
  - Accepts `key`, `max_length` (int, default 500), `include_raw` (bool, default False).
  - Returns type-aware compact summary from `GenericEntry.compact_summary()`.
  - When `include_raw=True`, also include the raw data object in the response
    (serialised to string if needed for non-JSON-serialisable types).

- Add `search_stored()` async tool method:
  - Accepts `query` (substring match on key or description, case-insensitive),
    `entry_type` (optional `EntryType` filter).
  - Returns matching entries with compact summaries.

- Update `drop_stored()` to work with both `CatalogEntry` and `GenericEntry`
  (should already work since it delegates to `_catalog.drop()`, but update
  the docstring to reflect this).

- Update `list_stored()` to include `entry_type` in each entry summary.

- Update toolkit `description` to reflect the broader capability.

**NOT in scope**: AnswerMemory bridge (TASK-506), BasicAgent changes (TASK-507).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Add `store_result()`, `get_result()`, `search_stored()`, update descriptions |

---

## Implementation Notes

### Pattern to Follow

Follow the existing `@tool_schema` pattern used by `store()`, `get_stored()`, etc.:
```python
@tool_schema(StoreResultInput)
async def store_result(self, key: str, data: Any, ...) -> dict:
    """Store any intermediate result into working memory."""
    ...
```

### Key Constraints

- `store_result()` must auto-detect `EntryType` via `_detect_entry_type()` when
  `data_type="auto"`. When explicit, convert string to `EntryType` enum.
- `get_result()` should raise `KeyError` (via `_catalog.get()`) for missing keys.
  The existing error handling pattern wraps exceptions in a dict.
- `search_stored()` iterates `_catalog._store.values()` and matches:
  - `query` substring in `entry.key` or `entry.description` (case-insensitive)
  - `entry_type` filter (if provided) checks `GenericEntry.entry_type` or
    treats `CatalogEntry` as `EntryType.DATAFRAME`.
- For `include_raw=True` on `get_result()`, return the raw data directly in the
  result dict. For non-serialisable objects, use `repr()`.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` — existing tool methods

---

## Acceptance Criteria

- [ ] `store_result("key", "text")` stores and returns summary with `entry_type: "text"`
- [ ] `store_result("key", {"a": 1})` returns summary with `entry_type: "json"`
- [ ] `store_result("key", data, metadata={"tag": "v1"})` stores metadata
- [ ] `get_result("key")` returns type-aware summary
- [ ] `get_result("key", include_raw=True)` includes raw data
- [ ] `get_result("key", max_length=50)` truncates preview at 50 chars
- [ ] `search_stored(query="market")` finds entries with "market" in key or description
- [ ] `search_stored(entry_type="text")` filters to text entries only
- [ ] `list_stored()` includes `entry_type` for all entries
- [ ] `drop_stored()` works for generic entries
- [ ] Toolkit `description` updated
- [ ] All existing tests pass

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.working_memory import WorkingMemoryToolkit


@pytest.fixture
def toolkit():
    return WorkingMemoryToolkit()


class TestStoreResult:
    async def test_store_text(self, toolkit):
        result = await toolkit.store_result(key="note", data="hello world")
        assert result["status"] == "stored"
        assert "text" in str(result)

    async def test_store_dict(self, toolkit):
        result = await toolkit.store_result(key="api", data={"status": "ok"})
        assert result["status"] == "stored"

    async def test_store_with_metadata(self, toolkit):
        result = await toolkit.store_result(
            key="note", data="text", metadata={"source": "api"}
        )
        assert result["status"] == "stored"


class TestGetResult:
    async def test_get_text(self, toolkit):
        await toolkit.store_result(key="note", data="hello world")
        result = await toolkit.get_result(key="note")
        assert "preview" in result

    async def test_get_include_raw(self, toolkit):
        await toolkit.store_result(key="note", data="hello")
        result = await toolkit.get_result(key="note", include_raw=True)
        assert result.get("raw_data") == "hello"

    async def test_get_truncated(self, toolkit):
        await toolkit.store_result(key="note", data="a" * 1000)
        result = await toolkit.get_result(key="note", max_length=50)
        assert len(result.get("preview", "")) <= 53  # 50 + "..."


class TestSearchStored:
    async def test_search_by_description(self, toolkit):
        await toolkit.store_result(key="k1", data="x", description="market analysis")
        await toolkit.store_result(key="k2", data="y", description="weather report")
        results = await toolkit.search_stored(query="market")
        assert len(results["matches"]) == 1

    async def test_search_by_type(self, toolkit):
        await toolkit.store_result(key="txt", data="text")
        await toolkit.store(key="df", df=pd.DataFrame({"a": [1]}))
        results = await toolkit.search_stored(query="", entry_type="text")
        assert all(m.get("entry_type") == "text" for m in results["matches"])
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/extending-workingmemorytoolkit.spec.md` for full context
2. **Check dependencies** — TASK-503 and TASK-504 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-505-generic-tool-methods.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Implemented as specified. All 115 tests pass.

**Deviations from spec**: none
