---
type: Wiki Overview
title: 'TASK-1247: PartialFormData Pydantic Model'
id: doc:sdd-tasks-completed-task-1247-partial-form-data-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is the foundation model for the partial saves feature (Spec §2 Data
  Models,
---

# TASK-1247: PartialFormData Pydantic Model

**Feature**: FEAT-186 — FormDesigner Partial Saves
**Spec**: `sdd/specs/formdesigner-partial-saves.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation model for the partial saves feature (Spec §2 Data Models,
§3 Module 1). The `PartialFormData` Pydantic model represents an ephemeral
partial form answer cache entry stored in Redis. All other tasks depend on this
model for serialization and type safety.

---

## Scope

- Create `packages/parrot-formdesigner/src/parrot_formdesigner/core/partial.py`
- Implement `PartialFormData(BaseModel)` with fields:
  - `form_id: str`
  - `session_id: str`
  - `data: dict[str, Any]` (field_id -> value, sparse)
  - `field_errors: dict[str, list[str]]` (field_id -> [error_msg, ...])
  - `saved_at: datetime`
  - `expires_at: datetime`
- Ensure the model is serializable via `model_dump_json()` / `model_validate_json()`
  for Redis storage
- Write unit tests for serialization round-trip

**NOT in scope**: Redis storage logic (TASK-1248), handler logic (TASK-1249),
route registration (TASK-1251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/partial.py` | CREATE | PartialFormData model |
| `packages/parrot-formdesigner/tests/test_partial_model.py` | CREATE | Unit tests for model |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field  # verified: used throughout core/schema.py
from datetime import datetime, timezone  # verified: core/schema.py:12, services/cache.py:17
from typing import Any  # verified: core/schema.py:13
```

### Existing Signatures to Use
```python
# Reference pattern: packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):  # line 153
    form_id: str  # line 178
    version: str = "1.0"  # line 179
    # ... uses model_dump_json() / model_validate_json() for Redis serialization

class FormField(BaseModel):  # line 23
    model_config = ConfigDict(extra="forbid")  # line 47
    field_id: str  # line 49
```

### Does NOT Exist
- ~~`parrot_formdesigner.core.partial`~~ — does not exist yet (this task creates it)
- ~~`PartialFormData`~~ — does not exist yet
- ~~`parrot_formdesigner.models.partial`~~ — no `models` subpackage exists

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same Pydantic model style as core/schema.py
# No ConfigDict(extra="forbid") needed — partial data is flexible
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Any

class PartialFormData(BaseModel):
    form_id: str
    session_id: str
    data: dict[str, Any] = Field(default_factory=dict)
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    saved_at: datetime
    expires_at: datetime
```

### Key Constraints
- Use `Field(default_factory=dict)` for mutable defaults
- `saved_at` and `expires_at` should use UTC timezone-aware datetimes
- Model must round-trip through `model_dump_json()` / `model_validate_json()`

---

## Acceptance Criteria

- [ ] `PartialFormData` model exists in `core/partial.py`
- [ ] All fields typed per spec: form_id, session_id, data, field_errors, saved_at, expires_at
- [ ] `model_dump_json()` produces valid JSON
- [ ] `model_validate_json(json_str)` reconstructs the model from JSON
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/test_partial_model.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/test_partial_model.py
import pytest
from datetime import datetime, timezone, timedelta
from parrot_formdesigner.core.partial import PartialFormData


class TestPartialFormData:
    def test_basic_construction(self):
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="test-form",
            session_id="session-123",
            data={"name": "Alice", "age": 30},
            field_errors={},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert partial.form_id == "test-form"
        assert partial.session_id == "session-123"
        assert partial.data["name"] == "Alice"

    def test_empty_data(self):
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={},
            field_errors={},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert partial.data == {}

    def test_field_errors(self):
        now = datetime.now(tz=timezone.utc)
        partial = PartialFormData(
            form_id="f1",
            session_id="s1",
            data={"age": -5},
            field_errors={"age": ["Age must be at least 0"]},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        assert "age" in partial.field_errors
        assert len(partial.field_errors["age"]) == 1

    def test_json_round_trip(self):
        now = datetime.now(tz=timezone.utc)
        original = PartialFormData(
            form_id="test-form",
            session_id="session-456",
            data={"name": "Bob", "tags": ["a", "b"]},
            field_errors={"email": ["Invalid email"]},
            saved_at=now,
            expires_at=now + timedelta(hours=1),
        )
        json_str = original.model_dump_json()
        restored = PartialFormData.model_validate_json(json_str)
        assert restored.form_id == original.form_id
        assert restored.data == original.data
        assert restored.field_errors == original.field_errors
        assert restored.saved_at == original.saved_at
        assert restored.expires_at == original.expires_at
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-partial-saves.spec.md` §2 Data Models
2. **Check dependencies** — none (this is the first task)
3. **Verify the Codebase Contract** — confirm core/schema.py patterns still match
4. **Implement** the model in `core/partial.py`
5. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_partial_model.py -v`
6. **Update index** and move file on completion

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-19
**Notes**: Created `core/partial.py` with `PartialFormData(BaseModel)` implementing
all 6 fields per spec. Added 8 unit tests covering construction, defaults, field errors,
and JSON round-trip with complex nested values. All 8 tests pass.

**Deviations from spec**: none
