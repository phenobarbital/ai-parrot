# TASK-2511: Studio package scaffold, /api/v1/astudio routes, PBAC, shared models

**Feature**: FEAT-467 — Agent Studio — Management API
**Spec**: `sdd/specs/agentstudio-management.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. Foundation every Studio handler task builds on: the
`handlers/studio/` package, the `setup_studio_routes(app)` registration
function called from `BotManager.setup`, a shared `StudioBaseView` with
session/ownership/PBAC helpers, and the shared Pydantic request/response
models. Route prefix is **`/api/v1/astudio/`** (resolved: `/api/v1/studio`
belongs to another installed service — never register under it).

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/studio/` with:
  - `__init__.py` — `def setup_studio_routes(app: web.Application) -> None`
    (pattern: `setup_credentials_routes`, credentials.py:506). Registers
    placeholder routes for the areas later tasks fill in; each later task
    adds its own `add_view` lines here.
  - `_base.py` — `StudioBaseView(BaseView)` decorated
    `@is_authenticated()`/`@user_session()` at subclass sites; helpers:
    `_get_user()` (session → user_id/email), `_require_owner(resource_owner)`
    (403 unless owner or admin), `_pbac_allowed(resource: str, action: str)`
    (PBAC ids `astudio:<area>`; fail-open when `app['abac']` absent —
    pattern `_PBACHandlerMixin`).
  - `models.py` — shared Pydantic models from spec §2 Data Models:
    `CreateAgentRequest`, `ReloadResult`, `DraftValidationReport`,
    `SkillPublishRequest`, `ByokKeyRequest`, plus a common
    `StudioError` response shape.
- Wire `setup_studio_routes(self.app)` into `BotManager.setup`.
- Slug validation helper (regex `^[a-z0-9_-]+$`) + traversal-safe path
  resolver (used by files/drafts tasks).
- Tests: route registration, 401 unauthenticated, PBAC fail-open, admin
  bypass, slug/path helpers.

**NOT in scope**: any concrete endpoint behavior (later tasks); PBAC policy
*content* (only ids/enforcement plumbing).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/__init__.py` | CREATE | `setup_studio_routes` |
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | CREATE | `StudioBaseView` + helpers |
| `packages/ai-parrot-server/src/parrot/handlers/studio/models.py` | CREATE | shared Pydantic models |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | call `setup_studio_routes` in `setup()` |
| `packages/ai-parrot-server/tests/studio/conftest.py` | CREATE | `studio_app`, mocked session fixtures |
| `packages/ai-parrot-server/tests/studio/test_scaffold.py` | CREATE | wiring/auth/PBAC tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator.views import BaseView, BaseHandler                      # handlers/bots.py:18-22
from navigator_auth.decorators import is_authenticated, user_session   # stores/handler.py:11
from navigator_session import get_session                              # navigator/views/abstract.py:17
```

### Existing Signatures to Use
```python
# .venv/.../navigator/views/base.py
class BaseView(CorsViewMixin, BaseHandler, web.View): ...  # :619
def json_response(self, response=None, reason=None, headers=None, status=200, ...): ...  # :144
async def session(self): ...                             # :89
async def get_userid(self, session, idx='user_id') -> int: ...  # :99
async def post_data(self) -> dict: ...                   # :673
def post_init(self, *args, **kwargs): ...                # :79 (set self.logger; _logger_name attr)

# packages/ai-parrot-server/src/parrot/handlers/credentials.py:506
def setup_credentials_routes(app: web.Application) -> None:
    # app.router.add_route("*", "/api/v1/users/credentials", CredentialsHandler)  (:514)
    # — THE registration pattern to copy

# packages/ai-parrot-server/src/parrot/handlers/bots.py
class _PBACHandlerMixin:  # :45
    def _get_pbac_evaluator(self): ...           # :56 (app['abac'], fail-open)
    async def _build_eval_context(self): ...     # :68
_AGENT_SLUG_RE = re.compile(r"^[a-z0-9_-]+$")    # :85

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    def setup(self, app: web.Application) -> web.Application: ...  # :1686
        # self.app['bot_manager'] = self (:1702); router.add_view blocks :1709-:2037
        # call setup_studio_routes(self.app) near the setup_credentials_routes call (~:2039)
```

### Does NOT Exist
- ~~`handlers/__init__.py` in the server package~~ — do NOT create one;
  wiring is per-handler `setup_*_routes` functions.
- ~~Any existing "studio"/"astudio" route, class, or PBAC id~~ — greenfield.
- ~~`navigator_auth` admin decorator like `@is_admin()`~~ — derive
  admin/superuser from the session object (see how `_PBACHandlerMixin`
  builds context; check `session[AUTH_SESSION_OBJECT]` fields before use).
- ~~`AbstractModel.configure` for Studio views~~ — deliberately avoided
  (catch-all `{id:.*}` route-ordering trap, spec §7); use plain
  `app.router.add_view(path, cls)`.

---

## Implementation Notes

### Pattern to Follow
```python
# handlers/studio/__init__.py
from aiohttp import web
def setup_studio_routes(app: web.Application) -> None:
    """Register all /api/v1/astudio/* routes (FEAT-467)."""
    from .agents import StudioAgentsHandler        # imported lazily per area
    app.router.add_view("/api/v1/astudio/agents", StudioAgentsHandler)
    app.router.add_view("/api/v1/astudio/agents/{name}", StudioAgentsHandler)
    ...
```
`StudioBaseView`: `_logger_name = "Parrot.AgentStudio"`; session pattern:
`session = await self.session()` then `await self.get_userid(session)`
(see `handlers/stores/handler.py`, `handlers/credentials.py:90-121`).

### Key Constraints
- EVERY route path starts `/api/v1/astudio/` — add a test that greps the
  registered routes for `/api/v1/studio` and fails if any exist.
- PBAC resource ids: `astudio:agents`, `astudio:drafts`, `astudio:files`,
  `astudio:skills`, `astudio:keys`, `astudio:testing`, `astudio:toolkits`,
  `astudio:catalog`.
- Pydantic models: strict types, `SecretStr` for the BYOK key.
- Path resolver must reject `..`, absolute paths, and symlink escapes
  (resolve + `is_relative_to` check).

### References in Codebase
- `packages/ai-parrot/tests/handlers/conftest.py` — handler-test conftest
  pattern (mock session).
- `tests/manager/test_botmanager_wiring.py` — wiring-test pattern.

---

## Acceptance Criteria

- [ ] `setup_studio_routes` registered from `BotManager.setup`; all routes
      under `/api/v1/astudio/`; zero routes under `/api/v1/studio`.
- [ ] Unauthenticated request to any Studio route → 401.
- [ ] PBAC fail-open verified (no `app['abac']` → allowed); ownership 403
      path unit-tested via `_require_owner`.
- [ ] Traversal attempts rejected by the path resolver.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_scaffold.py -v` passes.
- [ ] `ruff check packages/ai-parrot-server/src/parrot/handlers/studio/` clean.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_scaffold.py
class TestStudioScaffold:
    async def test_routes_registered_under_astudio(self, studio_app): ...
    async def test_no_route_under_plain_studio(self, studio_app): ...
    async def test_unauthenticated_401(self, studio_app): ...
    def test_slug_validation(self): ...
    def test_path_resolver_rejects_traversal(self, tmp_path): ...
    async def test_pbac_fail_open_without_pdp(self, studio_app): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/agentstudio-management.json` → `"in-progress"`
5. **Implement**, **verify** acceptance criteria
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-27
**Notes**:
- `handlers/studio/__init__.py` — `setup_studio_routes(app)` registers no
  concrete routes yet (by design — TASK-2512 through TASK-2521 add their
  own `add_view` calls); wired into `BotManager.setup()` right next to
  `setup_credentials_routes(self.app)`.
- `handlers/studio/_base.py` — `StudioBaseView(BaseView)` with
  `_get_user()`/`StudioUser` (session → user_id/email/username/groups/
  is_superuser, using `AUTH_SESSION_OBJECT` — mirrors
  `handlers/agents/abstract.py:508`'s `userinfo.get('superuser', False)`
  convention, since plain `BaseView` subclasses do NOT get
  `self._session` auto-populated the way `AbstractModel` does — see the
  gotcha already documented at `handlers/comm_center.py:670-676`),
  `_require_owner()` (403 unless owner or superuser), `_pbac_allowed()`
  (fail-open `astudio:<area>` check via `ResourceType.URI` — no
  dedicated Studio `ResourceType` exists, and adding one is PBAC policy
  *content*, explicitly out of this task's scope), plus the
  `is_valid_slug()` / `resolve_safe_path()` helpers (traversal + symlink
  escape rejection) later file/draft tasks will use.
- `handlers/studio/models.py` — `CreateAgentRequest`,
  `DraftValidationReport`, `SkillPublishRequest` (typed
  `category: SkillCategory` per spec), `ByokKeyRequest` (`SecretStr`),
  `StudioError`. `ReloadResult` is imported/re-exported from
  `parrot.manager.manager` (FEAT-467 TASK-2510) rather than duplicated —
  the task lists it among "shared Pydantic models" but its canonical
  definition already exists as `BotManager.reload_agent`'s actual return
  type; two competing definitions would drift.
- Tests use `aiohttp.test_utils.make_mocked_request` +
  direct-instantiation (`StudioBaseView(request)` — `aiohttp.web.View
  .__init__` just sets `self._request`, no router required) rather than
  a full `aiohttp_client`/live app, matching the established
  lightweight pattern in
  `tests/handlers/test_comm_center_handler.py::
  TestGetBatchesAuthentication`. Caught and fixed one MagicMock
  footgun: `make_mocked_request(...)` defaults `request.app` to a bare
  `MagicMock()`, whose `.get('abac')` auto-mocks a truthy return instead
  of behaving like a real dict `.get()` — fixed by passing an explicit
  `app=web.Application()`.

**Deviations from spec**: none functionally. Two notes:
1. PBAC ids use `ResourceType.URI` as the closest-fit existing
   `navigator_auth` resource type (the enum has no generic/Studio
   member) — documented inline; picking/adding a dedicated resource
   type is policy *content*, out of this task's scope per its own NOT
   IN SCOPE line.
2. `packages/ai-parrot-server/tests/studio/__init__.py` (empty) created
   alongside the two listed test files, matching this package's
   sibling test-subpackage convention (same as TASK-2510's
   `tests/manager/__init__.py`).

Verification: `pytest packages/ai-parrot-server/tests/studio/ -v` →
25/25 passed. `ruff check packages/ai-parrot-server/src/parrot/handlers/
studio/` → clean except one intentional `BLE001` (blind
`except Exception` in the fail-open PBAC branch, matching
`handlers/bots.py::_PBACHandlerMixin`'s identical pattern at
bots.py:677). Broader regression sweep (`tests/manager/`, `tests/
studio/`, ephemeral-owner, DB-bot-fallback, comm_center auth tests) →
87/87 passed.
