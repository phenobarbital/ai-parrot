# TASK-581: Route Registration Auth Wrappers

**Feature**: formdesigner-authentication
**Spec**: `sdd/specs/formdesigner-authentication.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-580
**Assigned-to**: unassigned

---

## Context

This task applies `navigator-auth` decorators to all formdesigner handler methods
at route-registration time. Implements spec Module 2.

**Critical design decision**: `FormAPIHandler` and `FormPageHandler` are plain classes
(NOT `BaseView` subclasses). Their methods are named `list_forms`, `create_form`, etc.
— NOT `get`/`post`. The `is_authenticated()` and `user_session()` class-level decorators
only auto-wrap HTTP-method-named methods. Therefore we MUST wrap each handler method
individually when registering routes.

Per the resolved open questions:
- `FormPageHandler` routes **also require authentication**.
- `api_key` parameter is **fully removed** from `setup_form_routes`.
- `TelegramWebAppHandler` routes remain **unauthenticated** (public Telegram WebApp).

---

## Scope

- Modify `setup_form_routes()` in `routes.py`:
  - Remove `api_key` parameter.
  - Remove `api_key=api_key` from `FormAPIHandler()` constructor call.
  - Add conditional import of `navigator_auth.decorators` (try/except).
  - Create a helper function `_wrap_auth(handler)` that applies `is_authenticated()`
    and `user_session()` to a single async handler function.
  - Wrap each `FormAPIHandler` method with `_wrap_auth()` when registering API routes.
  - Wrap each `FormPageHandler` method with `_wrap_auth()` when registering page routes.
  - Leave `TelegramWebAppHandler` methods unwrapped.
  - When `navigator_auth` is not installed, `_wrap_auth` is a no-op (passthrough).
- Update `__init__.py` exports if needed.

**NOT in scope**: Modifying `FormAPIHandler` internals (done in TASK-580),
writing tests (TASK-582), modifying `FormPageHandler` class itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py` | MODIFY | Add auth wrapping at route registration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# navigator-auth decorators (conditional import — try/except)
from navigator_auth.decorators import is_authenticated   # function(content_type="application/json") -> decorator
from navigator_auth.decorators import user_session        # function() -> decorator

# Already in routes.py:
from aiohttp import web                                   # verified: routes.py:8
from ..services.registry import FormRegistry              # verified: routes.py:11
from .api import FormAPIHandler                           # verified: routes.py:13
from .forms import FormPageHandler                        # verified: routes.py:14
from .telegram import TelegramWebAppHandler               # verified: routes.py:15
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot/formdesigner/handlers/routes.py
def setup_form_routes(
    app: web.Application,
    *,
    registry: FormRegistry | None = None,
    client: "AbstractClient | None" = None,
    api_key: str | None = None,          # line 27 — REMOVE this param
    prefix: str = "",
) -> None:                                # line 28

# FormAPIHandler methods to wrap (after TASK-580 removes custom auth):
api.list_forms       # async def list_forms(self, request)
api.get_form         # async def get_form(self, request)
api.get_schema       # async def get_schema(self, request)
api.get_style        # async def get_style(self, request)
api.get_html         # async def get_html(self, request)
api.validate         # async def validate(self, request)
api.create_form      # async def create_form(self, request)
api.load_from_db     # async def load_from_db(self, request)

# FormPageHandler methods to wrap:
page.index           # async def index(self, request)
page.gallery         # async def gallery(self, request)
page.render_form     # async def render_form(self, request)
page.view_schema     # async def view_schema(self, request)
page.submit_form     # async def submit_form(self, request)

# TelegramWebAppHandler methods — do NOT wrap:
telegram.serve_webapp    # async def serve_webapp(self, request)
telegram.rest_fallback   # async def rest_fallback(self, request)
```

### Decorator Behavior (verified via inspect)

```python
# is_authenticated(content_type="application/json")
# Returns a decorator that wraps a function.
# For plain async functions: wraps directly.
# Checks request.get("authenticated", False), tries backends if not.
# Raises web.HTTPUnauthorized (401) if all backends fail.

# user_session()
# Returns a decorator that wraps a function.
# For plain async functions: injects session= and user= kwargs into the call.
# For bound methods: sets request.user, request.session.
# NOTE: since our handlers are bound methods (self, request), user_session
#   will call _method_wrapper which sets request.user and request.session.
#   BUT _apply_decorator checks inspect.isclass() — we're wrapping individual
#   bound methods, so it will use _func_wrapper which injects kwargs.
#   The handler signature must accept **kwargs or explicit session/user params,
#   OR we need to wrap differently.

# IMPORTANT: Since FormAPIHandler methods have signature (self, request),
# the decorator wraps them as plain functions. user_session's _func_wrapper
# injects session= and user= as kwargs. The handler methods don't accept these.
# SOLUTION: Create wrapper that applies is_authenticated and user_session,
# then strips the extra kwargs before calling the original handler.
```

### Does NOT Exist

- ~~`FormAPIHandler` inherits `BaseView`~~ — it is a plain class.
- ~~`FormPageHandler` inherits `BaseView`~~ — it is a plain class.
- ~~Class-level `@is_authenticated()` on plain classes auto-wraps custom methods~~ — it only wraps HTTP-method-named methods (`get`, `post`, etc.).
- ~~`navigator_auth.middleware`~~ — no standalone middleware module.

---

## Implementation Notes

### Pattern to Follow

```python
# Conditional import + wrapper pattern
try:
    from navigator_auth.decorators import is_authenticated, user_session
    _AUTH_AVAILABLE = True
except ImportError:
    _AUTH_AVAILABLE = False

def _wrap_auth(handler):
    """Wrap a handler with navigator-auth authentication.

    When navigator-auth is not installed, returns the handler unchanged.
    Applies is_authenticated + user_session, stripping injected kwargs
    that the handler doesn't expect.
    """
    if not _AUTH_AVAILABLE:
        return handler

    @wraps(handler)
    async def _wrapped(request, **kwargs):
        # user_session injects session= and user= kwargs
        # but our handlers expect just (self_is_already_bound, request)
        return await handler(request)

    # Apply decorators: outer is_authenticated checks auth first,
    # then user_session attaches user/session to request.
    _wrapped = user_session()(_wrapped)
    _wrapped = is_authenticated()(_wrapped)
    return _wrapped

# Then in setup_form_routes:
app.router.add_get(f"{p}/api/v1/forms", _wrap_auth(api.list_forms))
```

### Key Constraints

- `navigator_auth` must be imported conditionally (try/except).
- When not available, all routes work without auth (backward compatible for standalone usage).
- `TelegramWebAppHandler` routes are NEVER wrapped.
- Bound methods: `api.list_forms` is already `self`-bound, so the wrapper receives `(request)` as the first positional arg, plus any kwargs from decorators.
- The `functools.wraps` import will be needed.

### References in Codebase

- `packages/ai-parrot/src/parrot/handlers/credentials.py:69-71` — class-level decorator pattern (BaseView).
- `packages/ai-parrot/src/parrot/handlers/agent.py:45-47` — class-level decorator pattern (BaseView).
- The above are BaseView classes so class-level works for them. We need per-method wrapping.

---

## Acceptance Criteria

- [ ] `api_key` parameter removed from `setup_form_routes()`.
- [ ] All `FormAPIHandler` route handlers are wrapped with auth.
- [ ] All `FormPageHandler` route handlers are wrapped with auth.
- [ ] `TelegramWebAppHandler` routes are NOT wrapped.
- [ ] When `navigator_auth` is not installed, routes work without auth.
- [ ] No import errors: `python -c "from parrot.formdesigner.handlers.routes import setup_form_routes"`.
- [ ] File has no syntax errors.

---

## Test Specification

```python
# Tests are in TASK-582.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formdesigner-authentication.spec.md`
2. **Check dependencies** — verify TASK-580 is completed
3. **Verify the Codebase Contract** — read `routes.py` and confirm current state
4. **Test the decorator wrapping carefully** — the bound-method + kwargs interaction
   is the trickiest part. Verify by reading `user_session` source if needed.
5. **Update status** in `tasks/.index.json` → `"in-progress"`
6. **Implement** the scope above
7. **Verify** all acceptance criteria
8. **Move this file** to `tasks/completed/TASK-581-route-auth-wrappers.md`
9. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-04
**Notes**: Added conditional import of navigator_auth.decorators with try/except. Created `_wrap_auth()` helper that applies `is_authenticated()` + `user_session()` and strips injected kwargs. Wrapped all FormAPIHandler and FormPageHandler methods at route registration. TelegramWebAppHandler routes left unwrapped (public). Removed `api_key` parameter from `setup_form_routes()`.

**Deviations from spec**: none
