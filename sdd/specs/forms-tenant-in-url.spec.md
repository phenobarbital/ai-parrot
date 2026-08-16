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
concerns. Step 3 is worse: it silently lands the write in
`default_tenant` (`"navigator"`, `services/registry.py:199`).

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

The correct split is: **the client declares which tenant it is operating
against; the backend enforces that the declaration is legitimate; nobody
guesses.**

### Goals

- **G1** — The tenant is declared explicitly by the client, in the URL path,
  on every tenant-scoped forms route.
- **G2** — Declaration is authorized inside the request handler, natively by
  `parrot-formdesigner`, with **no** middleware, no route decorator, and no
  aiohttp per-request hook introduced for this purpose.
- **G3** — No declared tenant ⇒ **HTTP 400**. The `default_tenant` fallback is
  removed from the HTTP boundary entirely.
- **G4** — Zero host wiring. Installing the wheel is sufficient; neither
  `fieldsync` nor `navigator` edits an `app.py` to get correct scoping.
- **G5** — No query-string carries the tenant, on any verb.
- **G6** — A form reachable under one tenant is never reachable by declaring
  another.

### Non-Goals (explicitly out of scope)

- Removing `FormRegistry.default_tenant` as a constructor parameter. It stays
  for non-HTTP entry points (`load_from_directory`, boot hydration) where no
  request exists to declare a tenant. Only the **HTTP boundary** stops using it.
- Changing `require_tenant`. Analysis (§7) shows it is inert on the REST path.
- A tenant-backfill migration for forms already stored under `navigator`
  (tracked separately as FEAT-466).
- Retro-fitting `request["tenant_context"]`. Step 0 is removed, not extended.
- Host-supplied entitlement plugins (`tenant_authorizer=`). Rejected during
  design — it reproduces #1149's "each host must wire it" failure mode.

---

## 2. Architectural Design

### Overview

Three changes, in order of consequence:

**1. The tenant becomes a URL path segment, behind a literal `t` marker.**

```
/api/v1/t/{tenant}/forms
/api/v1/t/{tenant}/forms/{form_uid}
/api/v1/t/{tenant}/forms/{form_uid}/render/{format}
/api/v1/t/{tenant}/fields
/api/v1/t/{tenant}/org/graph
```

The literal `t` segment exists to remove router ambiguity. Without it,
`/api/v1/forms/{tenant}` and `/api/v1/forms/{form_uid}` are the same shape —
one path segment — and aiohttp would have to disambiguate by UUID-parsing the
segment, with reserved literals (`blank`, `from-db`) as special cases. `t/`
makes the grammar unambiguous by construction.

`form_uid` is a globally unique UUID (`services/registry.py:858`), so the
tenant segment is **not** a lookup key. It is a *declaration*, and its value
is that it can be **cross-checked**: if `{form_uid}` resolves to a form whose
tenant differs from `{tenant}`, the response is **404**, not 403 — a 403 would
confirm the form exists in some other tenant, which is an existence oracle.

**2. Authorization happens inside the handler, as a plain method call.**

No middleware, no decorator, no `@web.middleware`, no wrapper. Two helper
methods are invoked from the body of each handler:

```python
tenant = self._require_tenant(request)      # 400 if the segment is absent/empty
self._authorize_tenant(request, tenant)     # 403 if the caller is not entitled
```

`_authorize_tenant` reads the navigator-auth session that
`FormAPIHandler._get_programs` already reads today
(`api/handlers.py:235-254`) and checks membership, with a superuser bypass.
This drops #1146's "parrot is entitlement-agnostic" premise deliberately:
parrot already depends on the exact shape of that session (it reads
`programs[0]` from it right now), so the premise was never true in practice —
and honoring it is what pushed the producer into an uninstallable file.

**3. The fallback chain is deleted.**

`_get_tenant` (returns `str`, never `None`, falls back twice) is replaced by
`_require_tenant` (returns `str`, or raises `HTTPBadRequest`). There is no
path from an HTTP request to `registry.default_tenant`.

#### Public forms — the one authorization carve-out

A form with `is_public=True` is served without a session (`services/public_forms.py:6-41`
registers auth-exempt paths). Such a request has no `programs` to check
against, so `_authorize_tenant` **must not** run for it. The rule:

| | tenant declared? | authorized? |
|---|---|---|
| Authenticated route | required (400 if absent) | required (403 if not a member) |
| Public form route | required (400 if absent) | skipped — the form's `is_public` flag *is* the grant |

The tenant is still mandatory on public routes: it is what makes
`public_form_paths` derivable and keeps G6 intact.

### Component Diagram

```
client
  │  GET /api/v1/t/flexroc/forms/{uid}
  ▼
aiohttp router  ──(no middleware, no decorator for tenant)──┐
  │                                                          │
  ▼                                                          │
_wrap_auth (navigator-auth: is_authenticated + user_session) │  ← unchanged
  │                                                          │
  ▼                                                          │
FormAPIHandler.get_form(request)                             │
  ├─ _require_tenant(request)      ── 400 tenant_not_declared ┘
  ├─ _authorize_tenant(req, t)     ── 403 tenant_forbidden
  ├─ registry.get(uid, tenant=t)
  └─ _assert_form_tenant(form, t)  ── 404 (cross-tenant probe)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `FormAPIHandler` (`api/handlers.py:102`) | modifies | `_get_tenant` → `_require_tenant` + `_authorize_tenant`; **31 call sites** |
| `_get_request_tenant` (`api/_utils.py:16`) | replaces | module-level twin; **4 call sites** (`operations.py:551`, `render.py:131`, `uploads.py:247`, `ui/telegram.py:80,122`) |
| `setup_form_api` (`api/routes.py:94`) | modifies | route table rewritten with the `t/{tenant}` prefix (~40 routes) |
| `setup_form_ui` (`ui/routes.py:61`) | modifies | HTML page + Telegram routes gain the prefix |
| `public_form_paths` (`services/public_forms.py:6`) | modifies | signature gains `tenant`; patterns become tenant-qualified |
| `_wrap_auth` (`api/routes.py:69`) | **unchanged** | stays navigator-auth-only; deliberately NOT the tenant seam |
| `FormRegistry` (`services/registry.py:194`) | unchanged | already tenant-keyed; `tenant=` kwargs already exist on every method |
| `app.py` | **reverted** | `forms_tenant_context_middleware` (#1149) deleted |

### Data Models

```python
# api/errors.py  (new)
class TenantNotDeclaredError(web.HTTPBadRequest):
    """400 — the request carried no tenant segment."""

class TenantForbiddenError(web.HTTPForbidden):
    """403 — the caller is not entitled to the declared tenant."""
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
# api/_utils.py
def require_declared_tenant(request: "web.Request") -> str:
    """Return the tenant declared in the URL. Raise 400 when absent."""

def authorize_declared_tenant(request: "web.Request", tenant: str) -> None:
    """Raise 403 unless the session is a member of `tenant` (or superuser)."""

def assert_body_tenant_matches(body: dict, tenant: str) -> None:
    """Raise 400 when a POST/PUT/PATCH body declares a conflicting tenant."""

# services/public_forms.py
def public_form_paths(
    form_uid: str, tenant: str, base_path: str = "/api/v1"
) -> list[str]: ...
```

### Tenant in POST bodies (MUST-DO #3)

The URL is **authoritative** on every verb, including POST. For POST/PUT/PATCH
the body **may** additionally carry `"tenant"`; when present it must equal the
URL segment, otherwise **400 `tenant_conflict`**. It is a cross-check, never an
override and never a substitute.

Rationale for URL-authoritative rather than body-authoritative: one rule for
all verbs keeps `public_form_paths`, the auth exclusion globs, and access logs
derivable from the URL alone. A body-authoritative design would make the
tenant invisible to the router, to navigator-auth's exclusion matcher, and to
every access log line. This reverses #1146's "`body.tenant` deliberately NOT
honored" only in the weak sense: the body value is now *validated*, still
never *trusted*.

> **Flag for review** — this is the one MUST-DO where the letter ("add the
> tenant to the post-data") and the safest reading diverge. See §8 Q1.

---

## 3. Module Breakdown

### Module 1: Tenant declaration primitives
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py`
- **Responsibility**: `require_declared_tenant`, `authorize_declared_tenant`,
  `assert_body_tenant_matches`. Plain functions — no decorators, no wrappers.
  Deletes `_get_request_tenant` and its three-step fallback.
- **Depends on**: nothing new.

### Module 2: Typed error responses
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/errors.py` (new)
- **Responsibility**: `TenantNotDeclaredError`, `TenantForbiddenError`,
  `TenantConflictError`, each rendering the stable JSON body above.
- **Depends on**: Module 1.

### Module 3: `FormAPIHandler` migration
- **Path**: `.../api/handlers.py`
- **Responsibility**: replace `_get_tenant` with `_require_tenant` /
  `_authorize_tenant` / `_assert_form_tenant`; update all **31** call sites;
  add body cross-check on the write verbs. Keep `_get_programs` (`:235`) as the
  session reader.
- **Depends on**: Modules 1, 2.

### Module 4: Module-level handler migration
- **Path**: `.../api/operations.py:551`, `.../api/render.py:131`, `.../api/uploads.py:247`
- **Responsibility**: swap `_get_request_tenant` for `require_declared_tenant`
  + `authorize_declared_tenant`.
- **Depends on**: Modules 1, 2.

### Module 5: Route table rewrite
- **Path**: `.../api/routes.py`
- **Responsibility**: mount every route under `{bp}/t/{{tenant}}/...`. Old
  paths are **not** registered (hard cut). Includes the audio WS route
  (`/t/{tenant}/forms/{form_uid}/audio/ws`), which is not `_wrap_auth`-ed and
  validates JWT internally.
- **Depends on**: Module 3.

### Module 6: Public-form path derivation
- **Path**: `.../services/public_forms.py` + the `_public_toggle` closure in
  `api/routes.py`
- **Responsibility**: `public_form_paths(form_uid, tenant, base_path)` emits
  tenant-qualified globs; the registry toggle callback must supply the form's
  tenant. **Regression risk**: a stale unqualified glob silently makes a public
  form unreachable (or, worse, leaves a stale exemption registered).
- **Depends on**: Module 5.

### Module 7: UI + Telegram surface
- **Path**: `.../ui/routes.py:91-118`, `.../ui/telegram.py:24,80,122`
- **Responsibility**: HTML pages and Telegram WebApp routes gain the prefix.
  `ui/telegram.py` carries its **own copy** of `_get_request_tenant` (`:24`) —
  delete it and import the shared primitive.
- **Depends on**: Modules 1, 5.

### Module 8: `app.py` revert
- **Path**: `app.py`
- **Responsibility**: delete `forms_tenant_context_middleware` and its
  registration. Proves G4 — the repo's own host needs no tenant wiring.
- **Depends on**: Module 5.

### Module 9: Version bump + migration guide
- **Path**: `.../version.py` (`0.8.21` → `0.9.0`),
  `docs/migration/feat-<id>-forms-tenant-in-url.md`
- **Responsibility**: URL mapping table old→new for `navigator-svelte` and
  `fieldsync`; the coordinated-deploy checklist.
- **Depends on**: Modules 5, 7.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_require_tenant_returns_segment` | 1 | Declared segment is returned verbatim |
| `test_require_tenant_400_when_absent` | 1 | No `tenant` match info → `HTTPBadRequest` |
| `test_require_tenant_400_when_empty` | 1 | `/t//forms` → 400, not a silent empty tenant |
| `test_authorize_allows_member` | 1 | `programs=["flexroc"]`, declared `flexroc` → passes |
| `test_authorize_allows_superuser` | 1 | `superuser=True`, any declared tenant → passes |
| `test_authorize_403_non_member` | 1 | `programs=["navigator"]`, declared `flexroc` → 403 |
| `test_authorize_403_no_session` | 1 | Anonymous on an authenticated route → 403 |
| `test_no_default_tenant_fallback` | 1,3 | `registry.default_tenant` is never reached from HTTP |
| `test_body_tenant_match_ok` | 1 | Body `tenant` equal to URL → accepted |
| `test_body_tenant_conflict_400` | 1 | Body `tenant` ≠ URL → 400 `tenant_conflict` |
| `test_cross_tenant_form_returns_404` | 3 | Form of tenant A, declared B → 404 (not 403) |
| `test_public_form_paths_tenant_qualified` | 6 | Globs contain `/t/{tenant}/` |
| `test_public_form_skips_authorization` | 3,6 | `is_public=True`, no session → 200 |
| `test_public_form_still_requires_tenant` | 3,6 | `is_public=True`, no tenant segment → 400 |

### Integration Tests

| Test | Description |
|---|---|
| `test_create_then_get_same_tenant` | POST under `t/flexroc` → GET under `t/flexroc` → 200 (the NAV-9372 regression) |
| `test_edit_persists_under_declared_tenant` | PUT under `t/flexroc` writes to `flexroc`, never `navigator` (NAV-9370) |
| `test_multi_program_user_no_programs0_leak` | User with `programs=["navigator","flexroc"]` declaring `flexroc` never touches `navigator` |
| `test_legacy_url_is_404` | `GET /api/v1/forms/{uid}` → 404 (hard cut) |
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

**Migration load**: 27 test files reference `/api/v1/forms`
(`packages/parrot-formdesigner/tests/`). All must move to the new shape.

---

## 5. Acceptance Criteria

- [ ] **AC1** — Every tenant-scoped route is mounted under `{base_path}/t/{tenant}/`.
- [ ] **AC2** — `grep -rn "@web.middleware\|middlewares.append" app.py` returns no
      tenant-related hit; no decorator or aiohttp per-request hook is introduced
      for tenant resolution.
- [ ] **AC3** — `grep -rn "request.query.get(\"tenant\|program_slug" packages/parrot-formdesigner/src`
      returns nothing: the tenant never travels in a query string.
- [ ] **AC4** — A request without a declared tenant returns **400** with
      `error: "tenant_not_declared"`. No HTTP path reaches `registry.default_tenant`.
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
- [ ] **AC11** — `parrot-formdesigner` version is `0.9.0` and a migration guide
      with the full old→new URL table exists under `docs/migration/`.
- [ ] **AC12** — Full package suite green: `pytest packages/parrot-formdesigner/tests/ -v`.
- [ ] **AC13** — `ruff check packages/parrot-formdesigner/` clean.

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
# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:                                                    # line 102
    def __init__(self, registry: FormRegistry, ...):                     # line 132
    def _get_programs(self, request: web.Request) -> list[str]:          # line 235
        # reads session.get("session", {}).get("programs", []) — KEEP
    def _get_tenant(self, request: web.Request) -> str:                  # line 256
        # DELETE — 3-step fallback; 31 call sites listed below

# packages/parrot-formdesigner/src/parrot_formdesigner/api/_utils.py
def _get_request_tenant(request: "web.Request") -> str | None:           # line 16
    # DELETE — module-level twin of the above

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    def __init__(self, storage=None, *, app=None,
                 default_tenant: str = "navigator",
                 require_tenant: bool = True) -> None:                   # line 194
    @property
    def default_tenant(self) -> str:                                     # line 259
    async def register(self, form: FormSchema, *, persist: bool = False,
                       overwrite: bool = True,
                       tenant: str | None = None) -> None:               # line 367
    async def unregister(self, form_uid: uuid.UUID, *,
                         tenant: str | None = None) -> bool:             # line 671
    async def get(self, form_uid: uuid.UUID, *,
                  tenant: str | None = None) -> FormSchema | None:       # line 858
    async def get_by_slug(...)                                           # line 886
    async def list_forms(self, *, tenant: str | None = None) -> list[FormSchema]:  # line 984

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def _wrap_auth(handler: _Handler) -> _Handler:                           # line 69
    # navigator-auth is_authenticated + user_session — LEAVE UNCHANGED
def setup_form_api(app, registry, *, client=None, ..., base_path="/api/v1",
                   rbac_enforcing: bool = False) -> None:                # line 94
    #  bp = base_path.rstrip("/")                                        # line 204
    #  route table                                                       # lines 207-360

# packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py
def _page_wrap(handler: _Handler, *, protect: bool) -> _Handler:         # line 35
def setup_form_ui(...)                                                   # line 61
    #  HTML + Telegram routes                                            # lines 91-118

# packages/parrot-formdesigner/src/parrot_formdesigner/services/public_forms.py
def public_form_paths(form_uid: str, base_path: str = "/api/v1") -> list[str]:  # line 6
    # returns 5 globs: base, /schema, /render/*, /data, /validate        # lines 33-41
```

### Call Sites To Migrate (exhaustive)

```
api/handlers.py  self._get_tenant(request)  — 31 sites, lines:
  639, 738, 769, 797, 833, 895, 940, 994, 1041, 1168, 1230, 1285, 1349,
  1628, 1725, 1748, 1765, 1795, 1831, 1855, 1892, 1962, 2030, 2089, 2162, 2275

api/operations.py:551   tenant = _get_request_tenant(request)
api/render.py:131       tenant = _get_request_tenant(request)
api/uploads.py:247      tenant = _get_request_tenant(request)
ui/telegram.py:24       LOCAL DUPLICATE of _get_request_tenant  (delete)
ui/telegram.py:80,122   tenant = _get_request_tenant(request)

api/handlers.py  await self.registry.register(...)  — 953, 1202, 1267
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `require_declared_tenant` | `request.match_info["tenant"]` | aiohttp path param | `api/routes.py:204` (mount point) |
| `authorize_declared_tenant` | `FormAPIHandler._get_programs` logic | session read | `api/handlers.py:235-254` |
| `_assert_form_tenant` | `FormRegistry.get` | return-value check | `services/registry.py:858` |
| `public_form_paths(…, tenant)` | `_public_toggle` closure | callback arg | `api/routes.py` (`_public_toggle`, FEAT-241 M6 block) |

### Does NOT Exist (Anti-Hallucination)

- ~~any writer of `request["tenant_context"]` inside the distribution~~ — repo-wide
  grep finds **readers only** (`api/_utils.py:50`, `api/handlers.py:280`). The
  sole writer is `app.py` in PR #1149, which is not packaged.
- ~~`setup_form_api(tenant_resolver=...)`~~ / ~~`tenant_authorizer=`~~ — no such
  parameter exists today, and this spec deliberately does **not** add one.
- ~~`FormRegistry.resolve_tenant_for_request()`~~ — not a method. `_resolve_tenant`
  (`services/registry.py:269`) is internal and request-unaware.
- ~~a forms sub-application~~ — `setup_form_api` mounts on the **root** router
  (`app.router.add_*`, `api/routes.py:207+`). There is no subapp, which is
  precisely why a middleware could not be scoped to forms in #1149.
- ~~`parrot_formdesigner.api.errors`~~ — new in this spec (Module 2).
- ~~`request["tenant"]`~~ — not an established key; the tenant lives in
  `request.match_info`, not the request dict.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Google-style docstrings + strict type hints on every new function.
- `async`/`await` throughout; no blocking I/O.
- `self.logger` — never `print`.
- Raise the typed errors from Module 2; do not hand-roll `JSONResponse(status=400)`
  at each of the 31 call sites.
- Migrate handlers **in dependency order** (Modules 1→2→3→4→5) so the suite is
  never red for more than one module at a time.

### Known Risks / Gotchas

- **`require_tenant` is a red herring.** It only gates `register()` when *both*
  the `tenant=` kwarg and `form.tenant` are `None`
  (`services/registry.py:432-436`). Every REST write already passes an explicit
  `tenant=` (`api/handlers.py:953, 1202, 1267`) sourced from `_get_tenant`,
  which never returns `None`. Therefore `require_tenant=False` in fieldsync's
  `setup_form_registry` **does not disable multi-tenancy and is not the cause
  of NAV-9370/9372** — the registry is tenant-keyed regardless
  (`_forms: dict[tenant, dict[uid, FormSchema]]`, `services/registry.py:220`).
  It matters only for `load_from_directory` (`:1177-1181`). Do not "fix" it as
  part of this feature.
- **Public-form exclusions are the highest-regression-risk item.** The globs in
  `public_form_paths` are matched by navigator-auth. A tenant-qualified route
  with an unqualified glob = public form 404s for anonymous users. Module 6
  must land in the same commit as Module 5.
- **Route registration order.** `POST /forms/blank` is registered before the
  `{form_uid}` catch-all deliberately (`api/routes.py:211-214`). Preserve the
  relative ordering when re-prefixing.
- **Audio WS is not `_wrap_auth`-ed** (`api/routes.py`, FEAT-224/236 block) —
  it authenticates by JWT internally because navigator-auth decorators return
  401, which breaks the WS upgrade. Its tenant check must be implemented inside
  `AudioFormWSHandler`, not bolted onto the route.
- **Coordinated deploy.** Hard cut means `navigator-svelte`, `fieldsync` and the
  wheel must ship together. AC11's migration guide is the deliverable that makes
  this schedulable, not an afterthought.
- **`ui/telegram.py` duplicates the resolver** (`:24`). Missing it leaves a
  silent second fallback chain alive after the main one is deleted.
- **Superuser declaring an unprovisioned tenant** creates a new registry bucket
  silently. Same latent hole exists in #1149. Out of scope here, but log a
  `WARNING` when a superuser declares a tenant absent from
  `registry.list_tenants()`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiohttp` | existing | `match_info` path params — no new dependency |
| `navigator-auth` | `>=0.20.11` | already required for `register_exclusions` (`api/routes.py`) |

---

## 8. Open Questions

- [x] Which URL shape? — *Resolved by Jesus Lara*: explicit `/api/v1/t/{tenant}/…`
      marker segment, for zero router ambiguity.
- [x] Who authorizes the declaration? — *Resolved by Jesus Lara*: parrot validates
      natively against the navigator-auth session. No host-injected authorizer —
      it would reproduce #1149's wiring problem.
- [x] What happens to existing callers? — *Resolved by Jesus Lara*: hard cut,
      major bump to `0.9.0`. Old routes are not registered (404). No deprecation
      window, because a fallback window keeps alive exactly the inference that
      caused NAV-9370/9372.
- [ ] **Q1 — POST body tenant: cross-check or authoritative?** MUST-DO #3 says
      "in POST-type operations, add the tenant to the post-data". This spec makes
      the **URL authoritative on every verb** and treats a body `tenant` as an
      optional cross-check (400 on mismatch), because a body-authoritative tenant
      is invisible to the router, to navigator-auth's exclusion matcher, and to
      access logs. Confirm this reading, or switch POST/PUT/PATCH to
      body-authoritative. — *Owner: Jesus Lara*
- [ ] **Q2 — Should `/org/*` routes be tenant-scoped too?** They are currently
      **not** tenant-scoped at all (`/org/graph`, `/org/projects`, `/org/stores/*`,
      `/org/sync/workday`). Putting them under `t/{tenant}` scopes them for free;
      leaving them out keeps the org graph global. This is a behavioural change
      beyond the forms bug. — *Owner: Jesus Lara*
- [ ] **Q3 — Is 404-on-cross-tenant right for `is_public` forms?** A public form
      is by definition not secret, so 404-vs-403 leaks little; but consistency
      argues for 404 everywhere. — *Owner: implementation*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All modules run **sequentially** in one
  worktree.
- **Rationale**: Modules 3–7 all edit the same call graph and the same test
  suite; parallel worktrees would conflict on `api/handlers.py` and on the 27
  test files. There is no clean parallel seam.
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
