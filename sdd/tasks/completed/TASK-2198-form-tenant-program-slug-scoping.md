# TASK-2198: Host middleware declares browsed programme as form tenant_context

**Feature**: FEAT-421 — Host middleware declares browsed programme as form tenant
**Spec**: `sdd/specs/FEAT-421-form-tenant-program-slug-scoping.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none (builds on merged #1146)
**Assigned-to**: claude-session (fork PR)

---

## Context

#1146 made `FormAPIHandler._get_tenant` honor `request["tenant_context"]` over the
session's `programs[0]`, on the principle that authorizing a `program_slug` claim
is the HOST's job, not the library's. But nothing sets `tenant_context` for the
forms API, so `_get_tenant` still falls back to `programs[0]` and AI-created/edited
forms land under the user's first program (`navigator`) instead of the browsed
programme → 404 (NAV-9372 create, NAV-9370 edit/save). This task adds the host half.

---

## Scope

- Add `forms_tenant_context_middleware` to `app.py`: read `?program_slug`, authorize
  it against the caller's session (member of the programme OR superuser), and only
  then set `request["tenant_context"]`.
- Register it via `self.app.middlewares.append(...)` after `auth.setup(self.app)` so
  `request.session` is populated when it runs.
- Add `from aiohttp import web` import.
- Write authz-boundary tests.

**NOT in scope**: any parrot-formdesigner change (#1146 already did its half);
navigator-svelte (already sends `program_slug`); NAV-9329's activity-types (a
fieldsync host — separate change); the tenant backfill of already mis-tenanted forms.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `app.py` | MODIFY | `forms_tenant_context_middleware` + import + registration after auth |
| `tests/test_forms_tenant_context_middleware.py` | CREATE | 6 tests: member / superuser / non-member / no-slug / no-session / empty-programs |

---

## Test Criteria

- `pytest tests/test_forms_tenant_context_middleware.py -v` green (ai-parrot CI).
- member/superuser → `tenant_context` declared; non-member/no-slug/no-session → not set.

## Verification performed

- `python -m py_compile` clean (app.py + test).
- Middleware authz logic validated via standalone repro (all cases pass).
- Full suite NOT run on author machine (Python 3.10 < required 3.11; monorepo deps
  absent) — must run in ai-parrot CI.
