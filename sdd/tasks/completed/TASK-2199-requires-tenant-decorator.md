# TASK-2199: `requires_tenant` decorator and tenant helpers

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2198
**Assigned-to**: unassigned

---

## Context

Implements spec Module 1 — the single enforcement point for the whole feature.
This is what replaces PR #1149's `forms_tenant_context_middleware`: same
authorization rule, but as a per-route decorator that ships inside the wheel
instead of a middleware living in an `app.py` the PyPI package never installs.

A decorator is attached to specific handlers at registration time, so it is
structurally incapable of observing a non-forms request — which matters because
`setup_form_api` mounts on the **root** router (`api/routes.py:207+`), not a
sub-application, so no middleware could ever be forms-scoped here.

---

## Scope

- Create `api/tenant.py` with:
  - `requires_tenant(*, public: bool = False)` — decorator factory.
  - `declared_tenant(request) -> str` — read the validated value.
  - `assert_body_tenant_matches(body: dict, tenant: str) -> None`.
- Decorator behaviour, in order:
  1. Read `request.match_info.get("tenant")`. Missing or empty/whitespace →
     raise `TenantNotDeclaredError`.
  2. If `public=False`: authorize against the navigator-auth session —
     membership in `session["session"]["programs"]`, or a truthy
     `session["session"]["superuser"]`. Otherwise raise `TenantForbiddenError`.
     When `public=True`, skip this step entirely.
  3. Stash the validated value under the `request` key `"tenant"` and await
     the wrapped handler.
- `declared_tenant` raises `RuntimeError` when the key is absent — that state
  can only mean a forms route was mounted without the decorator, which is a
  programming error, never a runtime fallback.
- Write the full unit matrix (see Test Specification).

**NOT in scope**: applying the decorator to any route (TASK-2200), rewriting
the route table (TASK-2201), touching `handlers.py` (TASK-2202).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py` | CREATE | Decorator + helpers |
| `packages/parrot-formdesigner/tests/unit/api/test_requires_tenant.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from functools import wraps       # verified: api/routes.py imports `wraps` (used at :82)
from aiohttp import web           # verified: api/handlers.py:17
from .errors import (             # created by TASK-2198
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:66
_Handler = Callable[[web.Request], Awaitable[web.Response]]

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:69-91
def _wrap_auth(handler: _Handler) -> _Handler:
    @wraps(handler)                                    # line 82
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        return await handler(request)                  # line 87
    decorated = user_session()(_inner)                 # line 89
    decorated = is_authenticated(content_type="application/json")(decorated)  # line 90
    return decorated
# ^ COPY THIS SHAPE. Note `**kwargs` on _inner: navigator-auth's user_session
#   injects session= and user= kwargs that handlers do not accept.

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py:235-254
def _get_programs(self, request: web.Request) -> list[str]:
    session = getattr(request, "session", None)
    if session is None:
        return []
    userinfo = session.get("session", {})
    return userinfo.get("programs", [])
# ^ THE EXACT session read to reuse. The outer "session" key is navigator-auth's
#   AUTH_SESSION_OBJECT constant. `programs` is a list of plain slug strings.
```

The superuser flag is read from the same `userinfo` dict as
`userinfo.get("superuser", False)` — this is the shape PR #1149's middleware
used and it is the shape to keep.

### Does NOT Exist

- ~~`request["tenant_context"]`~~ — being removed by this feature. Do NOT read
  or write it. Its only readers are `api/_utils.py:50` and
  `api/handlers.py:280`, both deleted/replaced in TASK-2202/2203.
- ~~`request.query.get("program_slug")`~~ — PR #1149's query-string approach.
  Explicitly forbidden by spec AC3. The tenant comes from `match_info` only.
- ~~`FormRegistry.default_tenant` as a fallback here~~ — the decorator must
  never reach for it. Missing tenant is a 400, full stop.
- ~~`request.session` guaranteed present~~ — it is `None` for anonymous
  requests; `getattr(request, "session", None)` is the safe read (see
  `handlers.py:250-251`).
- ~~an `is_superuser` helper on `FormAPIHandler`~~ — not a method. Read the
  flag from `userinfo` directly.

---

## Implementation Notes

### Pattern to Follow

```python
def requires_tenant(*, public: bool = False) -> Callable[[_Handler], _Handler]:
    def _decorator(handler: _Handler) -> _Handler:
        @wraps(handler)
        async def _inner(request: web.Request, **kwargs) -> web.Response:
            tenant = (request.match_info.get("tenant") or "").strip()
            if not tenant:
                raise TenantNotDeclaredError(expected=...)
            if not public:
                _authorize(request, tenant)          # raises TenantForbiddenError
            request["tenant"] = tenant
            return await handler(request)
        return _inner
    return _decorator
```

### Key Constraints

- `@wraps` is mandatory — TASK-2200's router-introspection test
  (`test_every_forms_route_is_decorated`) relies on wrapper identity being
  traceable, and aiohttp logs handler names.
- Accept and discard `**kwargs` exactly as `_wrap_auth._inner` does — this
  decorator sits *inside* `user_session()`, which injects `session=`/`user=`.
- The decorator is sync-returning-async; do NOT make the factory itself async.
- `assert_body_tenant_matches(body, tenant)` raises `TenantConflictError` only
  when `body` contains a truthy `"tenant"` that differs. A missing key is fine —
  the body tenant is an optional cross-check, never required (spec §2).
- Log at `WARNING` on a rejected authorization, including the declared tenant
  and the session's programmes — this is the audit trail for cross-tenant
  probing.

### References in Codebase

- `api/routes.py:69-91` — the wrapper shape to mirror.
- `api/handlers.py:235-254` — the session read.
- PR #1149 `tests/test_forms_tenant_context_middleware.py` — the same case
  matrix (member / superuser / non-member / no-slug / no-session /
  empty-programs); reuse it, retargeted at `match_info`.

---

## Acceptance Criteria

- [ ] `from parrot_formdesigner.api.tenant import requires_tenant, declared_tenant, assert_body_tenant_matches` works
- [ ] Missing / empty / whitespace-only tenant segment → 400 `tenant_not_declared`
- [ ] Non-member → 403 `tenant_forbidden`; member → passes; superuser → passes for any tenant
- [ ] `public=True` skips authorization but still enforces the 400
- [ ] `declared_tenant` raises `RuntimeError` when the decorator did not run
- [ ] `assert_body_tenant_matches` raises on mismatch, passes on match, passes on absent key
- [ ] No reference to `tenant_context`, `program_slug`, or `default_tenant` in the new file
- [ ] All tests pass: `pytest packages/parrot-formdesigner/tests/unit/api/test_requires_tenant.py -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py`

---

## Test Specification

```python
import pytest
from parrot_formdesigner.api.errors import (
    TenantConflictError, TenantForbiddenError, TenantNotDeclaredError,
)
from parrot_formdesigner.api.tenant import (
    assert_body_tenant_matches, declared_tenant, requires_tenant,
)


def make_request(tenant=None, programs=None, superuser=False, with_session=True):
    """Minimal stub exposing .match_info, .session and __setitem__."""
    ...


class TestRequiresTenant:
    async def test_passes_declared_tenant(self):
        req = make_request(tenant="flexroc", programs=["flexroc"])
        seen = {}

        @requires_tenant()
        async def handler(request):
            seen["t"] = declared_tenant(request)
            return "ok"

        assert await handler(req) == "ok"
        assert seen["t"] == "flexroc"

    @pytest.mark.parametrize("value", [None, "", "   "])
    async def test_400_when_not_declared(self, value):
        req = make_request(tenant=value, programs=["flexroc"])

        @requires_tenant()
        async def handler(request):
            return "ok"

        with pytest.raises(TenantNotDeclaredError):
            await handler(req)

    async def test_403_non_member(self):
        req = make_request(tenant="flexroc", programs=["navigator"])
        ...  # expect TenantForbiddenError

    async def test_allows_superuser(self):
        req = make_request(tenant="anything", programs=[], superuser=True)
        ...  # expect pass

    async def test_403_no_session(self):
        req = make_request(tenant="flexroc", with_session=False)
        ...  # expect TenantForbiddenError

    async def test_public_skips_authorization(self):
        req = make_request(tenant="flexroc", with_session=False)

        @requires_tenant(public=True)
        async def handler(request):
            return "ok"

        assert await handler(req) == "ok"

    async def test_public_still_requires_tenant(self):
        req = make_request(tenant=None, with_session=False)
        ...  # expect TenantNotDeclaredError


class TestDeclaredTenant:
    def test_raises_without_decorator(self):
        with pytest.raises(RuntimeError):
            declared_tenant(make_request(tenant="flexroc"))


class TestBodyCrossCheck:
    def test_match_ok(self):
        assert_body_tenant_matches({"tenant": "flexroc"}, "flexroc")

    def test_absent_ok(self):
        assert_body_tenant_matches({"title": "x"}, "flexroc")

    def test_conflict_raises(self):
        with pytest.raises(TenantConflictError):
            assert_body_tenant_matches({"tenant": "navigator"}, "flexroc")
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (§2 point 2)
2. **Check dependencies** — TASK-2198 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2199-requires-tenant-decorator.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: Created `api/tenant.py` with `requires_tenant(*, public=False)`,
`declared_tenant(request)`, and `assert_body_tenant_matches(body, tenant)`,
mirroring `_wrap_auth`'s `@wraps` + `**kwargs`-swallowing shape and reusing
`FormAPIHandler._get_programs`'s exact session read. Superuser flag read
from the same `userinfo` dict as `programs`. Authorization rejection logs
at WARNING with the declared tenant and session programs. 14 unit tests
cover the full case matrix from the spec (member/superuser/non-member/
no-session/empty-tenant/public carve-out/body cross-check) plus a source
guard asserting no reference to `tenant_context`, `program_slug`, or
`default_tenant`. Pre-existing unrelated failure noted in
`test_form_controls_endpoint.py::test_form_controls_payload_shape` (out of
scope — controls endpoint, not touched by this feature).

**Deviations from spec**: none
