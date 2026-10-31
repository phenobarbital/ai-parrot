# TASK-4972: ServerConnectionsClient — aiohttp client for the connections API with bearer auto-refresh

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4968, TASK-4969
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (G3, U2, S5): the CLI side of the connections API, used by the principal resolver (TASK-4974), the
remote resolver (TASK-4973), `parrot connect` (TASK-4977) and agentd (TASK-4979). Bearer = the login's access token; on
the first 401 it refreshes once via `refresh_login` and retries. aiohttp client only — no server imports (FEAT-485).

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py`: `NotLoggedIn`, `ConnectAttempt`,
  `ServerConnectionsClient` (`me`, `list`, `status`, `start_connect`, `complete`, `pull_token`, `disconnect`,
  `device_start`, `device_poll`, `close`, async context manager); re-export `WhoAmI`, `PulledToken`, `NotConnected`.
- Tests against an aiohttp `TestServer` fake.

**NOT in scope**: the cache / resolver / broker (TASK-4973); exporting from `parrot/auth/oauth2/__init__.py` (would create an import cycle — see notes).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py` | CREATE | ServerConnectionsClient |
| `packages/ai-parrot/tests/auth/test_remote_client.py` | CREATE | client tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
import aiohttp
from pydantic import BaseModel
from parrot.auth.credentials import AuthRequiredPayload                         # credentials.py:114
from parrot.auth.oauth2.models import NotConnected, PulledToken, WhoAmI          # TASK-4969
from parrot.cli.login import LoginExpired, LoginRecord, LoginStore, refresh_login   # TASK-4968
```

### Existing Signatures to Use
```python
# TASK-4968 parrot/cli/login.py: LoginStore(path=None).load_optional(*, expected_uid=None) -> Optional[LoginRecord] (sync, raises LoginFileError)
#   LoginStore.save(record) (sync) ; refresh_login(record, session) -> LoginRecord (raises LoginExpired)
#   LoginRecord: server_url, access_token, refresh_token, expires_at, user_id, ...
# Server routes (FEAT-773 + TASK-4970/4971), all bearer-authenticated:
#   GET    /api/v1/connections                       → [IntegrationDescriptor]
#   GET    /api/v1/connections/me                    → WhoAmI
#   GET    /api/v1/connections/{provider}            → IntegrationDescriptor (status: connected|disconnected|needs_reconnect, connected_at, updated_at ISO)
#   POST   /api/v1/connections/{provider}/start      body {channel: "cli", scopes?} → ConnectInitResponse {auth_url, state, scopes, expires_in}
#   POST   /api/v1/connections/{provider}/complete   body {code, state} → IntegrationDescriptor
#   POST   /api/v1/connections/{provider}/token      → PulledToken | 409 AuthRequiredPayload
#   DELETE /api/v1/connections/{provider}            → DisconnectResponse
#   POST   /api/v1/connections/{provider}/device/start | device/poll {handle}
```

### Does NOT Exist
- ~~`parrot.auth.oauth2.remote_client` / `ServerConnectionsClient`~~ — created here.
- ~~`from parrot.auth.oauth2 import ServerConnectionsClient`~~ — do NOT export from the package `__init__`:
  `parrot.cli.login` imports `parrot.auth.oauth2.device_code`, which runs the package `__init__`; if that `__init__`
  imported `remote_client` (→ `parrot.cli.login`) the import would be circular.
- ~~server-side imports (`navigator`, `navigator_auth`, `parrot.handlers`)~~ — forbidden in this module (FEAT-485).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/auth/test_remote_client.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- `ServerConnectionsClient(store, *, session=None)`; lazily create an owned `aiohttp.ClientSession(timeout=30s)`;
  `close()` closes only an owned session; `__aenter__/__aexit__` call it.
- `_record()` loads the login with `await asyncio.to_thread(store.load_optional)`; `None` → `NotLoggedIn`.
- `_request(method, path, *, json=None)`: Bearer header from the record; on 401 **once**: under an `asyncio.Lock`,
  reload the record (another task may have refreshed), `refresh_login`, `await asyncio.to_thread(store.save, new)`,
  retry. A second 401 or `LoginExpired` → raise `LoginExpired`. Other non-2xx → `RuntimeError(f"{method} {path}: HTTP {status}")`
  (no body echo — it may carry codes).
- `pull_token`: 409 → `NotConnected(AuthRequiredPayload.model_validate(body))`.
- `start_connect` records `started_at=time.time()` *before* the POST (S10) and returns `ConnectAttempt`.
- Never log the Authorization header, tokens, codes or state values.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `remote_client.py` from the block — *why*: fixes the API all CLI consumers share.
2. Complete `_request` (401 single refresh) and the method bodies — *why*: Q5/S5.
3. Write tests with an aiohttp `TestServer` fake parrot server; run the validation command.

### `packages/ai-parrot/src/parrot/auth/oauth2/remote_client.py` (CREATE)
```python
"""aiohttp client for /api/v1/connections* (FEAT-774 M4). CLI-side only; never imports server code."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp
from pydantic import BaseModel

from parrot.auth.credentials import AuthRequiredPayload
from parrot.auth.oauth2.models import NotConnected, PulledToken, WhoAmI
from parrot.cli.login import LoginExpired, LoginRecord, LoginStore, refresh_login

__all__ = ["ConnectAttempt", "NotConnected", "NotLoggedIn", "PulledToken", "ServerConnectionsClient", "WhoAmI"]
logger = logging.getLogger(__name__)
_BASE = "/api/v1/connections"


class NotLoggedIn(RuntimeError):
    """No login record; run `parrot login`."""


class ConnectAttempt(BaseModel):
    """CLI-side correlation of one connect (S10); never stored server-side."""

    provider: str
    state: str
    auth_url: str
    started_at: float
    expires_in: int = 600


class ServerConnectionsClient:
    """Bearer = LoginRecord.access_token; on 401 once: refresh_login then retry; never logs tokens."""

    def __init__(self, store: LoginStore, *, session: Optional[aiohttp.ClientSession] = None) -> None:
        self.store = store
        self._session = session
        self._owns_session = session is None
        self._refresh_lock = asyncio.Lock()
        self.logger = logger

    async def __aenter__(self) -> "ServerConnectionsClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()

    async def _record(self) -> LoginRecord:
        record = await asyncio.to_thread(self.store.load_optional)
        if record is None:
            raise NotLoggedIn("not logged in — run `parrot login`")
        return record

    async def _request(self, method: str, path: str, *, json: Optional[Dict[str, Any]] = None) -> tuple[int, Any]:
        """Return ``(status, parsed_json_or_None)``; refreshes the login once on 401 (Q5)."""
        # FILL IN: lazily create the owned session; send with Authorization: Bearer; on 401 refresh once under
        #          self._refresh_lock (reload record, refresh_login, to_thread(store.save)), retry; second 401 → LoginExpired;
        #          return (status, body) — callers map 409 and other errors
        raise NotImplementedError

    async def me(self) -> WhoAmI:
        status, body = await self._request("GET", f"{_BASE}/me")
        # FILL IN: non-200 → RuntimeError("GET /me: HTTP <status>"); WhoAmI.model_validate(body)
        raise NotImplementedError

    async def pull_token(self, provider: str) -> PulledToken:
        status, body = await self._request("POST", f"{_BASE}/{provider}/token")
        if status == 409:
            raise NotConnected(AuthRequiredPayload.model_validate(body))
        # FILL IN: non-200 → RuntimeError; PulledToken.model_validate(body)
        raise NotImplementedError

    async def start_connect(
        self, provider: str, *, channel: str = "cli", scopes: Optional[List[str]] = None,
    ) -> ConnectAttempt:
        started_at = time.time()
        # FILL IN: POST {_BASE}/{provider}/start {"channel": channel, "scopes": scopes}; → ConnectAttempt(provider, state,
        #          auth_url, started_at, expires_in) — S10
        raise NotImplementedError

    # FILL IN: list() GET _BASE → list ; status(provider) GET → dict ; complete(provider, *, code, state) POST /complete → dict ;
    #          disconnect(provider) DELETE ; device_start(provider) POST /device/start → dict ;
    #          device_poll(provider, handle) POST /device/poll {"handle"} → dict — signatures per spec §2 New Public Interfaces
```
**Why this shape**: spec §2 fixes the class and its nine methods; `NotLoggedIn`, `close()` and the context manager are
additive. `WhoAmI`/`PulledToken`/`NotConnected` are re-exported so `parrot.auth.oauth2.remote_client.WhoAmI` (the spec's
path) keeps working while the server imports them from `models.py`.

### `packages/ai-parrot/tests/auth/test_remote_client.py` (CREATE)
```python
"""ServerConnectionsClient (FEAT-774 M4)."""
import pytest

from parrot.auth.oauth2.remote_client import NotConnected, NotLoggedIn, ServerConnectionsClient


async def test_me_and_bearer_header(aiohttp_server, tmp_path):
    # FILL IN: fake app records Authorization header; me() → WhoAmI; header == "Bearer <access_token>"
    ...

async def test_401_refreshes_once_then_retries(aiohttp_server, tmp_path, monkeypatch):
    # FILL IN: first call 401, refresh_login patched → new token saved; retry 200; a second 401 → LoginExpired
    ...

async def test_pull_token_409_raises_not_connected(aiohttp_server, tmp_path):
    ...

async def test_no_login_raises_not_logged_in(tmp_path):
    ...
```

### FILL IN checklist
- [ ] `_request` — owned session, bearer, single refresh under lock; bounded by Q5 (one refresh, then fail)
- [ ] `me` / `pull_token` / `start_connect` bodies and the six remaining methods; bounded by spec §2 signatures
- [ ] tests — aiohttp_server fake (pytest-aiohttp is installed)

---

## Acceptance Criteria

- [ ] All nine spec methods exist with the spec signatures; `pull_token` maps 409 → `NotConnected(AuthRequiredPayload)`
- [ ] A 401 triggers exactly one `refresh_login` + save + retry; a second failure raises `LoginExpired`
- [ ] No server-side imports; no token/code/state in logs (AC-14); `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/auth/test_remote_client.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/auth/test_remote_client.py block in the blueprint
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

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
