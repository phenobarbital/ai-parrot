---
type: Wiki Overview
title: 'TASK-1687: Replace hardcoded `tenant_id="cli"` with explicit tenant / fail-loud
  sentinel'
id: doc:sdd-tasks-completed-task-1687-cli-identity-tenant-sentinel-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-266 code review flagged that `build_cli_permission_context()`
relates_to:
- concept: mod:parrot.auth.identity
  rel: mentions
- concept: mod:parrot.auth.permission
  rel: mentions
---

# TASK-1687: Replace hardcoded `tenant_id="cli"` with explicit tenant / fail-loud sentinel

**Feature**: FEAT-267 — O365 Device-Code Follow-ups
**Spec**: `sdd/specs/o365-devicecode-followups.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (&lt;2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

FEAT-266 code review flagged that `build_cli_permission_context()`
(`packages/ai-parrot/src/parrot/cli/identity.py:80`) builds
`UserSession(user_id=canonical, tenant_id=CLI_CHANNEL, roles=frozenset())` — reusing the
`"cli"` channel literal as `tenant_id`, with zero roles, unconditionally. `PermissionContext`'s
`tenant_id`/`.roles` feed `to_eval_context()` for PBAC policy evaluation. This is dormant today
(no CLI path wires a `ToolManager._resolver`, no tool declares `_required_permissions`), but the
moment PBAC/role-gating is wired onto the CLI surface, every device-code CLI user silently
collapses into tenant `"cli"` with no roles — breaking any tenant/role-scoped policy silently.

This task closes the gap at the identity-construction seam, without attempting to build a real
CLI role-resolution system (out of scope — no role source exists yet).

---

## Scope

- Add an explicit tenant-id source for the CLI `PermissionContext`, distinct from the
  `CLI_CHANNEL` literal:
  - Prefer a new `O365_TENANT_ID` environment variable (verify no existing tenant-id env var
    convention already exists elsewhere in the codebase — grep for `TENANT_ID` before adding a
    new one; if one exists, reuse it instead of inventing a duplicate).
  - When unset, fall back to an explicit, distinctly-named sentinel constant (e.g.
    `UNSET_CLI_TENANT = "unset-cli-tenant"`) — NOT `CLI_CHANNEL` — so the placeholder can never
    be mistaken for (or silently collide with) a real tenant id in a future PBAC rule.
- Update `build_cli_permission_context()` to use the new tenant source instead of `CLI_CHANNEL`
  for `UserSession(tenant_id=...)`.
- Add a code comment directly at the `UserSession(...)` construction site documenting that
  `roles=frozenset()` is a known, currently-inert gap that will matter once a `ToolManager._resolver`
  is wired onto the CLI surface (do NOT attempt to resolve real roles in this task).
- Add/update unit tests confirming: (a) with `O365_TENANT_ID` set, `PermissionContext.session.tenant_id`
  equals that value; (b) with it unset, `tenant_id` equals the new sentinel, never `"cli"`/`CLI_CHANNEL`.

**NOT in scope**: wiring PBAC/role-gating onto the CLI surface itself, resolving real per-user
roles, any change to `packages/ai-parrot/src/parrot/auth/permission.py` internals.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/identity.py` | MODIFY | Explicit tenant source + sentinel constant + comment |
| `packages/ai-parrot/tests/auth/test_credentials_devicecode.py` or a new `packages/ai-parrot/tests/cli/test_identity.py` | MODIFY/CREATE | Unit tests for tenant resolution (check which test file already covers `cli/identity.py` before creating a new one) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.identity import CanonicalIdentityMapper   # cli/identity.py:19 (existing)
from parrot.auth.permission import PermissionContext, UserSession   # cli/identity.py:20 (existing)
```

### Existing Signatures (verified, `packages/ai-parrot/src/parrot/cli/identity.py`)
```python
O365_PRINCIPAL_ENV_VAR: str = "O365_PRINCIPAL"   # line 24
CLI_CHANNEL: str = "cli"                          # line 27

def resolve_cli_o365_principal() -> str: ...      # line 30

def build_cli_permission_context(user_id: Optional[str] = None) -> PermissionContext:
    # line 61
    canonical = user_id or resolve_cli_o365_principal()
    session = UserSession(user_id=canonical, tenant_id=CLI_CHANNEL, roles=frozenset())  # line 80 ← FIX HERE
    return PermissionContext(session=session, channel=CLI_CHANNEL)
```

Verify `UserSession`'s exact field names/types (`tenant_id`, `roles`) by reading
`packages/ai-parrot/src/parrot/auth/permission.py` before editing — do not assume beyond what's
shown above.

### Does NOT Exist
- No existing `O365_TENANT_ID` (or equivalent) env var — grep first; if a generic tenant-id env
  convention already exists elsewhere (e.g. for OBO/3LO flows), reuse its name instead of adding
  a second one.
- No CLI role-resolution mechanism — do not invent one.

---

## Implementation Notes

### Key Constraints
- Backward compatible: `build_cli_permission_context()`'s public signature must not change.
- Fail-loud philosophy already used in this module (`resolve_cli_o365_principal` raises
  `RuntimeError` on missing/invalid principal) — the tenant sentinel should be similarly
  explicit/greppable, not a silent reuse of an unrelated constant.
- Google-style docstrings, type hints, per project conventions.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/identity.py` — the file being fixed; read the whole module
  first (it's short, ~103 lines).
- `packages/ai-parrot/src/parrot/auth/permission.py` — `PermissionContext`/`UserSession`
  definitions and `to_eval_context()` usage of `tenant_id`/`roles`.

---

## Acceptance Criteria

- [ ] `tenant_id` passed to `UserSession` is no longer `CLI_CHANNEL`/`"cli"`.
- [ ] With `O365_TENANT_ID` (or reused existing env var) set, the resolved `PermissionContext.session.tenant_id`
      matches it exactly.
- [ ] With it unset, `tenant_id` is a distinctly-named sentinel, never equal to `CLI_CHANNEL`.
- [ ] A code comment at the `UserSession(...)` call site documents the `roles=frozenset()` gap.
- [ ] Existing tests referencing `build_cli_permission_context`/`identity.py` still pass.
- [ ] New/updated tests cover both the explicit-tenant and sentinel-fallback cases.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/auth/ packages/ai-parrot/tests/cli/ -v` (adjust path to wherever the new/updated test lives).

## Test Specification
```python
def test_tenant_id_from_env(monkeypatch):
    monkeypatch.setenv("O365_TENANT_ID", "contoso-tenant")
    ctx = build_cli_permission_context(user_id="user@contoso.com")
    assert ctx.session.tenant_id == "contoso-tenant"

def test_tenant_id_sentinel_when_unset(monkeypatch):
    monkeypatch.delenv("O365_TENANT_ID", raising=False)
    ctx = build_cli_permission_context(user_id="user@contoso.com")
    assert ctx.session.tenant_id != "cli"
    assert ctx.session.tenant_id != CLI_CHANNEL
```

## Output
When complete, the agent must:
1. Move this file to `sdd/tasks/completed/`
2. Update `sdd/tasks/index/o365-devicecode-followups.json` status to "done"
3. Add a brief completion note below

### Completion Note

Implemented as specified. `packages/ai-parrot/src/parrot/cli/identity.py`:
added `O365_TENANT_ID_ENV_VAR = "O365_TENANT_ID"` and
`UNSET_CLI_TENANT = "unset-cli-tenant"` constants; grepped the codebase for
an existing tenant-id env var convention first — none found (`o365_oauth.py`'s
`tenant_id` is a constructor parameter for OAuth endpoint templating, not an
env var), so `O365_TENANT_ID` is new. `build_cli_permission_context()` now
reads `O365_TENANT_ID` (stripped, blank treated as unset) and falls back to
`UNSET_CLI_TENANT`, never `CLI_CHANNEL`. Added a code comment at the
`UserSession(...)` call site documenting the `roles=frozenset()` gap.

New test file `packages/ai-parrot/tests/cli/test_identity.py` (no prior
dedicated test file for `cli/identity.py` existed — checked
`test_credentials_devicecode.py` and `test_cli_devicecode_e2e.py` first, the
latter covers `channel`/`user_id` but not `tenant_id`) covers: env-set case,
unset-sentinel case, blank-env-as-unset case, and roles-remains-empty.

All 9 tests pass (4 new + 5 existing in `test_cli_devicecode_e2e.py`,
unaffected since none asserted on `tenant_id`). `ruff check` clean.
