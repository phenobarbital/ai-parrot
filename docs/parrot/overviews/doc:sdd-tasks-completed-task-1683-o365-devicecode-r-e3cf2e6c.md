---
type: Wiki Overview
title: 'TASK-1683: Implement `O365DeviceCodeCredentialResolver` + canonical `o365:*`
  persistence'
id: doc:sdd-tasks-completed-task-1683-o365-devicecode-resolver-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 3 — the heart of the feature. A new resolver that
  wraps the
relates_to:
- concept: mod:parrot.auth.credentials
  rel: mentions
- concept: mod:parrot.auth.o365_oauth
  rel: mentions
- concept: mod:parrot.auth.oauth2.o365_devicecode_provider
  rel: mentions
- concept: mod:parrot.interfaces.o365
  rel: mentions
- concept: mod:parrot.services.vault_token_sync
  rel: mentions
---

# TASK-1683: Implement `O365DeviceCodeCredentialResolver` + canonical `o365:*` persistence

**Feature**: FEAT-266 — O365 Auth Homologation
**Spec**: `sdd/specs/o365-auth-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1681, TASK-1682
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 3 — the heart of the feature. A new resolver that wraps the
existing `O365Client.interactive_login()` device-code engine, persists the Entra token set to
the canonical `VaultTokenSync` `o365:*` store, silently refreshes via the public primitive
(TASK-1682), and surfaces `verification_uri`+`user_code` for the CLI. CLI-only: `resolve()`
blocks inline and returns the token on success (it does NOT raise `CredentialRequired` on the
happy path).

---

## Scope

- Create `O365DeviceCodeCredentialResolver(CredentialResolver)` in a new module.
- `resolve(channel, user_id)`:
  1. Read `o365:*` from `VaultTokenSync.read_tokens(user_id, "o365")`; if `access_token`
     present and `expires_at` not within a small skew → return it.
  2. If expired and `refresh_token` present → call
     `O365OAuthManager.refresh_access_token(refresh_token)`, re-persist, return. On
     `PermissionError` (dead refresh) → fall through to device flow.
  3. On miss → run `O365Client.interactive_login(open_browser=False, device_flow_callback=cb)`
     inline; `cb` receives `{verification_uri, user_code, expires_in, message}` and emits the
     prompt via an injected `prompt_callback` (default: print to stdout). Block until success
     or `expires_in`. On success, map the result to the canonical field set and persist via
     `VaultTokenSync.store_tokens(user_id, "o365", {...})`; return `access_token`.
- `get_auth_url(channel, user_id)`: return the device-login verification URI (for the extended
  `NeedsAuth` fields on failure/timeout and future chat).
- **Non-Telegram vault session scheme**: `VaultTokenSync` currently derives its `session_uuid`
  from a hardcoded `telegram-persistent:` prefix (`_synth_session_uuid`). Since device-code is
  CLI-only (Telegram is out of scope — spec §1 Non-Goals), add an ADDITIVE, backward-compatible
  way to persist under a CLI/canonical session scheme (e.g. a `session_scheme` constructor arg
  defaulting to the current telegram behavior so existing jira/fireflies/workiq callers are
  unaffected). Verify a canonical email/OID `user_id` round-trips.
- Write unit tests (vault hit / refresh / device-flow miss / expiry-no-partial-write / fail-closed).

**NOT in scope**: factory wiring (TASK-1684), CLI bootstrap / permission_context (TASK-1685),
Gen 1 deletion (TASK-1686), chat-surface rendering.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | CREATE | `O365DeviceCodeCredentialResolver` |
| `packages/ai-parrot-server/src/parrot/services/vault_token_sync.py` | MODIFY | Additive non-Telegram session scheme (backward-compatible default) |
| `packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py` | CREATE | Unit tests (mock O365Client + VaultTokenSync) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.auth.credentials import CredentialResolver, NeedsAuth        # credentials.py:128,82
from parrot.interfaces.o365 import O365Client                            # interfaces/o365.py:115 (alias O365Interface)
from parrot.auth.o365_oauth import O365OAuthManager                      # o365_oauth.py:55
from parrot.services.vault_token_sync import VaultTokenSync              # ai-parrot-server services/vault_token_sync.py:55
```

### Existing Signatures to Use
```python
# parrot/auth/credentials.py:128
class CredentialResolver(ABC):
    async def resolve(self, channel: str, user_id: str) -> Optional[Any]: ...   # line 132
    async def get_auth_url(self, channel: str, user_id: str) -> str: ...        # line 141

# parrot/interfaces/o365.py:763
async def interactive_login(self, scopes=None, redirect_uri="http://localhost",
    open_browser=True, login_callback=None, device_flow_callback=None) -> Dict[str, Any]: ...
    # device_flow_callback(flow: Dict) receives {verification_uri, user_code, expires_in, message,...}
    # returns a token dict on success (access_token, refresh_token, expires_in, scope, id_token, ...)

# parrot/auth/o365_oauth.py
async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]: ...  # ADDED by TASK-1682
    # raises PermissionError on dead refresh token

# parrot/services/vault_token_sync.py
class VaultTokenSync:                                                            # line 55
    async def store_tokens(self, nav_user_id: str, provider: str, tokens: Dict[str, Any]) -> None: ...  # line 106
    async def read_tokens(self, nav_user_id: str, provider: str) -> Optional[Dict[str, Any]]: ...       # line 141
    def _synth_session_uuid(nav_user_id) -> str  # line 29: returns f"telegram-persistent:{nav_user_id}"  ← generalize additively
```

Reference resolver shape: `parrot/auth/oauth2/workiq_provider.py:108-200` (vault read → exchange → cache → return; `get_auth_url`).

### Canonical `o365:*` field contract (persist EXACTLY these)
`access_token: str`, `refresh_token: str`, `expires_at: int` (epoch seconds),
`scope: str`, `id_token: str` (optional), `tenant_id: str`.

### Does NOT Exist
- ~~Any current writer of flat `o365:*` keys in the O365 path~~ — this resolver is the FIRST writer.
- ~~`VaultTokenSync` arbitrary `get`/`set`~~ — use `store_tokens`/`read_tokens` (token-set, flat `{provider}:{field}`).
- ~~A generic `parrot/auth/device_flow.py`~~ — O365-specific only.
- Do NOT write the MSAL Redis cache or `vault_utils` as a second source of truth.

---

## Implementation Notes

### Key Constraints
- Async throughout; Google-style docstrings; `self.logger` for lifecycle (NEVER log the token).
- The device prompt goes through `prompt_callback`/stdout deliberately — not the logger.
- Map `interactive_login` result `expires_in` → `expires_at = now + expires_in` before persisting.
- Fail closed: empty/`None` `user_id` → raise (no anonymous vault key).
- Expiry/cancel: respect Microsoft `expires_in`; on timeout/Ctrl-C do NOT write a partial token set.
- The `VaultTokenSync` change MUST stay backward-compatible (existing telegram callers default-unchanged).

### References in Codebase
- `parrot/auth/oauth2/workiq_provider.py` — resolver pattern + vault usage.
- `parrot/services/o365_remote_auth.py` (Gen 1, being deleted) — reference ONLY for how the
  device_flow_callback futures were wired; do not import it.

---

## Acceptance Criteria

- [ ] Valid `o365:*` in vault → `resolve` returns `access_token`, no device flow.
- [ ] Expired token + refresh_token → calls `refresh_access_token`, re-persists, returns new token.
- [ ] Empty vault → invokes `interactive_login` (mocked), surfaces `user_code` via callback, persists the canonical field set.
- [ ] Device-flow timeout → no partial vault write.
- [ ] Absent `user_id` → fails closed.
- [ ] `VaultTokenSync` change is additive; existing telegram-scheme callers behave identically.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/auth/test_o365_devicecode_resolver.py -v`.
- [ ] `ruff check` clean on both modified/created modules.

---

## Test Specification

```python
import pytest
from parrot.auth.oauth2.o365_devicecode_provider import O365DeviceCodeCredentialResolver

@pytest.fixture
def resolver(fake_o365_client, fake_manager, fake_vault):
    return O365DeviceCodeCredentialResolver(
        o365_client=fake_o365_client, o365_oauth_manager=fake_manager,
        vault_token_sync=fake_vault, scopes=["User.Read", "offline_access"])

async def test_cache_hit(resolver, fake_vault):
    fake_vault.seed("user@x", "o365", {"access_token": "tok", "expires_at": 9999999999})
    assert await resolver.resolve("cli", "user@x") == "tok"

async def test_refresh_on_expiry(resolver, fake_vault, fake_manager): ...
async def test_device_flow_on_miss(resolver, fake_o365_client): ...
async def test_no_partial_write_on_timeout(resolver, fake_vault): ...
async def test_fail_closed_without_identity(resolver):
    with pytest.raises((ValueError, PermissionError)):
        await resolver.resolve("cli", "")
```

---

## Agent Instructions
Standard SDD flow. Verify TASK-1681 + TASK-1682 are in `completed/` first.

## Completion Note
Created `O365DeviceCodeCredentialResolver` in
`parrot/auth/oauth2/o365_devicecode_provider.py` implementing the
vault-read → refresh → device-flow resolution chain exactly as specified
(cache hit, silent refresh with fallback-to-device-flow on dead refresh
token, inline blocking device flow with `prompt_callback`, canonical
`o365:*` persistence). Made the `VaultTokenSync` non-Telegram session
scheme change additively: `_synth_session_uuid` and `VaultTokenSync.__init__`
gained a `session_scheme` parameter defaulting to the legacy
`"telegram-persistent"` literal (verified byte-identical to the prior
hardcoded behavior — all 16 pre-existing `test_vault_token_sync.py` tests
pass unchanged). CLI callers (TASK-1685) are expected to construct their
`VaultTokenSync` with `session_scheme="cli-persistent"`.

7 new tests in `test_o365_devicecode_resolver.py` cover cache-hit,
refresh-on-expiry, device-flow-on-miss, dead-refresh-token fallback,
no-partial-write-on-timeout/error, fail-closed-without-identity, and
`get_auth_url`. All pass; `ruff check` clean on both modules. Verified no
regression via the full `tests/auth/` + `test_vault_token_sync.py` suite
(248 passed, 6 pre-existing unrelated failures confirmed present on `dev`
before this feature — `test_dataset_guard.py` / `test_pbac_setup.py`, no
relation to FEAT-266 files).
