# TASK-4971: Server device-code endpoints: IntegrationsService.device_start/device_poll + handler wiring

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4967, TASK-4969, TASK-4970
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3/8 (U4, G6, AC-10): `POST /api/v1/connections/{provider}/device/start` and `.../device/poll` let
`parrot connect <provider> --device` complete a provider's RFC 8628 grant **through the server** (the client secret
and the provider `device_code` never leave it). TASK-4970 registered the routes and returns 404 for them; this task
implements them.

---

## Scope

- `service.py`: `device_start(user_id, provider_id, *, principal, request=None)` and
  `device_poll(user_id, provider_id, *, handle, request=None)`.
- `handlers/connections.py`: replace the 404 placeholder for `device/start` and `device/poll`.
- Tests.

**NOT in scope**: the manager grant itself (TASK-4967); the CLI `--device` loop (TASK-4977); O365 store consolidation (S-3a).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/service.py` | MODIFY | device_start / device_poll |
| `packages/ai-parrot-server/src/parrot/handlers/connections.py` | MODIFY | device route dispatch |
| `packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py` | CREATE | service + handler tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.auth.principal import Principal                       # principal.py:18
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry    # service.py:42 (already imported)
```

### Existing Signatures to Use
```python
# TASK-4967 (descriptor.py, StandardOAuth2Manager):
#   async def start_device_authorization(self, principal, *, scopes=None) -> Tuple[str, DeviceAuthorization]  (ValueError when unsupported)
#   async def complete_device_authorization(self, handle) -> Dict  {status: pending|completed|failed|expired, interval?,
#       reason?, token_set? (completed only — NEVER serialize), account_id?}
#   def _device_key(self, handle) -> str   ("oauth2:{provider}:device:{handle}"; record JSON has "principal": {...user_id...})
# TASK-4969 (service.py): pull_access_token / complete_connect / whoami inserted above the "# Internal helpers" block
# service.py: persist_credential(user_id, provider_id, token_set, *, channel, canonical_identity=None)  :403
#             _check_pbac(request, action, provider_id=None, scopes=None) -> bool  :471
# TASK-4970 (connections.py post()): `if suffix in ("device/start", "device/poll"): return ... 404` placeholder
```

### Does NOT Exist
- ~~`IntegrationsService.device_start` / `device_poll`~~ — added here.
- ~~returning `device_code` to the CLI~~ — forbidden; the CLI only ever sees the opaque `handle`, `user_code`,
  `verification_uri(_complete)`, `expires_in`, `interval`.
- ~~ownership check inside `complete_device_authorization`~~ — the manager does not check who polls; the service must.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/service.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/connections.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/service.py#IntegrationsService"
  ]
}
```

---

## Implementation Notes

- `device_start`: unknown provider → ValueError; PBAC `integration:connect` false → PermissionError; call
  `manager.start_device_authorization(principal, scopes=...)`; return `{"handle", "user_code", "verification_uri",
  "verification_uri_complete", "expires_in", "interval"}`.
- `device_poll` ownership: peek `manager.redis.get(manager._device_key(handle))`; record's `principal.user_id` must equal
  `user_id` (`hmac.compare_digest`) else `PermissionError` — a handle is a bearer secret but must also be bound to its
  owner. Missing record → `{"status": "expired"}`.
- On `completed`: `token_set = result.pop("token_set")`, `persist_credential(user_id, provider_id, token_set,
  channel="cli")`, return the dict **without** `token_set`.
- Handler: `device/start` builds `Principal(user_id, channel="cli", channel_user_id=user_id)`; `device/poll` requires
  body `{"handle": str}` (else 400).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Insert `device_start` / `device_poll` into `IntegrationsService` — *why*: AC-10 server half.
2. Replace the handler's 404 placeholder — *why*: TASK-4970 left the routes inert on purpose.
3. Write the tests (fake manager) and run the validation commands.

### `packages/ai-parrot/src/parrot/auth/oauth2/service.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    # Internal helpers' service.py)
# BEFORE — insert above the `# ---- / # Internal helpers / # ----` block (after TASK-4969's complete_connect)
    async def device_start(
        self, user_id: str, provider_id: str, *, principal: Principal, request: Any = None,
        scopes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Start a provider RFC 8628 grant on behalf of ``principal`` (the device_code stays server-side)."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        if not await self._check_pbac(request, "integration:connect", provider_id, list(scopes or provider.default_scopes)):
            raise PermissionError(f"Not permitted to connect provider {provider_id!r}")
        handle, authorization = await provider.manager.start_device_authorization(principal, scopes=scopes)
        return {
            "handle": handle, "user_code": authorization.user_code, "verification_uri": authorization.verification_uri,
            "verification_uri_complete": authorization.verification_uri_complete,
            "expires_in": authorization.expires_in, "interval": authorization.interval,
        }

    async def device_poll(self, user_id: str, provider_id: str, *, handle: str, request: Any = None) -> Dict[str, Any]:
        """One provider poll: ``{status: pending|completed|failed|expired, interval?}``; completion persists the row."""
        provider = OAuth2ProviderRegistry().get(provider_id)
        if provider is None:
            raise ValueError(f"Unknown provider: {provider_id!r}")
        manager = provider.manager
        # FILL IN: peek manager.redis.get(manager._device_key(handle)); missing → {"status": "expired"};
        #          record["principal"]["user_id"] != user_id (hmac.compare_digest) → PermissionError
        result = await manager.complete_device_authorization(handle)
        if result.get("status") == "completed":
            token_set = result.pop("token_set")
            await self.persist_credential(user_id, provider_id, token_set, channel="cli")
        result.pop("token_set", None)
        return result

```

### `packages/ai-parrot-server/src/parrot/handlers/connections.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'if suffix in ("device/start", "device/poll"):' handlers/connections.py — written by TASK-4970)
# REPLACE that `if` and its 404 return with:
            if suffix == "device/start":
                principal = Principal(user_id=user_id, channel="cli", channel_user_id=user_id)
                started = await service.device_start(
                    user_id, provider, principal=principal, request=self.request, scopes=body.get("scopes"),
                )
                return web.json_response(started)
            if suffix == "device/poll":
                handle = body.get("handle")
                if not isinstance(handle, str) or not handle:
                    return web.json_response({"error": "handle is required"}, status=400)
                return web.json_response(await service.device_poll(user_id, provider, handle=handle, request=self.request))
```

### `packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py` (CREATE)
```python
"""Server device-code endpoints (FEAT-774 M3/M8)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal


async def test_device_start_never_returns_device_code(monkeypatch):
    # FILL IN: fake manager.start_device_authorization → (handle, DeviceAuthorization); "device_code" not in result
    ...

async def test_device_poll_owner_check(monkeypatch):
    # FILL IN: record principal user_id "2" polled by user "1" → PermissionError; manager never polled
    ...

async def test_device_poll_completed_persists_without_token(monkeypatch):
    # FILL IN: completed → persist_credential(channel="cli") awaited; returned dict has no "token_set"
    ...
```

### FILL IN checklist
- [ ] `device_poll` ownership peek — bounded by S11/S10 spirit (bind handle to owner)
- [ ] tests — fake registry/manager, PBAC monkeypatch

---

## Acceptance Criteria

- [ ] `device/start` returns handle + user_code + verification URI(s) + expires_in + interval and never `device_code` (AC-10)
- [ ] `device/poll` performs one provider poll, enforces the handle owner, persists the row with channel `cli` on completion
- [ ] `ruff check` clean; FEAT-773 handler tests stay green (TASK-4970's route tests run at merge tier)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_connections_handler.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/unit/auth/test_service_device_endpoints.py block in the blueprint
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

**Completed by**: gpt-5.6-terra (codex) (1 attempt), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Implemented as specified; task tests green. Merge-tier: only tests/cli/test_session.py::test_stream_closed_in_turn_task_after_final_message fails (sandbox read-only ~/.parrot/cli, environmental).
