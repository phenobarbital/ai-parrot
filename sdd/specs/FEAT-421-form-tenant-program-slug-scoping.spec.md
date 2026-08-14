---
type: feature
base_branch: dev
---

# Feature Specification: Host middleware declares browsed programme as form tenant

**Feature ID**: FEAT-421
**Date**: 2026-08-13
**Author**: José Mendoza + Claude (fork PR for the parrot owner's review)
**Status**: review — implemented in fork (host middleware + tests)
**Target version**: 1.x
**Jira**: NAV-9372, NAV-9370 (NAV-9329 activity-types is a fieldsync host — see §7)
**Related**: #1146 (parrot-formdesigner honors `request["tenant_context"]`), FEAT-466 (navigator-svelte program-slug)

---

## 1. Motivation

navigator-svelte sends the browsed programme as `?program_slug=<slug>` on every
forms call (FEAT-466). Before #1146, `FormAPIHandler._get_tenant` resolved the
tenant from `session.programs[0]` (the user's FIRST program) and ignored
`program_slug`, so a superuser browsing *epson* created/edited forms under
*navigator* → 404 on the follow-up load/save (NAV-9372 create, NAV-9370 edit).

**#1146 already did the parrot-library half correctly**: `_get_tenant` now prefers
`request["tenant_context"]` — a tenant the HOST resolves AND authorizes — over
`programs[0]`, on the explicit principle that *authorizing* a `program_slug` claim
"cannot be this library's job" (parrot doesn't know the host's entitlement model).

**The missing half is the host**: nothing sets `request["tenant_context"]` for the
forms API, so `_get_tenant` still falls back to `programs[0]` and the bug persists.
This spec adds that host piece.

## 2. Design

`app.py` (the aiohttp host that mounts `setup_form_api` and runs `navigator_auth`)
gains a middleware `forms_tenant_context_middleware`:

1. Reads `?program_slug` from the request.
2. Reads the caller's session (`request.session["session"]`): `programs` + `superuser`.
3. Authorizes the claim: the caller must be a **member** of that programme
   (`program_slug in programs`) OR a **superuser**.
4. Only if authorized, sets `request["tenant_context"] = program_slug`.

Registered **after** `auth.setup(self.app)` so `request.session` is populated when
it runs. parrot's `_get_tenant` (#1146) then honors it → create/read/write scope to
the browsed programme. A non-member's claim is ignored (no cross-tenant access);
parrot falls back to its existing behavior.

```python
@web.middleware
async def forms_tenant_context_middleware(request, handler):
    program_slug = request.query.get("program_slug")
    if program_slug:
        session = getattr(request, "session", None)
        if session is not None:
            userinfo = session.get("session", {}) or {}
            programs = userinfo.get("programs", []) or []
            is_superuser = bool(userinfo.get("superuser", False))
            if is_superuser or program_slug in programs:
                request["tenant_context"] = program_slug
    return await handler(request)
```

### Why the host, not the library
This mirrors #1146's rationale and `_utils._get_request_tenant` step 0: the host
owns the entitlement model (navigator-auth session), so it is the only layer that
can authorize a `program_slug` claim. parrot stays entitlement-agnostic.

## 3. Files

| File | Action | Description |
|---|---|---|
| `app.py` | MODIFY | `forms_tenant_context_middleware` + `from aiohttp import web`; append it after `auth.setup` |
| `tests/test_forms_tenant_context_middleware.py` | CREATE | authz boundary tests (member / superuser / non-member / no-slug / no-session / empty) |

## 4. Acceptance Criteria
- [ ] A member browsing programme X → `tenant_context == X` → forms create/load/save under X.
- [ ] A superuser → any browsed programme is declared.
- [ ] A non-member / no `program_slug` / no session → `tenant_context` NOT set (no cross-tenant access; parrot falls back).
- [ ] Middleware runs after `AuthHandler` (session populated).
- [ ] `pytest tests/test_forms_tenant_context_middleware.py -v` green (ai-parrot CI).

## 5. Codebase Contract (verified on origin/dev 2026-08-13)
- `_get_tenant` prefers `request["tenant_context"]` (#1146, handlers.py ~281-285) then `programs[0]` then `default_tenant`.
- Nothing sets `request["tenant_context"]` for forms (grep: only a test does) → the fix.
- `app.py` mounts forms via `setup_form_api` and auth via `AuthHandler().setup()`; middlewares appended with `self.app.middlewares.append(...)` (pattern: `a2a/security.py:1426`).
- Session shape: `request.session["session"]["programs" | "superuser"]` (formdesigner `_get_programs`; ai-parrot-server `abstract.py:508`).

### Does NOT change
- parrot-formdesigner (#1146 already did its half); navigator-svelte (already sends `program_slug`).

## 6. Verification performed (author machine)
- `python -m py_compile app.py` + test file: clean.
- Middleware authz logic validated with a standalone repro (all cases pass).
- Full suite NOT run locally (Python 3.10 < required 3.11; monorepo deps not installed) — must run in ai-parrot CI.

## 7. Follow-ups (out of scope here)
- **NAV-9329** (form activity-types 404) is served by a DIFFERENT host (**fieldsync**
  `apps/formtypes`), not this app. It needs the equivalent host-side `program_slug`
  authorization there — separate change in fieldsync.
- One-time tenant backfill of forms already stored under `navigator` (FEAT-466 / navigator-svelte TASK-2198).

## Revision History
| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-08-13 | José Mendoza + Claude | Host middleware approach (aligned with merged #1146); supersedes the earlier parrot-side draft |
