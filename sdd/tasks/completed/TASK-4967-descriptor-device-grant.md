# TASK-4967: Descriptor device_authorization_url + StandardOAuth2Manager device grant + O365 prompt to stderr

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4966
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (G6, U4, S8, AC-10, AC-13): FEAT-773's `OAuth2ProviderDescriptor` gains an optional
`device_authorization_url`; `StandardOAuth2Manager` gains a server-side device grant (start + one-poll complete) whose
`device_code` is kept under a short-lived Redis handle; the O365 device-code default prompt moves to stderr because stdout
is reserved for stdio JSON-RPC (FEAT-485).

---

## Scope

- `descriptor.py`: add `device_authorization_url: Optional[str] = None` to `OAuth2ProviderDescriptor`; add
  `StandardOAuth2Manager.start_device_authorization`, `complete_device_authorization` and a `_device_key` helper.
- `o365_devicecode_provider.py`: `_default_prompt_callback` prints to `sys.stderr` only.
- Tests for the descriptor field, the manager device grant (handle TTL, pending/slow_down/completed/expired) and the
  O365 prompt.

**NOT in scope**: HTTP endpoints and `IntegrationsService.device_start/device_poll` (TASK-4971); the CLI `--device` flow (TASK-4977); editing deployment descriptor YAML (the providers file is `OAUTH2_PROVIDERS_FILE`, deployment config — documented by TASK-4982).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` | MODIFY | descriptor field + manager device grant |
| `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` | MODIFY | prompt to stderr |
| `packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor_device.py` | CREATE | descriptor + manager tests |
| `packages/ai-parrot/tests/auth/test_o365_prompt_stderr.py` | CREATE | stdout stays empty |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.auth.oauth2.descriptor import OAuth2ProviderDescriptor, StandardOAuth2Manager   # descriptor.py:51, :152
from parrot.auth.oauth2_base import AbstractOAuth2Manager, AbstractOAuth2TokenSet            # oauth2_base.py:193, :165
from parrot.auth.principal import Principal                                                  # principal.py:18
from parrot.auth.oauth2.device_code import (                                                 # TASK-4966
    DeviceAuthorization, DeviceCodeError, SLOW_DOWN_INCREMENT_S, request_device_authorization, request_device_token,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py
# imports today (:9-28): asyncio, logging, time, Path, typing(Any, Awaitable, Callable, Dict, List, Literal, Mapping,
#   Optional, Sequence, Union) — NO json, NO secrets, NO Tuple; navconfig.config; from parrot.auth.oauth2_base import (...)
class OAuth2ProviderDescriptor(BaseModel):            # :51 ; last field `pbac_action_namespace: str = "integration"` :67
class StandardOAuth2Manager(AbstractOAuth2Manager):   # :152
    descriptor; provider_id; token_url; default_scopes; use_pkce (pkce != "none"); require_client_secret   # :155-175
    async def _discover_identity(self, access_token: str) -> Dict[str, Any]                 # :241
    def _build_token_set(self, token_payload, identity) -> AbstractOAuth2TokenSet          # :265
    async def _post_exchange(self, token_response, token_set) -> AbstractOAuth2TokenSet   # :286
    async def _revoke_remote(self, token_set) -> None                                      # :298 — LAST method of the class (ends :320)
# packages/ai-parrot/src/parrot/auth/oauth2_base.py (inherited)
    self.redis (set(key, value, ex=), get, delete, ttl)     # used by create_authorization_url :449-453
    @staticmethod _new_pkce_pair() -> Tuple[str, str]       # :389
    async def _get_session(self) -> aiohttp.ClientSession   # :371
    @asynccontextmanager async def principal_lock(self, user_id: str)   # :351
    async def _persist_token(self, principal, token_set, *, minted: bool, state_payload=None) -> None   # :581
    async def _publish(self, kind, principal, token_set, *, reason=None, state_payload=None) -> None   # :551
    def _public_metadata(self, token_set) -> Dict[str, Any]   # :539
    self.client_id, self.client_secret, self.scopes, self.logger
    _NONCE_KEY_TEMPLATE = "oauth2:{provider}:nonce:{nonce}"   # :60 (device handle mirrors it)
# packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py
# imports (:35-41): logging, time, typing(Any, Callable, Dict, List, Optional) — NO sys
def _default_prompt_callback(flow: Dict[str, Any]) -> None:   # :57 ; three print() calls :68-70
```

### Does NOT Exist
- ~~`OAuth2ProviderDescriptor.device_authorization_url`~~ — added here.
- ~~`StandardOAuth2Manager.start_device_authorization` / `complete_device_authorization` / `_device_key`~~ — added here.
- ~~`AbstractOAuth2Manager._device_key`~~ — do not add to the base class (`oauth2_base.py` is out of scope).
- ~~descriptor YAML files in the repo~~ — descriptors load from `OAUTH2_PROVIDERS_FILE` (`parrot/conf.py:751`, manager.py:2817);
  Microsoft/Google `device_authorization_url` values (§8 Q4) are deployment config, documented by TASK-4982.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor_device.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_o365_prompt_stderr.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py#OAuth2ProviderDescriptor",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py#StandardOAuth2Manager",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py#_default_prompt_callback"
  ]
}
```

---

## Implementation Notes

- The completed poll returns the **token set object** in the dict (`{"status": "completed", "token_set": ts, ...}`) so
  TASK-4971's service can call `persist_credential`. It is never serialized to a client — TASK-4971 strips it.
- Persist exactly like `handle_callback` does (oauth2_base.py:519-528): durable `_persist_token(..., minted=True)` inside
  `principal_lock`, then `_publish("connection.completed", ...)`.
- Store the principal in the Redis record as `principal.model_dump(mode="json")`; TTL = `authorization.expires_in`.
- Never log `device_code`, tokens or the verifier; the handle is an opaque `secrets.token_urlsafe(32)`.
- O365: replace each `print(...)` with `print(..., file=sys.stderr)`; add `import sys`. Docstring: say stderr.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the descriptor field and imports — *why*: AC-10 requires the field to default to `None`.
2. Append the three manager members after `_revoke_remote` — *why*: §3 M8 fixes their signatures.
3. Move the O365 prompt to stderr — *why*: AC-13 / FEAT-485 stdout purity.
4. Write both test files and run the validation commands.

### `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c 'from typing import Any, Awaitable, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Union' descriptor.py)
# REPLACE that line (verified: descriptor.py:13) with the three lines below, and add `import json` / `import secrets`
# next to `import asyncio` (:9).
from typing import Any, Awaitable, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, Union
# AFTER the `from parrot.auth.oauth2_base import (...)` block (:22-28):
from parrot.auth.oauth2.device_code import (
    SLOW_DOWN_INCREMENT_S, DeviceAuthorization, DeviceCodeError, request_device_authorization, request_device_token,
)
from parrot.auth.principal import Principal
```

### `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (MODIFY — field)
```python
# occurrences: 1 (verified: grep -c '    pbac_action_namespace: str = "integration"' descriptor.py)
# AFTER — insert below `    pbac_action_namespace: str = "integration"` (verified: descriptor.py:67)
    device_authorization_url: Optional[str] = None  # RFC 8628 §3.1 endpoint; None = device grant unsupported
```

### `packages/ai-parrot/src/parrot/auth/oauth2/descriptor.py` (MODIFY — manager methods)
```python
# occurrences: 1 (verified: grep -c 'self.logger.warning("%s remote revoke transport failure: %s", self.provider_id, type(exc).__name__)' descriptor.py)
# AFTER — insert below that line (verified: descriptor.py:320), as new methods of StandardOAuth2Manager (4-space indent)

    def _device_key(self, handle: str) -> str:
        """Redis key of a pending provider device grant."""
        return f"oauth2:{self.provider_id}:device:{handle}"

    async def start_device_authorization(
        self, principal: Principal, *, scopes: Optional[List[str]] = None,
    ) -> Tuple[str, DeviceAuthorization]:
        """Start an RFC 8628 grant for ``principal``; returns ``(handle, authorization)``."""
        url = self.descriptor.device_authorization_url
        if not url:
            raise ValueError(f"{self.provider_id} does not support the device authorization grant")
        verifier, challenge = self._new_pkce_pair() if self.use_pkce else (None, None)
        session = await self._get_session()
        authorization = await request_device_authorization(
            session, url, client_id=self.client_id, scopes=list(scopes or self.scopes), code_challenge=challenge,
            client_secret=self.client_secret if self.require_client_secret else None,
        )
        handle = secrets.token_urlsafe(32)
        record = {
            "device_code": authorization.device_code, "code_verifier": verifier,
            "interval": authorization.interval, "principal": principal.model_dump(mode="json"),
        }
        await self.redis.set(self._device_key(handle), json.dumps(record), ex=authorization.expires_in)
        return handle, authorization

    async def complete_device_authorization(self, handle: str) -> Dict[str, Any]:
        """One provider poll: ``{status: pending|completed|failed|expired, ...}``; completed persists + publishes."""
        key = self._device_key(handle)
        raw = await self.redis.get(key)
        if not raw:
            return {"status": "expired"}
        record = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        session = await self._get_session()
        try:
            outcome, payload = await request_device_token(
                session, self.token_url, client_id=self.client_id, device_code=record["device_code"],
                code_verifier=record.get("code_verifier"),
                client_secret=self.client_secret if self.require_client_secret else None,
            )
        except DeviceCodeError as exc:
            await self.redis.delete(key)
            return {"status": "expired" if exc.code in {"expired_token", "timeout"} else "failed", "reason": exc.code}
        if outcome != "approved":
            # FILL IN: on slow_down add SLOW_DOWN_INCREMENT_S to record["interval"] and re-store it keeping the remaining
            #          TTL (await self.redis.ttl(key)); return {"status": "pending", "interval": record["interval"]} — RFC 8628 §3.5
            raise NotImplementedError
        principal = Principal.model_validate(record["principal"])
        identity = await self._discover_identity(payload["access_token"])
        token_set = await self._post_exchange(payload, self._build_token_set(payload, identity))
        async with self.principal_lock(principal.user_id):
            await self._persist_token(principal, token_set, minted=True, state_payload={"channel": principal.channel})
        await self.redis.delete(key)
        await self._publish(
            "connection.completed", principal, token_set,
            state_payload={"channel": principal.channel, "connection_meta": self._public_metadata(token_set)},
        )
        return {"status": "completed", "token_set": token_set, "account_id": token_set.account_id}
```
**Why this shape**: the spec fixes both method signatures (§3 M8); the handle key mirrors the nonce key family
(`oauth2_base.py:60`) and the persist/publish order mirrors `handle_callback` (durable-first, S-1 convention).

### `packages/ai-parrot/src/parrot/auth/oauth2/o365_devicecode_provider.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _default_prompt_callback(flow: Dict\[str, Any\]) -> None:' o365_devicecode_provider.py)
# In the body (verified: :57-70) replace the three print() calls:
    print("\n" + "=" * 60, file=sys.stderr)
    print(message, file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
# and add `import sys` after `import logging` (:37); docstring: "Print the device-login prompt to stderr ..."
```

### `packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor_device.py` (CREATE)
```python
"""Descriptor device field + StandardOAuth2Manager device grant (FEAT-774 M8)."""
import pytest

from parrot.auth.oauth2.descriptor import OAuth2ProviderDescriptor, StandardOAuth2Manager
from parrot.auth.principal import Principal


def test_descriptor_device_url_optional():
    # FILL IN: minimal descriptor (provider_id, display_name, authorization_url, token_url, default_scopes) → field is None
    ...


async def test_start_device_without_url_raises():
    # FILL IN: manager built with a fake redis_client (dict-backed AsyncMock) → ValueError
    ...


async def test_server_device_start_poll(monkeypatch):
    # FILL IN: monkeypatch request_device_authorization/request_device_token in parrot.auth.oauth2.descriptor; start → handle stored
    #          with ex=expires_in; poll pending → {"status": "pending"}; poll approved → _persist_token + _publish called,
    #          key deleted, result["status"] == "completed"; DeviceCodeError("expired_token") → {"status": "expired"}
    ...
```

### `packages/ai-parrot/tests/auth/test_o365_prompt_stderr.py` (CREATE)
```python
"""The O365 device-code prompt never touches stdout (AC-13)."""
from parrot.auth.oauth2.o365_devicecode_provider import _default_prompt_callback


def test_o365_prompt_goes_to_stderr(capsys):
    _default_prompt_callback({"message": "visit https://microsoft.com/devicelogin code ABC"})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "ABC" in captured.err
```

### FILL IN checklist
- [ ] `complete_device_authorization` pending branch — slow_down interval bump + TTL-preserving re-store; bounded by RFC 8628 §3.5
- [ ] descriptor/manager tests — fake Redis + monkeypatched engine calls; bounded by AC-10

---

## Acceptance Criteria

- [ ] `OAuth2ProviderDescriptor.device_authorization_url` defaults to `None`; starting a device grant without it raises `ValueError` (AC-10)
- [ ] `start_device_authorization` stores `oauth2:{provider}:device:{handle}` with TTL `expires_in`; `complete_device_authorization` returns pending/completed/failed/expired and persists durable-first on approval
- [ ] `_default_prompt_callback` writes nothing to stdout (AC-13)
- [ ] Existing descriptor tests stay green; `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor_device.py -q`
- `pytest packages/ai-parrot/tests/auth/test_o365_prompt_stderr.py -q`
- `pytest packages/ai-parrot/tests/unit/auth/test_oauth2_descriptor.py -q`
- `pytest packages/ai-parrot/tests/auth/test_credentials_devicecode.py -q`

---

## Test Specification

```python
# see the two test blocks in the blueprint
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
**Notes**: Implemented as specified; task and merge-tier tests green.
