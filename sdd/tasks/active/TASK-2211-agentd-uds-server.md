# TASK-2211: JsonRpcUnixServer — UDS server, sessions, dispatch, event broker

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2208
**Assigned-to**: unassigned

---

## Context

Spec Module 4: transport server between protocol layer (TASK-2208) and the
daemon service (TASK-2212). Owns the socket, per-connection sessions,
method dispatch, streaming notifications, and event fan-out.

---

## Scope

- Implement `server.py` in `parrot/integrations/agentd/`:
  - `JsonRpcUnixServer(socket_path, dispatch, *, max_line_bytes)`:
    `asyncio.start_unix_server` accept loop; per-connection `Session`
    (session_id uuid, subscription flag, active stream_ids, writer lock).
  - Boot sequence: create parent dir `0700`; if socket exists, try-connect —
    alive ⇒ raise `DaemonAlreadyRunning`; dead ⇒ unlink; after bind, chmod
    socket `0600`.
  - Dispatch: `dispatch: dict[str, Handler]` where
    `Handler = Callable[[Session, dict], Awaitable[Any]]`. Wrap every call:
    exception → RpcResponse error (message only), full traceback to logger.
    Unknown method → −32601; invalid params (pydantic validation) → −32602.
  - Streaming support: helper `session.notify(method, params)` (serialized
    writes under the session lock) used by handlers to emit
    `chat.delta`/`chat.complete`/`chat.error`.
  - `EventBroker`: `subscribe(session)`, `unsubscribe(session)`,
    `async publish(method, params)` fan-out to subscribed sessions (drop
    dead connections silently).
  - Disconnect handling: cancel that session's in-flight tasks/streams,
    unsubscribe, close writer.
  - `async close()`: stop accepting, close sessions, unlink socket.
- Unit tests over a tmp socket with a toy dispatch table (no agent).

**NOT in scope**: real RPC method implementations (TASK-2212), client
(TASK-2213), signals/sd_notify (TASK-2212).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/server.py` | CREATE | Server, Session, EventBroker, boot/stale-socket logic |
| `packages/ai-parrot-integrations/tests/agentd/test_server.py` | CREATE | Unit tests (tmp socket, toy handlers) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.agentd.protocol import (   # from TASK-2208
    RpcRequest, RpcResponse, RpcNotification, read_message, write_message,
    METHOD_NOT_FOUND, INVALID_PARAMS,  # names may differ — use whatever TASK-2208 exported; VERIFY first
)
import asyncio, os, stat, uuid
from pathlib import Path
```

### Existing Signatures to Use
```python
# asyncio.start_unix_server(client_connected_cb, path=...) -> Server   # stdlib
# TASK-2208 protocol.py — read the actual file for exact codec signatures before coding.
```

### Does NOT Exist
- ~~`parrot.integrations.agentd.server`~~ — created by this task.
- ~~aiohttp / navigator anything~~ — forbidden in agentd (spec §7).
- ~~a repo ConnectionManager/SessionManager to reuse~~ — none applies here; implement locally.

---

## Implementation Notes

### Key Constraints
- One writer at a time per connection (asyncio.Lock per session) — responses
  and notifications interleave otherwise.
- Handlers run as tasks so a slow `chat.send` doesn't block other requests
  on the same connection; track tasks per session for cancel-on-disconnect.
- Socket permissions are the auth model: dir `0700`, socket `0600` (spec §2).
- TOCTOU on stale socket is accepted (spec §7 Known Risks) — implement
  try-connect-then-unlink exactly.
- Logging via module logger; never print.

### References in Codebase
- Spec §2 "Wire Protocol" + "Error Handling" — behaviour source of truth.

---

## Acceptance Criteria

- [ ] Request → response roundtrip over a real tmp UDS.
- [ ] Two concurrent connections have distinct session_ids and isolated state.
- [ ] Handler exception → JSON-RPC error response; server stays alive.
- [ ] Stale dead socket unlinked and rebound; live socket ⇒ `DaemonAlreadyRunning`.
- [ ] Socket file mode `0600`, parent dir `0700` (asserted in test).
- [ ] Broker publishes only to subscribed sessions; dead subscriber dropped without error.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_server.py -v`; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_server.py
import pytest
from parrot.integrations.agentd.server import JsonRpcUnixServer, DaemonAlreadyRunning

@pytest.mark.asyncio
class TestServer:
    async def test_roundtrip(self, tmp_path): ...
    async def test_unknown_method_32601(self, tmp_path): ...
    async def test_handler_exception_isolated(self, tmp_path): ...
    async def test_stale_socket_reboot(self, tmp_path): ...
    async def test_live_socket_refuses(self, tmp_path): ...
    async def test_permissions(self, tmp_path): ...
    async def test_event_broker_fanout(self, tmp_path): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2208 is in `sdd/tasks/completed/`; 3. verify contract
(read protocol.py as built — exact names); 4. index → in-progress; 5. implement;
6. verify criteria; 7. move to completed/; 8. index → done; 9. Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
