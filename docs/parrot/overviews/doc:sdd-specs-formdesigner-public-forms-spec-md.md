---
type: Wiki Overview
title: 'Feature Specification: FormDesigner Public Forms'
id: doc:sdd-specs-formdesigner-public-forms-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'parrot-formdesigner needs to expose *public* forms: when a new'
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: FormDesigner Public Forms

**Feature ID**: FEAT-241
**Date**: 2026-06-16
**Author**: Jesus Lara
**Status**: approved
**Target version**: parrot-formdesigner ≥ 0.4.0 + a coordinated navigator-auth release (see §8)

> **Source of truth**: `sdd/proposals/formdesigner-public-forms.proposal.md`
> (research-grounded, FEAT-241). Codebase references re-verified for this spec —
> see §6. This is a **cross-repo** feature: changes land in both
> `ai-parrot` (`packages/parrot-formdesigner`) and the sibling repo
> `../navigator-auth`.

---

## 1. Motivation & Business Requirements

### Problem Statement

parrot-formdesigner needs to expose *public* forms: when a new
`FormSchema.is_public` property is `True`, the form's read/representation URLs
(the form object, its JSON schema, its rendered formats) and its
result-submission/validation URLs must be reachable **without authentication**.
When `is_public` is turned off (or the form is deleted), those URLs must revert
to authenticated-only.

The original request assumed navigator-auth's auth-exempt routes are a
`frozenset` frozen at server boot. Research showed this is **outdated for the
per-app exclude list**: `AuthHandler.setup` already seeds
`app["auth_exclude_list"]` as a **mutable list**, evaluated at *request time* by
all three middlewares via `fnmatch`, and exposes `add_exclude_list(path)` (the
mutable-list refactor landed in navigator-auth `27b478b`, 2026-04-02). The
genuine gaps are therefore:

1. navigator-auth has **no removal** API and no way to re-hydrate runtime
   exemptions after a restart (the list is re-seeded from defaults each boot).
2. Every formdesigner route is individually wrapped with `is_authenticated`, a
   **handler-level** decorator that ignores the exclude list and will `401`
   anonymous callers even when the middleware would have exempted the path.

### Goals

- Add an `is_public: bool` property to `FormSchema` (default `False`).
- When a form transitions to `is_public=True`, register its public paths in
  navigator-auth's runtime exclude list; when it transitions to `False` **or is
  deleted**, unregister them.
- Make navigator-auth's exemption authoritative at **both** layers: the
  middleware exclude list **and** the `is_authenticated` handler decorator.
- Survive server restarts: re-hydrate public-form exemptions on startup from the
  forms store (the source of truth), via a navigator-auth exclude-provider hook.
- Add the navigator-auth API surface required: idempotent `add_exclude_list`,
  `remove_exclude_list`, and bulk `register_exclusions` / `unregister_exclusions`.

### Non-Goals (explicitly out of scope)

- The per-middleware `exclude_routes` **tuple** mechanism
  (`base_middleware.exclude_routes`) — genuinely frozen at init and the wrong
  hook; untouched. (Rejected as the integration point — see proposal §2.2.)
- RBAC / tenant authorization changes — "public" means *anonymous-readable* and
  is orthogonal to RBAC.
- The Telegram / UI surface (`parrot_formdesigner.ui.setup_form_ui`) — only the
  JSON REST surface (`api.setup_form_api`) is in scope.

---

## 2. Architectural Design

### Overview

Two cooperating changes, one per repo:

**navigator-auth (sibling repo `../navigator-auth`)** becomes the general home for
dynamic, restart-safe auth exemptions:
- `AuthHandler` gains idempotent `add_exclude_list(path)`, `remove_exclude_list(path)`,
  and bulk `register_exclusions(paths)` / `unregister_exclusions(paths)`, all
  mutating the existing `app["auth_exclude_list"]` list.
- `AuthHandler` gains an **exclude-provider callback** registry
  (`add_exclude_provider(async_fn)`); on `on_startup`, navigator-auth invokes
  every provider and registers the paths they yield — re-hydrating in-memory
  exemptions after each restart.
- `is_authenticated` (decorator) short-circuits to the handler when the request
  path is in `app["auth_exclude_list"]` (same `fnmatch` semantics as the
  middleware) **or** `request.allow_anonymous` is set — closing the second-layer
  gap.

**parrot-formdesigner (this repo)**:
- `FormSchema.is_public: bool = False`.
- A pure helper computing a form's public glob patterns from `(form_id, base_path)`.
- Lifecycle integration: on `is_public` transitions in
  `create_form`/`update_form`/`patch_form`/`publish_form` and on `delete_form`
  (centralized in `FormRegistry.register` / `FormRegistry.delete` to avoid
  4-way duplication), call the navigator-auth bulk register/unregister.
- An exclude-provider registered in `setup_form_api`, yielding the public paths
  of all persisted `is_public=True` forms (restart re-hydration).

### Component Diagram

```
                       parrot-formdesigner (this repo)
  setup_form_api ──registers──→ exclude-provider callback ─┐
        │                                                  │
  create/update/patch/publish_form ─→ FormRegistry.register┤  (diff old/new is_public)
  delete_form ───────────────────────→ FormRegistry.delete ┤
        │                                                  │
        └── public_paths(form_id, base_path) ──────────────┤
                                                           ▼
                       navigator-auth (../navigator-auth, sibling repo)
   AuthHandler.register_exclusions / unregister_exclusions ──→ app["auth_exclude_list"] (mutable list)
   AuthHandler.add_exclude_provider ──invoked on on_startup──→ app["auth_exclude_list"]
                                                           │
            ┌──────────────────────────────────────────────┘
            ▼ (request time, fnmatch)
   middlewares (auth / abac / backends)   +   is_authenticated decorator
            └────────── both honor app["auth_exclude_list"] ──────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AuthHandler` (`../navigator-auth/navigator_auth/auth.py`) | extends | new mutation + provider APIs; reachable at `app["auth"]` |
| `is_authenticated` (`../navigator-auth/navigator_auth/decorators.py`) | modifies | honor exclude list / `allow_anonymous` |
| `app["auth_exclude_list"]` (per-app list) | uses | the single mutable structure all middlewares read |
| `FormSchema` (`core/schema.py`) | extends | add `is_public` |
| `FormRegistry.register` / `.delete` (`services/registry.py`) | extends | central toggle point |
| `setup_form_api` (`api/routes.py`) | extends | register the exclude-provider |

### Data Models

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):
    ...
    is_public: bool = False  # NEW — anonymous access to this form's public URLs
```

### New Public Interfaces

```python
# ../navigator-auth/navigator_auth/auth.py  (AuthHandler)
def add_exclude_list(self, path: str) -> None: ...          # made idempotent
def remove_exclude_list(self, path: str) -> None: ...       # NEW (idempotent)
def register_exclusions(self, paths: Iterable[str]) -> None: ...    # NEW
def unregister_exclusions(self, paths: Iterable[str]) -> None: ...  # NEW
def add_exclude_provider(self, provider: Callable[[], Awaitable[Iterable[str]]]) -> None: ...  # NEW

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py (or a small services/ module)
def public_form_paths(form_id: str, base_path: str = "/api/v1") -> list[str]:
    """Return the auth-exempt glob patterns for a public form."""
```

For a form `{id}` under `base_path` `/api/v1`, `public_form_paths` returns:
- `"/api/v1/forms/{id}"`            (GET form)
- `"/api/v1/forms/{id}/schema"`     (GET JSON schema)
- `"/api/v1/forms/{id}/render/*"`   (GET rendered formats — glob)
- `"/api/v1/forms/{id}/data"`       (POST submit results)
- `"/api/v1/forms/{id}/validate"`   (POST pre-submit validation)

---

## 3. Module Breakdown

> Modules M1–M3 live in the **sibling repo** `../navigator-auth` (separate git
> repo, separate PR/release). Modules M4–M7 live in this repo under
> `packages/parrot-formdesigner`. See §Worktree Strategy.

### Module 1: navigator-auth exclude-list mutation API
- **Path**: `../navigator-auth/navigator_auth/auth.py`
- **Responsibility**: idempotent `add_exclude_list`, new `remove_exclude_list`,
  bulk `register_exclusions` / `unregister_exclusions` over `app["auth_exclude_list"]`.
- **Depends on**: existing `AUTH_EXCLUDE_LIST_KEY` / per-app list (verified §6).

### Module 2: navigator-auth exclude-provider callback
- **Path**: `../navigator-auth/navigator_auth/auth.py`
- **Responsibility**: `add_exclude_provider(async_fn)` registry + an
  `on_startup` hook that awaits each provider and registers yielded paths
  (restart re-hydration).
- **Depends on**: Module 1.

### Module 3: `is_authenticated` honors the exclude list
- **Path**: `../navigator-auth/navigator_auth/decorators.py`
- **Responsibility**: short-circuit to the handler when the request path matches
  `app["auth_exclude_list"]` (via `fnmatch`) or `request.allow_anonymous` is set,
  in both the function- and method-wrapper branches.
- **Depends on**: existing per-app list (no hard dep on M1/M2, but ships together).

### Module 4: `FormSchema.is_public` field
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py`
- **Responsibility**: add `is_public: bool = False`; ensure it round-trips through
  persistence and the existing extractors/renderers without breakage.
- **Depends on**: none (foundational).

### Module 5: public-path helper
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  (or `services/public_forms.py`)
- **Responsibility**: pure `public_form_paths(form_id, base_path)` returning the
  five patterns above; single source of truth used by both M6 and M7.
- **Depends on**: Module 4 (conceptually); no runtime dep.

### Module 6: lifecycle toggle integration
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`
  (centralized in `register` / `delete`), consumed by
  `api/handlers.py` (`create_form`/`update_form`/`patch_form`/`publish_form`/`delete_form`)
- **Responsibility**: diff old-vs-new `is_public`; on `False→True` call
  `app["auth"].register_exclusions(public_form_paths(...))`; on `True→False` or
  delete-of-public call `unregister_exclusions(...)`. No-op when `app["auth"]`
  is absent (formdesigner must remain runnable without the auth handler mounted).
- **Depends on**: Module 1, Module 4, Module 5.

### Module 7: exclude-provider registration (restart re-hydration)
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`
  (in `setup_form_api`)
- **Responsibility**: register a provider with `app["auth"].add_exclude_provider`
  that lists persisted `is_public=True` forms and yields their public paths.
- **Depends on**: Module 2, Module 5; uses `FormRegistry.list_forms`.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_remove_exclude_list_idempotent` | M1 | remove on absent path is a no-op; remove drops the pattern |
| `test_add_exclude_list_idempotent` | M1 | adding a duplicate path does not create duplicates |
| `test_register_unregister_exclusions_bulk` | M1 | bulk add/remove of N paths |
| `test_exclude_provider_invoked_on_startup` | M2 | registered provider's yielded paths land in `app["auth_exclude_list"]` after startup |
| `test_is_authenticated_short_circuits_on_excluded_path` | M3 | anonymous request to an excluded path reaches the handler (no 401) |
| `test_is_authenticated_still_401_on_protected_path` | M3 | non-excluded path still 401s anonymous |
| `test_formschema_is_public_default_false` | M4 | new field defaults to False and round-trips |
| `test_public_form_paths` | M5 | returns the five expected patterns incl. `/render/*` glob |
| `test_register_toggle_on_make_public` | M6 | False→True registers paths via `app["auth"]` |
| `test_unregister_toggle_on_make_private` | M6 | True→False unregisters paths |
| `test_unregister_on_delete_public_form` | M6 | deleting a public form unregisters its paths |
| `test_toggle_noop_without_auth_handler` | M6 | no error when `app["auth"]` is absent |
| `test_provider_yields_persisted_public_forms` | M7 | provider lists only `is_public=True` forms |

### Integration Tests
| Test | Description |
|---|---|
| `test_public_form_anonymous_access_end_to_end` | A public form's `/schema`, `/render/*`, `/data`, `/validate`, and GET are reachable anonymously through a real auth-mounted aiohttp app; a private form's are 401 |
| `test_public_paths_survive_restart` | After re-running `AuthHandler.setup` + startup, a persisted public form's paths are exempt again |

### Test Data / Fixtures
```python
@pytest.fixture
def public_form() -> FormSchema:
    return FormSchema(form_id="contact", title=..., sections=[...], is_public=True)
```

---

## 5. Acceptance Criteria

- [ ] `FormSchema.is_public` exists, defaults to `False`, and round-trips through persistence.
- [ ] navigator-auth `AuthHandler` exposes idempotent `add_exclude_list`,
      `remove_exclude_list`, `register_exclusions`, `unregister_exclusions`.
- [ ] navigator-auth `AuthHandler.add_exclude_provider` + an `on_startup` hook
      re-register provider paths after a restart.
- [ ] `is_authenticated` returns the handler result (no 401) for an anonymous
      request whose path is in `app["auth_exclude_list"]`, and still 401s for
      non-excluded paths.
- [ ] Making a form public registers exactly the five public paths; making it
      private or deleting it unregisters them.
- [ ] The toggle is a no-op (no exception) when `app["auth"]` is not mounted.
- [ ] End-to-end: a public form is anonymously reachable on GET form, `/schema`,
      `/render/*`, POST `/data`, POST `/validate`; a private form is not.
- [ ] Public exemptions survive a server restart (provider re-hydration).
- [ ] No breaking change to existing `add_exclude_list` callers
      (`backends/*`, `adfs`, `oauth2`, `basic`, `external`).
- [ ] All unit tests pass (`pytest tests/unit/ -v` in each repo).
- [ ] Integration tests pass.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** References verified this session.
> navigator-auth entries are in the **sibling repo** `../navigator-auth`.

### Verified Imports
```python
# parrot-formdesigner (this repo)
from parrot_formdesigner.core.schema import FormSchema        # verified: core/schema.py:267
from parrot_formdesigner.services.registry import FormRegistry # verified: services/registry.py
from parrot_formdesigner.api.routes import setup_form_api      # verified: api/routes.py:92

# navigator-auth (../navigator-auth) — already a HARD dep of parrot-formdesigner (api/routes.py:34)
from navigator_auth.decorators import is_authenticated, user_session  # verified: decorators.py:126,74
from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY          # verified: conf.py:45  (= "auth_exclude_list")
```

### Existing Class Signatures
```python
# ../navigator-auth/navigator_auth/auth.py
class AuthHandler:
    def __init__(self, app_name: str = "auth", secure_cookies: bool = True, **kwargs): ...  # line 69 → app["auth"]
    def setup(self, app: web.Application) -> web.Application:                                 # line 505
        self.app[AUTH_EXCLUDE_LIST_KEY] = list(exclude_list)                                 # line 535 (mutable list, re-seeded each boot)
        self.app[self.name] = self                                                           # line 537
        self.app.on_startup.append(self.auth_startup)                                        # line 530 (existing startup hook)
    def add_exclude_list(self, path: str):                                                   # line 666 (append; NOT idempotent today)
        self.app[AUTH_EXCLUDE_LIST_KEY].append(path)
    async def verify_exceptions(self, request) -> bool:                                      # line 669 (request-time fnmatch over the list)

# ../navigator-auth/navigator_auth/middlewares/abstract.py
class base_middleware(ABC):
    exclude_routes: tuple = tuple()                       # line 23 — FROZEN per-middleware tuple (NOT the hook; non-goal)
    def excluding_routes(self, request): ...              # line 46 — fnmatch.fnmatch(request.path, path)

# ../navigator-auth/navigator_auth/conf.py
AUTH_EXCLUDE_LIST_KEY = "auth_exclude_list"               # line 45
exclude_list = EXCLUDE_DEFAULTS + [...]                   # line 58 — default seed (list)

# ../navigator-auth/navigator_auth/decorators.py
def is_authenticated(content_type="application/json"):    # line 126 — checks only request["authenticated"], else 401 (line 169)
def allow_anonymous(handler):                             # line 42 — sets request.allow_anonymous = True
def user_session():                                       # line 74

# packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py
class FormSchema(BaseModel):                              # line 267
    form_id: str                                          # line 300
    form_type: FormType = FormType.SIMPLE                 # line 313
    published_version: str | None = None                 # line 315  (NO is_public today)

# packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py
class FormRegistry:
    async def register(self, form: FormSchema, *, persist=False, overwrite=True, tenant=None) -> None:  # line 262
    async def delete(self, form_id: str, *, tenant=None) -> bool:                                       # line 103
    async def get(self, form_id: str, *, tenant=None) -> FormSchema | None:                             # line 575
    async def list_forms(self, *, tenant=None) -> list[FormSchema]:                                     # line 591
    async def on_startup(self, app) -> None:                                                            # line 371
    @property
    def has_storage(self) -> bool:                                                                       # line 833

# packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py
def setup_form_api(app, registry, *, base_path="/api/v1", ...) -> None:   # line 92
def _wrap_auth(handler):  # line 67 — applies user_session() + is_authenticated() to EVERY route (200-349)

# packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py
class FormAPIHandler:
    async def create_form(self, request): ...    # line 741
    async def get_schema(self, request): ...      # line 596
    async def update_form(self, request): ...     # line 915 (existing = await registry.get; then registry.register, line 959)
    async def patch_form(self, request): ...      # line 963
    async def delete_form(self, request): ...     # line 1014
    async def submit_data(self, request): ...     # line 1061
    async def publish_form(self, request): ...    # line 1437
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `FormRegistry.register` toggle | `AuthHandler.register/unregister_exclusions` | `request.app["auth"].…(paths)` | auth.py:537 (`app["auth"]`), registry.py:262 |
| exclude-provider | `AuthHandler.add_exclude_provider` | `app["auth"].add_exclude_provider(fn)` | routes.py:92, auth.py (NEW) |
| `public_form_paths` | `AUTH_EXCLUDE_LIST_KEY` list | path strings registered into the list | conf.py:45, auth.py:535 |
| `is_authenticated` exemption | `app["auth_exclude_list"]` | `fnmatch` over `request.app.get(KEY)` | decorators.py:126, auth.py:535 |

### Does NOT Exist (Anti-Hallucination)
- ~~`frozenset` anywhere in `navigator_auth`~~ — grep returned zero; the exclude list is a mutable `list`.
- ~~`AuthHandler.remove_exclude_list`~~ — **to be created** (M1). Only `add_exclude_list` exists today.
- ~~`AuthHandler.register_exclusions` / `unregister_exclusions`~~ — **to be created** (M1).
- ~~`AuthHandler.add_exclude_provider`~~ and any provider-invocation startup hook — **to be created** (M2).
- ~~`is_authenticated` consulting the exclude list / `allow_anonymous`~~ — does NOT happen today; **to be added** (M3).
- ~~`FormSchema.is_public`~~ — **to be created** (M4); no `is_public` exists anywhere in the package today.
- ~~Any existing exclude/anonymous wiring in parrot-formdesigner~~ — none exists (clean greenfield integration).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mutate the **existing** `app[AUTH_EXCLUDE_LIST_KEY]` list — mirror the idiom of
  the current `add_exclude_list` (auth.py:666). Do not touch `base_middleware.exclude_routes`.
- `fnmatch` patterns are globs — use `/render/*`; keep other paths exact.
- Centralize the toggle in `FormRegistry.register` / `.delete`, not in the four
  handlers, to avoid drift; diff `is_public` against `registry.get(...)`.
- Derive paths from the SAME `base_path` `setup_form_api` mounted with, or
  exemptions silently won't match.
- async-first throughout; the exclude-provider callback is `async`.
- Toggle and provider must degrade gracefully when `app["auth"]` is absent.

### Known Risks / Gotchas
- **Two-repo, ordered rollout.** navigator-auth (M1–M3) must ship before
  parrot-formdesigner relies on the new API; parrot-formdesigner already
  hard-imports navigator-auth (routes.py:34). Pin a minimum navigator-auth
  version (§8).
- **Restart loss.** The exclude list is re-seeded from defaults every boot
  (auth.py:535); without the provider (M2/M7) all runtime exemptions vanish on
  restart. The provider is mandatory, not optional.
- **Stale exemptions on delete.** `delete_form` MUST unregister, else a deleted
  public form's URLs remain anonymous (resolved — see §8).
- **Backward compatibility.** Making `add_exclude_list` idempotent must not break
  existing callers (`backends/external.py`, `adfs.py`, `oauth2/backend.py`,
  `basic.py`) that append today.
- **Setup ordering.** `setup_form_api` must run after `AuthHandler.setup` so
  `app["auth"]` exists when the provider is registered; otherwise register the
  provider lazily / guard for absence.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `navigator-auth` | `>= <coordinated release>` | new `remove_exclude_list` / bulk / provider API + `is_authenticated` exemption (§8) |

---

## 8. Open Questions

### Resolved (carried forward from the proposal — do not re-open)

- [x] **Which form URLs become anonymous when `is_public=True`?** —
  *Resolved in proposal*: `GET /forms/{id}`, `GET /forms/{id}/schema`,
  `GET /forms/{id}/render/*`, `POST /forms/{id}/data`, `POST /forms/{id}/validate`.
  (Reflected in §2 New Public Interfaces, §3 M5, §5.)
- [x] **How to bypass the handler-level `is_authenticated`?** —
  *Resolved in proposal*: navigator-auth's `is_authenticated` honors the exclude
  list / `allow_anonymous` (global fix). (Reflected in §3 M3, §6, §5.)
- [x] **Who re-hydrates the in-memory exclude list on restart?** —
  *Resolved in proposal*: a navigator-auth exclude-provider callback invoked on
  `on_startup`; parrot-formdesigner supplies one yielding persisted public-form
  paths. (Reflected in §3 M2/M7.)
- [x] **What navigator-auth API to add?** — *Resolved in proposal*: idempotent
  `add_exclude_list` + `remove_exclude_list` + bulk
  `register_exclusions`/`unregister_exclusions`. (Reflected in §3 M1, §2.)
- [x] **Should `delete_form` also unregister exempt paths?** — *Resolved*: yes —
  deleting a public form unregisters its paths so its URLs do not remain
  anonymous. (Reflected in §3 M6, §5, §7.)

### Unresolved (decide before/with the navigator-auth release)

- [ ] **Minimum navigator-auth version & two-repo release ordering** — *Owner: Jesus Lara*.
  Pin the exact navigator-auth version in parrot-formdesigner's dependency
  constraint once the navigator-auth PR (M1–M3) is tagged.

---

## Worktree Strategy

- **Isolation unit: mixed (cross-repo).**
- **parrot-formdesigner tasks (M4–M7)** run sequentially in one ai-parrot
  worktree branched from `dev`:
  ```bash

…(truncated)…
