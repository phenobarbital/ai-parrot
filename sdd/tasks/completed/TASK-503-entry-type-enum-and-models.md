# TASK-503: Add EntryType Enum, GenericEntry, and New Pydantic Input Models

**Feature**: extending-workingmemorytoolkit
**Spec**: `sdd/specs/extending-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-074. It adds the data types needed by all
subsequent tasks: the `EntryType` discriminator enum, the `GenericEntry` dataclass
for non-DataFrame storage, and new Pydantic input models for the new tool methods.

Implements **Module 1** from the spec.

---

## Scope

- Add `EntryType` enum to `models.py` with values: `dataframe`, `text`, `json`,
  `message`, `binary`, `object`.
- Add new Pydantic input models to `models.py`:
  - `StoreResultInput` — with `key`, `data_type` (default "auto"), `description`,
    `metadata` (dict, optional — resolved open question), `turn_id`.
  - `GetResultInput` — with `key`, `max_length` (default 500),
    `include_raw` (bool, default False — resolved open question).
  - `SearchStoredInput` — with `query` (substring), `entry_type` (optional
    `EntryType` filter) — resolved open question.
  - `SaveInteractionInput` — with `turn_id`, `question`, `answer`.
  - `RecallInteractionInput` — with `turn_id` (optional), `query` (optional),
    `import_as` (optional).
- Add `GenericEntry` dataclass to `internals.py`:
  - Fields: `key`, `data` (Any), `entry_type` (EntryType), `created_at`,
    `description`, `turn_id`, `session_id`, `metadata` (dict).
  - `compact_summary(max_length=500)` method with type-aware summaries per
    the spec's "Summary Strategy per Type" table.
- Add `_detect_entry_type(data) -> EntryType` helper function to `internals.py`.

**NOT in scope**: modifying `WorkingMemoryCatalog`, `WorkingMemoryToolkit`,
or `__init__.py` exports (those are separate tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/models.py` | MODIFY | Add `EntryType` enum, 5 new Pydantic models |
| `packages/ai-parrot/src/parrot/tools/working_memory/internals.py` | MODIFY | Add `GenericEntry` dataclass + `_detect_entry_type()` |

---

## Implementation Notes

### Pattern to Follow

`EntryType` follows the same pattern as `OperationType` in `models.py`:
```python
class EntryType(str, Enum):
    DATAFRAME = "dataframe"
    TEXT = "text"
    JSON = "json"
    MESSAGE = "message"
    BINARY = "binary"
    OBJECT = "object"
```

`GenericEntry` follows the same `@dataclass` pattern as `CatalogEntry` in `internals.py`.

### Key Constraints

- `GenericEntry.compact_summary()` must handle each `EntryType` differently:
  - TEXT: `char_count`, `word_count`, truncated `preview`
  - JSON: `type` (dict/list), `keys` or `length`, truncated JSON preview
  - MESSAGE: `role`, truncated `content` preview, `content_length`
  - BINARY: `size_bytes`, `size_human` (e.g. "1.2 KB"), NO content dump
  - OBJECT: `type_name`, `repr(obj)` truncated, `attributes` list
- `_detect_entry_type()` must check `isinstance` in order: str → bytes → dict/list → DataFrame → duck-type (content+role) → fallback OBJECT
- Use `repr()` with character limit for OBJECT to avoid expensive `str()` calls

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/working_memory/models.py` — existing enums + models
- `packages/ai-parrot/src/parrot/tools/working_memory/internals.py` — existing `CatalogEntry`

---

## Acceptance Criteria

- [ ] `EntryType` enum has all 6 values
- [ ] `StoreResultInput` has `metadata: Optional[dict]` field
- [ ] `GetResultInput` has `include_raw: bool = False` field
- [ ] `SearchStoredInput` has `query` and optional `entry_type` fields
- [ ] `SaveInteractionInput` and `RecallInteractionInput` match spec signatures
- [ ] `GenericEntry.compact_summary()` produces correct output for each `EntryType`
- [ ] `_detect_entry_type("hello")` returns `EntryType.TEXT`
- [ ] `_detect_entry_type({"a": 1})` returns `EntryType.JSON`
- [ ] `_detect_entry_type(b"bytes")` returns `EntryType.BINARY`
- [ ] All existing tests still pass: `pytest packages/ai-parrot/src/parrot/tools/working_memory/tests/ -v`

---

## Test Specification

```python
# packages/ai-parrot/src/parrot/tools/working_memory/tests/test_generic_entries.py
import pytest
from parrot.tools.working_memory.models import EntryType, StoreResultInput, GetResultInput, SearchStoredInput
from parrot.tools.working_memory.internals import GenericEntry, _detect_entry_type


class TestEntryType:
    def test_all_values(self):
        assert set(EntryType) == {
            EntryType.DATAFRAME, EntryType.TEXT, EntryType.JSON,
            EntryType.MESSAGE, EntryType.BINARY, EntryType.OBJECT,
        }


class TestDetectEntryType:
    def test_text(self):
        assert _detect_entry_type("hello") == EntryType.TEXT

    def test_bytes(self):
        assert _detect_entry_type(b"data") == EntryType.BINARY

    def test_dict(self):
        assert _detect_entry_type({"a": 1}) == EntryType.JSON

    def test_list(self):
        assert _detect_entry_type([1, 2, 3]) == EntryType.JSON

    def test_message(self):
        class Msg:
            content = "hi"
            role = "assistant"
        assert _detect_entry_type(Msg()) == EntryType.MESSAGE

    def test_fallback(self):
        assert _detect_entry_type(42) == EntryType.OBJECT


class TestGenericEntrySummary:
    def test_text_summary(self):
        entry = GenericEntry(key="k", data="hello world", entry_type=EntryType.TEXT)
        s = entry.compact_summary()
        assert s["entry_type"] == "text"
        assert "preview" in s
        assert s["char_count"] == 11

    def test_binary_summary_no_content(self):
        entry = GenericEntry(key="k", data=b"x" * 100, entry_type=EntryType.BINARY)
        s = entry.compact_summary()
        assert "preview" not in s
        assert s["size_bytes"] == 100
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/extending-workingmemorytoolkit.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-503-entry-type-enum-and-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Implemented as specified. All 115 tests pass.

**Deviations from spec**: none
