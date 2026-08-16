---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Client-declared tenant in the forms URL

**Feature ID**: FEAT-TBD *(pending `scripts/sdd/reserve_ids.py` — see §8)*
**Date**: 2026-08-16
**Author**: Jesus Lara + Claude
**Status**: draft
**Target version**: parrot-formdesigner 0.9.0 (major, breaking)

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot-formdesigner` never requires the caller to say which tenant a request
is about. It **infers** one, through an unconditional fallback chain
(`api/handlers.py:280-286`):

```
request["tenant_context"]  →  session["session"]["programs"][0]  →  registry.default_tenant
```

Step 2 is the defect. `programs[0]` is "the first programme that happened to
be in the session list" — a user who belongs to eleven programmes belongs to
all eleven, and the ordering states nothing about which one this request
concerns. Step 3 is worse: it silently lands the write in `default_tenant`
(`"navigator"`, `services/registry.py:199`).

Observed consequence: AI-created and AI-edited forms are written under
`navigator` instead of the browsed programme, then 404 on load/save
(NAV-9372 create, NAV-9370 edit/save).

Two PRs attempted a fix and both are rejected as designed:

- **#1146 (merged)** added resolution step 0 — `request["tenant_context"]`,
  "a tenant the HOST resolved, authorized and declared". This shipped a
  contract with **consumers but no producer**: a repo-wide grep finds only
  readers (`api/_utils.py:50`, `api/handlers.py:280`) and no writer anywhere
  in the distribution.
- **#1149 (open)** supplies the producer as `forms_tenant_context_middleware`
  in the repository's `app.py`. **`app.py` is not installed by the PyPI
  wheel**, so the fix reaches no client. The PR's own *Out of scope* section
  concedes this: *"NAV-9329 is served by a different host (fieldsync
  `apps/formtypes`) — equivalent fix needed there separately."* A
  security-sensitive cross-tenant authorization check that every host must
  copy-paste is a distribution defect, not an implementation detail.

Beyond distribution, the middleware is the wrong *mechanism*: aiohttp
middlewares are per-`Application`, and `setup_form_api` mounts its routes on
the **root** router rather than a sub-application (`api/routes.py:207+`), so
any middleware necessarily runs for every request in the host — agents, A2A,
MCP, WebSockets and static assets included — to serve a forms-only concern.

The correct split is: **the client declares which tenant it is operating
against; the backend enforces that the declaration is legitimate; nobody
guesses.**

### Goals

- **G1** — The tenant is declared explicitly by the client, in the URL path,
  on every **forms** route.
- **G2** — Declaration is validated and authorized by a **per-route decorator**
  owned by `parrot-formdesigner`, composed at route-registration time. **No
  aiohttp middleware** is introduced or retained: the enforcement point is
  attached to forms handlers only, never to the host's request pipeline.
- **G3** — No declared tenant on a forms route ⇒ **HTTP 400**. The
  `default_tenant` fallback is removed from the forms HTTP boundary entirely.
- **G4** — Zero host wiring. Installing the wheel is sufficient; neither
  `fieldsync` nor `navigator` edits an `app.py` to get correct scoping.
- **G5** — No query-string carries the tenant, on any verb.
- **G6** — A form reachable under one tenant is never reachable by declaring
  another.
- **G7** — The `/org/*` surface is **untouched**. Organizations are the
  foundational layer that *defines* tenants; scoping them *by* a tenant would
  invert the dependency.

### Non-Goals (explicitly out of scope)

- **Tenant-scoping the `/org/*` routes.** Resolved decision, see §8. They keep
  their current URLs and their current tenant behaviour. This spec touches
  exactly zero `/org/*` semantics.
- Removing `FormRegistry.default_tenant` as a constructor parameter. It stays
  for non-HTTP entry points (`load_from_directory`, boot hydration) where no
  request exists to declare a tenant. Only the **forms HTTP boundary** stops
  using it.
- Changing `require_tenant`. Analysis (§7) shows it is inert on the REST path.
- A tenant-backfill migration for forms already stored under `navigator`
  (tracked separately as FEAT-466).
- Retro-fitting `request["tenant_context"]`. Step 0 is removed, not extended.
- Host-supplied entitlement plugins (`tenant_authorizer=`). Rejected during
  design — it reproduces #1149's "each host must wire it" failure mode.
- Fixing the `organizations[0]` / `programs[0]` arbitrary-index pattern that
  survives inside `/org/*`. See §7 "Residual" — it deserves its own ticket.

---

## 2. Architectural Design

### Overview

Three changes, in order of consequence:

**1. The tenant becomes a URL path segment on forms routes, behind a literal
`t` marker.**

```
/api/v1/t/{tenant}/forms
/api/v1/t/{tenant}/forms/{form_uid}
/api/v1/t/{tenant}/forms/{form_uid}/render/{format}
/api/v1/t/{tenant}/fields                     # question bank — part of forms

# UNCHANGED — organizations define tenants, they are not scoped by one:
/api/v1/org/graph
/api/v1/org/projects
/api/v1/org/stores/{store_id}/sites
/api/v1/org/sites/{site_id}/locations
/api/v1/org/locations/{location_id}
/api/v1/org/users/{user_id}/assign
/api/v1/org/sync/workday
```

The literal `t` segment exists to remove router ambiguity. Without it,
`/api/v1/forms/{tenant}` and `/api/v1/forms/{form_uid}` are the same shape —
one path segment — and aiohttp would have to disambiguate by UUID-parsing the
segment, with reserved literals (`blank`, `from-db`) as special cases. `t/`
makes the grammar unambiguous by construction. It also keeps the forms
namespace and the `org` namespace visibly disjoint.

`form_uid` is a globally unique UUID (`services/registry.py:858`), so the
tenant segment is **not** a lookup key. It is a *declaration*, and its value
is that it can be **cross-checked**: if `{form_uid}` resolves to a form whose
tenant differs from `{tenant}`, the response is **404**, not 403 — a 403 would
confirm the form exists in some other tenant, which is an existence oracle.

**2. Enforcement is a decorator, composed into the existing route wrapper.**

`api/routes.py` already wraps every route with `_wrap_auth`
(`api/routes.py:69-91`), which composes navigator-auth's `is_authenticated` +
`user_session`. That is the seam. A new `@requires_tenant` decorator is
composed into it, under an explicit per-route mode:

```python
def _wrap_auth(handler, *, tenant: str = "required"):
    # tenant="required" → forms routes: declare + authorize
    # tenant="public"   → public-form routes: declare, skip authorization
    # tenant="none"     → /org/* routes: decorator not applied at all
    if tenant != "none":
        handler = requires_tenant(public=(tenant == "public"))(handler)
    decorated = user_session()(_consume_kwargs(handler))
    decorated = is_authenticated(content_type="application/json")(decorated)
    return decorated
```

The default is `"required"`, so a newly added forms route is protected unless
someone opts out deliberately. The nine `/org/*` routes pass `tenant="none"`.

When applied, the decorator runs **after** `user_session` has populated
`request.session` and **before** the handler body. It:

1. reads `request.match_info["tenant"]` → **400 `tenant_not_declared`** if
   absent or empty;
2. authorizes it against the navigator-auth session — membership in
   `session["session"]["programs"]`, or `superuser` — → **403
   `tenant_forbidden`** (skipped when `public=True`);
3. stashes the validated value and calls the handler.

Why a decorator and not a middleware: a decorator is attached to *specific
handlers at registration time*, so it is structurally impossible for it to
observe a non-forms request — and the `/org/*` carve-out becomes a one-word
argument rather than a path-prefix test inside a global hook. It ships inside
the wheel, so no host edits anything (G4).

**3. The forms fallback chain is deleted; `/org/*` keeps its own resolver.**

`FormAPIHandler._get_tenant` (`api/handlers.py:256`) keeps its name and
signature — `(self, request) -> str` — so the **21 forms call sites are
untouched**. Its *body* becomes a read of the value the decorator already
validated, raising `RuntimeError` if it is missing (which can only mean a
forms route was mounted without the decorator — a programming error, caught by
AC2's test, not a runtime fallback).

The **9 `/org/*` call sites** switch to a new, explicitly-named
`_session_tenant(request)` that preserves today's session-derived behaviour
verbatim. Renaming rather than sharing is the point: it makes the surviving
inference greppable and impossible to reach from a forms handler by accident.

#### Public forms — the one authorization carve-out

A form with `is_public=True` is served without a session
(`services/public_forms.py:6-41` registers auth-exempt paths). Such a request
has no `programs` to check against, so step 2 **must not** run for it —
`tenant="public"`.

| | tenant declared? | authorized? |
|---|---|---|
| Forms route (authenticated) | required (400 if absent) | required (403 if not a member) |
| Public form route | required (400 if absent) | skipped — the form's `is_public` flag *is* the grant |
| `/org/*` route | not applicable | unchanged (session `org_id`, already 400s when absent) |

The tenant stays mandatory on public routes: it is what makes
`public_form_paths` derivable and keeps G6 intact.

### Component Diagram

```
client
  │  GET /api/v1/t/flexroc/forms/{uid}          │  GET /api/v1/org/graph
  ▼                                              ▼
aiohttp root router     ← NO middleware added to the host pipeline
  │                                              │
  ▼                                              ▼
_wrap_auth(h, tenant="required")            _wrap_auth(h, tenant="none")
  ├─ is_authenticated   (unchanged)           ├─ is_authenticated  (unchanged)
  ├─ user_session       (unchanged)           └─ user_session      (unchanged)
  └─ requires_tenant    ── NEW                     (no tenant decorator)
        ├─ match_info["tenant"]  ─ 400              │
        ├─ authorize vs session  ─ 403              │
        └─ stash validated tenant                   │
  │                                                 ▼
  ▼                                        FormAPIHandler.get_org_graph()
FormAPIHandler.get_form(request)             ├─ _get_org_id()      ─ 400 (existing)
  ├─ self._get_tenant(request)  ← validated  └─ self._session_tenant(request)
  ├─ registry.get(uid, tenant=t)                     ↑ legacy path, preserved
  └─ _assert_form_tenant(form, t)  ─ 404
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `_wrap_auth` (`api/routes.py:69`) | **composes** | gains `tenant="required"\|"public"\|"none"` |
| `requires_tenant` | new | the single enforcement point (Module 1) |
| `FormAPIHandler._get_tenant` (`api/handlers.py:256`) | body replaced | **signature preserved ⇒ 21 forms call sites untouched** |
| `FormAPIHandler._session_tenant` | new | legacy session-derived resolver for the 9 `/org/*` sites |
| `FormAPIHandler._get_org_id` (`api/handlers.py:207`) | **unchanged** | `/org/*` identity; already 400s when absent |
| `_get_request_tenant` (`api/_utils.py:16`) | replaces | module-level twin; 4 call sites (`operations.py:551`, `render.py:131`, `uploads.py:247`, `ui/telegram.py:80,122`) — all forms |
| `setup_form_api` (`api/routes.py:94`) | modifies | forms routes re-prefixed; `/org/*` routes keep their paths |
| `setup_form_ui` (`ui/routes.py:61`) | modifies | `_page_wrap` (`ui/routes.py:35`) gains the same decorator |
| `public_form_paths` (`services/public_forms.py:6`) | modifies | signature gains `tenant`; patterns become tenant-qualified |
| `AudioFormWSHandler` | modifies | not `_wrap_auth`-ed; needs the check inline (see §7) |
| `FormRegistry` (`services/registry.py:194`) | unchanged | already tenant-keyed; `tenant=` kwargs exist on every method |
| `app.py` | **reverted** | `forms_tenant_context_middleware` (#1149) deleted |

### Data Models

```python
# api/errors.py  (new)
class TenantNotDeclaredError(web.HTTPBadRequest):
    """400 — the request carried no tenant segment."""

class TenantForbiddenError(web.HTTPForbidden):
    """403 — the caller is not entitled to the declared tenant."""

class TenantConflictError(web.HTTPBadRequest):
    """400 — the body declared a tenant differing from the URL."""
```

Error body shape (stable contract for `navigator-svelte`):

```json
{
  "error": "tenant_not_declared",
  "message": "This endpoint requires an explicit tenant.",
  "expected": "/api/v1/t/{tenant}/forms/{form_uid}"
}
```

### New Public Interfaces

```python
# api/tenant.py  (new)
def requires_tenant(*, public: bool = False) -> Callable[[_Handler], _Handler]:
    """Decorator: validate + authorize the URL-declared tenant.

    Applied at route-registration time to forms handlers only. Never
    registered as an aiohttp middleware.
    """

def declared_tenant(request: "web.Request") -> str:
    """Return the tenant validated by `requires_tenant` for this request."""

def assert_body_tenant_matches(body: dict, tenant: str) -> None:
    """Raise 400 when a POST/PUT/PATCH body declares a conflicting tenant."""

# services/public_forms.py
def public_form_paths(
    form_uid: str, tenant: str, base_path: str = "/api/v1"
) -> list[str]: ...
```

### Tenant in POST bodies (MUST-DO #3)

The URL is **authoritative on every verb, including POST** — confirmed
decision, see §8. For POST/PUT/PATCH the body **may** additionally carry
`"tenant"`; when present it must equal the URL segment, otherwise **400
`tenant_conflict`**. It is a cross-check, never an override and never a
substitute.

Rationale: one rule for all verbs keeps `public_form_paths`, the auth
exclusion globs, and access logs derivable from the URL alone. A
body-authoritative tenant would be invisible to the router, to navigator-auth's
exclusion matcher, and to every access log line. This reverses #1146's
"`body.tenant` deliberately NOT honored" only in the weak sense: the body value
is now *validated*, still never *trusted*.

---

## 3. Module Breakdown

### Module 1: `requires_tenant` decorator
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py` (new)
- **Responsibility**: `requires_tenant(public=False)`, `declared_tenant`,
  `assert_body_tenant_matches`. Uses `functools.wraps`, mirroring the existing
  `_wrap_auth` style (`api/routes.py:82`). Session read follows
  `FormAPIHandler._get_programs` (`api/handlers.py:235-254`).
- **Depends on**: Module 2.

### Module 2: Typed error responses
- **Path**: `.../api/errors.py` (new)
- **Responsibility**: `TenantNotDeclaredError`, `TenantForbiddenError`,
  `TenantConflictError`, each rendering the stable JSON body above.
- **Depends on**: nothing.

### Module 3: Wire the decorator into route wrappers
- **Path**: `.../api/routes.py` (`_wrap_auth`, `:69`), `.../ui/routes.py`
  (`_page_wrap`, `:35`)
- **Responsibility**: add the `tenant="required"|"public"|"none"` mode and
  compose `requires_tenant` accordingly. Default `"required"` so new forms
  routes are protected by omission.
- **Depends on**: Module 1.

### Module 4: Forms route table rewrite
- **Path**: `.../api/routes.py:204-360`, `.../ui/routes.py:91-118`
- **Responsibility**: mount every **forms** route under `{bp}/t/{{tenant}}/...`
  Old forms paths are **not** registered (hard cut). The nine `/org/*` routes
  keep their exact current paths and are registered with `tenant="none"`.
  Preserve the deliberate ordering of `POST /forms/blank` before the
  `{form_uid}` catch-all (`api/routes.py:211-214`).
- **Depends on**: Module 3.

### Module 5: `_get_tenant` body swap + `_session_tenant` split
- **Path**: `.../api/handlers.py`
- **Responsibility**:
  - Replace the body of `_get_tenant` (`:256`) with a read of the
    decorator-validated value — **signature preserved, 21 forms call sites
    untouched**.
  - Add `_session_tenant(request)` carrying today's session-derived logic and
    repoint the **9 `/org/*` call sites** to it (mechanical rename).
  - Add `_assert_form_tenant` after every `registry.get` / `get_by_slug`.
  - Add the body cross-check to the write verbs (`register` sites
    `:953, :1202, :1267`).
- **Depends on**: Modules 1, 4.

### Module 6: Module-level handler migration
- **Path**: `.../api/operations.py:551`, `.../api/render.py:131`,
  `.../api/uploads.py:247`, `.../api/_utils.py:16`
- **Responsibility**: swap `_get_request_tenant` for `declared_tenant`; delete
  `_get_request_tenant` and its three-step fallback. All four are forms paths.
- **Depends on**: Modules 1, 4.

### Module 7: Public-form path derivation
- **Path**: `.../services/public_forms.py` + the `_public_toggle` closure in
  `api/routes.py`
- **Responsibility**: `public_form_paths(form_uid, tenant, base_path)` emits
  tenant-qualified globs; the registry toggle callback must supply the form's
  tenant. **Regression risk**: a stale unqualified glob silently makes a public
  form unreachable, or leaves a stale exemption registered.
- **Depends on**: Module 4.

### Module 8: Telegram + audio WS surface
- **Path**: `.../ui/telegram.py:24,80,122`, `.../api/audio_ws.py`
- **Responsibility**: `ui/telegram.py` carries its **own copy** of
  `_get_request_tenant` (`:24`) — delete it and use `declared_tenant`. The
  audio WS route is not `_wrap_auth`-ed (JWT is validated inside the handler
  because navigator-auth returns 401, breaking the WS upgrade), so its tenant
  check is inline rather than decorated.
- **Depends on**: Modules 1, 4.

### Module 9: `app.py` revert
- **Path**: `app.py`
- **Responsibility**: delete `forms_tenant_context_middleware` and its
  registration. Proves G4 — the repo's own host needs no tenant wiring.
- **Depends on**: Module 4.

### Module 10: Version bump + migration guide
- **Path**: `.../version.py` (`0.8.21` → `0.9.0`),
  `docs/migration/feat-<id>-forms-tenant-in-url.md`
- **Responsibility**: full old→new URL mapping table for `navigator-svelte` and
  `fieldsync`, stating explicitly that **`/org/*` URLs do not change**;
  coordinated-deploy checklist.
- **Depends on**: Modules 4, 8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_decorator_passes_declared_tenant` | 1 | Declared segment reaches the handler |
| `test_decorator_400_when_absent` | 1 | No `tenant` match info → 400 `tenant_not_declared` |
| `test_decorator_400_when_empty` | 1 | `/t//forms` → 400, not a silent empty tenant |
| `test_decorator_allows_member` | 1 | `programs=["flexroc"]`, declared `flexroc` → passes |
| `test_decorator_allows_superuser` | 1 | `superuser=True`, any declared tenant → passes |
| `test_decorator_403_non_member` | 1 | `programs=["navigator"]`, declared `flexroc` → 403 |
| `test_decorator_403_no_session` | 1 | Anonymous on an authenticated forms route → 403 |
| `test_decorator_public_skips_authorization` | 1 | `public=True`, no session → passes |
| `test_decorator_public_still_requires_tenant` | 1 | `public=True`, no segment → 400 |
| `test_wrap_auth_none_skips_decorator` | 3 | `tenant="none"` composes no tenant layer |
| `test_wrap_auth_defaults_to_required` | 3 | Omitting the flag protects the route |
| `test_get_tenant_raises_without_decorator` | 5 | Undecorated forms route → `RuntimeError`, never a default |
| `test_session_tenant_preserves_legacy` | 5 | `_session_tenant` returns exactly what `_get_tenant` returned pre-change |
| `test_no_default_tenant_fallback_on_forms` | 5 | `registry.default_tenant` unreachable from a forms request |
| `test_body_tenant_match_ok` | 1 | Body `tenant` equal to URL → accepted |
| `test_body_tenant_conflict_400` | 1 | Body `tenant` ≠ URL → 400 `tenant_conflict` |
| `test_cross_tenant_form_returns_404` | 5 | Form of tenant A, declared B → 404 (not 403) |
| `test_public_form_paths_tenant_qualified` | 7 | Globs contain `/t/{tenant}/` |
| `test_every_forms_route_is_decorated` | 3 | Introspect the router: no forms route lacks `requires_tenant` |
| `test_no_org_route_is_decorated` | 3 | Introspect the router: no `/org/*` route carries it (G7) |

### Integration Tests

| Test | Description |
|---|---|
| `test_create_then_get_same_tenant` | POST under `t/flexroc` → GET under `t/flexroc` → 200 (the NAV-9372 regression) |
| `test_edit_persists_under_declared_tenant` | PUT under `t/flexroc` writes to `flexroc`, never `navigator` (NAV-9370) |
| `test_multi_program_user_no_programs0_leak` | User with `programs=["navigator","flexroc"]` declaring `flexroc` never touches `navigator` |
| `test_legacy_forms_url_is_404` | `GET /api/v1/forms/{uid}` → 404 (hard cut) |
| `test_org_urls_unchanged` | All nine `/org/*` endpoints respond exactly as on 0.8.21 — the G7 regression net |
| `test_public_form_end_to_end_unauthenticated` | Render + submit a public form with no session |
| `test_audio_ws_tenant_scoped` | WS upgrade under `t/{tenant}` resolves the right form |

### Test Data / Fixtures

```python
@pytest.fixture
def session_programs():
    """Build a request whose navigator-auth session declares `programs`."""

@pytest.fixture
def two_tenant_registry():
    """FormRegistry pre-loaded with the same-slug form under two tenants."""
```

**Migration load**: **26** test files under
`packages/parrot-formdesigner/tests/` reference form URL paths (**17** of them
match `api/v1/forms` specifically). All must move to the new shape. Tests that
exercise `/org/*` must **not** change — an `/org/*` test diff is a red flag
that G7 was violated.

---

## 5. Acceptance Criteria

- [ ] **AC1** — Every **forms** route is mounted under `{base_path}/t/{tenant}/`.
- [ ] **AC2** — No aiohttp middleware is used for tenant resolution:
      `grep -rn "@web.middleware\|middlewares.append" app.py packages/parrot-formdesigner/src`
      returns no tenant-related hit, and `test_every_forms_route_is_decorated`
      proves each forms route carries `requires_tenant`.
- [ ] **AC3** — `grep -rn "query.get(\"tenant\|query.get(\"program_slug" packages/parrot-formdesigner/src`
      returns nothing: the tenant never travels in a query string.
- [ ] **AC4** — A forms request without a declared tenant returns **400** with
      `error: "tenant_not_declared"`. No forms HTTP path reaches
      `registry.default_tenant`.
- [ ] **AC5** — A caller declaring a tenant they are not a member of receives
      **403**; a superuser is exempt.
- [ ] **AC6** — Requesting a `form_uid` belonging to another tenant returns **404**.
- [ ] **AC7** — POST/PUT/PATCH with a body `tenant` differing from the URL
      returns **400**; when equal, the request succeeds.
- [ ] **AC8** — `request["tenant_context"]` is gone: no reader and no writer
      remains in `packages/` or `app.py`.
- [ ] **AC9** — Public forms (`is_public=True`) are reachable unauthenticated
      under their tenant-qualified URLs; `public_form_paths` emits those exact globs.
- [ ] **AC10** — `fieldsync` and `navigator` require **no** application-code
      change to get correct scoping — only the URL update in their HTTP clients.
- [ ] **AC11** — **G7 net**: all nine `/org/*` route paths are byte-identical to
      0.8.21, none carries `requires_tenant`, and no `/org/*` test file changed.
- [ ] **AC12** — `parrot-formdesigner` version is `0.9.0` and a migration guide
      with the full old→new URL table — stating that `/org/*` is unchanged —
      exists under `docs/migration/`.
- [ ] **AC13** — Full package suite green: `pytest packages/parrot-formdesigner/tests/ -v`.
- [ ] **AC14** — `ruff check packages/parrot-formdesigner/` clean.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> All line numbers verified on branch `dev` at commit `045a555fc`.

### Verified Imports

```python
from aiohttp import web                                     # api/handlers.py:17
from navigator.responses import JSONResponse                # api/handlers.py:19
from ..services.registry import FormAlreadyExistsError, FormRegistry  # api/handlers.py:28
from ._utils import _bump_version, _deep_merge, _loc_to_str # api/handlers.py:30
from ..services.public_forms import public_form_paths       # services/public_forms.py:3 (__all__)
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def _wrap_auth(handler: _Handler) -> _Handler:                           # line 69
    #   @wraps(handler) async def _inner(request, **kwargs)              # lines 82-87
    #   decorated = user_session()(_inner)                               # line 89
    #   decorated = is_authenticated(content_type="application/json")(…) # line 90
    # ^ THIS is the composition seam requires_tenant plugs into.
def setup_form_api(app, registry, *, client=None, ..., base_path="/api/v1",
                   rbac_enforcing: bool = False) -> None:                # line 94
    #   bp = base_path.rstrip("/")                                       # line 204
    #   route table                                                      # lines 207-360

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                                                    # line 102
    def __init__(self, registry: FormRegistry, ...):                     # line 132
    def _get_org_id(self, request: web.Request) -> int | None:           # line 207
        # request.user.organizations[0].org_id — /org/* identity, LEAVE UNCHANGED
    def _get_programs(self, request: web.Request) -> list[str]:          # line 235
        # session.get("session", {}).get("programs", [])
        # ^ the exact session read requires_tenant must reuse
    def _get_tenant(self, request: web.Request) -> str:                  # line 256
        # SIGNATURE PRESERVED — body replaced (Module 5)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _get_request_tenant(request: "web.Request") -> str | None:           # line 16
    # DELETE — module-level twin with the same 3-step fallback (line 50)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    def __init__(self, storage=None, *, app=None,
                 default_tenant: str = "navigator",
                 require_tenant: bool = True) -> None:                   # line 194
    @property
    def default_tenant(self) -> str:                                     # line 259
    def _resolve_tenant(self, ...)                                       # line 269
    async def register(self, form: FormSchema, *, persist: bool = False,
                       overwrite: bool = True,
                       tenant: str | None = None) -> None:               # line 367
    async def unregister(self, form_uid: uuid.UUID, *,
                         tenant: str | None = None) -> bool:             # line 671
    async def get(self, form_uid: uuid.UUID, *,
                  tenant: str | None = None) -> FormSchema | None:       # line 858
    async def get_by_slug(...)                                           # line 886
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]:  # line 984

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py
def _page_wrap(handler: _Handler, *, protect: bool) -> _Handler:         # line 35
def setup_form_ui(...)                                                   # line 61
    #   HTML + Telegram routes                                           # lines 91-118

# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py
def public_form_paths(form_uid: str, base_path: str = "/api/v1") -> list[str]:  # line 6
    #   returns 5 globs: base, /schema, /render/*, /data, /validate      # lines 33-41
```

### Call Sites — the 30 `self._get_tenant(request)` sites, classified

```
FORMS (21) — keep calling _get_tenant; signature preserved, lines UNTOUCHED:
   639 list_forms          738 get_form           769 get_schema
   797 get_style           833 remote_event       895 validate
   940 create_blank_form   994 create_form       1041 edit_form
  1168 update_form        1230 patch_form        1285 delete_form
  1349 submit_data        1628 load_from_db      1725 publish_form
  1748 list_fields        1765 create_field      1795 list_versions
  1831 get_version        1855 get_import_report 1892 _rbac_shadow_gate
  # _rbac_shadow_gate is a helper called ONLY from form write handlers
  # (create 976 / edit 1033 / update 1166 / patch 1228 / delete 1283)

ORG (9) — repoint to _session_tenant; routes and behaviour UNCHANGED (G7):
  1962 get_org_graph      2030 create_project    2089 map_project_workday
  2162 assign_user_role   2275 list_sites        2326 create_site
  2368 list_locations     2435 create_location   2482 get_location

MODULE-LEVEL (4 sites + 1 duplicate definition) — all forms:
  api/operations.py:551   tenant = _get_request_tenant(request)
  api/render.py:131       tenant = _get_request_tenant(request)
  api/uploads.py:247      tenant = _get_request_tenant(request)
  ui/telegram.py:24       LOCAL DUPLICATE of _get_request_tenant  (delete)
  ui/telegram.py:80,122   tenant = _get_request_tenant(request)

GAIN the body cross-check + tenant assertion:
  api/handlers.py: 953, 1202, 1267   await self.registry.register(...)
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `requires_tenant` | `_wrap_auth` composition chain | decorator wrap | `api/routes.py:82-91` |
| `requires_tenant` | `request.match_info["tenant"]` | aiohttp path param | `api/routes.py:204` (mount point) |
| `requires_tenant` | session `programs` read | same shape as `_get_programs` | `api/handlers.py:235-254` |
| `declared_tenant` | `FormAPIHandler._get_tenant` | function call | `api/handlers.py:256` |
| `_session_tenant` | the 9 `/org/*` handlers | method call | `api/handlers.py:1962-2482` |
| `_assert_form_tenant` | `FormRegistry.get` | return-value check | `services/registry.py:858` |
| `public_form_paths(…, tenant)` | `_public_toggle` closure | callback arg | `api/routes.py` (FEAT-241 M6 block) |

### Does NOT Exist (Anti-Hallucination)

- ~~any writer of `request["tenant_context"]` inside the distribution~~ — repo-wide
  grep finds **readers only** (`api/_utils.py:50`, `api/handlers.py:280`). The
  sole writer is `app.py` in PR #1149, which is not packaged.
- ~~`setup_form_api(tenant_resolver=...)`~~ / ~~`tenant_authorizer=`~~ — no such
  parameter exists, and this spec deliberately does **not** add one.
- ~~`FormRegistry.resolve_tenant_for_request()`~~ — not a method. `_resolve_tenant`
  (`services/registry.py:269`) is internal and request-unaware.
- ~~a forms sub-application~~ — `setup_form_api` mounts on the **root** router
  (`app.router.add_*`, `api/routes.py:207+`). There is no subapp, which is
  exactly why a middleware could not be scoped to forms in #1149 — and why a
  decorator is the only correctly-scoped mechanism available.
- ~~`parrot_formdesigner.api.errors`~~ / ~~`parrot_formdesigner.api.tenant`~~ —
  new in this spec (Modules 1, 2).
- ~~`FormAPIHandler._session_tenant`~~ — new in this spec (Module 5).
- ~~`request["tenant"]`~~ — not an established key today; introduced by
  `requires_tenant` and read only through `declared_tenant()`.
- ~~an org→tenant mapping service~~ — none exists. `/org/*` handlers pass
  `org_id` (session) and `tenant` (session) as two independent arguments; there
  is no lookup that derives one from the other.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `functools.wraps` on the decorator, mirroring `_wrap_auth` (`api/routes.py:82`).
- Google-style docstrings + strict type hints on every new function.
- `async`/`await` throughout; no blocking I/O.
- `self.logger` — never `print`.
- Raise the typed errors from Module 2; never hand-roll `JSONResponse(status=400)`.
- Land modules in dependency order (1→2→3→4→5…) so the suite is never red for
  more than one module at a time.

### Known Risks / Gotchas

- **`require_tenant` is a red herring.** It only gates `register()` when *both*
  the `tenant=` kwarg and `form.tenant` are `None`
  (`services/registry.py:432-436`). Every REST write already passes an explicit
  `tenant=` (`api/handlers.py:953, 1202, 1267`) sourced from `_get_tenant`,
  which never returns `None`. Therefore `require_tenant=False` in fieldsync's
  `setup_form_registry` **does not disable multi-tenancy and is not the cause
  of NAV-9370/9372** — the registry is tenant-keyed regardless
  (`_forms: dict[tenant, dict[uid, FormSchema]]`, `services/registry.py:220`).
  It matters only for `load_from_directory` (`:1177-1181`). Do not "fix" it here.
- **A forms route mounted without the decorator is the new failure mode.**
  Middleware was blanket; a decorator is opt-in per route. Mitigations, all
  mandatory: `tenant="required"` is the *default* of `_wrap_auth`, so silence
  protects rather than exposes; `test_every_forms_route_is_decorated` guards the
  router; and `_get_tenant` raising `RuntimeError` rather than falling back is
  the fail-loud backstop.
- **Public-form exclusions are the highest-regression-risk item.** The globs in
  `public_form_paths` are matched by navigator-auth. A tenant-qualified route
  with an unqualified glob = public form 404s for anonymous users. Module 7 must
  land in the same commit as Module 4.
- **Route registration order.** `POST /forms/blank` is registered before the
  `{form_uid}` catch-all deliberately (`api/routes.py:211-214`). Preserve the
  relative ordering when re-prefixing.
- **Audio WS cannot use the decorator** (`api/routes.py`, FEAT-224/236 block) —
  it is not `_wrap_auth`-ed because navigator-auth decorators return 401, which
  breaks the WS upgrade handshake. Its tenant check goes inside
  `AudioFormWSHandler`, after JWT validation (Module 8).
- **Coordinated deploy.** Hard cut means `navigator-svelte`, `fieldsync` and the
  wheel ship together. AC12's migration guide makes this schedulable.
- **`ui/telegram.py` duplicates the resolver** (`:24`). Missing it leaves a
  silent second fallback chain alive after the main one is deleted.
- **Superuser declaring an unprovisioned tenant** creates a new registry bucket
  silently — the same latent hole exists in #1149. Out of scope to fix, but log
  a `WARNING` when a superuser declares a tenant absent from
  `registry.list_tenants()`.

### Residual (deliberately not fixed here)

`/org/*` keeps **two** arbitrary-index inferences: `organizations[0]`
(`_get_org_id`, `:207-230`) and, via `_session_tenant`, `programs[0]`. These are
the same anti-pattern this spec removes from forms. They are left standing
because G7 puts `/org/*` out of scope and because organizations are the layer
that *defines* tenants — resolving them properly is a different design question
(does a user act on behalf of one organization at a time, and how is that
declared?). **Recommend a follow-up ticket.** `_session_tenant`'s explicit name
exists precisely so this residual is greppable rather than invisible.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | `match_info` path params — no new dependency |
| `navigator-auth` | `>=0.20.11` | already required for `register_exclusions` (`api/routes.py`) |

---

## 8. Open Questions

All blocking questions are resolved — ready for `/sdd-task`.

- [x] Which URL shape? — *Resolved by Jesus Lara*: explicit `/api/v1/t/{tenant}/…`
      marker segment, for zero router ambiguity.
- [x] Who authorizes the declaration? — *Resolved by Jesus Lara*: parrot validates
      natively against the navigator-auth session. No host-injected authorizer —
      it would reproduce #1149's wiring problem.
- [x] What happens to existing callers? — *Resolved by Jesus Lara*: hard cut,
      major bump to `0.9.0`. Old forms routes are not registered (404). No
      deprecation window, because a fallback window keeps alive exactly the
      inference that caused NAV-9370/9372.
- [x] Which enforcement mechanism? — *Resolved by Jesus Lara*: **middleware is
      forbidden; decorators are explicitly allowed.** Enforcement is a per-route
      decorator composed into the existing `_wrap_auth` chain, so it is scoped to
      forms handlers and ships in the wheel.
- [x] POST body tenant: cross-check or authoritative? — *Resolved by Jesus Lara*:
      **URL-authoritative on every verb.** A body `tenant` is an optional
      cross-check that must match, returning 400 `tenant_conflict` otherwise.
- [x] Should `/org/*` be tenant-scoped too? — *Resolved by Jesus Lara*: **no.**
      The tenant-based URL affects forms only. `/org/*` is *organizations*, the
      foundational layer that defines tenants; scoping it by a tenant would
      invert the dependency. Captured as G7, AC11 and the §7 Residual note.
- [ ] **Q3 — Is 404-on-cross-tenant right for `is_public` forms?** A public form
      is by definition not secret, so 404-vs-403 leaks little; consistency argues
      for 404 everywhere. Deferrable to implementation. — *Owner: implementation*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All modules run **sequentially** in one
  worktree.
- **Rationale**: Modules 3–8 edit the same call graph and the same test suite;
  parallel worktrees would conflict on `api/routes.py` and on the 26 test files.
  There is no clean parallel seam.
- **Suggested worktree**:
  ```bash
  git worktree add -b feat-<ID>-forms-tenant-in-url \
    .claude/worktrees/feat-<ID>-forms-tenant-in-url HEAD
  ```
- **Cross-feature dependencies**:
  - PR **#1149** must be **closed unmerged** before this lands — it adds the
    middleware this spec deletes.
  - PR **#1146** is already merged; its items 2–4 (jsonb double-encoding, slug
    suffix, registry read-through) are **good and stay**. Only its item 1
    (resolution step 0) is reverted here.
  - **FEAT-466** (tenant backfill of forms stored under `navigator`) should run
    *after* this, since it needs the corrected write path first.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-16 | Jesus Lara + Claude | Initial draft — alternative to PRs #1146 (step 0) and #1149 (host middleware) |
| 0.2 | 2026-08-16 | Jesus Lara + Claude | Enforcement changed from handler-internal calls to a per-route decorator composed into `_wrap_auth` (middleware forbidden, decorators allowed) |
| 0.3 | 2026-08-16 | Jesus Lara + Claude | Q1/Q2 resolved: URL-authoritative on every verb; `/org/*` excluded from tenant scoping (G7, AC11). 30 call sites classified 21 forms / 9 org; `_session_tenant` added for the org side |
