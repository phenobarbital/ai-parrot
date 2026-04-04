# Feature Specification: FormDesigner Authentication

**Feature ID**: FEAT-083
**Date**: 2026-04-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.10.x

---

## 1. Motivation & Business Requirements

### Problem Statement

The `parrot-formdesigner` API endpoints currently use a custom shared-secret
Bearer token (`PARROT_FORM_API_KEY`) for authentication. This is disconnected
from the Navigator platform's authentication system (`navigator-auth`), which
manages sessions, user identity, organizations, and programs via middleware.

All other AI-Parrot HTTP handlers (`AgentTalk`, `CredentialsHandler`, `ChatBot`)
already use `@is_authenticated()` / `@user_session()` from `navigator-auth`.
The formdesigner endpoints need the same integration so that:

- Users are authenticated via the platform session (JWT / backend chain).
- Organization (`org_id`), client, and tenant/program context are derived from
  the authenticated user — not passed as raw request parameters.
- The `/api/v1/forms/from-db` endpoint no longer requires the caller to supply
  `orgid` explicitly; it comes from the session (but leaves if caller supply the `orgid` explicitly, use that.)

### Goals

- Protect all `FormAPIHandler` API routes with `navigator-auth` authentication.
- Extract `org_id` from `request.user.organizations[0].org_id`, or caller supply the `orgid` explicitly.
- Extract `programs` (tenant context) from the user session.
- Remove the custom `PARROT_FORM_API_KEY` auth mechanism from `FormAPIHandler`.
- Keep `FormPageHandler` and `TelegramWebAppHandler` routes unauthenticated
  (public-facing form rendering and Telegram WebApp).

### Non-Goals (explicitly out of scope)

- PBAC / fine-grained permission checks (handled separately by FEAT-080).
- Changing `FormPageHandler` or `TelegramWebAppHandler` auth behavior.
- Modifying `navigator-auth` itself.
- Adding `navigator-auth` as a hard dependency to `parrot-formdesigner` package
  (it must remain an optional/runtime dependency since the package can be used
  standalone).

---

## 2. Architectural Design

### Overview

Apply `@is_authenticated()` and `@user_session()` decorators at class level on
`FormAPIHandler`. This mirrors the pattern used by `CredentialsHandler` and
`AgentTalk`. The decorators are applied in `routes.py` at registration time
(not at class definition) to avoid a hard import dependency in the package.

For function-based handlers (which `FormAPIHandler` methods are — they receive
`request: web.Request` as a plain argument, not via `self.request`), the
`user_session` decorator injects `session` and `user` keyword arguments. Since
`is_authenticated` works on both classes and plain functions via
`_apply_decorator`, and `FormAPIHandler` is a plain class (not a `BaseView`),
decoration must wrap each handler method individually at route registration.

### Component Diagram

```
request
  │
  ▼
navigator-auth middleware (sets request["authenticated"], request["session"])
  │
  ▼
@is_authenticated — verifies auth, raises 401 if unauthenticated
  │
  ▼
@user_session — decodes user from session, attaches request.user
  │
  ▼
FormAPIHandler.method(request)
  │  reads: request.user.organizations[0].org_id
  │  reads: session.get(AUTH_SESSION_OBJECT, {}).get("programs", [])
  ▼
business logic (registry, tools, etc.)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `navigator_auth.decorators.is_authenticated` | decorator | Class-level or per-method |
| `navigator_auth.decorators.user_session` | decorator | Injects session + user |
| `navigator_auth.identities.AuthUser` | model | `user.organizations[0].org_id` |
| `navigator_auth.conf.AUTH_SESSION_OBJECT` | config | Key = `"session"` |
| `FormAPIHandler` | modify | Remove custom auth, add navigator-auth |
| `setup_form_routes` | modify | Apply decorators at registration time |

### Data Models

No new data models. The existing `AuthUser` and `Organization` from
`navigator-auth` provide all needed attributes:

```python
# navigator_auth.identities
class AuthUser(Identity):
    organizations: List[Organization]  # org_id, organization, slug
    groups: List[Group]
    superuser: bool

class Organization:
    org_id: str
    organization: str
    slug: str
```

Programs are stored in the session dict under `AUTH_SESSION_OBJECT`:
```python
session.get("session", {}).get("programs", [])
```

### New Public Interfaces

```python
# New helper methods on FormAPIHandler
class FormAPIHandler:
    def _get_org_id(self, request: web.Request) -> str | None:
        """Extract org_id from authenticated user's first organization."""
        ...

    def _get_programs(self, request: web.Request) -> list[str]:
        """Extract programs (tenant context) from user session."""
        ...
```

---

## 3. Module Breakdown

### Module 1: FormAPIHandler Auth Integration

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py`
- **Responsibility**:
  - Remove `_api_key`, `_is_authorized()`, `_auth_error()` (custom auth).
  - Add `_get_org_id(request)` helper — returns `request.user.organizations[0].org_id`.
  - Add `_get_programs(request)` helper — returns programs from session.
  - Update `load_from_db` to use `_get_org_id()` instead of requiring `orgid` in body.
  - Update `create_form` and other methods to pass org context where needed.
- **Depends on**: None (uses navigator-auth at runtime only).

### Module 2: Route Registration with Auth Decorators

- **Path**: `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py`
- **Responsibility**:
  - Apply `@is_authenticated()` and `@user_session()` to API handler methods
    at registration time via wrapper functions.
  - Keep page/telegram routes unauthenticated.
  - Remove `api_key` parameter from `setup_form_routes()`.
- **Depends on**: Module 1.

### Module 3: Tests

- **Path**: `packages/parrot-formdesigner/tests/test_api_auth.py`
- **Responsibility**:
  - Test that API routes return 401 without valid session.
  - Test that authenticated requests pass through with user context.
  - Test `_get_org_id()` and `_get_programs()` extraction.
  - Test `load_from_db` uses org_id from session (no longer required in body).
- **Depends on**: Module 1, Module 2.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_get_org_id_from_user` | 1 | Returns org_id from first organization |
| `test_get_org_id_no_organizations` | 1 | Returns None when user has no orgs |
| `test_get_programs_from_session` | 1 | Returns programs list from session |
| `test_get_programs_empty` | 1 | Returns empty list when no programs |

### Integration Tests

| Test | Description |
|---|---|
| `test_api_routes_require_auth` | All `/api/v1/forms*` routes return 401 without session |
| `test_api_routes_pass_with_auth` | Routes succeed with valid authenticated session |
| `test_load_from_db_uses_session_org` | `POST /api/v1/forms/from-db` uses org_id from user |
| `test_page_routes_no_auth` | `/`, `/gallery`, `/forms/{id}` remain public |
| `test_telegram_routes_no_auth` | `/forms/{id}/telegram` remains public |

### Test Fixtures

```python
@pytest.fixture
def mock_auth_user():
    """Simulated AuthUser with organizations and programs."""
    return {
        "organizations": [{"org_id": "42", "organization": "Test Org", "slug": "test-org"}],
        "programs": ["program-a", "program-b"],
        "username": "testuser",
        "email": "test@example.com",
    }
```

---

## 5. Acceptance Criteria

- [ ] All `FormAPIHandler` API routes (`/api/v1/forms*`) require authentication via navigator-auth.
- [ ] `FormPageHandler` routes (`/`, `/gallery`, `/forms/{id}`) remain public.
- [ ] `TelegramWebAppHandler` routes remain public.
- [ ] `org_id` is extracted from `request.user.organizations[0].org_id`.
- [ ] `programs` are extracted from user session data.
- [ ] `load_from_db` no longer requires `orgid` in request body (uses session).
- [ ] Custom `PARROT_FORM_API_KEY` mechanism is removed from `FormAPIHandler`.
- [ ] `navigator-auth` is NOT added as a hard dependency to `parrot-formdesigner` `pyproject.toml`.
- [ ] All tests pass.
- [ ] No breaking changes to `FormPageHandler` or `TelegramWebAppHandler`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# navigator-auth decorators (verified: installed in venv)
from navigator_auth.decorators import is_authenticated   # function(content_type="application/json") -> decorator
from navigator_auth.decorators import user_session        # function() -> decorator
from navigator_auth.conf import AUTH_SESSION_OBJECT       # value: "session"

# navigator_auth.identities (verified: installed in venv)
from navigator_auth.identities import AuthUser            # datamodel with .organizations: List[Organization]
from navigator_auth.identities import Organization        # datamodel with .org_id: str, .organization: str, .slug: str
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/api.py
class FormAPIHandler:                                     # line 30 — plain class, NOT BaseView
    def __init__(self, registry, client=None, api_key=None)  # line 45
    _client: AbstractClient | None                        # line 51
    _api_key: str | None                                  # line 53 — TO BE REMOVED
    def _is_authorized(self, request) -> bool             # line 74 — TO BE REMOVED
    def _auth_error(self, request) -> web.Response | None # line 91 — TO BE REMOVED
    def _get_llm_client(self) -> AbstractClient | None    # lazy GoogleGenAI client
    async def list_forms(self, request)                   # line 112
    async def get_form(self, request)                     # line 127
    async def get_schema(self, request)                   # line 145
    async def get_style(self, request)                    # line 164
    async def get_html(self, request)                     # line 183
    async def validate(self, request)                     # line 202
    async def create_form(self, request)                  # line 230
    async def load_from_db(self, request)                 # line 278

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py
def setup_form_routes(app, *, registry=None, client=None, api_key=None, prefix="")  # line 21

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/forms.py
class FormPageHandler:                                    # line 22 — plain class, public routes
    def __init__(self, registry, renderer=None, validator=None)  # line 31

# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/telegram.py
class TelegramWebAppHandler:                              # line 27 — plain class, public routes
    def __init__(self, registry, renderer=None, validator=None)  # line 36
```

### Decorator Behavior (verified via inspect)

```python
# is_authenticated() — can decorate functions AND classes
# For classes: wraps each HTTP-method-named method (get, post, etc.) via _apply_decorator
# For plain functions: wraps directly
# Raises web.HTTPUnauthorized (401) if not authenticated
# Signature: is_authenticated(content_type: str = "application/json") -> Callable[[F], F]

# user_session() — can decorate functions AND classes
# For functions: injects session=, user= kwargs
# For class methods: sets self.session, self.user, request.session, request.user
# For plain classes (not BaseView): wraps methods, sets request.user as AuthUser
# NOTE: FormAPIHandler methods receive (self, request) — NOT BaseView pattern
#   so user_session will wrap each method and attach request.user / request.session
```

### Existing Auth Pattern (reference implementation)

```python
# packages/ai-parrot/src/parrot/handlers/credentials.py:69-71
@is_authenticated()
@user_session()
class CredentialsHandler(BaseView):
    ...

# packages/ai-parrot/src/parrot/handlers/agent.py:45-47
@is_authenticated()
@user_session()
class AgentTalk(BaseView):
    ...
```

### Session Data Structure

```python
# From handlers/agents/abstract.py:496-501 (verified)
userinfo = session.get(AUTH_SESSION_OBJECT, {})  # AUTH_SESSION_OBJECT = "session"
userinfo.get('email', None)
userinfo.get('username', None)
userinfo.get('programs', [])      # list of program slugs
userinfo.get('groups', [])
userinfo.get('superuser', False)

# AuthUser.organizations access (verified: identities.py)
user.organizations[0].org_id      # str
user.organizations[0].organization  # str
user.organizations[0].slug        # str
```

### Does NOT Exist (Anti-Hallucination)

- ~~`request.user.programs`~~ — `programs` is NOT an attribute of `AuthUser`; it lives in the session dict under `AUTH_SESSION_OBJECT`.
- ~~`request.user.org_id`~~ — there is no top-level `org_id` on `AuthUser`; access via `user.organizations[0].org_id`.
- ~~`request.user.client_id`~~ — no `client_id` attribute on `AuthUser` or `Identity`.
- ~~`FormAPIHandler` inherits `BaseView`~~ — it does NOT. It is a plain class with methods receiving `request: web.Request`.
- ~~`navigator_auth.decorators.require_auth`~~ — does not exist; use `is_authenticated`.
- ~~`navigator_auth.middleware`~~ — there is no standalone middleware module; auth is registered via `AuthHandler` on the app.

---

## 7. Implementation Notes & Constraints

### Key Design Decisions

1. **Decorator application at route-registration time**: Since `FormAPIHandler`
   is not a `BaseView` and its methods are plain `async def method(self, request)`,
   the `is_authenticated` / `user_session` decorators should wrap each API method
   individually when routes are registered in `setup_form_routes()`. This avoids
   importing `navigator_auth` at module level in the formdesigner package.

2. **Conditional import**: `navigator_auth` is an optional dependency. Wrap the
   import in a try/except at the top of `routes.py`. When not available, API
   routes run without auth (backward compatible for standalone/dev usage).

3. **`load_from_db` backward compatibility**: The `orgid` parameter in the
   request body becomes optional. If provided, it takes precedence over the
   session org_id. If not provided, falls back to session. This allows a
   smooth migration.

### Patterns to Follow

- Follow `CredentialsHandler` / `AgentTalk` decorator pattern.
- Extract user info via `request.user` (set by `user_session` decorator).
- Extract programs via session dict, not via user object.
- Use `self.logger` for all logging.

### Known Risks / Gotchas

- **`user_session` on non-BaseView classes**: The decorator wraps each
  HTTP-method-named method (`get`, `post`, etc.), but `FormAPIHandler` methods
  are named `list_forms`, `create_form`, etc. — NOT `get`/`post`. Therefore
  class-level `@user_session()` will NOT auto-wrap them. Each method must be
  wrapped individually at registration time.
- **`is_authenticated` same issue**: Class-level decoration only wraps methods
  named after HTTP methods. Must wrap individual handler methods instead.
- **Empty organizations**: Must handle the case where `user.organizations` is
  an empty list — return 403 or use a fallback.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | (runtime, optional) | Session-based authentication |

---

## Worktree Strategy

- **Isolation unit**: per-spec (sequential tasks).
- All 3 modules are tightly coupled — Module 2 depends on Module 1, Module 3
  depends on both. Sequential execution in one worktree.
- **Cross-feature dependencies**: None. This spec only modifies formdesigner
  handler files.

---

## 8. Open Questions

- [x] Should `FormPageHandler` routes (public HTML pages) also require auth
      in production? Currently scoped as public. — *Owner: Jesus*: Yes, authentication is required.
- [x] Should `api_key` fallback be kept as an alternative auth method alongside
      navigator-auth, or fully removed? — *Owner: Jesus*: fully removed.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-04-04 | Jesus Lara | Initial draft |
