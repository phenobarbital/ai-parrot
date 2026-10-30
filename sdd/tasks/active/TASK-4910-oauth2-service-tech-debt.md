# TASK-4910: Split integration-status tests by credential owner (Session vs Identity Vault)

**Feature**: FEAT-780 — oauth2-service-tech-debt
**Spec**: `sdd/specs/oauth2-service-tech-debt.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:267fb119e6f1`

---

## Context

Since TASK-4670 `jira` status is probed in the Identity Vault, so the Session-Vault tests in
`test_integrations_status.py` (which use `jira`) never reach their fake sync; two fail on `dev`.
Implements spec §3 Module 1 in full.

## Scope

- Session-Vault tests use provider `o365` and assert the fake sync was consulted.
- New `TestIdentityVaultStatus` for `jira`, fake store injected via `service._identity_store_instance`:
  no row → needs_reconnect; `IdentityCredentialError` → needs_reconnect; readable → connected (sync
  untouched); `get_by_provider` raising → connected; no store → connected.

**NOT in scope**: any change under `packages/ai-parrot/src/`; FEAT-773 M6.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/tests/auth/test_integrations_status.py` | MODIFY |

## Codebase Contract

See spec §6 (verified against `d47ab5340`).

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/auth/test_integrations_status.py` — 0 failures.
- [ ] Session-Vault tests assert `sync.calls >= 1`.
- [ ] No diff under `packages/ai-parrot/src`.
- [ ] `ruff check` clean.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/auth/test_integrations_status.py -q
ruff check packages/ai-parrot/tests/auth/test_integrations_status.py
```

## Completion Note

_(filled on close)_
