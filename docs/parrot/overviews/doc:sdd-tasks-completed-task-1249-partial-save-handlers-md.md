---
type: Wiki Overview
title: 'TASK-1249: Partial Save Handler Methods'
id: doc:sdd-tasks-completed-task-1249-partial-save-handlers-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task adds three new handler methods to `FormAPIHandler` for the partial
---

# TASK-1249: Partial Save Handler Methods

**Feature**: FEAT-186 — FormDesigner Partial Saves
**Spec**: `sdd/specs/formdesigner-partial-saves.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1247, TASK-1248
**Assigned-to**: unassigned

---

## Context

This task adds three new handler methods to `FormAPIHandler` for the partial
saves REST endpoints (Spec §2 API Contracts, §3 Module 3). Each handler extracts
the session ID from the auth session, delegates to `PartialSaveStore`, and runs
per-field validation via `FormValidator.validate_field()`.

---

## Scope

- Modify `FormAPIHandler.__init__()` to accept `partial_store: PartialSaveStore | None = None`
- Implement `save_partial(request)`:
  - Extract `form_id` from URL, `session_id` from `request["session"]["id"]`
  - Parse `{"answers": {...}}` from JSON body
  - Load form from `self.registry.get(form_id)` (404 if missing)
  - Save to `self._partial_store.save(...)` (503 if store is None)
  - For each field in `answers`, look up the `FormField` from form schema and
    run `self.validator.validate_field(field, value)` — collect errors
  - Set `field_errors` on the returned `PartialFormData`
  - Return 200 with the full partial state as JSON
- Implement `get_partial(request)`:
  - Extract form_id and session_id
  - Call `self._partial_store.get(...)` — return 404 if None
  - Return 200 with the cached partial as JSON
- Implement `delete_partial(request)`:
  - Extract form_id and session_id
  - Call `self._partial_store.delete(...)`
  - Return 204
- Write unit tests for all three handlers

**NOT in scope**: Submit merge logic (TASK-1250), route registration (TASK-1251).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | MODIFY | Add partial_store param + 3 handler methods |
| `packages/parrot-formdesigner/tests/test_partial_handlers.py` | CREATE | Unit tests for handlers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Already imported in handlers.py
from aiohttp import web  # verified: api/handlers.py top-level
import json  # verified: api/handlers.py:12
import logging  # verified: api/handlers.py:13

# Existing imports in handlers.py
from ..core.schema import FormSchema, FormField  # verified: api/handlers.py:19, core/schema.py:23,153
from ..services.registry import FormRegistry  # verified: api/handlers.py:22, services/registry.py:134
from ..services.validators import FormValidator  # verified: api/handlers.py:23, services/validators.py:91

# New TYPE_CHECKING import needed
from ..services.partial_saves import PartialSaveStore  # TASK-1248 creates this
```

### Existing Signatures to Use
```python
# api/handlers.py
class FormAPIHandler:  # line 33
    def __init__(
        self,
        registry: FormRegistry,
        client: "AbstractClient | None" = None,
        submission_storage: "FormSubmissionStorage | None" = None,
        forwarder: "SubmissionForwarder | None" = None,
    ) -> None:  # line 51
        self.registry = registry  # line 58
        self._submission_storage = submission_storage  # line 60
        self.validator = FormValidator()  # line 63
        self.logger = logging.getLogger(__name__)  # line 64

    async def submit_data(self, request: web.Request) -> web.Response:  # line 566

# services/validators.py
class FormValidator:  # line 91
    async def validate_field(
        self, field: FormField, value: Any,
        *, all_data: dict[str, Any] | None = None,
        locale: str = "en", auth_context: AuthContext | None = None,
    ) -> list[str]:  # line 179 — returns list of error strings (empty = valid)

# services/registry.py
class FormRegistry:  # line 134
    async def get(self, form_id: str) -> FormSchema | None:  # uses async lock

# core/schema.py
class FormSchema(BaseModel):  # line 153
    form_id: str  # line 178
    sections: list[FormSection]  # line 182

class FormSection(BaseModel):  # line 101
    def iter_fields(self) -> Iterator[FormField]:  # line 127

class FormField(BaseModel):  # line 23
    field_id: str  # line 49

# Session ID extraction pattern (api/uploads.py:316-319)
# session_id: str | None = None
# if "session" in request:
#     _sid = request["session"].get("id")
#     session_id = str(_sid) if _sid else None
```

### Does NOT Exist
- ~~`FormAPIHandler.save_partial()`~~ — does not exist yet (this task creates it)
- ~~`FormAPIHandler.get_partial()`~~ — does not exist yet
- ~~`FormAPIHandler.delete_partial()`~~ — does not exist yet
- ~~`FormAPIHandler._partial_store`~~ — does not exist yet
- ~~`FormSchema.get_field(field_id)`~~ — no such method; must iterate sections/fields manually
- ~~`FormValidator.validate_partial()`~~ — not a real method; use `validate_field()` per field

---

## Implementation Notes

### Pattern to Follow — Session Extraction
```python
# Copy from api/uploads.py:316-319
session_id: str | None = None
if "session" in request:
    _sid = request["session"].get("id")
    session_id = str(_sid) if _sid else None
if not session_id:
    return web.json_response({"error": "Session ID required"}, status=400)
```

### Pattern to Follow — Field Lookup Helper
```python
def _find_field(self, form: FormSchema, field_id: str) -> FormField | None:
    """Find a FormField by field_id across all sections."""
    for section in form.sections:
        for field in section.iter_fields():
            if field.field_id == field_id:
                return field
    return None
```

### Key Constraints
- If `self._partial_store is None`, return 503 with `{"error": "Partial save service not configured"}`
- Validate each field independently — don't fail the save if one field is invalid
- Store both valid and invalid fields in `data`, but report errors in `field_errors`
- Use the same JSON response pattern as existing handlers (web.json_response)

---

## Acceptance Criteria

- [ ] `FormAPIHandler.__init__()` accepts `partial_store` parameter
- [ ] `save_partial()` saves answers and validates each field
- [ ] `save_partial()` returns full cached state including field_errors
- [ ] `save_partial()` returns 404 if form not in registry
- [ ] `save_partial()` returns 400 if session_id missing
- [ ] `save_partial()` returns 503 if partial_store not configured
- [ ] `get_partial()` returns cached data or 404
- [ ] `delete_partial()` returns 204
- [ ] All handlers extract session_id from `request["session"]["id"]`
- [ ] Unit tests pass: `pytest packages/parrot-formdesigner/tests/test_partial_handlers.py -v`

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/test_partial_handlers.py
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestSavePartial:
    async def test_save_single_field(self):
        """POST /partial with one field returns updated state."""
        ...

    async def test_save_bulk_fields(self):
        """POST /partial with multiple fields."""
        ...

    async def test_save_returns_validation_errors(self):
        """Invalid field values produce field_errors in response."""
        ...

    async def test_save_form_not_found(self):
        """Returns 404 when form not in registry."""
        ...

    async def test_save_no_session(self):
        """Returns 400 when session_id missing."""
        ...

    async def test_save_store_not_configured(self):
        """Returns 503 when partial_store is None."""
        ...


class TestGetPartial:
    async def test_get_returns_cached(self):
        """GET /partial returns cached partial data."""
        ...

    async def test_get_not_found(self):
        """GET /partial returns 404 when nothing cached."""
        ...


class TestDeletePartial:
    async def test_delete_returns_204(self):
        """DELETE /partial returns 204."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-partial-saves.spec.md` §2 API Contracts
2. **Check dependencies** — verify TASK-1247 and TASK-1248 are complete
3. **Read `api/handlers.py`** — understand the existing handler pattern (constructor DI, validator usage)
4. **Read `api/uploads.py:316-319`** — session_id extraction pattern
5. **Implement** the three handler methods
6. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_partial_handlers.py -v`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: SDD Worker (Claude Sonnet 4.6)
**Date**: 2026-05-19
**Notes**: Modified `api/handlers.py` to add `partial_store` param to `__init__`,
`_extract_session_id()` helper, `_find_field()` helper, and `save_partial()`,
`get_partial()`, `delete_partial()` handler methods. Also added `PartialSaveStore`
to `TYPE_CHECKING` block. 20 unit tests all pass.

**Deviations from spec**: none
