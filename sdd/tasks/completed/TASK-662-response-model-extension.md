# TASK-662: DatasetResult Model & PandasAgentResponse Extension

**Feature**: datasetmanager-more-data
**Spec**: `sdd/specs/datasetmanager-more-data.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-098. It adds the `DatasetResult` Pydantic model
and the `data_variables` field to `PandasAgentResponse`. All other tasks depend on these
data structures being in place.

Implements **Module 1** from the spec.

---

## Scope

- Add `DatasetResult` Pydantic model class (after `PandasTable`, before `PandasAgentResponse`)
- Add `data_variables: Optional[List[str]]` field to `PandasAgentResponse`
- Update the `json_schema_extra` example in `PandasAgentResponse.model_config` to show the new field
- Write unit tests validating:
  - `DatasetResult` instantiation and serialization
  - `PandasAgentResponse` accepts `data_variables` field
  - Backward compat: `PandasAgentResponse` without `data_variables` still works

**NOT in scope**:
- Injection logic (TASK-663)
- Prompt changes (TASK-664)
- Serialization changes (TASK-665)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | Add `DatasetResult` model, add `data_variables` field |
| `tests/unit/test_dataset_result_model.py` | CREATE | Unit tests for new models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/bots/data.py — top-level imports (lines 1-38)
from __future__ import annotations
from typing import Any, List, Dict, Union, Optional, TYPE_CHECKING  # line 6
from pydantic import BaseModel, Field, ConfigDict, field_validator  # line 14
import pandas as pd  # line 16
from datamodel.parsers.json import json_encoder, json_decoder  # line 18
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/data.py
Scalar = Union[str, int, float, bool, None]  # line 41

class PandasTable(BaseModel):  # line 49
    columns: List[str]  # line 51
    rows: List[List[Scalar]]  # line 54

class PandasAgentResponse(BaseModel):  # line 126
    model_config = ConfigDict(extra='allow', json_schema_extra={...})  # line 128
    explanation: str  # line 156
    data: Optional[PandasTable]  # line 163
    data_variable: Optional[str]  # line 175
    code: Optional[Union[str, Dict[str, Any]]]  # line 179

    def to_dataframe(self) -> Optional[pd.DataFrame]:  # line 202
```

### Does NOT Exist
- ~~`PandasAgentResponse.data_variables`~~ — does not exist yet (this task adds it)
- ~~`DatasetResult`~~ — does not exist yet (this task adds it)
- ~~`PandasAgentResponse.datasets`~~ — does not exist, do NOT use this name
- ~~`AIMessage.datasets`~~ — does not exist

---

## Implementation Notes

### Pattern to Follow
```python
# Add DatasetResult AFTER PandasTable (line ~95), BEFORE PandasAgentResponse (line 126)
from typing import Tuple  # add to existing typing imports on line 6

class DatasetResult(BaseModel):
    """A single named dataset in a multi-dataset response."""
    name: str = Field(description="Dataset name or alias")
    variable: str = Field(description="Python variable name holding this DataFrame")
    data: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Records (list of row dicts)"
    )
    shape: Tuple[int, int] = Field(description="(rows, columns)")
    columns: List[str] = Field(default_factory=list, description="Column names")
```

### Key Constraints
- `DatasetResult` must be JSON-serializable (no DataFrame fields)
- `Tuple` must be imported from `typing` (add to existing import on line 6)
- `data_variables` field must default to `None` to preserve backward compatibility
- Place `DatasetResult` before `PandasAgentResponse` so it can be referenced

---

## Acceptance Criteria

- [ ] `DatasetResult` model exists and validates correctly
- [ ] `PandasAgentResponse` has `data_variables: Optional[List[str]]` field
- [ ] Existing `PandasAgentResponse` instantiation without `data_variables` still works
- [ ] `DatasetResult` can be serialized to dict/JSON
- [ ] Tests pass: `pytest tests/unit/test_dataset_result_model.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/bots/data.py`

---

## Test Specification

```python
# tests/unit/test_dataset_result_model.py
import pytest
from parrot.bots.data import DatasetResult, PandasAgentResponse, PandasTable


class TestDatasetResult:
    def test_instantiation(self):
        """DatasetResult initializes with required fields."""
        result = DatasetResult(
            name="users_q3",
            variable="users_q3",
            data=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            shape=(2, 2),
            columns=["id", "name"],
        )
        assert result.name == "users_q3"
        assert result.shape == (2, 2)
        assert len(result.data) == 2

    def test_serialization(self):
        """DatasetResult serializes to dict."""
        result = DatasetResult(
            name="test",
            variable="test_df",
            data=[{"a": 1}],
            shape=(1, 1),
            columns=["a"],
        )
        d = result.model_dump()
        assert isinstance(d, dict)
        assert d["name"] == "test"


class TestPandasAgentResponseExtension:
    def test_backward_compat_no_data_variables(self):
        """PandasAgentResponse without data_variables still works."""
        resp = PandasAgentResponse(
            explanation="Test",
            data=PandasTable(columns=["a"], rows=[[1]]),
        )
        assert resp.data_variables is None
        assert resp.data_variable is None

    def test_data_variables_accepted(self):
        """PandasAgentResponse accepts data_variables list."""
        resp = PandasAgentResponse(
            explanation="Test",
            data_variables=["df1", "df2"],
        )
        assert resp.data_variables == ["df1", "df2"]

    def test_both_singular_and_plural(self):
        """Both data_variable and data_variables can coexist."""
        resp = PandasAgentResponse(
            explanation="Test",
            data_variable="df1",
            data_variables=["df1", "df2"],
        )
        assert resp.data_variable == "df1"
        assert resp.data_variables == ["df1", "df2"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/datasetmanager-more-data.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `PandasTable` is at line ~49 and `PandasAgentResponse` at line ~126
   - Confirm `Tuple` is not already in the typing import (line 6) — add it if missing
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-662-response-model-extension.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-14
**Notes**: Implemented DatasetResult Pydantic model and added data_variables field to PandasAgentResponse. Added Tuple to typing imports. Created unit test file. Syntax verified clean.

**Deviations from spec**: none
