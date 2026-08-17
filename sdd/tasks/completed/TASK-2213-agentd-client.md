# TASK-2213: AgentDaemonClient — async UDS JSON-RPC client

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2208
**Assigned-to**: unassigned

---

## Context

Spec Module 6 — the single shared client used by the Rich console
(TASK-2214), the one-shot `parrot ask` and the MCP proxy (TASK-2215).

---

## Scope

- Implement `client.py` in `parrot/integrations/agentd/`:
  - `resolve_socket(name_or_path: str) -> Path`: existing path → use it;
    else treat as service name via `default_socket_path()` (TASK-2210).
  - `AgentDaemonClient`:
    - `classmethod async connect(socket_path, *, retries=3, backoff=0.5)` —
      retry with short backoff (survives `systemctl restart`); raise
      `DaemonNotRunning` with an actionable message after exhaustion.
    - Background reader task demultiplexing incoming lines:
      responses matched to pending futures by `id`; notifications routed
      by `stream_id` to per-stream queues, event notifications
      (`event.*`) to an optional `on_event` callback.
    - `async call(method, **params) -> Any` — request/response, raises
      `RpcRemoteError(code, message)` on error responses.
    - `stream(prompt, **metadata) -> AsyncIterator[StreamEvent]` — issues
      `chat.send {stream=true}`, yields typed events
      (`delta(text)` / `complete(response, usage)` / `error(message)`),
      terminating on complete/error.
    - `async subscribe_events(callback)` / `async close()` (cancel reader,
      close writer; pending futures get `ConnectionClosed`).
- Unit tests against a scripted fake server (raw `start_unix_server` with
  canned NDJSON lines — do NOT depend on TASK-2211/2212): call roundtrip,
  interleaved dual-stream demux, error mapping, retry-then-fail, event
  callback, close-with-pending.

**NOT in scope**: REPL proxy (TASK-2214), MCP tools (TASK-2215), CLI
commands (TASK-2216).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/client.py` | CREATE | Client + StreamEvent types + errors |
| `packages/ai-parrot-integrations/tests/agentd/test_client.py` | CREATE | Unit tests (scripted fake server) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.agentd.protocol import (...)        # TASK-2208 — read the file for exact exports
from parrot.integrations.agentd.config import default_socket_path  # TASK-2210
import asyncio, uuid
from pathlib import Path
```

### Existing Signatures to Use
```python
# asyncio.open_unix_connection(path) -> (StreamReader, StreamWriter)   # stdlib
```

### Does NOT Exist
- ~~`parrot.integrations.agentd.client`~~ — created by this task.
- ~~server-side classes needed here~~ — tests use a scripted raw fake, NOT JsonRpcUnixServer (keeps this task parallel-safe after 2208/2210).
- ~~aiohttp~~ — forbidden.

---

## Implementation Notes

### Key Constraints
- Request ids: monotonically increasing int per client instance.
- The reader task must never die silently: on EOF/parse error, fail all
  pending futures with `ConnectionClosed` and surface via `on_event` hook.
- Stream queues bounded (e.g. maxsize=1024) to avoid unbounded memory on a
  slow consumer; document the backpressure choice.
- `StreamEvent` as a small Pydantic model or dataclass — pick Pydantic for
  consistency with the repo.

### References in Codebase
- Spec §2 "New Public Interfaces" (`AgentDaemonClient` shape) and "Error Handling" (retry policy).

---

## Acceptance Criteria

- [ ] Roundtrip call against scripted server; `RpcRemoteError` carries code+message.
- [ ] Two interleaved streams demux correctly by `stream_id`.
- [ ] `connect` retries then raises `DaemonNotRunning` with actionable text.
- [ ] Event notifications reach the callback; streams unaffected.
- [ ] `close()` fails pending futures with `ConnectionClosed` (no hang).
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_client.py -v`; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_client.py
import pytest
from parrot.integrations.agentd.client import (
    AgentDaemonClient, DaemonNotRunning, RpcRemoteError,
)

@pytest.fixture
async def scripted_server(tmp_path):
    """Raw asyncio UDS server replaying canned NDJSON exchanges."""

@pytest.mark.asyncio
class TestClient:
    async def test_call_roundtrip(self, scripted_server): ...
    async def test_error_mapping(self, scripted_server): ...
    async def test_stream_demux_interleaved(self, scripted_server): ...
    async def test_retry_then_daemon_not_running(self, tmp_path): ...
    async def test_close_with_pending(self, scripted_server): ...
```

---

## Agent Instructions

1. Read the spec; 2. verify TASK-2208 (and TASK-2210 for `default_socket_path`) completed;
3. verify contract; 4. index → in-progress; 5. implement; 6. verify criteria;
7. move to completed/; 8. index → done; 9. Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-16
**Notes**: Implemented `client.py` with `resolve_socket()` (existing path
passthrough, else `default_socket_path()` from TASK-2210),
`AgentDaemonClient.connect()` (fixed-backoff retry, raises
`DaemonNotRunning` with an actionable message after exhaustion), a
background `_read_loop()` reader task demuxing responses by `id` (pending
`asyncio.Future`s) and `chat.*` notifications by `stream_id` (bounded
per-stream `asyncio.Queue`, maxsize=1024 for backpressure), `call()`
(raises `RpcRemoteError(code, message)` on error responses),
`stream()` (async generator yielding typed `StreamEvent` — Pydantic model
per project convention — terminating on `complete`/`error`),
`subscribe_events()`, and `close()` (cancels the reader, fails all pending
calls/streams with `ConnectionClosed`). The reader loop never dies
silently: EOF, protocol errors, and unexpected exceptions all funnel into
`_fail_all(ConnectionClosed(...))` so no caller can hang.

6 unit tests in `test_client.py` (5 from the spec + 1 extra for the event
callback) use a scripted raw `asyncio.start_unix_server` fake — NOT
`JsonRpcUnixServer` (TASK-2211), per the task's explicit parallel-safety
instruction — covering: call roundtrip, error-code mapping, two
interleaved streams demuxed correctly by `stream_id`, retry-then-
`DaemonNotRunning`, `close()` failing a pending call with
`ConnectionClosed` (no hang), and `event.*` notifications reaching the
`on_event`/`subscribe_events()` callback. All 6 pass; full `agentd/` suite
(38 tests) still green. `ruff check` clean after auto-fix (unused `noqa`,
import ordering).

**Deviations from spec**: none.
