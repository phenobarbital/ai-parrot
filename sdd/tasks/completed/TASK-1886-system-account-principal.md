# TASK-1886: System account principal for scheduled refreshes

**Feature**: FEAT-326 — DataAgent Infographic — Infographic Authoring for Data Agents
**Spec**: `sdd/specs/dataagent-infographic.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Module 5 of FEAT-326. Scheduled recipe refreshes must run under a real `PermissionContext` —
`RecipeRunner.run()` with a falsy `pctx` makes `DatasetManager`'s PBAC/data-plane guards fail
**OPEN** (documented security hazard, `runner.py` module docstring). The brainstorm resolved
that a **system account** entity must be created; this task creates that principal concept and
the fail-closed guard for scheduled runs. It touches only `parrot/auth/` + tests, sharing no
files with the other tasks (`parallel: true`).

---

## Scope

- Create a **system account** principal in `parrot/auth/` (exact sub-module per the existing
  auth layout — spec §8 leaves config-declared vs DB-backed to the implementer; prefer the
  simplest mechanism consistent with how `parrot/auth/identity.py` / `models.py` define
  principals — READ them first and follow the established shape).
- Provide a helper that resolves the system account into a `PermissionContext` via the
  existing `build_principal_context` (`parrot/auth/permission.py:166`).
- **Fail-closed guard**: a scheduled-refresh entry point must refuse to call
  `RecipeRunner.run()` when the system-account context cannot be resolved (raise; never pass
  `pctx=None`).
- Unit tests.

**NOT in scope**: the FEAT-324 scheduler trigger itself (exists), recipe publication
(TASK-1885), any change to `RecipeRunner` (stays untouched), OAuth flows.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/<module per layout>.py` | CREATE/MODIFY | System-account principal + resolver helper |
| `packages/ai-parrot/tests/unit/auth/test_system_account.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.permission import build_principal_context   # permission.py:166
# Read its full signature at parrot/auth/permission.py:166 before calling —
# the parameter list was NOT captured in the spec contract (verify first).
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/infographic_recipes/runner.py
class RecipeRunner:                                            # __init__ line 194
    async def run(self, name: str, *, params: dict | None = None,
                  pctx: Any | None = None,
                  recipe_owner: Optional[str] = None) -> RenderedArtifact: ...  # line 208
# SECURITY (runner.py docstring): falsy pctx ⇒ DatasetManager PBAC fails OPEN.
# This task's guard exists precisely to make that impossible for scheduled runs.

# parrot/auth/ layout (files verified to exist; contents NOT yet read — read before coding):
#   identity.py, models.py, context.py, permission.py, pbac.py, resolver.py, grants.py
```

### Does NOT Exist
- ~~a system-account / service-principal entity anywhere in `parrot/auth/`~~ — created HERE
  `(the exact base classes to extend are unverified — read identity.py/models.py first)`.
- ~~`RecipeRunner.run_as_system()`~~ — do NOT add; the guard wraps the CALLER side.
- ~~any default/anonymous pctx fallback~~ — explicitly forbidden (fail closed).

---

## Implementation Notes

### Key Constraints
- **Fail closed, loudly**: unresolvable system account → raise a specific exception (reuse or
  extend `parrot/auth/exceptions.py`), log at ERROR. Never degrade to `pctx=None`.
- Async-first; Pydantic if a new model is introduced; Google-style docstrings.
- Keep it minimal: one principal concept + one resolver + one guard. No provisioning UI/CLI.
- Document (docstring) how a deployment provisions the system account (env/config keys used).

### References in Codebase
- `parrot/auth/permission.py:166` — `build_principal_context` (read full signature)
- `parrot/auth/identity.py`, `parrot/auth/models.py` — principal shapes to follow
- `parrot/tools/infographic_recipes/runner.py` module docstring — the threat model

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass: `pytest packages/ai-parrot/tests/unit/auth/test_system_account.py -v`
- [ ] No linting errors on new/modified files (`ruff check`)
- [ ] System account resolves to a truthy `PermissionContext` via `build_principal_context`
- [ ] Unresolvable system account → raise (fail closed); `pctx=None` is never forwarded
- [ ] `parrot/tools/infographic_recipes/runner.py` unchanged

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/auth/test_system_account.py
class TestSystemAccount:
    async def test_resolves_permission_context(self): ...
    async def test_missing_provisioning_fails_closed(self): ...
    async def test_guard_refuses_falsy_pctx(self): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** — none; 3. **Verify the Codebase Contract**
(read `identity.py`/`models.py`/`permission.py:166` FIRST — several anchors are deliberately
marked unverified); 4. **Update index** → `"in-progress"`; 5. **Implement**; 6. **Verify
criteria**; 7. **Move file to completed/**; 8. **Update index** → `"done"`;
9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-24
**Notes**: Created `parrot/auth/system_account.py` with a **config-declared**
system account (spec §8 open question resolved → simplest mechanism, no DB/UI):
`SystemAccount` (Pydantic, `extra="forbid"`; `account_id`/`tenant_id`/`roles`)
with `from_env()` (reads `PARROT_SYSTEM_ACCOUNT_ID` / `_TENANT` / `_ROLES`) and
`to_permission_context(channel)` delegating to the verified
`build_principal_context(principal, *, channel, tenant_id, roles)`
(permission.py:166). `resolve_system_account_context()` fails **closed** —
raises the new `SystemAccountNotProvisioned` (added to `parrot/auth/exceptions.py`,
the documented auth-exception home) when no account is provisioned, and never
returns a falsy context. `run_scheduled_refresh(runner, name, ...)` is the
caller-side guard: it resolves the context (raising if unresolvable) and calls
`runner.run(name, ..., pctx=ctx)` — `pctx=None` is never forwarded.
`RecipeRunner` is untouched (verified via git). 7 tests pass; ruff clean.

**Deviations from spec**: none. Open question (§8, owner=implementer) resolved
in favour of a config/env-declared account over a DB-backed one.
