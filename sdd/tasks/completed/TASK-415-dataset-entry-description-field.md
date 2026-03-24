# TASK-415: Add description field to DatasetEntry

**Feature**: add-description-datasetmanager
**Spec**: `sdd/specs/add-description-datasetmanager.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-059. `DatasetEntry` needs a first-class `description` field so that all downstream features (registration methods, summary generation, metadata output) can use it. Currently descriptions are only available via the opaque `metadata["description"]` convention.

Implements **Module 1** from the spec.

---

## Scope

- Add `description: Optional[str] = None` parameter to `DatasetEntry.__init__`
- Implement priority resolution: explicit `description` > `metadata["description"]` > `""`
- Truncate description to 300 characters max
- Update `to_info()` method to always populate `DatasetInfo.description` from `self.description`
- Ensure backward compatibility: existing code that doesn't pass `description` continues to work

**NOT in scope**: Changes to registration methods (TASK-416), summary generation (TASK-417), or guide updates (TASK-418).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` | MODIFY | Add `description` field to `DatasetEntry.__init__` and update `to_info()` |

---

## Implementation Notes

### Pattern to Follow
```python
class DatasetEntry:
    def __init__(
        self,
        name: str,
        description: Optional[str] = None,  # NEW
        source: Optional[DataSource] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ...
    ):
        # Priority: explicit description > metadata["description"] > ""
        raw_desc = description or (metadata or {}).get("description", "")
        self.description = raw_desc[:300] if raw_desc else ""
```

### Key Constraints
- Do not break existing `DatasetEntry` instantiation signatures
- `DatasetInfo.description` field already exists (defaults to `""`) — just populate it
- Max 300 characters for description (per owner decision)

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py` — `DatasetEntry` class and `DatasetInfo` model

---

## Acceptance Criteria

- [ ] `DatasetEntry` accepts optional `description` parameter
- [ ] Priority resolution works: explicit > metadata fallback > empty string
- [ ] Description truncated to 300 characters
- [ ] `to_info()` populates `DatasetInfo.description` from `self.description`
- [ ] Existing code without `description` parameter still works
- [ ] No linting errors

---

## Test Specification

```python
import pytest
import pandas as pd
from parrot.tools.dataset_manager.tool import DatasetEntry, DatasetInfo

class TestDatasetEntryDescription:
    def test_explicit_description(self):
        """Explicit description is stored."""
        entry = DatasetEntry(name="test", description="My dataset")
        assert entry.description == "My dataset"

    def test_metadata_fallback(self):
        """Falls back to metadata['description'] when no explicit description."""
        entry = DatasetEntry(name="test", metadata={"description": "From metadata"})
        assert entry.description == "From metadata"

    def test_explicit_overrides_metadata(self):
        """Explicit description takes priority over metadata."""
        entry = DatasetEntry(
            name="test",
            description="Explicit",
            metadata={"description": "From metadata"},
        )
        assert entry.description == "Explicit"

    def test_no_description(self):
        """No description defaults to empty string."""
        entry = DatasetEntry(name="test")
        assert entry.description == ""

    def test_description_truncated(self):
        """Description is truncated to 300 characters."""
        long_desc = "x" * 500
        entry = DatasetEntry(name="test", description=long_desc)
        assert len(entry.description) == 300

    def test_to_info_includes_description(self):
        """to_info() populates DatasetInfo.description."""
        entry = DatasetEntry(name="test", description="My dataset")
        entry._df = pd.DataFrame({"a": [1]})
        info = entry.to_info(alias="df1")
        assert info.description == "My dataset"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/add-description-datasetmanager.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-415-dataset-entry-description-field.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-24
**Notes**: Added `description: Optional[str] = None` to `DatasetEntry.__init__`. Priority resolution (explicit > metadata["description"] > "") implemented with 300-char truncation. `to_info()` updated to use `self.description`. All acceptance criteria met.

**Deviations from spec**: none
