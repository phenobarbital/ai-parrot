# TASK-602: Submission Endpoint

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-599, TASK-600
**Assigned-to**: unassigned

---

## Context

Adds the `POST /api/v1/forms/{form_id}/data` endpoint that receives form submissions, validates them, stores locally, and forwards to the configured endpoint. Combines `FormSubmissionStorage` (TASK-599) and `SubmissionForwarder` (TASK-600).

Implements Spec Module 6.

---

## Scope

- Add `submit_data()` method to `FormAPIHandler`
- Modify `FormAPIHandler.__init__()` to accept optional `submission_storage: FormSubmissionStorage | None = None` and `forwarder: SubmissionForwarder | None = None`
- Flow:
  1. Load form from registry (404 if not found)
  2. Parse JSON body (400 if invalid)
  3. Validate data via `self.validator.validate(form, data)`
  4. Generate submission_id via `uuid.uuid4()`
  5. Build `FormSubmission` record
  6. If `submission_storage` is configured, store locally
  7. If form has `submit` with `action_type == "endpoint"` and forwarder is configured, forward
  8. Update `FormSubmission` with forward result
  9. If storage is configured, update the stored record with forward status
  10. Return JSON response with submission_id, is_valid, forwarded status

**NOT in scope**: Route registration (TASK-603), auth resolution (handled by forwarder)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` | MODIFY | Add `submit_data()`, modify `__init__()` signature |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already in api.py:
from aiohttp import web
import json
import logging
from ..services.registry import FormRegistry
from ..services.validators import FormValidator

# New imports needed:
import uuid
from datetime import datetime, timezone
from ..services.submissions import FormSubmission, FormSubmissionStorage  # TASK-599
from ..services.forwarder import SubmissionForwarder, ForwardResult  # TASK-600
```

### Existing Signatures to Use
```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py:45
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client: "AbstractClient | None" = None) -> None:
        # ADD: submission_storage and forwarder parameters

# packages/parrot-formdesigner/src/parrot/formdesigner/services/validators.py:87
async def validate(self, form: FormSchema, data: dict[str, Any], *, locale: str = "en") -> ValidationResult

# From TASK-599:
class FormSubmissionStorage:
    async def store(self, submission: FormSubmission) -> str

# From TASK-600:
class SubmissionForwarder:
    async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult

class ForwardResult(BaseModel):
    success: bool
    status_code: int | None = None
    error: str | None = None
```

### Does NOT Exist
- ~~`FormAPIHandler.submit_data()`~~ — does not exist; this task creates it
- ~~`FormAPIHandler._submission_storage`~~ — does not exist; this task adds it to `__init__`
- ~~`FormAPIHandler._forwarder`~~ — does not exist; this task adds it to `__init__`

---

## Implementation Notes

### Submit Flow
```python
async def submit_data(self, request: web.Request) -> web.Response:
    form_id = request.match_info["form_id"]
    form = await self.registry.get(form_id)
    if form is None:
        return web.json_response({"error": f"Form '{form_id}' not found"}, status=404)

    try:
        data = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    # Validate
    result = await self.validator.validate(form, data)
    if not result.is_valid:
        return web.json_response(
            {"is_valid": False, "errors": result.errors},
            status=422,
        )

    # Build submission
    submission = FormSubmission(
        submission_id=str(uuid.uuid4()),
        form_id=form_id,
        form_version=form.version,
        data=result.sanitized_data,
        is_valid=True,
        created_at=datetime.now(timezone.utc),
    )

    # Store locally
    if self._submission_storage is not None:
        await self._submission_storage.store(submission)

    # Forward
    forwarded = False
    forward_status = None
    forward_error = None
    if (
        form.submit is not None
        and form.submit.action_type == "endpoint"
        and self._forwarder is not None
    ):
        fwd_result = await self._forwarder.forward(result.sanitized_data, form.submit)
        forwarded = fwd_result.success
        forward_status = fwd_result.status_code
        forward_error = fwd_result.error

    return web.json_response({
        "submission_id": submission.submission_id,
        "is_valid": True,
        "forwarded": forwarded,
        "forward_status": forward_status,
        "forward_error": forward_error,
    })
```

### Constructor Change
Add optional parameters with `None` defaults for backward compatibility:
```python
def __init__(
    self,
    registry: FormRegistry,
    client: "AbstractClient | None" = None,
    submission_storage: "FormSubmissionStorage | None" = None,
    forwarder: "SubmissionForwarder | None" = None,
) -> None:
    # ... existing init ...
    self._submission_storage = submission_storage
    self._forwarder = forwarder
```

### Key Constraints
- Constructor change must be backward-compatible (new params default to None)
- Validation failure → 422 with errors (same pattern as existing `validate` endpoint)
- If no storage configured, data is validated and forwarded but NOT stored (log warning)
- If no forwarder configured, skip forwarding
- If forward fails, still return 200 with `forwarded: false` and error details

---

## Acceptance Criteria

- [ ] `submit_data()` method added to `FormAPIHandler`
- [ ] `__init__()` accepts optional `submission_storage` and `forwarder`
- [ ] Existing constructor calls still work (backward-compatible)
- [ ] Valid submission → stored locally + forwarded → 200 response
- [ ] Invalid submission → 422 with validation errors
- [ ] Forward failure → still 200, `forwarded: false` with error
- [ ] No storage configured → skip local storage (no error)
- [ ] No forwarder configured → skip forwarding (no error)

---

## Test Specification

```python
# tests/test_submit_endpoint.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.services.registry import FormRegistry


class TestSubmitData:
    @pytest.fixture
    def handler_with_storage(self, sample_form_schema):
        registry = FormRegistry()
        mock_storage = AsyncMock()
        mock_storage.store = AsyncMock(return_value="sub-001")
        mock_forwarder = AsyncMock()
        handler = FormAPIHandler(
            registry=registry,
            submission_storage=mock_storage,
            forwarder=mock_forwarder,
        )
        return handler

    def test_constructor_backward_compat(self):
        """Old constructor calls still work."""
        registry = FormRegistry()
        handler = FormAPIHandler(registry=registry)
        assert handler._submission_storage is None
        assert handler._forwarder is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md`
2. **Check dependencies** — verify TASK-599 and TASK-600 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `handlers/api.py` in full
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the scope above
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/ -v`
7. **Move this file** to `tasks/completed/`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
