# TASK-2208: JSON-RPC 2.0 / NDJSON protocol layer for agentd

**Feature**: FEAT-422 — Agent CLI Daemon
**Spec**: `sdd/specs/agent-cli-daemon.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation of the daemon wire format (spec §2 "Wire Protocol", Module 1).
Every other agentd module (server, client, service) builds on these framing
codecs and Pydantic message models. Pure-stdlib + pydantic; no I/O beyond
StreamReader/StreamWriter helpers.

---

## Scope

- Create package `packages/ai-parrot-integrations/src/parrot/integrations/agentd/` (`__init__.py`, PEP 420-compatible with the existing `parrot.integrations` namespace — mirror how sibling dirs like `slack/` are laid out).
- Implement `protocol.py`:
  - Pydantic v2 models: `RpcRequest` (jsonrpc="2.0", id, method, params), `RpcResponse` (id, result | error), `RpcError` (code, message, data?), `RpcNotification` (method, params, no id).
  - Error-code constants: JSON-RPC standard (−32700, −32600, −32601, −32602, −32603) + application codes `AGENT_BUSY=1001`, `UNKNOWN_AGENT_METHOD=1002`, `SCHEDULER_UNAVAILABLE=1003`, `SCHEDULE_NOT_FOUND=1004`.
  - NDJSON codec: `async read_message(reader, *, max_line_bytes)` → parsed model or raises `ProtocolError`; `write_message(writer, model)` — one `\n`-terminated UTF-8 JSON object per line. Handle partial/coalesced lines (StreamReader.readline does this) and enforce the size limit (default 10 MB) raising a distinguishable oversize error.
  - Method-name constants for the RPC surface (`chat.send`, `chat.delta`, `chat.complete`, `chat.error`, `agent.info`, `agent.invoke`, `tools.list`, `schedules.list/add/pause/resume/remove`, `events.subscribe/unsubscribe`, `event.job_executed`, `event.job_error`, `event.shutdown`, `daemon.status`, `daemon.shutdown`).
- Unit tests: model roundtrips, split/joined/oversized frames, malformed JSON → error.

**NOT in scope**: socket server (TASK-2211), client (TASK-2213), any dispatch logic, config models (TASK-2210).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/__init__.py` | CREATE | Package init (docstring + re-exports of protocol names) |
| `packages/ai-parrot-integrations/src/parrot/integrations/agentd/protocol.py` | CREATE | Models, error codes, NDJSON codec |
| `packages/ai-parrot-integrations/tests/agentd/__init__.py` | CREATE | Test package |
| `packages/ai-parrot-integrations/tests/agentd/test_protocol.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field   # pydantic v2, already a core dependency
# stdlib only otherwise: asyncio, json
```

### Existing Signatures to Use
```python
# Sibling layout reference — namespace package, no parent __init__ magic:
# packages/ai-parrot-integrations/src/parrot/integrations/slack/  (existing sibling dir)
# asyncio.StreamReader.readline() / .readuntil() — stdlib, used for NDJSON framing
```

### Does NOT Exist
- ~~`parrot.integrations.agentd`~~ — this task CREATES it; nothing to import from it yet.
- ~~any shared "jsonrpc" helper in the repo~~ — do not search for one; there is none. `parrot.mcp.local_server` has inline JSON-RPC handling but it is stdio/MCP-specific — do NOT import from it here.

---

## Implementation Notes

### Key Constraints
- Async-first; no aiohttp imports anywhere in agentd (spec §7).
- Pydantic v2 idioms (`model_dump_json`, `model_validate_json`).
- Oversize protection BEFORE json parsing: use `reader.readuntil(b"\n")` with `limit` set on the reader, or explicit length check; must not buffer unbounded input.
- Google-style docstrings + strict type hints.

### References in Codebase
- `packages/ai-parrot-integrations/src/parrot/integrations/slack/` — sibling package layout to mirror.
- Spec §2 "Wire Protocol" table — authoritative method list.

---

## Acceptance Criteria

- [ ] `from parrot.integrations.agentd.protocol import RpcRequest, RpcResponse, RpcNotification` works (venv, namespace-merged).
- [ ] Split frames (one message over two reads) and coalesced frames (two messages one read) both decode correctly.
- [ ] A line over `max_line_bytes` raises a specific oversize error without OOM.
- [ ] Malformed JSON → parse error (−32700) representation, not a crash.
- [ ] All tests pass: `pytest packages/ai-parrot-integrations/tests/agentd/test_protocol.py -v`
- [ ] `ruff check` clean on new files.

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/agentd/test_protocol.py
import pytest
from parrot.integrations.agentd.protocol import (
    RpcRequest, RpcResponse, RpcNotification, ProtocolError,
    read_message, write_message,
)

class TestModels:
    def test_request_roundtrip(self): ...
    def test_response_error_shape(self): ...
    def test_notification_has_no_id(self): ...

@pytest.mark.asyncio
class TestFraming:
    async def test_split_frame(self): ...       # feed bytes in two chunks
    async def test_coalesced_frames(self): ...  # two messages, one chunk
    async def test_oversized_line_rejected(self): ...
    async def test_malformed_json(self): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing ANY code
4. **Update status** in `sdd/tasks/index/agent-cli-daemon.json` → `"in-progress"`
5. **Implement** following the scope, contract, and notes above
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
