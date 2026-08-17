# TASK-2200: Wire `requires_tenant` into the route wrappers

**Feature**: FEAT-421 — Client-declared tenant in the forms URL
**Spec**: `sdd/specs/forms-tenant-in-url.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2199
**Assigned-to**: unassigned

---

## Context

Implements spec Module 3. `_wrap_auth` (`api/routes.py:69`) and `_page_wrap`
(`ui/routes.py:35`) already compose navigator-auth around every handler; this
task adds the tenant layer to that composition under an explicit per-route
mode, so the `/org/*` carve-out (spec G7) is a one-word argument rather than a
path test inside a global hook.

The default must be `"required"`, so a forms route added later is protected by
omission rather than exposed by omission.

---

## Scope

- `api/routes.py`: change `_wrap_auth(handler)` →
  `_wrap_auth(handler, *, tenant: str = "required")`, accepting
  `"required" | "public" | "none"`. Compose `requires_tenant` as the
  **innermost** layer (inside `user_session`, so `request.session` is already
  populated when it runs). `"none"` composes no tenant layer.
- Validate the mode: any other value raises `ValueError` at registration time.
- `ui/routes.py`: same mode parameter on `_page_wrap`.
  **Critical**: `_page_wrap` currently returns the handler *unchanged* when
  `protect=False` (`ui/routes.py:47-48`), and fieldsync runs with
  `protect_pages=False`. The tenant layer must therefore be applied **outside**
  the `protect` early-return, or UI pages get no tenant validation in the very
  deployment this feature exists for.
- Add the two router-introspection tests (see Test Specification).

**NOT in scope**: changing any route path (TASK-2201), passing `tenant="none"`
at the `/org/*` call sites (TASK-2201 owns the route table).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | MODIFY | `_wrap_auth` gains the `tenant` mode |
| `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py` | MODIFY | `_page_wrap` gains the `tenant` mode |
| `packages/parrot-formdesigner/tests/unit/api/test_wrap_auth_tenant_mode.py` | CREATE | Mode + introspection tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from functools import wraps                                  # api/routes.py (used at :82)
from aiohttp import web                                       # api/handlers.py:17
from navigator_auth.decorators import is_authenticated, user_session  # ui/routes.py:22
from .tenant import requires_tenant                           # created by TASK-2199
```

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:66
_Handler = Callable[[web.Request], Awaitable[web.Response]]

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py:69-91
def _wrap_auth(handler: _Handler) -> _Handler:
    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        return await handler(request)                                        # :87
    decorated = user_session()(_inner)                                       # :89
    decorated = is_authenticated(content_type="application/json")(decorated) # :90
    return decorated

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py:35-60
def _page_wrap(handler: _Handler, *, protect: bool) -> _Handler:
    if not protect:
        return handler                    # <-- lines 47-48, THE GOTCHA
    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        return await handler(request)
    decorated = user_session()(_inner)
    decorated = is_authenticated(content_type="text/html")(decorated)  # text/html, not json
    return decorated

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py:61
def setup_form_ui(...)   # `protect_pages` flows in here; fieldsync passes False
```

Note the content-type difference: `api/routes.py` uses
`content_type="application/json"`, `ui/routes.py` uses `"text/html"` so
browsers render auth failures. Preserve both.

### Does NOT Exist

- ~~a sub-application for forms~~ — `setup_form_api` calls `app.router.add_*`
  on the root router (`api/routes.py:207+`). There is nothing to attach a
  scoped middleware to; the decorator is the only correctly-scoped mechanism.
- ~~`app.middlewares.append(...)` anywhere in the package~~ — and this task
  must not add one. Spec AC2.
- ~~a `tenant` kwarg on `_wrap_auth` today~~ — it takes exactly one positional
  argument (`api/routes.py:69`). All ~40 existing call sites pass one argument,
  so a keyword-only parameter with a default is backwards-compatible at the
  call site and no caller needs editing in this task.
- ~~`web.RouteDef.handler.__wrapped__` guaranteed~~ — verify how you detect the
  decorator before writing the introspection test; prefer tagging the wrapper
  with an explicit attribute (e.g. `_inner._requires_tenant = True`) over
  relying on `__wrapped__` chains through navigator-auth's decorators.

---

## Implementation Notes

### Pattern to Follow

```python
_TENANT_MODES = ("required", "public", "none")


def _wrap_auth(handler: _Handler, *, tenant: str = "required") -> _Handler:
    if tenant not in _TENANT_MODES:
        raise ValueError(f"tenant must be one of {_TENANT_MODES}, got {tenant!r}")

    if tenant != "none":
        handler = requires_tenant(public=(tenant == "public"))(handler)

    @wraps(handler)
    async def _inner(request: web.Request, **kwargs) -> web.Response:
        return await handler(request)

    decorated = user_session()(_inner)
    decorated = is_authenticated(content_type="application/json")(decorated)
    return decorated
```

Ordering matters: wrapping `handler` *before* `_inner` puts `requires_tenant`
inside `user_session`, so `request.session` is populated by the time it runs.

### Key Constraints

- Keyword-only (`*, tenant=...`) so the ~40 existing single-argument call sites
  keep working untouched in this task.
- Tag the produced wrapper so the introspection tests can assert coverage
  without depending on navigator-auth internals.
- In `ui/routes.py`, apply the tenant layer before the `if not protect: return`
  early-return. Add a regression test for `protect=False`.
- Raise `ValueError` eagerly at registration (import/setup time), not per
  request — a typo'd mode should fail the app boot, loudly.

### References in Codebase

- `api/routes.py:69-91`, `ui/routes.py:35-60` — the two wrappers.
- `api/routes.py:207-360` — the route table TASK-2201 rewrites using this mode.

---

## Acceptance Criteria

- [ ] `_wrap_auth(h)` (no kwarg) applies `requires_tenant(public=False)`
- [ ] `_wrap_auth(h, tenant="public")` applies `requires_tenant(public=True)`
- [ ] `_wrap_auth(h, tenant="none")` applies no tenant layer
- [ ] `_wrap_auth(h, tenant="bogus")` raises `ValueError` at call time
- [ ] `_page_wrap(h, protect=False, tenant="required")` STILL applies the tenant layer
- [ ] `ui/routes.py` keeps `content_type="text/html"`; `api/routes.py` keeps `"application/json"`
- [ ] `grep -rn "middlewares.append\|@web.middleware" packages/parrot-formdesigner/src` returns nothing
- [ ] Existing suite still green: `pytest packages/parrot-formdesigner/tests/unit/api/ -v`
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/`

---

## Test Specification

```python
import pytest
from parrot_formdesigner.api.routes import _wrap_auth
from parrot_formdesigner.ui.routes import _page_wrap


async def _handler(request):
    return "ok"


class TestWrapAuthTenantMode:
    def test_defaults_to_required(self):
        """Silence must protect, not expose."""
        wrapped = _wrap_auth(_handler)
        assert _has_tenant_layer(wrapped) is True

    def test_public_mode_applies_layer(self):
        assert _has_tenant_layer(_wrap_auth(_handler, tenant="public")) is True

    def test_none_mode_skips_layer(self):
        assert _has_tenant_layer(_wrap_auth(_handler, tenant="none")) is False

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="tenant must be one of"):
            _wrap_auth(_handler, tenant="bogus")


class TestPageWrapTenantMode:
    def test_unprotected_page_still_gets_tenant_layer(self):
        """fieldsync runs protect_pages=False — the early return must not
        skip tenant validation (ui/routes.py:47-48)."""
        wrapped = _page_wrap(_handler, protect=False, tenant="required")
        assert _has_tenant_layer(wrapped) is True
```

`_has_tenant_layer` is a test helper reading the marker attribute set in
`requires_tenant`; the same helper backs the router-wide coverage tests
`test_every_forms_route_is_decorated` / `test_no_org_route_is_decorated`
delivered in TASK-2201.

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/forms-tenant-in-url.spec.md` (§2 point 2, Module 3)
2. **Check dependencies** — TASK-2199 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/forms-tenant-in-url.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2200-wire-tenant-decorator-route-wrappers.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-08-16
**Notes**: `_wrap_auth` gained `*, tenant: str = "required"` composing
`requires_tenant` as the innermost layer (before `_inner` wraps it), with
`ValueError` raised eagerly for invalid modes. `_page_wrap` gained the same
mode parameter, applying the tenant layer BEFORE the `protect=False`
early-return so fieldsync's `protect_pages=False` deployment still gets
tenant validation. Marker attribute `_requires_tenant` is set (only when
`True`, never force-set `False`) on the final composed handler so tests can
introspect coverage without depending on navigator-auth's decorator
internals — this also sidesteps `AttributeError` on bound methods when
`tenant="none"` and `protect=False` combine (no production call site hits
that combination today, but it's guarded regardless). Verified via ruff
diff-count that no NEW lint errors were introduced in either file (both
carry pre-existing, unrelated lint debt from before this feature). Full
`tests/unit/api/` suite: 93 passed, 1 pre-existing unrelated failure
(`test_form_controls_endpoint.py`, controls payload shape — not touched by
this feature). AC grep for `middlewares.append`/`@web.middleware` returns
nothing.

**Deviations from spec**: none
