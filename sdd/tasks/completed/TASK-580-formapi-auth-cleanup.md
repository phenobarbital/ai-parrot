# TASK-580: FormAPIHandler Auth Cleanup & User Context Helpers

**Feature**: formdesigner-authentication
**Spec**: `sdd/specs/formdesigner-authentication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-083. It removes the custom `PARROT_FORM_API_KEY`
shared-secret authentication from `FormAPIHandler` and adds helper methods to extract
user identity from the navigator-auth session. Implements spec Module 1.

The open questions in the spec have been resolved:
- `api_key` is **fully removed** (no fallback).
- `FormPageHandler` also requires auth (handled in TASK-581).

---

## Scope

- Remove `_api_key` attribute from `__init__`.
- Remove `api_key` parameter from `__init__`.
- Remove `_is_authorized()` method.
- Remove `_auth_error()` method.
- Remove all `if (err := self._auth_error(request)) ...` checks from every handler method.
- Remove `import hmac` and `import os` (if no longer needed after cleanup).
- Add `_get_org_id(self, request: web.Request) -> str | None` helper:
  - Returns `request.user.organizations[0].org_id` if available.
  - Returns `None` if user has no organizations.
- Add `_get_programs(self, request: web.Request) -> list[str]` helper:
  - Gets session from `request.get("session")` or `request.session`.
  - Returns `session.get(AUTH_SESSION_OBJECT, {}).get("programs", [])`.
  - AUTH_SESSION_OBJECT = `"session"` — use a string literal, do NOT import from navigator_auth.
- Update `load_from_db` endpoint:
  - `orgid` in request body becomes optional.
  - If not provided, fall back to `self._get_org_id(request)`.
  - If neither available, return 400 error.
- Update `create_form` check: replace `self._get_llm_client() is None` with same logic (already correct, just remove old auth guard).
- Update class docstring to reflect navigator-auth authentication.

**NOT in scope**: Applying decorators (TASK-581), modifying routes.py (TASK-581),
modifying FormPageHandler or TelegramWebAppHandler, writing tests (TASK-582).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py` | MODIFY | Remove custom auth, add user context helpers, update load_from_db |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Already in api.py — keep these:
from aiohttp import web                                    # verified: api.py:18
from ..core.schema import RenderedForm                     # verified: api.py:20
from ..renderers.html5 import HTML5Renderer                # verified: api.py:21
from ..renderers.jsonschema import JsonSchemaRenderer       # verified: api.py:22
from ..services.registry import FormRegistry               # verified: api.py:23
from ..services.validators import FormValidator            # verified: api.py:24

# REMOVE these (no longer needed after cleanup):
# import hmac                                              # line 12 — REMOVE
# import os                                                # line 14 — KEEP only if _get_llm_client or env vars still need it
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py
class FormAPIHandler:                                      # line 30
    def __init__(self, registry, client=None, api_key=None)  # line 45 — REMOVE api_key param
    _client: AbstractClient | None                         # line 52
    _api_key: str | None                                   # line 53 — REMOVE
    html_renderer: HTML5Renderer                           # line 54
    schema_renderer: JsonSchemaRenderer                    # line 55
    validator: FormValidator                               # line 56
    logger: logging.Logger                                 # line 57
    _create_tool: CreateFormTool                            # line 62
    _db_tool: DatabaseFormTool                              # line 66
    def _get_llm_client(self) -> AbstractClient | None     # line 70
    def _is_authorized(self, request) -> bool              # line 74 — REMOVE
    def _auth_error(self, request) -> web.Response | None  # line 91 — REMOVE

    # Handler methods — all have pattern:
    #   if (err := self._auth_error(request)) is not None:
    #       return err
    # This guard must be removed from ALL of them:
    async def list_forms(self, request)                    # line 112
    async def get_form(self, request)                      # line 127
    async def get_schema(self, request)                    # line 145
    async def get_style(self, request)                     # line 164
    async def get_html(self, request)                      # line 183
    async def validate(self, request)                      # line 202
    async def create_form(self, request)                   # line 230
    async def load_from_db(self, request)                  # line 278
```

### Session Data Access Pattern (verified from handlers/agents/abstract.py:496-501)

```python
# AUTH_SESSION_OBJECT = "session" (from navigator_auth.conf)
# Do NOT import this — use the string literal "session" to avoid hard dependency.
# Access pattern:
session = getattr(request, 'session', None) or request.get('session')
userinfo = session.get("session", {}) if session else {}
programs = userinfo.get("programs", [])
```

### AuthUser Access Pattern (verified from navigator_auth.identities)

```python
# request.user is set by @user_session() decorator (applied in TASK-581)
# AuthUser.organizations: List[Organization]
# Organization.org_id: str
user = getattr(request, 'user', None)
if user and user.organizations:
    org_id = user.organizations[0].org_id  # str
```

### Does NOT Exist

- ~~`request.user.programs`~~ — programs is NOT on AuthUser; it's in the session dict.
- ~~`request.user.org_id`~~ — no top-level org_id; access via `user.organizations[0].org_id`.
- ~~`request.user.client_id`~~ — no client_id attribute on AuthUser.
- ~~`navigator_auth.conf.AUTH_SESSION_OBJECT`~~ — exists but do NOT import it; use `"session"` literal to avoid hard dependency.
- ~~`request["authenticated"]`~~ — set by middleware but don't rely on it directly; the decorator handles this.

---

## Implementation Notes

### Pattern to Follow

```python
# Existing pattern from handlers/agents/abstract.py:496-501
userinfo = session.get("session", {})
email = userinfo.get('email', None)
username = userinfo.get('username', None)
programs = userinfo.get('programs', [])
groups = userinfo.get('groups', [])
```

### Key Constraints

- Do NOT import anything from `navigator_auth` in this file.
- `_get_org_id` and `_get_programs` must handle `request.user` being `None`
  gracefully (return `None` / `[]`).
- `os` import may still be needed if `_get_llm_client` or env var logic remains.
  Check before removing.
- `hmac` import should be fully removed.

---

## Acceptance Criteria

- [ ] `_api_key`, `_is_authorized()`, `_auth_error()` are fully removed.
- [ ] `api_key` parameter removed from `__init__`.
- [ ] `hmac` import removed.
- [ ] No `_auth_error` calls remain in any handler method.
- [ ] `_get_org_id(request)` correctly extracts org_id from `request.user`.
- [ ] `_get_programs(request)` correctly extracts programs from session.
- [ ] `load_from_db` uses org_id from session when not in body, body value takes precedence.
- [ ] File has no syntax errors: `python -c "import ast; ast.parse(open('...').read())"`.

---

## Test Specification

```python
# Tests are in TASK-582. For this task, just verify no syntax errors.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-authentication.spec.md`
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — read `api.py` and confirm line numbers
4. **Update status** in `tasks/.index.json` → `"in-progress"`
5. **Implement** the scope above
6. **Verify** all acceptance criteria
7. **Move this file** to `tasks/completed/TASK-580-formapi-auth-cleanup.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-04
**Notes**: Removed `_api_key`, `_is_authorized()`, `_auth_error()`, `hmac` import. Added `_get_org_id()` and `_get_programs()` helpers. Updated `load_from_db` to use session org_id when body omits `orgid` (body takes precedence). No navigator_auth imports added to api.py.

**Deviations from spec**: none | describe if any
