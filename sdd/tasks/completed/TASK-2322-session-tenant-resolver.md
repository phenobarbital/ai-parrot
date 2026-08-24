# TASK-2322: Session-derived tenant resolver (`handlers/crew/_tenancy.py`)

**Feature**: FEAT-446 — SaaS Auth Hardening (S0 of Parrot Research Cloud)
**Spec**: `sdd/specs/saas-auth-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2320
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 / Goals G2+G3. Tenant identity must come from the
authenticated session, never from body/query. This task builds the private
interim resolver that TASK-2323 wires into the crew handlers. S1 will
replace it with the core `TenantContext` + per-route decorator (FEAT-442
resolved question U1) — hence *private* (`_tenancy.py`), so no external
dependency can grow on it.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/handlers/crew/_tenancy.py` with:
  ```python
  async def resolve_session_tenant(
      request: web.Request, *, declared: str | None = None
  ) -> str
  ```
- Resolution order: explicit `tenant_id` claim in the userinfo session dict →
  `programs[0]` → no result.
- No result: `PARROT_SAAS_MODE=true` → raise `web.HTTPForbidden` (reason
  states the tenant could not be resolved); flag false → return `"global"`
  (legacy compatibility).
- `declared` (client-supplied tenant from body/query, passed by callers for
  the compatibility check): if not `None` and different from the resolved
  tenant → raise `web.HTTPBadRequest` (FEAT-421 `assert_body_tenant_matches`
  semantics). `declared` is NEVER the source of truth.
- Unit tests for the full matrix (claim priority, programs fallback,
  SaaS-403, legacy-global, declared-mismatch-400, declared-match passes).

**NOT in scope**: wiring into the handlers (TASK-2323), any `TenantContext`
dataclass or decorator (S1), superuser bypass logic (S1 — the interim
resolver treats everyone uniformly).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/crew/_tenancy.py` | CREATE | resolver |
| `packages/ai-parrot-server/tests/unit/test_crew_tenancy.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from aiohttp import web
from navigator_auth.conf import AUTH_SESSION_OBJECT   # lazy, fallback "userinfo" — pattern: parrot/auth/agent_guard.py:184-186
from navigator_session import get_session             # lazy fallback — pattern: agent_guard.py:190
from parrot.conf import PARROT_SAAS_MODE              # created by TASK-2320
```

### Existing Signatures to Use
```python
# Session access pattern (parrot/auth/agent_guard.py:192-199, verified):
session = getattr(request, "session", None)
# fallback: session = await get_session(request)
userinfo = session.get(AUTH_SESSION_OBJECT, {}) if session else {}

# Reference-only semantics to mirror (do NOT import — formdesigner is a
# sibling distribution): packages/parrot-formdesigner/src/parrot_formdesigner/api/tenant.py
#   _get_programs(request)              — programs from the same session dict
#   _authorize(request, tenant)         — membership check against programs
#   assert_body_tenant_matches(body, tenant)  — 400 on conflicting declaration
```

### Does NOT Exist
- ~~`PARROT_SAAS_MODE`~~ until TASK-2320 merges — this task depends on it;
  verify the import resolves before starting.
- ~~`parrot.tenancy` / `TenantContext` / `resolve_tenant` in core~~ — S1
  deliverables; do not create or import them.
- ~~`from parrot_formdesigner.api.tenant import ...`~~ — forbidden import
  direction (server package must not depend on formdesigner); the file is a
  pattern reference only.
- ~~a `superuser` bypass in this resolver~~ — deliberately omitted in S0.

---

## Implementation Notes

### Key Constraints
- Async, typed, Google docstrings; module-level `logger = logging.getLogger(__name__)`.
- The helper must not read the request body itself — callers extract any
  declared tenant and pass it in (`declared=`); this keeps body parsing in
  one place per handler and the resolver side-effect-free.
- Raise aiohttp `web.HTTPForbidden` / `web.HTTPBadRequest` directly (the
  crew handlers are `BaseView`s; raising web exceptions is the established
  short-circuit).
- Read `PARROT_SAAS_MODE` at call time (module-level import of the value is
  fine only if tests can monkeypatch it — prefer importing the module and
  reading the attribute, or a small `_saas_mode()` indirection, so
  `monkeypatch.setattr` works).

### References in Codebase
- `parrot/auth/agent_guard.py:163-200` — session/userinfo access pattern
- `parrot_formdesigner/api/tenant.py` — semantic reference (no import)
- `handlers/crew/execution_history_handler.py:89-150` — the half-migrated
  `_get_authenticated_user_id`/`_get_tenant_user` this replaces in TASK-2323

---

## Acceptance Criteria

- [ ] Claim beats `programs[0]`; `programs[0]` used when no claim
- [ ] Unresolvable + SaaS mode → 403; legacy mode → `"global"`
- [ ] `declared` mismatch → 400; match → resolved tenant returned
- [ ] `pytest packages/ai-parrot-server/tests/unit/test_crew_tenancy.py -v` green
- [ ] `ruff check` clean; no import of formdesigner or parrot.tenancy

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_crew_tenancy.py
import pytest

class TestResolveSessionTenant:
    async def test_claim_priority(self): ...
    async def test_programs_fallback(self): ...
    async def test_saas_mode_403(self, monkeypatch): ...
    async def test_legacy_global(self): ...
    async def test_declared_mismatch_400(self): ...
    async def test_declared_match_ok(self): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2320 is in `sdd/tasks/completed/`;
3. re-verify the contract; 4. index → `"in-progress"`; 5. implement;
6. verify; 7. move to `sdd/tasks/completed/`; 8. index → `"done"`;
9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-24
**Notes**: Created
`packages/ai-parrot-server/src/parrot/handlers/crew/_tenancy.py` with
`async def resolve_session_tenant(request, *, declared=None) -> str`.
Resolution order implemented exactly as specified: explicit `tenant_id`
claim → `programs[0]` → unresolvable. Unresolvable + `PARROT_SAAS_MODE`
(read via a `_saas_mode()` indirection over `parrot.conf.PARROT_SAAS_MODE`
at call time, per the Key Constraint, so `monkeypatch.setattr(conf,
"PARROT_SAAS_MODE", ...)` is observed) → `web.HTTPForbidden`; flag off →
`"global"`. `declared` mismatch → `web.HTTPBadRequest` regardless of SaaS
mode; `declared=None` skips the check entirely; match passes through.
The function does not read the request body itself (callers pass
`declared=`, per the Key Constraint). Session access mirrors
`agent_guard.py`'s pattern: `getattr(request, "session", None)` →
`navigator_session.get_session()` fallback → lazy `AUTH_SESSION_OBJECT`
import with `"userinfo"` fallback. No `superuser` bypass (deliberately
out of scope, S1). No import of `parrot_formdesigner` or
`parrot.tenancy`/`TenantContext` — verified via grep, only mentioned in
prose comments as a semantic reference, never imported.
`pytest packages/ai-parrot-server/tests/unit/test_crew_tenancy.py -v` —
9 passed (6 from the Test Specification plus 3 additional edge cases:
`declared=None` skip, SaaS-mode+mismatch still 400, and no-session
fallback to legacy `"global"`). `ruff check --fix` applied; one
intentional `BLE001` (broad-except around the `get_session` fallback)
left, matching the same fail-open pattern already used throughout
`pbac.py` / `agent_guard.py` / `eval_context.py` in this feature.

**Deviations from spec**: none.
