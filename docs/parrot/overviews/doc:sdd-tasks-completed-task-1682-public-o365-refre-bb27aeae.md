---
type: Wiki Overview
title: 'TASK-1682: Promote O365 refresh to a public stateless `refresh_access_token`'
id: doc:sdd-tasks-completed-task-1682-public-o365-refresh-primitive-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 2. The device-code resolver (TASK-1683) must refresh
  the Entra
relates_to:
- concept: mod:parrot.auth.o365_oauth
  rel: mentions
---

# TASK-1682: Promote O365 refresh to a public stateless `refresh_access_token`

**Feature**: FEAT-266 — O365 Auth Homologation
**Spec**: `sdd/specs/o365-auth-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. The device-code resolver (TASK-1683) must refresh the Entra
access token using the SAME Entra token-endpoint code path the 3LO flow already uses, then
persist to the canonical `VaultTokenSync` `o365:*` store. Today that call exists only as the
private `O365OAuthManager._refresh_request`. This task promotes it to a documented public
method so the resolver can reuse it without depending on a private API.

---

## Scope

- Add a public `async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]`
  to `O365OAuthManager`.
- Implement it as the body of (or a thin delegate to) the existing `_refresh_request`. Keep
  `_refresh_request` working for any internal callers (delegate one to the other — no dup logic).
- Preserve the existing error contract: `PermissionError` on HTTP 400/401 (dead refresh token),
  `aiohttp.ClientError` on other non-200.
- Write unit tests.

**NOT in scope**: changing `get_valid_token`, `_refresh_tokens`, the vault/Redis persistence of
the 3LO manager, or the token-set model.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/o365_oauth.py` | MODIFY | Add public `refresh_access_token`; keep `_refresh_request` |
| `packages/ai-parrot/tests/auth/test_o365_refresh.py` | CREATE | Unit tests (mock the aiohttp session) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.o365_oauth import O365OAuthManager  # packages/ai-parrot/src/parrot/auth/o365_oauth.py:55
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/o365_oauth.py
class O365OAuthManager(AbstractOAuth2Manager):                                  # line 55
    async def _refresh_request(self, refresh_token: str) -> Dict[str, Any]:     # line 140
        # POST self.token_url, grant_type=refresh_token, client_id/secret, scope=" ".join(self.scopes)
        # raises PermissionError on 400/401; aiohttp.ClientError on other non-200; returns response.json()
    async def _get_session(self) -> aiohttp.ClientSession: ...                  # (used internally)
DEFAULT_O365_SCOPES = [..., "offline_access", ...]                             # line 30 (refresh token enabled)
```

### Does NOT Exist
- ~~`O365OAuthManager.refresh_access_token`~~ (public) — added by THIS task.
- Do NOT call MSAL silent acquire here — the standard refresh path is the Entra token endpoint
  (`_refresh_request`). See spec §7 "three token stores".

---

## Implementation Notes

### Pattern to Follow
```python
async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
    """Public, stateless Entra refresh: exchange a refresh_token for a new token dict.

    Reused by the device-code resolver (FEAT-266). Does NOT persist — the caller
    persists to its canonical store.
    """
    return await self._refresh_request(refresh_token)
# (or move the body here and make _refresh_request delegate — either way, one implementation)
```

### Key Constraints
- One implementation, no duplicated HTTP logic.
- Do not swallow `PermissionError` — the resolver relies on it to decide "re-prompt device flow".

### References in Codebase
- `packages/ai-parrot/src/parrot/auth/o365_oauth.py:140-165` — existing `_refresh_request`.

---

## Acceptance Criteria

- [ ] `O365OAuthManager.refresh_access_token(refresh_token)` is public and returns the token dict.
- [ ] On a mocked HTTP 400 `invalid_grant`, it raises `PermissionError`.
- [ ] `_refresh_request` still works (internal callers, if any, unaffected) — no logic duplicated.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/auth/test_o365_refresh.py -v`.
- [ ] `ruff check packages/ai-parrot/src/parrot/auth/o365_oauth.py` clean.

---

## Test Specification

```python
import pytest
from parrot.auth.o365_oauth import O365OAuthManager

async def test_refresh_access_token_returns_token(monkeypatch):
    mgr = O365OAuthManager(client_id="c", client_secret="s", redirect_uri="http://localhost")
    # monkeypatch mgr._refresh_request or the aiohttp session to return a fixed dict
    ...

async def test_refresh_access_token_dead_token_raises_permissionerror(monkeypatch):
    mgr = O365OAuthManager(client_id="c", client_secret="s", redirect_uri="http://localhost")
    # simulate HTTP 400 invalid_grant -> expect PermissionError
    with pytest.raises(PermissionError):
        await mgr.refresh_access_token("dead-token")
```

---

## Agent Instructions
Standard SDD flow: verify contract, implement, test, move to completed, update index.

## Completion Note
Added a public `refresh_access_token(refresh_token)` to `O365OAuthManager` that
delegates to the existing `_refresh_request` (no duplicated HTTP logic; the
abstract-method override required by `AbstractOAuth2Manager._refresh_tokens`
is untouched). Created `packages/ai-parrot/tests/auth/test_o365_refresh.py`
with 4 tests (200 success, 400/401 → `PermissionError`, and a delegation
test proving no duplicated logic) using a fake aiohttp session/response.
All tests pass; `ruff check` clean. No deviations from spec.
