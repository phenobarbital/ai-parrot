# TASK-2933: `SurfaceScope`, `SurfaceScopeResolver` and the default session resolver

**Feature**: FEAT-535 — Tenant-aware, permission-based visibility for UI surfaces
**Spec**: `sdd/specs/ui-surfaces-tenant-visibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2932
**Assigned-to**: unassigned

---

## Context

Implements **Module 2**. Parrot must not know how a host decides the caller's
tenant (FieldSync reads it from the URL; another host may read it from the
session). So the handler asks a pluggable resolver installed on the app under
`app["ui_surfaces_scope_resolver"]`; when none is installed, a default reads
the navigator-auth session and resolves a tenant ONLY when the session carries
exactly one program. The rule "who may see this record" is a pure function
beside it.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py`:
  - `@dataclass(frozen=True) class SurfaceScope`: `user_id: str | None`, `tenant: str | None`, `groups: frozenset[str]`, `is_superuser: bool = False`. Class constant `EMPTY = SurfaceScope(None, None, frozenset(), False)` (module-level `EMPTY_SCOPE`).
  - `class SurfaceScopeResolver(Protocol)`: `async def resolve(self, request: web.Request) -> SurfaceScope`.
  - `class SessionSurfaceScopeResolver`: `resolve()` = `user_id` via `parrot.auth.session_identity.resolve_user_id(request, session)` (falls back to the `_get_user_id` order used by the handler today); `session = await get_session(request)` inside `try/except → EMPTY_SCOPE`; `userinfo = session.get(AUTH_SESSION_OBJECT)` MUST be a `dict` else empty; `programs`/`groups` MUST be `list`/`tuple` whose items are `str` (filter others out) else `[]`; `superuser` MUST be `bool` else `False`; `tenant = programs[0] if len(programs) == 1 else None`.
  - `def get_scope_resolver(app) -> SurfaceScopeResolver`: `app.get("ui_surfaces_scope_resolver")` or a module-level default instance. Accept plain-dict apps too (the handler tests use `{"ui_surfaces_store": store}` as the app).
  - `def scope_grants(record, scope) -> bool` — pure: `False` when `scope.tenant is None` or `record.tenant is None` or `record.tenant != scope.tenant`; then `True` if `scope.is_superuser`, or `record.visibility is tenant`, or (`record.visibility is groups` and `scope.groups & set(record.allowed_groups)`). Owner is NOT considered here (the caller handles owner first).
- Tests `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py`: default resolver on `make_mocked_request("GET", "/api/v1/ui/surfaces")` with nothing installed → `EMPTY_SCOPE`; with `request["NAV_SESSION"] = SessionData(data={AUTH_SESSION_OBJECT: {...}})` (the same construction `tests/handlers/test_a2ui_surfaces_route.py:97-103` uses) → filled scope; two programs → `tenant None`; type checks (`programs="epson"`, `superuser="yes"`, `groups=[1, "g"]` → `frozenset({"g"})`); `get_scope_resolver` with dict app and with `web.Application`; `scope_grants` truth table (parametrized over visibility × tenant match × groups × superuser).

**NOT in scope**: wiring into the handler (TASK-2934), the FieldSync resolver (FieldSync repo).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/ui_surfaces_scope.py` | CREATE | scope type, protocol, default resolver, `scope_grants` |
| `packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py` | CREATE | resolver + truth-table tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navigator_auth.conf import AUTH_SESSION_OBJECT          # value "session" (verified 2026-09-06)
from navigator_session import get_session, SESSION_OBJECT     # SESSION_OBJECT == "NAV_SESSION" — the request-dict key
from parrot.auth.session_identity import resolve_user_id, resolve_session_user   # packages/ai-parrot/src/parrot/auth/session_identity.py:90, :56
from parrot.handlers.models.ui_surfaces import UISurfaceRecord, SurfaceVisibility   # TASK-2932
from aiohttp import web
from aiohttp.test_utils import make_mocked_request            # tests
from navigator_session.storages... import SessionData          # verify the exact import used at tests/handlers/test_a2ui_surfaces_route.py (top of file) and reuse it verbatim
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/session_identity.py
def resolve_session_user(request) -> Any | None                 # :56   AuthUser on request.user (every backend populates Identity.id)
def resolve_user_id(request, session=None) -> str | None        # :90   normalizes to str; falls back to session keys under AUTH_SESSION_OBJECT

# packages/ai-parrot-server/src/parrot/handlers/ui_surfaces.py
async def _get_user_id(request) -> str | None                   # :97-124  request.user.user_id/id → get_session → userinfo["user_id"] → session["user_id"]  (the order to preserve; TASK-2934 may delegate it here)
# app keys already used beside the new one: app["ui_surfaces_store"] (:287-292), app["ui_surfaces_negotiation"] (:295-300)

# tests/handlers/test_a2ui_surfaces_route.py:97-103 — how a test installs a real session:
#   request["authenticated"] = True ; request["NAV_SESSION"] = SessionData(data={"user_id": "u-test"})

# navigator-auth session shape (fieldsync verification): session[AUTH_SESSION_OBJECT] = {"user_id": ..., "programs": list[str], "groups": list[str], "superuser": bool}
```

### Does NOT Exist
- ~~`request.session` attribute~~ — the session is `request[SESSION_OBJECT]`, read through `get_session(request)`. An object with only a `.session` attribute must resolve to `EMPTY_SCOPE` (write that test).
- ~~a tenant on `PermissionContext`/`UserSession` usable here~~ — `parrot.auth.permission` is PBAC for tools/data; do not import it for scope.
- ~~`EmployeeProfile` lookups~~ — that is a DB path (`auth.vw_users`); the default resolver reads the SESSION only.
- ~~`programs[0]` for multi-program sessions~~ — forbidden by design (the FEAT-366 failure); `None` when `len != 1`.

---

## Implementation Notes

### Key Constraints
- Pure, small, no I/O except `get_session`. Type-check every value read from the session Mapping; never truth-check (a `Mock` answers `.get()` with a truthy `Mock`).
- No import of `parrot.handlers.ui_surfaces` from this module (the handler imports THIS module; avoid the cycle).
- Google docstrings; explain the single-program rule in the class docstring.

### References in Codebase
- `handlers/ui_surfaces.py:97-124` — identity order.
- `tests/handlers/test_a2ui_surfaces_route.py:89-131` — session/app fixtures.

---

## Acceptance Criteria

- [ ] `SessionSurfaceScopeResolver().resolve(make_mocked_request(...))` with nothing installed → `EMPTY_SCOPE`; attribute-only double → `EMPTY_SCOPE`
- [ ] Real session dict → filled scope; two programs → `tenant None`; malformed types ignored
- [ ] `get_scope_resolver` honours `app["ui_surfaces_scope_resolver"]` for dict and `web.Application` apps
- [ ] `scope_grants` truth table passes; owner is not part of it
- [ ] `ruff check` clean

---

## Test Specification

```python
# tests/handlers/test_ui_surfaces_scope.py (excerpt)
@pytest.mark.parametrize("visibility,same_tenant,groups,superuser,expected", [
    ("private", True, set(), False, False),
    ("tenant", True, set(), False, True),
    ("tenant", False, set(), False, False),
    ("groups", True, {"g1"}, False, True),
    ("groups", True, {"g2"}, False, False),
    ("private", True, set(), True, True),      # superuser sees private rows of others in the tenant
    ("tenant", False, set(), True, False),     # never cross-tenant
])
def test_scope_grants(visibility, same_tenant, groups, superuser, expected): ...

async def test_default_resolver_empty_request():
    req = make_mocked_request("GET", "/api/v1/ui/surfaces")
    assert await SessionSurfaceScopeResolver().resolve(req) == EMPTY_SCOPE
```

---

## Agent Instructions

1. Read spec §2 Overview item 2, §3 Module 2, §6, §7 gotchas.
2. Verify imports (especially `SessionData`'s module) against the tree; implement; `pytest packages/ai-parrot-server/tests/handlers/test_ui_surfaces_scope.py -v`; `ruff check`.
3. Index → `in-progress` → `done`; move to `completed/`; Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
