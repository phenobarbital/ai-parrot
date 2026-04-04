# TASK-582: FormDesigner Authentication Tests

**Feature**: formdesigner-authentication
**Spec**: `sdd/specs/formdesigner-authentication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-580, TASK-581
**Assigned-to**: unassigned

---

## Context

This task writes unit and integration tests for the formdesigner authentication
feature. Implements spec Module 3 and the full Test Specification from Section 4.

---

## Scope

- Create test file `packages/parrot-formdesigner/tests/test_api_auth.py`.
- Test `FormAPIHandler._get_org_id()`:
  - Returns org_id from first organization.
  - Returns None when user has no organizations.
  - Returns None when request.user is None.
- Test `FormAPIHandler._get_programs()`:
  - Returns programs list from session.
  - Returns empty list when no programs in session.
  - Returns empty list when no session.
- Test `load_from_db` org_id precedence:
  - Body orgid takes precedence over session org_id.
  - Falls back to session org_id when body omits orgid.
  - Returns 400 when neither body nor session has org_id.
- Test route auth integration:
  - All `/api/v1/forms*` routes return 401 without authenticated session.
  - All page routes (`/`, `/gallery`, `/forms/{id}`) return 401 without session.
  - Routes succeed with valid authenticated session mock.
  - Telegram routes (`/forms/{id}/telegram`) remain accessible without auth.
- Test backward compatibility:
  - When navigator_auth is not installed, routes work without auth.

**NOT in scope**: Modifying handler code, modifying routes.py.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/tests/test_api_auth.py` | CREATE | Unit + integration tests for auth |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Test dependencies
import pytest                                              # standard test framework
from aiohttp import web                                    # for test client
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop  # aiohttp testing
from unittest.mock import AsyncMock, MagicMock, patch      # mocking

# Formdesigner imports
from parrot.formdesigner.handlers.api import FormAPIHandler
from parrot.formdesigner.handlers.routes import setup_form_routes
from parrot.formdesigner.services.registry import FormRegistry
```

### Existing Signatures to Use (after TASK-580/581)

```python
# FormAPIHandler (after TASK-580 cleanup):
class FormAPIHandler:
    def __init__(self, registry: FormRegistry, client=None) -> None:  # no api_key
    def _get_org_id(self, request: web.Request) -> str | None:
    def _get_programs(self, request: web.Request) -> list[str]:
    def _get_llm_client(self) -> AbstractClient | None:
    async def list_forms(self, request: web.Request) -> web.Response:
    async def load_from_db(self, request: web.Request) -> web.Response:
    # ... other handlers

# setup_form_routes (after TASK-581):
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: AbstractClient | None = None,
    prefix: str = "",
) -> None:  # no api_key param

# AuthUser mock structure:
# user.organizations = [Organization(org_id="42", organization="Test", slug="test")]
# session.get("session", {}).get("programs", []) -> ["program-a"]
```

### Does NOT Exist

- ~~`FormAPIHandler._is_authorized()`~~ — removed in TASK-580.
- ~~`FormAPIHandler._auth_error()`~~ — removed in TASK-580.
- ~~`FormAPIHandler.__init__(api_key=...)`~~ — removed in TASK-580.
- ~~`setup_form_routes(api_key=...)`~~ — removed in TASK-581.

---

## Implementation Notes

### Pattern to Follow

```python
# Use aiohttp test_utils or pytest-aiohttp for route testing
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

# Mock the navigator_auth authentication
# Pattern: mock request.get("authenticated") and request.user

@pytest.fixture
def mock_auth_user():
    """Simulated AuthUser with organizations and programs."""
    user = MagicMock()
    org = MagicMock()
    org.org_id = "42"
    org.organization = "Test Org"
    org.slug = "test-org"
    user.organizations = [org]
    return user

@pytest.fixture
def mock_session():
    """Simulated session with programs."""
    return {
        "session": {
            "programs": ["program-a", "program-b"],
            "username": "testuser",
            "email": "test@example.com",
        }
    }
```

### Key Constraints

- Tests must work even when `navigator_auth` is installed in the venv.
- Use mocking to simulate auth states (authenticated vs unauthenticated).
- For route-level tests, create a test aiohttp app with `setup_form_routes`.
- Mock the `is_authenticated` decorator behavior by patching at import time
  or by testing the handler methods directly.

### References in Codebase

- `packages/ai-parrot/tests/handlers/test_dataset_routes.py` — existing handler test pattern.
- `packages/ai-parrot/tests/conftest.py` — auth mocking fixtures.

---

## Acceptance Criteria

- [ ] Test file created at `packages/parrot-formdesigner/tests/test_api_auth.py`.
- [ ] `_get_org_id` tests pass for all cases (valid, empty, None).
- [ ] `_get_programs` tests pass for all cases.
- [ ] `load_from_db` org_id precedence test passes.
- [ ] Route auth tests verify 401 for unauthenticated requests.
- [ ] Telegram routes verified as accessible without auth.
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/test_api_auth.py -v`.

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/test_api_auth.py
import pytest
from unittest.mock import MagicMock
from aiohttp import web


class TestGetOrgId:
    """Tests for FormAPIHandler._get_org_id()."""

    def test_returns_org_id_from_first_organization(self):
        """Extract org_id from user.organizations[0].org_id."""
        ...

    def test_returns_none_when_no_organizations(self):
        """Returns None when user.organizations is empty."""
        ...

    def test_returns_none_when_no_user(self):
        """Returns None when request.user is None."""
        ...


class TestGetPrograms:
    """Tests for FormAPIHandler._get_programs()."""

    def test_returns_programs_from_session(self):
        """Extract programs list from session dict."""
        ...

    def test_returns_empty_when_no_programs(self):
        """Returns [] when session has no programs key."""
        ...

    def test_returns_empty_when_no_session(self):
        """Returns [] when request has no session."""
        ...


class TestLoadFromDbOrgId:
    """Tests for load_from_db org_id resolution."""

    async def test_body_orgid_takes_precedence(self):
        """When body has orgid, use it over session."""
        ...

    async def test_falls_back_to_session_org(self):
        """When body omits orgid, use session org_id."""
        ...

    async def test_400_when_no_org_available(self):
        """When neither body nor session has org_id, return 400."""
        ...


class TestRouteAuth:
    """Integration tests for route authentication."""

    async def test_api_routes_require_auth(self):
        """All /api/v1/forms* routes return 401 without session."""
        ...

    async def test_page_routes_require_auth(self):
        """Page routes return 401 without session."""
        ...

    async def test_telegram_routes_no_auth(self):
        """/forms/{id}/telegram accessible without auth."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-authentication.spec.md`
2. **Check dependencies** — verify TASK-580 and TASK-581 are completed
3. **Read the actual implementation** in `api.py` and `routes.py` after tasks 580/581
4. **Verify the Codebase Contract** — confirm method signatures match
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the tests
7. **Run tests**: `pytest packages/parrot-formdesigner/tests/test_api_auth.py -v`
8. **Verify** all acceptance criteria
9. **Move this file** to `tasks/completed/TASK-582-formdesigner-auth-tests.md`
10. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-04
**Notes**: Created `tests/test_api_auth.py` with 22 tests covering all acceptance criteria. Used simple auth mock for route tests (patches `_AUTH_AVAILABLE`, `is_authenticated`, `user_session`). All 22 tests pass.

**Deviations from spec**: none
