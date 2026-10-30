---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [auth, oauth2, integrations, tests, tech-debt, ledger-fix]
---

# Feature Specification: oauth2-service-tech-debt

**Feature ID**: FEAT-780
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude Opus 5.5, via /sdd-fix)
**Status**: approved
**Target version**: 1.2.6

> **Source**: work-ledger group `fixgroup:651ea8fa848c`, routed to the SDD lane by
> `wikitoolkit ledger plan-fix` (two files → not fast-lane eligible).
> Resolves `issue:267fb119e6f1`. Parent `spec:FEAT-773` (delegated-auth-connections) has no
> task index yet, so this is not folded into its M6.

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot/tests/auth/test_integrations_status.py` uses `jira` as its only provider and drives
status through a fake `vault_token_sync`. Since TASK-4670 (`79c856423`),
`IntegrationsService._token_status` routes providers in `_IDENTITY_OWNED_PROVIDERS = {"jira"}` to
`_identity_token_status`, which probes the navigator-auth Identity Vault. With
`request=SimpleNamespace(app={})` there is no `IdentityStore`, so the probe fails open to `"connected"`
and the fake Session-Vault sync is never consulted. Result on `dev`:

- `TestListForUserStatus::test_unusable_tokens_need_reconnect[unreadable]` — FAIL
- `TestListForUserStatus::test_unusable_tokens_need_reconnect[missing]` — FAIL

The other Session-Vault tests pass only by accident of the fail-open. The production code is correct.

### Goals
- The Session-Vault status tests exercise the Session-Vault path (non-identity-owned provider).
- The Identity-Vault path for `jira` has its own tests: no identity row → `needs_reconnect`;
  `IdentityCredentialError` on decrypt → `needs_reconnect`; readable credential, no store, or a probe
  error → `connected`.
- The whole of `test_integrations_status.py` passes on `dev`.

### Non-Goals (explicitly out of scope)
- Any change to `parrot/auth/oauth2/service.py` (listed in the issue only as the code under test).
- FEAT-773 M6 (durable-owner status for every provider, removal of `_IDENTITY_OWNED_PROVIDERS`).

---

## 2. Architectural Design

### Overview
Test-only fix. Parametrize the Session-Vault tests over a non-identity provider (`o365`) and add a
`TestIdentityVaultStatus` class for `jira` that injects a fake store through the service's existing
`_identity_store_instance` cache attribute (the same seam `_identity_store()` reads first).

### Integration Points
None — no production code path changes.

### Data Models / New Public Interfaces
None.

---

## 3. Module Breakdown

### Module 1: Split integration-status tests by credential owner
- **Path**: `packages/ai-parrot/tests/auth/test_integrations_status.py`
- **Responsibility**: Session-Vault cases on `o365`; new Identity-Vault cases on `jira` with a fake
  `IdentityStore` (`get_by_provider` async, `decrypt_credential` sync).
- **Depends on**: nothing.

---

## 4. Test Specification

### Unit Tests
| Test | Expectation |
|---|---|
| Session-Vault `ok` / `unreadable` / `missing` / `unavailable` / probe error on `o365` | connected / needs_reconnect / needs_reconnect / connected / connected, and the fake sync IS called |
| `jira` + store `get_by_provider → None` | needs_reconnect |
| `jira` + `decrypt_credential` raises `IdentityCredentialError` | needs_reconnect |
| `jira` + readable credential | connected, Session-Vault sync NOT called |
| `jira` + store `get_by_provider` raises `RuntimeError` | connected |
| `jira` + no store (`app={}`) | connected |

### Validation Contract

tests:
- packages/ai-parrot/tests/auth/test_integrations_status.py
markers: none

---

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/auth/test_integrations_status.py` passes with 0 failures.
- [ ] Session-Vault tests assert the fake sync was consulted (`sync.calls >= 1`).
- [ ] `git diff origin/dev -- packages/ai-parrot/src` is empty.
- [ ] `ruff check` is clean on the test file.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.auth.oauth2.service import IntegrationsService  # packages/ai-parrot/src/parrot/auth/oauth2/service.py
from navigator_auth.identity.store import IdentityCredentialError  # navigator_auth/identity/store.py:44
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
_IDENTITY_OWNED_PROVIDERS = frozenset({"jira"})                       # :53
def __init__(self, vault_token_sync: Any = None) -> None:             # :86
    self._identity_store_instance: Any = None                         # :88
async def _identity_token_status(self, user_id, provider_id, request) -> str  # :202
async def _token_status(self, user_id, provider_id, request) -> str  # :250
# navigator_auth/identity/store.py
async def get_by_provider(...)                                        # :322
def decrypt_credential(self, identity: UserIdentity) -> TokenResponse # :444 (sync)
```

### Does NOT Exist (Anti-Hallucination)
- ~~`IntegrationsService(identity_store=...)`~~ — no constructor parameter; inject via `_identity_store_instance`.
- ~~`async def decrypt_credential`~~ — it is synchronous.

### Edit Sites (Blueprint Anchors)

Verified against: `d47ab5340`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/tests/auth/test_integrations_status.py` | MODIFY | `PROVIDER = SimpleNamespace(` | `:12` | 1 |
| `packages/ai-parrot/tests/auth/test_integrations_status.py` | MODIFY | `async def list_one(sync, row=ROW):` | `:53` | 1 |

---

## 7. Implementation Notes & Constraints

### Known Risks / Gotchas
- Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`; a bare `pytest` imports the
  main checkout.

---

## 8. Open Questions

None.

---

## Revision History

| Date | Author | Change |
|---|---|---|
| 2026-10-30 | Claude Opus 5.5 (/sdd-fix) | Initial spec from ledger group `fixgroup:651ea8fa848c` |
