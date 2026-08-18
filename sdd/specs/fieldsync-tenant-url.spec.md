---
type: feature
base_branch: dev
---

# Feature Specification: Remove `/t/` marker from tenant-qualified URLs

**Feature ID**: FEAT-429
**Date**: 2026-08-18
**Author**: Jesus Lara + Claude
**Status**: draft
**Target version**: parrot-formdesigner 0.9.0 (amends FEAT-421 before first production release)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-421 introduced a `/t/{tenant}/` URL prefix on every FormDesigner forms
route — e.g. `/api/v1/t/flexroc/forms/{form_uid}`. The literal `t` segment
was added as a router-disambiguation marker: without it, a bare
`/api/v1/{tenant}/forms` at the same tree level as `/api/v1/org/graph` was
considered risky because `{tenant}` is dynamic while `org` is literal, and
the two share position 3 in the URL hierarchy.

In practice the disambiguation is unnecessary: aiohttp's `UrlDispatcher`
resolves literal resource nodes before dynamic ones at every tree level, so
`/api/v1/org/graph` always matches the literal `org` branch before the
`{tenant}` catch-all is considered. The `/t/` marker therefore adds a URL
segment that serves no structural purpose, complicates every client URL
template, and doubles the migration effort — consumers update once for
`/t/{tenant}`, then a second time when `/t/` is eventually cleaned up.

Since both **Fieldsync** (the middleware host) and **navigator-svelte** (the
frontend) are being repaired in parallel as part of the FEAT-421 coordinated
deploy — neither has shipped the `/t/{tenant}/` URLs to production yet — the
cleanest path is to remove `/t/` now, before any consumer has adopted it.
One migration, not two. Hard cut, no backward compatibility for the
`/t/{tenant}/` shape.

### Goals

- **G1** — Remove the literal `/t/` segment from every forms URL (REST API,
  HTML pages, Telegram WebApp, audio WS). Resulting URL shape:
  `/api/v1/{tenant}/forms/...` (API), `/{tenant}/...` (UI).
- **G2** — Preserve every FEAT-421 semantic unchanged: the `requires_tenant`
  decorator, session-based authorization, error contract
  (`tenant_not_declared` / `tenant_forbidden` / `tenant_conflict`), the
  POST-body cross-check, the `/org/*` carve-out (G7/AC11), the public-form
  authorization gap closure (`enforce_membership_unless_public`).
- **G3** — Update every client-facing URL reference: error hint messages,
  response-body `"url"` fields, renderer upload-URL templates, `public_form_paths`
  globs, and the migration guide.
- **G4** — Hard cut from the `/t/{tenant}/` format. Old `/t/`-prefixed
  routes are not registered — they return a router-level 404.
- **G5** — `/org/*` routes remain byte-identical and un-prefixed (unchanged
  from FEAT-421 G7).

### Non-Goals (explicitly out of scope)

- Changing any FEAT-421 behavior (decorator logic, authorization, error
  semantics, `_session_tenant`, `_assert_form_tenant`).
- Touching `/org/*` routes or their handlers.
- Re-engineering the `requires_tenant` decorator or `_wrap_auth`.
- Introducing backward-compatible routing for the old `/t/` format.
- A version bump beyond 0.9.0 — this is an amendment to FEAT-421's URL
  shape before 0.9.0 reaches production.
- Reserving tenant slugs against literal route prefixes (e.g. preventing a
  programme named `"org"`) — see §7 Known Risks.

---

## 2. Architectural Design

### Overview

This is a **URL-format-only change**. All FEAT-421 plumbing — the
`requires_tenant` decorator, `declared_tenant()`, `assert_body_tenant_matches()`,
`enforce_membership_unless_public()`, `_session_tenant()`, the typed errors,
the `_wrap_auth(tenant=...)` composition — remains structurally and
behaviorally identical. The only things that change are:

1. **Route registration prefixes**: `f"{bp}/t/{{tenant}}"` →
   `f"{bp}/{{tenant}}"` in `api/routes.py` and `ui/routes.py`.
2. **Hardcoded URL strings** in response bodies, renderer templates, error
   hints, public-form globs, docstrings, log messages, and comments that
   embed the `/t/` marker.
3. **Test assertions** referencing the old URL shape.
4. **The migration guide** for consumers.

### Router Ambiguity Analysis

With `/t/` removed, the tenant segment sits at the same URL tree level as
the `org` and `form-controls` literals:

```
/api/v1/{tenant}/forms           ← dynamic segment at position 3
/api/v1/{tenant}/fields          ← dynamic segment at position 3
/api/v1/org/graph                ← literal "org" at position 3
/api/v1/org/stores/{store_id}/…  ← literal "org" at position 3
/api/v1/form-controls            ← literal "form-controls" at position 3
```

**aiohttp's `UrlDispatcher` is a trie**: at every tree node, literal child
nodes are tested before the dynamic (variable) child. Therefore:

- `GET /api/v1/org/graph` → matches literal `org` → literal `graph`. ✓
- `GET /api/v1/form-controls` → matches literal `form-controls`. ✓
- `GET /api/v1/flexroc/forms` → no literal match for `flexroc` → matches
  `{tenant}` → literal `forms`. ✓

The only residual risk: a tenant slug that *equals* a reserved literal
(e.g., a programme named `"org"`). A request to `/api/v1/org/forms` would
match the literal `org` branch, find no `/org/forms` route, and 404 — the
`{tenant}` branch is never reached. This is a **non-issue in practice**
(programme slugs are organization names, never router keywords), but
documented in §7 as a known edge case worth logging.

For UI routes (`base_path=""`), `/{tenant}/` is the only dynamic root. Any
host-level literal routes (`/health`, `/api/...`) take priority
automatically.

### Component Diagram

```
BEFORE (FEAT-421):                         AFTER (FEAT-429):
/api/v1/t/{tenant}/forms/…                 /api/v1/{tenant}/forms/…
/api/v1/t/{tenant}/fields                  /api/v1/{tenant}/fields
/t/{tenant}/                               /{tenant}/
/t/{tenant}/gallery                        /{tenant}/gallery
/t/{tenant}/forms/{form_uid}/telegram      /{tenant}/forms/{form_uid}/telegram
/api/v1/t/{tenant}/forms/…/telegram-submit /api/v1/{tenant}/forms/…/telegram-submit

UNCHANGED:
/api/v1/org/*                              /api/v1/org/*
/api/v1/form-controls                      /api/v1/form-controls
```

Internal plumbing (decorator chain, handler methods, registry) is
**identical** — only the URL string changes.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `setup_form_api` (`api/routes.py:116`) | modifies | `tp` variable drops `/t/` |
| `setup_form_ui` (`ui/routes.py:105`) | modifies | `tp` variable drops `/t/`; telegram-submit route too |
| `_EXPECTED_HINT` (`api/tenant.py:36`) | modifies | string update |
| `TenantNotDeclaredError` docstring (`api/errors.py:11`) | modifies | example URL |
| `FormAPIHandler` response URLs (`api/handlers.py`) | modifies | 4 f-string sites |
| `public_form_paths` (`services/public_forms.py:46`) | modifies | glob pattern |
| `html5.py` upload URL template (`:1105`) | modifies | client-side placeholder |
| `jsonschema.py` upload URL template (`:468`) | modifies | client-side placeholder |
| `TelegramWebAppHandler` URLs (`ui/telegram.py`) | modifies | URL construction + docstrings |
| `requires_tenant` decorator | **unchanged** | reads `request.match_info["tenant"]` — same key |
| `declared_tenant()` | **unchanged** | reads `request["tenant"]` — same key |
| `_wrap_auth` | **unchanged** | composition logic untouched |
| `/org/*` routes | **unchanged** | still mounted at `f"{bp}/org/..."` |
| `form-controls` route | **unchanged** | still mounted at `f"{bp}/form-controls"` |

### Data Models

No new data models. All FEAT-421 error types (`TenantNotDeclaredError`,
`TenantForbiddenError`, `TenantConflictError`) are unchanged in structure —
only the `expected` hint string embedded in their bodies is updated.

---

## 3. Module Breakdown

### Module 1: Route table — drop `/t/` from route registration

- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py`,
  `packages/parrot-formdesigner/src/parrot_formdesigner/ui/routes.py`
- **Responsibility**:
  - `api/routes.py:233` — change `tp = f"{bp}/t/{{tenant}}"` to
    `tp = f"{bp}/{{tenant}}"`. Update the FEAT-421 comment block above it.
  - `api/routes.py:357` — update the log message.
  - `ui/routes.py:136` — same `tp` change.
  - `ui/routes.py:169` — telegram-submit route: `/api/v1/t/{tenant}/…` →
    `/api/v1/{tenant}/…`.
  - Update all comments referencing `/t/{tenant}` in both files.
- **Depends on**: nothing.

### Module 2: URL pattern references in source

- **Path**: `api/tenant.py`, `api/errors.py`, `api/handlers.py`,
  `services/public_forms.py`, `renderers/html5.py`, `renderers/jsonschema.py`,
  `ui/telegram.py`
- **Responsibility**: Mechanical `/t/` removal from every hardcoded URL
  string, f-string, docstring, and comment that embeds the old pattern.
  Specific sites:
  - `api/tenant.py:36` — `_EXPECTED_HINT`: drop `/t/`
  - `api/errors.py:11` — docstring example
  - `api/handlers.py:265` — docstring
  - `api/handlers.py:1051,1105,1175,1788` — response-body `"url"` f-strings
  - `api/handlers.py:1179` — docstring
  - `services/public_forms.py:3,39-43,46` — module docstring + glob
    construction
  - `renderers/html5.py:543` — comment
  - `renderers/html5.py:1105` — upload URL template (client-side placeholder)
  - `renderers/jsonschema.py:468` — upload URL template (client-side placeholder)
  - `ui/telegram.py:50,77,91` — docstrings + URL construction
- **Depends on**: nothing (can run in parallel with Module 1, but sequenced
  for simplicity).

### Module 3: Test suite migration

- **Path**: `packages/parrot-formdesigner/tests/` (~60 references across
  ~15 test files)
- **Responsibility**: Update every `/t/{tenant}/` URL pattern in test
  assertions, route registrations, and comments. **Key files**:
  - `unit/api/test_setup_form_api.py` — route path assertions
  - `unit/api/test_setup_form_api_rest.py` — REST route assertions
  - `unit/api/test_route_tenant_coverage.py` — coverage introspection
  - `unit/api/test_tenant_errors.py` — error `expected` field
  - `unit/ui/test_setup_form_ui_routes.py` — UI route assertions
  - `unit/ui/test_setup_form_ui_protect_pages.py` — handler lookup by path
  - `unit/services/test_public_forms.py` — glob assertions
  - `integration/test_registry_multi_tenancy_e2e.py` — route registration
  - `integration/test_render_xml.py`, `test_render_pdf.py` — render routes
  - `integration/test_operations_e2e.py` — operations route
  - `integration/test_clone_rest.py` — clone route
  - `integration/test_upload_rest.py` — upload route
  - `integration/test_field_uid_flows.py` — operations + upload routes

  **Regression net**: after updating, `test_route_tenant_coverage.py:75`
  (`assert not any("/t/" in p for p in paths)`) must STILL pass — it
  verifies that `/org/*` routes do NOT carry the tenant prefix. The
  assertion stays correct because `/org/*` routes never had `/t/` and
  still won't have `/{tenant}/`.
- **Depends on**: Modules 1, 2 (tests must reference the new URL shape to
  pass against the updated source).

### Module 4: Migration guide update

- **Path**: `docs/migration/feat-421-forms-tenant-in-url.md`
- **Responsibility**: Update the existing migration guide **in place** (FEAT-421
  has not shipped to production). Changes:
  - All URL examples: `/t/{tenant}/` → `/{tenant}/`
  - The "Old → new URL table": Old column stays (0.8.x), New column
    changes from `/t/{tenant}/` to `/{tenant}/`
  - The error contract `expected` examples
  - Add a note explaining FEAT-429 amended the URL shape before release
  - The "coordinated deploy checklist" item about `/t/{tenant}/`
- **Depends on**: Modules 1, 2 (the guide must reflect the final URL shape).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_forms_routes_use_tenant_segment` | 1 | Every forms route contains `/{tenant}/` and no `/t/{tenant}/` |
| `test_org_routes_unchanged` | 1 | All `/org/*` routes are byte-identical to pre-change |
| `test_form_controls_unchanged` | 1 | `/form-controls` path is unchanged |
| `test_expected_hint_no_t_prefix` | 2 | `_EXPECTED_HINT` is `/api/v1/{tenant}/forms/{form_uid}` |
| `test_public_form_paths_no_t_prefix` | 2 | Globs use `/{tenant}/`, not `/t/{tenant}/` |
| `test_upload_url_template_no_t_prefix` | 2 | Both renderers emit `/{tenant}/` in upload URL |
| `test_no_t_prefix_in_source` | 3 | `grep -rn "/t/{tenant}" src/` returns zero hits (belt-and-braces) |

### Integration Tests

| Test | Description |
|---|---|
| `test_legacy_t_prefix_url_is_404` | `GET /api/v1/t/flexroc/forms` → 404 (old URL not registered) |
| `test_new_url_resolves` | `GET /api/v1/flexroc/forms/{uid}` → 200 (new URL works) |
| `test_org_routes_unaffected` | All `/org/*` endpoints respond identically |

### Test Data / Fixtures

Existing FEAT-421 fixtures (`session_programs`, `two_tenant_registry`) are
reused unchanged — only the URL strings in test request calls change.

---

## 5. Acceptance Criteria

- [ ] **AC1** — Every forms route is mounted under `{base_path}/{tenant}/`.
      No route contains the literal `/t/` segment.
- [ ] **AC2** — `grep -rn '"/t/{tenant}\|/t/{{tenant}}\|/t/' packages/parrot-formdesigner/src/`
      returns zero hits (excluding this spec and git history).
- [ ] **AC3** — All `/org/*` route paths are byte-identical to their FEAT-421
      state. No `/org/*` test file is modified (G5).
- [ ] **AC4** — `/api/v1/form-controls` path is unchanged.
- [ ] **AC5** — `requires_tenant` decorator, `declared_tenant()`,
      `assert_body_tenant_matches()`, `enforce_membership_unless_public()` —
      function bodies are **not modified** (only the `_EXPECTED_HINT` string
      is updated).
- [ ] **AC6** — Error responses (`tenant_not_declared`, `tenant_forbidden`,
      `tenant_conflict`) include the corrected `expected` URL pattern
      without `/t/`.
- [ ] **AC7** — `public_form_paths()` emits globs using `/{tenant}/`, not
      `/t/{tenant}/`.
- [ ] **AC8** — Response-body `"url"` fields in create/edit/clone/publish
      handlers use the new URL shape.
- [ ] **AC9** — Renderer upload URL templates (`html5.py`, `jsonschema.py`)
      use `/{tenant}/`, not `/t/{tenant}/`.
- [ ] **AC10** — The migration guide at `docs/migration/feat-421-forms-tenant-in-url.md`
      reflects the final (post-FEAT-429) URL shape.
- [ ] **AC11** — Full package suite green:
      `pytest packages/parrot-formdesigner/tests/ -v`.
- [ ] **AC12** — `ruff check packages/parrot-formdesigner/` clean.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.**
> All line numbers verified on branch `dev` at merge commit including
> `c42c40868` (formdesigner clone slug collision fix).

### Verified Imports

```python
from ..api.tenant import requires_tenant        # ui/routes.py:27
from .tenant import requires_tenant             # api/routes.py:43
from .errors import (                           # api/tenant.py:26-30
    TenantConflictError,
    TenantForbiddenError,
    TenantNotDeclaredError,
)
from ..services.public_forms import public_form_paths  # api/routes.py:36
```

### Existing Class Signatures (unchanged by this spec)

```python
# api/tenant.py
_EXPECTED_HINT = "/api/v1/t/{tenant}/forms/{form_uid}"     # line 36 — CHANGE THIS

def requires_tenant(*, public: bool = False) -> ...:        # line 100 — DO NOT MODIFY BODY
def declared_tenant(request: web.Request) -> str:           # line 140 — DO NOT MODIFY BODY
def enforce_membership_unless_public(request, form, tenant): # line 163 — DO NOT MODIFY BODY
def assert_body_tenant_matches(body, tenant) -> None:       # line 194 — DO NOT MODIFY BODY

# api/routes.py
def _wrap_auth(handler, *, tenant="required") -> _Handler:  # line 72 — DO NOT MODIFY
def setup_form_api(app, registry, *, ...):                  # line 116
    bp = base_path.rstrip("/")                              # line 226
    tp = f"{bp}/t/{{tenant}}"                               # line 233 — CHANGE THIS

# ui/routes.py
def _page_wrap(handler, *, protect, tenant="required"):     # line 38 — DO NOT MODIFY
def setup_form_ui(app, registry, *, ...):                   # line 105
    bp = base_path.rstrip("/")                              # line 132
    tp = f"{bp}/t/{{tenant}}"                               # line 136 — CHANGE THIS
    # telegram-submit route                                 # line 169 — CHANGE THIS

# api/handlers.py
class FormAPIHandler:                                       # line 102
    # Response URL f-strings referencing /t/{tenant}:
    # line 1051: f"{prefix}/t/{tenant}/forms/{form.form_uid}"
    # line 1105: f"{prefix}/t/{tenant}/forms/{form_uid}"
    # line 1175: f"{prefix}/t/{tenant}/forms/{updated_form_uid}"
    # line 1788: f"{prefix}/t/{tenant}/forms/{form_uid}"

# api/errors.py
class TenantNotDeclaredError(web.HTTPBadRequest):           # line 22
    # docstring example at line 11 references /t/{tenant}

# services/public_forms.py
def public_form_paths(form_uid, tenant, base_path="/api/v1"):  # line 13
    base = f"{bp}/t/{tenant}/forms/{form_uid}"                 # line 46 — CHANGE THIS

# renderers/html5.py
# line 1105: f"/api/v1/t/{{tenant}}/forms/{{form_id}}/fields/{field.field_id}/upload"

# renderers/jsonschema.py
# line 468: "/api/v1/t/{tenant}/forms/{form_id}/fields/{field_id}/upload"

# ui/telegram.py
# line 77: f"{prefix}/api/v1/t/{tenant}/forms/{form_uid}/telegram-submit"
```

### Does NOT Exist (Anti-Hallucination)

- ~~a `ROUTE_PREFIX` constant or config option~~ — the `/t/` marker is
  inline in the `tp` f-string assignment, not extracted to a named constant.
- ~~`api/routes.py:_TENANT_PREFIX`~~ — does not exist; `_TENANT_MODES` is
  the tuple of mode strings (`"required"`, `"public"`, `"none"`), not a URL
  fragment.
- ~~`FormAPIHandler._build_url()`~~ — no such method; the response URLs are
  inline f-strings at each handler site.
- ~~`setup_form_api(tenant_prefix=...)`~~ — no such parameter.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Mechanical find-and-replace**: the change is `/t/{tenant}` → `/{tenant}`
  (and `/t/{{tenant}}` → `/{{tenant}}` in f-string escapes). Apply
  consistently across all files.
- **Preserve FEAT-421 comments** but update the URL examples within them.
  Do not delete the explanatory comments about why the tenant is in the URL
  — they still apply.
- **Preserve route registration order**: `POST /forms/blank` must still be
  registered before the `{form_uid}` catch-all (same constraint as FEAT-421).
- **Preserve the `_public_toggle` closure** in `api/routes.py:443+` — it
  calls `public_form_paths()` which is updated in Module 2. No structural
  change to the closure itself.

### Known Risks / Gotchas

- **Reserved-literal tenant slug collision**: if a programme slug exactly
  matches a literal route prefix (`org`, `form-controls`), requests to
  `/{slug}/forms` would hit the literal branch and 404. This is
  **extremely unlikely in practice** (programme slugs are organization names
  like `"flexroc"`, `"navigator"`, never router keywords). Mitigation: add
  a `WARNING`-level log in `requires_tenant` if the validated tenant matches
  a known reserved prefix. This is advisory, not blocking — do not reject
  the request, because a tenant named `"org"` that was somehow provisioned
  should still work via the `/org/*` branch not having a `/forms` sub-route.
  Actually: requests to `/api/v1/org/forms` would NOT match any `/org/*`
  route (there is no `org/forms` registered), so aiohttp would fall through
  to the `{tenant}` branch. **Verify this behavior in a test** (AC11 test
  suite covers it).
- **The 60 test references are the highest-effort item.** They are
  mechanical but numerous. A missed test URL produces a false-green (test
  hits the old route, gets a 404, and may still pass if the assertion is
  on status code rather than response body). Mitigate with the belt-and-
  braces grep in AC2.
- **Renderer upload URL templates are client-side placeholders** — `{tenant}`,
  `{form_id}`, `{field_id}` are substituted by the frontend `<RestUploader>`
  component. The update here ensures the template the frontend receives
  matches the actual route. If the frontend has already been updated for the
  `/t/{tenant}/` shape (FEAT-421 coordinated deploy), it must be updated
  again — but since the coordinated deploy hasn't shipped, both changes land
  simultaneously.
- **`_public_toggle` callback in `api/routes.py:443+`** calls
  `public_form_paths()`. Once Module 2 updates the glob construction, the
  callback automatically produces the correct patterns. No structural change
  to the callback. But verify: the `register_exclusions` patterns must match
  the actual routes — a mismatch silently breaks public-form access.

### External Dependencies

None. This spec adds no new dependencies — it only modifies URL strings.

---

## 8. Open Questions

All blocking questions are resolved.

- [x] URL shape after removing `/t/`? — *Resolved*: `/{tenant}/forms/...`
      (tenant replaces `t/{tenant}`). The `{tenant}` dynamic segment sits
      at the same tree level as `org` — safe because aiohttp matches
      literals before dynamics.
- [x] Version strategy? — *Resolved*: stay at 0.9.0. FEAT-421 hasn't
      shipped to production; this amends the URL shape before release.
      The migration guide is updated in place.
- [x] Backward compatibility for `/t/` format? — *Resolved by Jesus Lara*:
      hard cut, no backward compatibility. Old `/t/`-prefixed routes are
      not registered.
- [ ] **Q1 — Should the reserved-literal guard be a runtime log or a
      startup-time validation?** A startup check could reject a
      FormRegistry tenant list containing `"org"` or `"form-controls"`.
      A runtime log is less intrusive. Deferrable to implementation.
      — *Owner: implementation*

---

## Worktree Strategy

- **Default isolation unit**: `per-spec`. All modules run **sequentially**
  in one worktree.
- **Rationale**: Every module touches the same package. Modules 1–2 change
  the routes and URL strings; Module 3 updates the tests that validate them;
  Module 4 updates docs. No parallel seam.
- **Cross-feature dependencies**: FEAT-421 must be fully merged to `dev`
  first (it is — all 10 tasks completed and merged).
- **Suggested worktree**:
  ```bash
  git worktree add -b feat-429-fieldsync-tenant-url \
    .claude/worktrees/feat-429-fieldsync-tenant-url HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-18 | Jesus Lara + Claude | Initial draft — remove `/t/` marker from FEAT-421 tenant URLs before first production release |
