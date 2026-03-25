# TASK-437: Credential Data Models

**Feature**: user-based-credentials
**Spec**: `sdd/specs/user-based-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> This task creates the Pydantic data models that all other tasks depend on.
> Implements Module 1 from the spec (Section 3).

---

## Scope

- Implement `CredentialPayload` — input validation model for POST/PUT requests (name, driver, params)
- Implement `CredentialDocument` — DocumentDB storage model (user_id, name, encrypted credential, timestamps)
- Implement `CredentialResponse` — API response model for single credential
- Ensure `name` has min_length=1, max_length=128 validation
- Ensure `driver` is required and non-empty
- `params` defaults to empty dict

**NOT in scope**: encryption logic, handler logic, route registration

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/models/credentials.py` | CREATE | Pydantic models for credentials |
| `tests/handlers/test_credential_models.py` | CREATE | Unit tests for model validation |

---

## Implementation Notes

### Pattern to Follow
```python
from pydantic import BaseModel, Field
from typing import Any, Optional
from datetime import datetime

class CredentialPayload(BaseModel):
    """Input model for creating/updating a credential."""
    name: str = Field(..., min_length=1, max_length=128)
    driver: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)

class CredentialDocument(BaseModel):
    """DocumentDB storage model."""
    user_id: str
    name: str
    credential: str  # encrypted JSON string
    created_at: datetime
    updated_at: datetime

class CredentialResponse(BaseModel):
    """Response model for a single credential."""
    name: str
    driver: str
    params: dict[str, Any]
```

### Key Constraints
- Use strict Pydantic v2 style (BaseModel with Field)
- All fields must have type hints
- Add Google-style docstrings to each model
- Check if `packages/ai-parrot/src/parrot/handlers/models/` directory exists; create `__init__.py` if needed

### References in Codebase
- `parrot/interfaces/credentials.py` — existing `CredentialsInterface` pattern
- Other Pydantic models in the project for style reference

---

## Acceptance Criteria

- [ ] `CredentialPayload` validates name (1-128 chars), requires driver, defaults params to {}
- [ ] `CredentialDocument` contains user_id, name, credential (str), created_at, updated_at
- [ ] `CredentialResponse` contains name, driver, params
- [ ] Invalid payloads raise `ValidationError` (missing name, missing driver, name too long)
- [ ] All tests pass: `pytest tests/handlers/test_credential_models.py -v`
- [ ] Import works: `from parrot.handlers.models.credentials import CredentialPayload, CredentialDocument, CredentialResponse`

---

## Test Specification

```python
# tests/handlers/test_credential_models.py
import pytest
from pydantic import ValidationError
from parrot.handlers.models.credentials import (
    CredentialPayload,
    CredentialDocument,
    CredentialResponse,
)


class TestCredentialPayload:
    def test_valid_payload(self):
        payload = CredentialPayload(
            name="my-postgres",
            driver="pg",
            params={"host": "localhost", "port": 5432}
        )
        assert payload.name == "my-postgres"
        assert payload.driver == "pg"

    def test_missing_driver_raises(self):
        with pytest.raises(ValidationError):
            CredentialPayload(name="test")

    def test_missing_name_raises(self):
        with pytest.raises(ValidationError):
            CredentialPayload(driver="pg")

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            CredentialPayload(name="x" * 129, driver="pg")

    def test_params_defaults_to_empty(self):
        payload = CredentialPayload(name="test", driver="pg")
        assert payload.params == {}


class TestCredentialResponse:
    def test_valid_response(self):
        resp = CredentialResponse(
            name="my-pg",
            driver="pg",
            params={"host": "localhost"}
        )
        assert resp.name == "my-pg"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/user-based-credentials.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-437-credential-data-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker
**Date**: 2026-03-25
**Notes**: Created `parrot/handlers/models/__init__.py` and `parrot/handlers/models/credentials.py` with all three models. All 15 unit tests pass.

**Deviations from spec**: Spec path `parrot/handlers/models/credentials.py` would conflict with existing `parrot/handlers/models.py` module. Created `parrot/handlers/models/` as a package alongside `models.py`. Python resolves the new `models/` package from the worktree's src path. The import path `from parrot.handlers.models.credentials import ...` works correctly.
