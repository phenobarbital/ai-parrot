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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-09
**Notes**:
- Created `packages/ai-parrot-server/tests/integration/test_a2a_v1_roundtrip.py`
  (17 tests) using a real `aiohttp.test_utils.TestServer` + `A2AClient`
  connected over an actual local socket (genuine end-to-end, not mocked):
  full v1.0 lifecycle (discover -> send -> get -> list), v0.3 backward
  compat (a real `aiohttp.ClientSession` that never sends `A2A-Version`,
  proving the SAME server instance serves both wire formats correctly),
  v1.0 SSE streaming (fallback path — the mock agent is built with
  `spec=[...]` explicitly excluding `ask_stream` so the test exercises the
  intended non-streaming-fallback branch rather than accidentally tripping
  `hasattr(agent, "ask_stream")` truthy on a bare `MagicMock()`), version
  negotiation (-32009), push notification CRUD via BOTH REST and JSON-RPC,
  and the full A2A error code table.
- **Error code table verification design decision**: -32001
  (TaskNotFoundError), -32002 (TaskNotCancelableError), -32003
  (PushNotificationNotSupportedError), -32007
  (ExtendedAgentCardNotConfiguredError), and -32009
  (VersionNotSupportedError) are triggered END-TO-END over real HTTP calls.
  -32004 (UnsupportedOperationError), -32005 (ContentTypeNotSupportedError),
  -32006 (InvalidAgentResponseError), and -32008
  (ExtensionSupportRequiredError) have NO operation in this spec that raises
  them — extensions, content-negotiation, and gRPC are all explicitly listed
  as out of scope in the spec's Non-Goals (§1) and Gap Analysis (§ "Out of
  scope" rows). Rather than inventing new server operations (which would
  violate this task's own file list — test files only — and TASK-1715's
  scope, which only wired the 5 codes above), these four are verified
  directly against the `A2A_ERRORS` table (code + HTTP status), plus a
  completeness assertion that all 9 codes are present. Documented inline in
  the test file's module docstring and `TestA2AErrorCodeTable` class
  docstring.
- Created `packages/ai-parrot/tests/test_a2a_v1_compat.py` (12 tests).
  **Scope note flagged clearly in the file's own docstring**: this file was
  kept WITHIN the `ai-parrot` package boundary (models + client only, no
  `A2AServer` import) rather than importing across into `ai-parrot-server`.
  Verified empirically that `ai-parrot`'s own test conftest chain
  (`packages/ai-parrot/conftest.py` + `packages/ai-parrot/tests/conftest.py`)
  only inserts `ai-parrot`'s OWN worktree `src/` into `sys.path` — NOT
  `ai-parrot-server`'s — so a bare `import parrot.a2a.server` from a test
  under `packages/ai-parrot/tests/` resolves to the stale MAIN-REPO
  `ai-parrot-server` install (pre-FEAT-272), not this worktree's version,
  when that test file is run standalone (outside a combined invocation that
  happens to load `ai-parrot-server`'s conftest first). Modifying the shared
  `packages/ai-parrot/tests/conftest.py` to insert a cross-package path was
  judged out of scope (a shared infra file, not part of any of this
  feature's 8 tasks' file lists, and risky to touch for every other test in
  that tree). Since every "cross-version compatibility" scenario is fully
  expressible in terms of `parrot.a2a.client` + `parrot.a2a.models` alone
  (AgentCard round-tripping both wire shapes, Task/Part/enum compat parsing,
  and the client's route-selection logic for v0.3-vs-v1.0 servers), this
  file covers that ground with synthetic payloads and mocked
  `aiohttp.ClientSession`s instead. All the scenarios that genuinely need a
  live server (full roundtrip, SSE, push CRUD, error codes) are already
  covered end-to-end in `test_a2a_v1_roundtrip.py` (same package as
  `A2AServer`, no cross-package import concern).
- **Full regression run** (final, after all 8 tasks):
  - `packages/ai-parrot/tests/test_a2a_tools.py` (22) — pass
  - `packages/ai-parrot/tests/test_a2a_v1_models.py` (40) — pass
  - `packages/ai-parrot/tests/test_a2a_v1_client.py` (11) — pass
  - `packages/ai-parrot/tests/test_a2a_v1_mesh_router.py` (10) — pass
  - `packages/ai-parrot/tests/test_a2a_v1_compat.py` (12) — pass
  - `packages/ai-parrot-server/tests/unit/test_a2a_v1_server.py` (14) — pass
  - `packages/ai-parrot-server/tests/unit/test_a2a_v1_jsonrpc_errors.py` (15) — pass
  - `packages/ai-parrot-server/tests/unit/test_a2a_push_notifications.py` (16) — pass
  - `packages/ai-parrot-server/tests/unit/test_a2a_credential_gate.py` (existing, pre-FEAT-272) — pass
  - `packages/ai-parrot-server/tests/unit/test_a2a_identity.py` (existing) — pass
  - `packages/ai-parrot-server/tests/unit/test_a2a_resume_trigger.py` (existing) — pass
  - `packages/ai-parrot-server/tests/integration/test_a2a_bridge_e2e.py` (existing) — pass
  - `packages/ai-parrot-server/tests/integration/test_a2a_v1_roundtrip.py` (17) — pass
  - Total new tests across the feature: 155. Total including pre-existing
    A2A regression coverage exercised: 195 passing.
- **`ruff check` acceptance criterion — partial, with pre-existing
  violations flagged, NOT fixed (file-fidelity decision)**:
  `ruff check packages/ai-parrot-server/src/parrot/a2a/` — **clean, 0
  errors**. `ruff check packages/ai-parrot/src/parrot/a2a/` — **3
  pre-existing errors** (`client.py`: unused `asyncio`, unused
  `dataclasses.field`; `router.py`: unused exception variable `e` at one
  `except Exception as e: ... raise` site), all three confirmed via
  `git show dev:packages/ai-parrot/src/parrot/a2a/<file>.py` + `ruff check`
  against `dev` directly to predate FEAT-272 entirely — none are on lines I
  touched. I chose NOT to fix them here: TASK-1719's own file list is
  exactly the two test files above (no source files), and the cardinal
  "touch ONLY the files listed in the task" rule takes precedence over the
  literal wording of this task's ruff-check acceptance bullet when the two
  conflict. Flagging this explicitly rather than silently either violating
  file fidelity or silently leaving the acceptance criterion looking
  unaddressed.
- Pre-existing, unrelated failures (present before and after this entire
  feature, confirmed unrelated to A2A): 3 tests in
  `test_a2a_jira_vertical.py` / `test_a2a_fireflies_vertical.py` /
  `test_a2a_workiq_vertical.py` (`*_broker_registers_provider`) fail on an
  assertion about `CredentialBroker._resolvers` internal tuple structure —
  this is in `parrot.auth.broker`, a module untouched by any of this
  feature's 8 tasks.
**Deviations from spec**: the two design decisions above (error-code
verification split between live-triggered and table-only for codes with no
wired operation; and `test_a2a_v1_compat.py` staying within the `ai-parrot`
package boundary) are both documented in-file and here. The `ruff check`
partial-pass on `ai-parrot/src/parrot/a2a/` (3 pre-existing, unrelated
violations) is flagged for the user's awareness — recommend a separate,
explicitly-scoped cleanup task if a fully clean `ruff check` is desired
across that file.
