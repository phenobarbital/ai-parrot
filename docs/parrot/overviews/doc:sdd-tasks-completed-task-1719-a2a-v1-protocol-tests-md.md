---
type: Wiki Overview
title: 'TASK-1719: v1.0 Protocol Integration Tests'
id: doc:sdd-tasks-completed-task-1719-a2a-v1-protocol-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Each prior task includes unit tests for its specific changes. This task adds
relates_to:
- concept: mod:parrot.a2a.client
  rel: mentions
- concept: mod:parrot.a2a.models
  rel: mentions
- concept: mod:parrot.a2a.server
  rel: mentions
---

# TASK-1719: v1.0 Protocol Integration Tests

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1712, TASK-1713, TASK-1714, TASK-1715, TASK-1716, TASK-1717, TASK-1718
**Assigned-to**: unassigned

---

## Context

Each prior task includes unit tests for its specific changes. This task adds
integration tests that exercise the full v1.0 protocol stack end-to-end:
client ↔ server roundtrips, version negotiation across the wire, SSE
streaming with v1.0 event format, and backward compatibility between
v0.3 clients and v1.0 servers (and vice versa).

Implements spec §3 Module 7 and §4 Integration Tests.

---

## Scope

- Create integration test suite exercising full v1.0 protocol stack:
  - **v1.0 roundtrip**: A2AClient (v1.0) → A2AServer (v1.0) → full task
    lifecycle (create → working → completed).
  - **v0.3 client + v1.0 server**: Client sends no `A2A-Version` header,
    server responds in v0.3 format. Verify backward compat.
  - **v1.0 streaming**: SSE events use v1.0 serialization
    (SCREAMING_SNAKE enums, v1.0 event structure).
  - **Version negotiation**: Unsupported version returns -32009.
  - **Push notification CRUD roundtrip**: Create → List → Get → Delete
    via REST and JSON-RPC.
  - **Error code verification**: Each A2A error code (-32001 to -32009)
    is triggered and verified.
- Verify existing v0.3 tests still pass (no regression).
- Run `ruff check` on all modified A2A files.

**NOT in scope**:
- Performance/load testing
- gRPC binding tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/integration/test_a2a_v1_roundtrip.py` | CREATE | End-to-end v1.0 protocol tests |
| `packages/ai-parrot/tests/test_a2a_v1_compat.py` | CREATE | Cross-version compatibility tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.a2a.models import (
    AgentCard, Task, TaskState, Message, Part, AgentInterface,
    AgentCapabilities, SendMessageConfiguration,
    TaskPushNotificationConfig, parse_task_state,
)
from parrot.a2a.server import A2AServer
from parrot.a2a.client import A2AClient
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
```

### Existing Test Patterns to Follow

```python
# packages/ai-parrot-server/tests/integration/test_a2a_bridge_e2e.py
# Uses aiohttp test client pattern — follow the same setup:
#   1. Create a mock agent (BasicAgent or MagicMock with ask() method)
#   2. Wrap in A2AServer
#   3. Create aiohttp app, call server.setup(app)
#   4. Use aiohttp_client fixture to make HTTP requests
```

### Does NOT Exist

- ~~`test_a2a_v1_roundtrip.py`~~ — must be created
- ~~`test_a2a_v1_compat.py`~~ — must be created

---

## Implementation Notes

### Integration Test Setup Pattern

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp import web

@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.name = "TestAgent"
    agent.description = "Test"
    agent.ask = AsyncMock(return_value="Hello from agent")
    agent.tool_manager = None
    agent.tools = []
    return agent

@pytest.fixture
def a2a_app(mock_agent):
    app = web.Application()
    server = A2AServer(mock_agent, capabilities=AgentCapabilities(streaming=True))
    server.setup(app, url="https://test.example.com/a2a")
    return app
```

### Key Test Scenarios

1. **Full lifecycle**: Send message → get task → verify COMPLETED
2. **Version header**: Verify response format changes based on header
3. **Discovery fallback**: agent-card.json (v1.0) vs agent.json (v0.3)
4. **Enum format**: v1.0 response has `TASK_STATE_COMPLETED`, v0.3 has `completed`
5. **Error codes**: Each error type returns the correct JSON-RPC code
6. **Push notification CRUD**: Full lifecycle via REST endpoints
7. **Streaming**: SSE events have correct v1.0 format

### Key Constraints

- Tests must not require a running LLM or external services.
- Use `AsyncMock` for the agent's `ask()` method.
- Test both REST and JSON-RPC bindings.

---

## Acceptance Criteria

- [ ] v1.0 roundtrip test passes (client → server → response)
- [ ] v0.3 client + v1.0 server backward compat test passes
- [ ] SSE streaming test with v1.0 event format passes
- [ ] Version negotiation test passes (unsupported → -32009)
- [ ] Push notification CRUD roundtrip test passes
- [ ] All A2A error codes verified in tests
- [ ] All existing A2A tests pass (no regression):
      `pytest packages/ai-parrot/tests/test_a2a*.py -v`
      `pytest packages/ai-parrot-server/tests/ -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/a2a/`
- [ ] `ruff check packages/ai-parrot-server/src/parrot/a2a/`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/integration/test_a2a_v1_roundtrip.py

class TestV1Roundtrip:
    async def test_send_message_v1(self, aiohttp_client, a2a_app):
        """Full v1.0 message lifecycle."""
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message:send",
            headers={"A2A-Version": "1.0"},
            json={
                "message": {
                    "messageId": "msg-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello"}]
                }
            }
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"]["state"] == "TASK_STATE_COMPLETED"

    async def test_v03_compat(self, aiohttp_client, a2a_app):
        """v0.3 client (no version header) gets v0.3 format."""
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message/send",
            json={
                "message": {
                    "messageId": "msg-1",
                    "role": "user",
                    "parts": [{"text": "Hello"}]
                }
            }
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"]["state"] == "completed"

    async def test_streaming_v1(self, aiohttp_client, a2a_app):
        """SSE streaming uses v1.0 event format."""
        client = await aiohttp_client(a2a_app)
        resp = await client.post(
            "/a2a/message:stream",
            headers={"A2A-Version": "1.0"},
            json={
                "message": {
                    "messageId": "msg-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello"}]
                }
            }
        )
        assert resp.status == 200
        assert "text/event-stream" in resp.content_type


class TestErrorCodes:
    async def test_task_not_found(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/a2a/tasks/nonexistent",
                                headers={"A2A-Version": "1.0"})
        assert resp.status == 404
        data = await resp.json()
        assert data["error"]["code"] == -32001

    async def test_version_not_supported(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message:send",
                                 headers={"A2A-Version": "99.0"},
                                 json={"message": {"role": "user", "parts": [{"text": "hi"}]}})
        assert resp.status == 400
```

---

## Agent Instructions

When you pick up this task:

1. **Verify all prior tasks** (TASK-1712 through TASK-1718) are complete
2. **Run existing tests first**: `pytest packages/ai-parrot/tests/test_a2a*.py -v`
   to establish baseline
3. **Read existing integration tests** in
   `packages/ai-parrot-server/tests/integration/test_a2a_bridge_e2e.py`
   for the test fixture pattern
4. **Create** integration test files
5. **Run all tests**: both new and existing
6. **Run linting**: `ruff check packages/ai-parrot/src/parrot/a2a/` and
   `ruff check packages/ai-parrot-server/src/parrot/a2a/`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 4.8) — 2026-07-10
**Notes**: Added `test_a2a_v1_roundtrip.py` (server): v1.0 REST/JSON-RPC/SSE
round-trips, well-known v1.0 card, push-config CRUD, v0.3 backward compat, and
all error codes (-32001/-32007/-32009/-32601). Added `test_a2a_v1_compat.py`
(core): transport-free cross-version model round-trips (enums, Task, Message,
Part, AgentCard). Full a2a suites green: ai-parrot 74 passed, ai-parrot-server
78 passed (incl. bridge-e2e, credential-gate, identity, resume-trigger — no
regressions). `ruff check` clean on both `parrot/a2a/` dirs.
**Deviations from spec**: none. (Two unrelated server test modules —
test_suspended_store / test_hitl_web_suspend_resume — fail to *collect* due to a
missing `fakeredis` dev dependency; pre-existing and unrelated to A2A.)
