# TASK-665: Serialization Guard for Multi-Dataset Responses

**Feature**: datasetmanager-more-data
**Spec**: `sdd/specs/datasetmanager-more-data.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-663
**Assigned-to**: unassigned

---

## Context

The response serialization block (~L1594) currently assumes `response.data` is either
a `pd.DataFrame` (to be serialized) or `None`. After TASK-663, `response.data` can
also be a `list[dict]` (pre-serialized `DatasetResult` entries). This task ensures
the serialization block handles all three cases correctly without breaking backward compatibility.

Implements **Module 4** from the spec.

---

## Scope

- Modify the serialization block (~L1594-1602) to handle three cases:
  1. `response.data` is a `pd.DataFrame` → serialize as `list[dict]` (existing behavior)
  2. `response.data` is a `list` (of `DatasetResult` dicts) → leave as-is (already serialized)
  3. `response.data` is `None` → leave as-is (existing behavior)
- Add a type check for multi-dataset results that avoids double-serialization
- Write unit tests covering all three serialization paths

**NOT in scope**:
- Model changes (TASK-662)
- Injection logic (TASK-663)
- Prompt changes (TASK-664)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Update serialization block |
| `tests/unit/test_multi_dataset_serialization.py` | CREATE | Unit tests for serialization paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# No new imports needed
import pandas as pd  # already imported at line 16
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py — serialization block

# Current code at ~line 1594-1602:
if isinstance(response.data, pd.DataFrame):
    response.data = response.data.to_dict(orient='records')
elif response.data is not None and not isinstance(response.data, list):
    self.logger.warning(
        "PandasAgent response.data unexpected type: %s",
        type(response.data),
    )

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage(BaseModel):  # line 72
    data: Optional[Any]  # line 86 — accepts any type
```

### Does NOT Exist
- ~~`response.serialize_data()`~~ — no such method
- ~~`DatasetResult.to_records()`~~ — no such method, data is already serialized by TASK-663

---

## Implementation Notes

### Modified Serialization Block
Replace the existing block at ~L1594-1602 with:

```python
# Serialize response.data for JSON output
if isinstance(response.data, pd.DataFrame):
    # Single DataFrame → list of record dicts (existing behavior)
    response.data = response.data.to_dict(orient='records')
elif isinstance(response.data, list):
    # Already serialized — either:
    # - Multi-dataset: list of DatasetResult dicts (from TASK-663)
    # - Single dataset: list of record dicts (from prior path)
    # Leave as-is in both cases.
    pass
elif response.data is not None:
    self.logger.warning(
        "PandasAgent response.data unexpected type: %s",
        type(response.data),
    )
```

### Key Constraints
- The `isinstance(response.data, list)` check MUST come after the DataFrame check (DataFrame is not a list, but be explicit)
- Do NOT attempt to re-serialize `DatasetResult` dicts — they were already `.model_dump()`'d in TASK-663
- The `pass` for list case is intentional — no transformation needed

---

## Acceptance Criteria

- [ ] `pd.DataFrame` in `response.data` is serialized to `list[dict]` (unchanged)
- [ ] `list` in `response.data` (multi-dataset) passes through without modification
- [ ] `None` in `response.data` passes through without error
- [ ] Unexpected types still log a warning
- [ ] Tests pass: `pytest tests/unit/test_multi_dataset_serialization.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# tests/unit/test_multi_dataset_serialization.py
import pytest
import pandas as pd
from parrot.bots.data import DatasetResult


class TestSerializationGuard:
    def test_dataframe_serialized_to_records(self):
        """DataFrame response.data is serialized to list of dicts."""
        # Create a mock response with data = pd.DataFrame(...)
        # Run through serialization
        # Assert response.data is a list of dicts
        pass

    def test_multi_dataset_list_passthrough(self):
        """List of DatasetResult dicts passes through unchanged."""
        results = [
            DatasetResult(
                name="ds1", variable="ds1",
                data=[{"a": 1}], shape=(1, 1), columns=["a"],
            ).model_dump(),
            DatasetResult(
                name="ds2", variable="ds2",
                data=[{"b": 2}], shape=(1, 1), columns=["b"],
            ).model_dump(),
        ]
        # Set response.data = results
        # Run through serialization
        # Assert response.data == results (unchanged)
        pass

    def test_none_passthrough(self):
        """None response.data passes through."""
        # response.data = None
        # No error raised
        pass

    def test_unexpected_type_logs_warning(self):
        """Non-list, non-DataFrame type logs a warning."""
        # response.data = "some string"
        # Assert warning logged
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-more-data.spec.md` for full context
2. **Check dependencies** — verify TASK-663 is in `tasks/completed/`
3. **Verify the Codebase Contract**:
   - Read lines ~1590-1605 to confirm the serialization block location
   - Confirm `DatasetResult` exists (TASK-662)
   - Confirm `_inject_multi_data_from_variables` sets `response.data` to a list (TASK-663)
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-665-serialization-guard.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
