# TASK-605: Unit and Integration Tests

**Feature**: form-designer-edition
**Spec**: `sdd/specs/form-designer-edition.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-597, TASK-598, TASK-599, TASK-600, TASK-601, TASK-602, TASK-603, TASK-604
**Assigned-to**: unassigned

---

## Context

Final task for FEAT-086. Creates comprehensive unit and integration tests for all new functionality: auth models, SubmitAction extension, FormSubmissionStorage, SubmissionForwarder, PUT/PATCH endpoints, and submission endpoint.

Implements Spec Module 9.

---

## Scope

- Create test files covering:
  - `AuthConfig` models (resolve, missing env, serialization)
  - `SubmitAction` with auth (backward compat, roundtrip)
  - `FormSubmissionStorage` (model creation, serialization)
  - `SubmissionForwarder` (success, failure, non-endpoint, auth headers)
  - `_deep_merge()` and `_bump_version()` utilities
  - Edit endpoints via aiohttp test client (PUT success, PUT 404, PUT 400 mismatch, PATCH merge, PATCH 422, PATCH empty)
  - Submission endpoint via aiohttp test client (valid, invalid 422, forward success/failure, no storage)
  - Integration: create → edit → submit lifecycle

**NOT in scope**: Performance benchmarks, load testing

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/test_auth_config.py` | CREATE | Auth model unit tests |
| `packages/parrot-formdesigner/tests/test_submit_action_auth.py` | CREATE | SubmitAction with auth tests |
| `packages/parrot-formdesigner/tests/test_submissions.py` | CREATE | FormSubmission model tests |
| `packages/parrot-formdesigner/tests/test_forwarder.py` | CREATE | SubmissionForwarder tests |
| `packages/parrot-formdesigner/tests/test_edit_endpoints.py` | CREATE | PUT/PATCH handler + utility tests |
| `packages/parrot-formdesigner/tests/test_submit_endpoint.py` | CREATE | Submission endpoint tests |
| `packages/parrot-formdesigner/tests/test_form_edition_integration.py` | CREATE | End-to-end integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All imports from completed tasks:
from parrot.formdesigner.core.auth import AuthConfig, NoAuth, BearerAuth, ApiKeyAuth  # TASK-597
from parrot.formdesigner.core.schema import FormSchema, SubmitAction, FormField, FormSection  # existing + TASK-598
from parrot.formdesigner.core.types import FieldType  # existing
from parrot.formdesigner.services.submissions import FormSubmission, FormSubmissionStorage  # TASK-599
from parrot.formdesigner.services.forwarder import SubmissionForwarder, ForwardResult  # TASK-600
from parrot.formdesigner.services.registry import FormRegistry  # existing
from parrot.formdesigner.services.validators import FormValidator, ValidationResult  # existing
from parrot.formdesigner.handlers.api import FormAPIHandler  # existing + TASK-601/602
from parrot.formdesigner.handlers.routes import setup_form_routes  # existing + TASK-603

# Utilities from TASK-601:
from parrot.formdesigner.handlers.api import _deep_merge, _bump_version

# Test utilities:
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp.test_utils import AioHTTPTestCase, TestClient
from aiohttp import web
```

### Does NOT Exist
- ~~`FormAPIHandler.update_form()` before TASK-601~~ — verify it exists before writing tests
- ~~`FormAPIHandler.submit_data()` before TASK-602~~ — verify it exists before writing tests

---

## Implementation Notes

### Test Structure
Organize tests by component, not by spec module. Each test file should be self-contained with its own fixtures.

### Key Test Patterns

**For auth tests** — use `monkeypatch.setenv()` to set env vars, verify `resolve()` output.

**For handler tests** — use aiohttp test client:
```python
@pytest.fixture
def app(sample_form_schema):
    app = web.Application()
    registry = FormRegistry()
    # Pre-register a form for edit tests
    setup_form_routes(app, registry=registry)
    return app, registry

async def test_put_form(aiohttp_client, app):
    app_instance, registry = app
    client = await aiohttp_client(app_instance)
    # ... register form, then PUT
```

**For forwarder tests** — use `aiohttp.test_utils.TestServer` or mock `aiohttp.ClientSession`.

**For integration tests** — full lifecycle: create form (register in registry) → PATCH to edit → POST data to submit.

### Key Constraints
- Use `pytest-asyncio` for async tests
- Use `monkeypatch` for env var tests (not `os.environ` directly)
- Mock PostgreSQL — do not require a live database for unit tests
- Integration tests can use in-memory registry (no storage backend)
- Follow existing test patterns in the project

---

## Acceptance Criteria

- [ ] All test files created per scope
- [ ] All unit tests pass: `pytest packages/parrot-formdesigner/tests/ -v`
- [ ] Auth model tests: resolve, missing env, backward compat
- [ ] Edit endpoint tests: PUT, PATCH, validation, version bump
- [ ] Submission endpoint tests: valid, invalid, forward success/failure
- [ ] Integration test: create → edit → submit lifecycle
- [ ] No tests require live database or external services

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/form-designer-edition.spec.md` — especially Section 4 (Test Specification)
2. **Check dependencies** — ALL prior tasks (TASK-597 through TASK-604) must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm all imports work before writing tests
4. **Read existing tests** in `packages/parrot-formdesigner/tests/` for patterns and fixtures
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** all test files
7. **Run**: `pytest packages/parrot-formdesigner/tests/ -v`
8. **Move this file** to `tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
