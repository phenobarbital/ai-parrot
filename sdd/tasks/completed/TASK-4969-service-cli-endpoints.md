# TASK-4969: IntegrationsService whoami / pull_access_token / complete_connect + wire models

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G3, S5, S7, S10, AC-5): the server side of the CLI. `whoami` backs `GET /api/v1/connections/me`;
`pull_access_token` vends **access tokens only** (refresh never leaves the server) behind PBAC `integration:use` with an
audit event `connection.token_pulled`; `complete_connect` is the paste fallback (`{code, state}` → FEAT-773's
`handle_callback` → `persist_credential`). The HTTP handler is TASK-4970; the device pair is TASK-4971.

---

## Scope

- `models.py`: append `WhoAmI`, `PulledToken` (spec §2 Data Models) and `NotConnected(Exception)` carrying an
  `AuthRequiredPayload`.
- `events.py`: extend `ConnectionEventKind` with `"connection.token_pulled"`.
- `service.py`: add `whoami`, `pull_access_token`, `complete_connect` to `IntegrationsService`.
- Unit tests.

**NOT in scope**: handler routes and route registration (TASK-4970); `device_start` / `device_poll` (TASK-4971); the CLI client (TASK-4972); changing `start_connect` / `status` / `persist_credential` / `_check_pbac`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/models.py` | MODIFY | WhoAmI, PulledToken, NotConnected |
| `packages/ai-parrot/src/parrot/auth/oauth2/events.py` | MODIFY | connection.token_pulled kind |
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | whoami, pull_access_token, complete_connect |
| `packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py` | CREATE | service tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.auth.credentials import AuthRequiredPayload          # credentials.py:114 (credentials imports only stdlib+pydantic → no cycle)
from parrot.auth.principal import Principal                      # principal.py:18 (already imported in service.py:26)
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry   # already imported in service.py:42
from parrot.auth.session_identity import resolve_user_id         # session_identity.py:90 (handler side; service may reuse)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/credentials.py
class AuthRequiredPayload(BaseModel):   # :114 — provider, auth_url, scopes, tool_name, message, auth_kind, user_code, verification_uri, expires_in
# packages/ai-parrot/src/parrot/auth/oauth2/events.py
ConnectionEventKind = Literal["connection.completed", "connection.revoked", "connection.refresh_failed"]   # :14
# packages/ai-parrot/src/parrot/auth/oauth2/service.py
class IntegrationsService:                                                                    # :65
    async def start_connect(self, user_id, provider_id, return_origin=None, *, channel=_WEB_CHANNEL,
                            principal: Optional[Principal] = None, scopes=None, request=None, extra_state=None) -> ConnectInitResponse   # :288 (non-web REQUIRES principal)
    async def status(self, user_id: str, provider_id: str, request: Any = None) -> IntegrationDescriptor   # :360 (PBAC integration:list)
    async def persist_credential(self, user_id, provider_id, token_set, *, channel: str, canonical_identity=None) -> UsersIntegrationRow   # :403
    async def _check_pbac(self, request, action: str, provider_id=None, scopes=None) -> bool   # :471 — request None → False (fail closed)
    # comment block `# ---- / # Internal helpers / # ----` at :467-469 precedes _check_pbac
# provider = OAuth2ProviderRegistry().get(provider_id) → .manager, .default_scopes  (service.py:320-322 pattern)
# packages/ai-parrot/src/parrot/auth/oauth2_base.py (provider.manager)
    async def get_valid_token(self, channel, user_id, *, channel_user_id=None) -> Optional[AbstractOAuth2TokenSet]   # :642 (refreshes server-side)
    async def handle_callback(self, code: str, state: str) -> Tuple[AbstractOAuth2TokenSet, Dict[str, Any]]   # :465 — CONSUMES the nonce first
    def _nonce_key(self, nonce: str) -> str   # :344 ; self.redis.get(...) → JSON with "nav_user_id"
    async def _publish(self, kind, principal, token_set, *, reason=None, state_payload=None) -> None   # :551
class AbstractOAuth2TokenSet(BaseModel): access_token, refresh_token, expires_at, scopes, account_id, display_name, email   # :165
```

### Does NOT Exist
- ~~`IntegrationsService.whoami` / `pull_access_token` / `complete_connect`~~ — added here.
- ~~`WhoAmI` / `PulledToken` / `NotConnected` anywhere~~ — added here, in `models.py` (the spec drew them in
  `remote_client.py`; TASK-4972 re-exports them from there so both import paths work, and the server never imports CLI code).
- ~~`ConnectionEventKind` value `connection.token_pulled`~~ — added here.
- ~~`IntegrationDescriptor.status == "active"`~~ — `IntegrationStatus` is `connected | disconnected | needs_reconnect`
  (`models.py:18`); `"active"` exists only on `UsersIntegrationRow`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/models.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/events.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/models.py#IntegrationDescriptor"
  ]
}
```

---

## Implementation Notes

- **Additive deviation:** `complete_connect` gains `request: Any = None` (needed because `status()` evaluates PBAC and
  fails closed without a request). Signature otherwise as in spec §3 M3.
- **Security (S10):** `handle_callback` consumes the nonce *before* checking anything. Peek first:
  `raw = await manager.redis.get(manager._nonce_key(state))`; missing → `ValueError("Invalid or expired state nonce.")`;
  parse JSON; if `str(nav_user_id) != user_id` (`hmac.compare_digest`) → `ValueError` **without** consuming it. Only then
  call `handle_callback`.
- `pull_access_token`: unknown provider → `ValueError`; PBAC `integration:use` false → `PermissionError` (no event);
  `token = await manager.get_valid_token("cli", user_id)`; `None` → `NotConnected(AuthRequiredPayload(provider=...,
  auth_url=<start_connect(channel="cli", principal=Principal(user_id, channel="cli", channel_user_id=user_id)).auth_url>,
  scopes=default_scopes, auth_kind="oauth2", message="not_connected"))`. If `start_connect` itself raises
  (PermissionError/ValueError) leave `auth_url=None`. On success publish via
  `manager._publish("connection.token_pulled", principal, token)` — `ConnectionEvent` carries no token fields — and
  return `PulledToken` built from the token set. Never put `refresh_token` in the response (S5).
- `whoami(user_id, request)`: read the session the handler already bound (`request.get("session")` or
  `getattr(request, "session", None)`); tenant/email/roles from it. Never default `tenant_id` to `user_id`
  (principal_guard discipline, spec §7).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Append the three models to `models.py` — *why*: one wire schema shared by server (here) and CLI (TASK-4972).
2. Extend `ConnectionEventKind` — *why*: AC-5 audit event.
3. Insert the three service methods — *why*: §3 M3; S5 (no refresh token), S10 (peek nonce).
4. Write the tests and run the validation commands (S-1 service/handler tests must stay green).

### `packages/ai-parrot/src/parrot/auth/oauth2/models.py` (MODIFY — append at end of file)
```python
# APPEND after the last line of models.py (UsersIntegrationRow._fold_channel ends the file); add
# `from parrot.auth.credentials import AuthRequiredPayload` next to the pydantic import (:14).


class WhoAmI(BaseModel):
    """GET /api/v1/connections/me — the Navigator principal behind a CLI bearer."""

    user_id: str
    tenant_id: Optional[str] = None
    canonical_identity: Optional[str] = None
    email: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    scopes: List[str] = Field(default_factory=list)


class PulledToken(BaseModel):
    """POST /api/v1/connections/{provider}/token — access token only, NEVER a refresh token (S5)."""

    provider: str
    access_token: str
    expires_at: float
    scopes: List[str] = Field(default_factory=list)
    account_id: str = ""


class NotConnected(Exception):
    """No active connection for the provider; ``payload`` is the 409 body."""

    def __init__(self, payload: AuthRequiredPayload) -> None:
        super().__init__(f"{payload.provider} is not connected")
        self.payload = payload
```

### `packages/ai-parrot/src/parrot/auth/oauth2/events.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'ConnectionEventKind = Literal\["connection.completed", "connection.revoked", "connection.refresh_failed"\]' events.py)
# REPLACE that line (verified: events.py:14) with:
ConnectionEventKind = Literal[
    "connection.completed", "connection.revoked", "connection.refresh_failed", "connection.token_pulled",
]
```

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    # Internal helpers' service.py)
# BEFORE — insert above the 3-line comment block `# ---- / # Internal helpers / # ----` (verified: service.py:467-469).
# Extend the models import (:30-35) with NotConnected, PulledToken, WhoAmI; add `import hmac`, `import json`,
# `from parrot.auth.credentials import AuthRequiredPayload`.

    async def whoami(self, user_id: str, request: Any = None) -> WhoAmI:
        """Return the Navigator identity of the authenticated caller (CLI `parrot whoami`, M2 resolver)."""
        # FILL IN: session = request.get("session") / getattr(request, "session", None); tenant_id, email, roles from it;
        #          scopes from token claims when present — never default tenant_id to user_id (spec §7)
        raise NotImplementedError

    async def pull_access_token(self, user_id: str, provider_id: str, request: Any = None) -> PulledToken:
        """Vend the provider access token for ``user_id`` (PBAC integration:use, fail closed, audited)."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:use", provider_id, list(provider.default_scopes)):
            raise PermissionError(f"Not permitted to use provider {provider_id!r}")
        principal = Principal(user_id=user_id, channel="cli", channel_user_id=user_id)
        token = await provider.manager.get_valid_token("cli", user_id)
        if token is None:
            # FILL IN: auth_url from self.start_connect(..., channel="cli", principal=principal, request=request).auth_url
            #          (PermissionError/ValueError → None); raise NotConnected(AuthRequiredPayload(...)) — AC-5
            raise NotImplementedError
        await provider.manager._publish("connection.token_pulled", principal, token)  # audit only, no token material
        return PulledToken(
            provider=provider_id, access_token=token.access_token, expires_at=float(token.expires_at),
            scopes=list(token.scopes or []), account_id=token.account_id or "",
        )

    async def complete_connect(
        self, user_id: str, provider_id: str, *, code: str, state: str, channel: str, request: Any = None,
    ) -> IntegrationDescriptor:
        """Paste fallback (S10): verify the nonce belongs to ``user_id``, then exchange + persist."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        manager = provider.manager
        # FILL IN: peek manager.redis.get(manager._nonce_key(state)) WITHOUT consuming; missing → ValueError("Invalid or
        #          expired state nonce."); nav_user_id mismatch (hmac.compare_digest) → ValueError — bounded by S10
        token_set, state_payload = await manager.handle_callback(code, state)
        await self.persist_credential(
            user_id, provider_id, token_set, channel=channel,
            canonical_identity=state_payload.get("canonical_identity"),
        )
        return await self.status(user_id, provider_id, request)

```

### `packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py` (CREATE)
```python
"""IntegrationsService CLI endpoints (FEAT-774 M3)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2.models import NotConnected, PulledToken
from parrot.auth.oauth2.service import IntegrationsService


async def test_pull_access_token_never_returns_refresh(monkeypatch):
    # FILL IN: registry → provider whose manager.get_valid_token returns a token set with refresh_token="rt";
    #          PBAC allowed; result.model_dump().keys() ⊆ {provider, access_token, expires_at, scopes, account_id};
    #          manager._publish awaited with "connection.token_pulled" and no token in its args
    ...

async def test_pull_token_not_connected_payload(monkeypatch):
    # FILL IN: get_valid_token → None → NotConnected whose payload validates as AuthRequiredPayload with auth_url
    ...

async def test_pull_token_pbac_denied(monkeypatch):
    # FILL IN: _check_pbac False → PermissionError and _publish never awaited
    ...

async def test_complete_connect_state_mismatch_rejected(monkeypatch):
    # FILL IN: nonce record with another nav_user_id → ValueError and handle_callback NOT called (nonce intact);
    #          missing nonce → ValueError; matching → persist_credential(channel="cli") then status()
    ...
```

### FILL IN checklist
- [ ] `whoami` — session fields; bounded by spec §7 (tenant never defaults to user_id)
- [ ] `pull_access_token` not-connected branch — auth_url via start_connect, NotConnected payload; bounded by AC-5
- [ ] `complete_connect` nonce peek — bounded by S10 (never consume a nonce that is not the caller's)
- [ ] test bodies — registry monkeypatch + fake manager

---

## Acceptance Criteria

- [ ] `pull_access_token` returns only provider/access_token/expires_at/scopes/account_id, enforces PBAC `integration:use` fail-closed and publishes `connection.token_pulled` without token material (AC-5)
- [ ] No connection → `NotConnected` whose payload is an `AuthRequiredPayload` (AC-5)
- [ ] `complete_connect` rejects a nonce minted for another user without consuming it (S10)
- [ ] FEAT-773 tests `tests/unit/integrations/oauth2/test_service.py` and `packages/ai-parrot/tests/unit/auth/test_connection_events.py` stay green; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py -q`
- `pytest tests/unit/integrations/oauth2/test_service.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_connection_events.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/unit/auth/test_service_cli_endpoints.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: gpt-5.6-sol (codex), 1 attempt, orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Service CLI endpoints implemented as specified; task tests green.
