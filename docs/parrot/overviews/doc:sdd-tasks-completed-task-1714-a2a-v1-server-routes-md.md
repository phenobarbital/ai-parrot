---
type: Wiki Overview
title: 'TASK-1714: A2AServer — v1.0 REST Routes & Version Negotiation'
id: doc:sdd-tasks-completed-task-1714-a2a-v1-server-routes-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The A2A v1.0.0 spec defines specific REST binding routes using colon syntax
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
---

# TASK-1714: A2AServer — v1.0 REST Routes & Version Negotiation

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1712, TASK-1713
**Assigned-to**: unassigned

---

## Context

The A2A v1.0.0 spec defines specific REST binding routes using colon syntax
(`POST /message:send`, `POST /tasks/{id}:cancel`) that differ from the current
custom routes (`POST /a2a/message/send`, `POST /a2a/tasks/{id}/cancel`). The
spec also mandates an `A2A-Version` header for version negotiation and changes
the well-known discovery URI from `agent.json` to `agent-card.json`.

This task adds the v1.0 routes alongside existing v0.3 routes, implements
version negotiation, and adds the v1.0 well-known endpoint.

Implements spec §3 Module 3 (route/version part).

---

## Scope

- Add v1.0.0 REST binding routes in `setup()`:
  - `POST {base_path}/message:send` → `_handle_send_message`
  - `POST {base_path}/message:stream` → `_handle_stream_message`
  - `GET {base_path}/tasks/{task_id}` → (already exists, shared)
  - `POST {base_path}/tasks/{task_id}:cancel` → `_handle_cancel_task`
  - `POST {base_path}/tasks/{task_id}:subscribe` → `_handle_subscribe`
- Add `/.well-known/agent-card.json` endpoint (v1.0 discovery URI),
  keeping `/.well-known/agent.json` for v0.3 compat.
- Implement `_get_request_version(request) -> str` helper that reads the
  `A2A-Version` header: `"1.0"` → v1.0; empty/`"0.3"` → v0.3;
  unsupported → raise `VersionNotSupportedError`.
- Update all response handlers to pass `version` to `to_dict()`:
  - `_handle_agent_card`: version-aware AgentCard serialization.
  - `_handle_send_message`: version-aware Task serialization.
  - `_handle_get_task`, `_handle_list_tasks`, `_handle_cancel_task`:
    version-aware Task serialization.
  - `_handle_stream_message`: version-aware SSE event serialization.
- Set `Content-Type: application/a2a+json` for v1.0 responses (keep
  `application/json` for v0.3).
- Process `SendMessageConfiguration` from request body:
  - `historyLength`: trim `task.history` to this length in response.
  - `returnImmediately`: if `true`, return task with `SUBMITTED` status
    immediately, process in background.

**NOT in scope**:
- JSON-RPC method refactoring (TASK-1715)
- Push notification routes (TASK-1716)
- Error code table (TASK-1715)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | Add v1.0 routes, version negotiation, well-known endpoint |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.a2a.models import (
    AgentCard, Task, TaskState, TaskStatus, Message, Part, Artifact,
    AgentSkill, AgentCapabilities, SendMessageConfiguration,
)
from aiohttp import web
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/a2a/server.py

class A2AServer:                                           # line 50
    def setup(self, app, url=None) -> None:                # line 171
    # Current routes registered at lines 186-197:
    #   GET  /.well-known/agent.json
    #   POST {base}/message/send
    #   POST {base}/message/stream
    #   GET  {base}/tasks/{task_id}
    #   GET  {base}/tasks
    #   POST {base}/tasks/{task_id}/cancel
    #   GET  {base}/tasks/{task_id}/subscribe
    #   POST {base}/rpc

    async def _handle_agent_card(self, request):           # line 873
    async def _handle_send_message(self, request):         # line 878
    async def _handle_stream_message(self, request):       # line 906
    async def _handle_get_task(self, request):             # line 1151
    async def _handle_list_tasks(self, request):           # line 1162
    async def _handle_cancel_task(self, request):          # line 1184
    async def _handle_subscribe(self, request):            # line 1205
    async def _handle_jsonrpc(self, request):              # line 1228

    async def process_message(self, message) -> Task:      # line 595
    async def _send_sse(self, response, data):             # line 1147
```

### Does NOT Exist

- ~~`A2AServer._get_request_version()`~~ — must be created
- ~~`A2AServer._handle_agent_card_v1()`~~ — does not exist; reuse `_handle_agent_card`
- ~~`SendMessageConfiguration`~~ — created in TASK-1712 (verify exists)
- ~~Route `/message:send`~~ — not yet registered (must be added)
- ~~Route `/.well-known/agent-card.json`~~ — not yet registered

---

## Implementation Notes

### Version Negotiation Pattern

```python
def _get_request_version(self, request: web.Request) -> str:
    """Extract A2A protocol version from request header."""
    version = request.headers.get("A2A-Version", "").strip()
    if not version or version.startswith("0.3"):
        return "0.3"
    if version.startswith("1."):
        return "1.0"
    raise web.HTTPBadRequest(
        text=json.dumps({
            "error": {
                "code": -32009,
                "message": f"Version not supported: {version}"
            }
        }),
        content_type="application/json"
    )
```

### Route Registration (v1.0 alongside v0.3)

```python
# In setup():
# v0.3 compat routes (existing)
app.router.add_post(f"{bp}/message/send", self._handle_send_message)
# v1.0 REST binding routes (new)
app.router.add_post(f"{bp}/message:send", self._handle_send_message)
app.router.add_post(f"{bp}/message:stream", self._handle_stream_message)
app.router.add_post(f"{bp}/tasks/{{task_id}}:cancel", self._handle_cancel_task)
app.router.add_post(f"{bp}/tasks/{{task_id}}:subscribe", self._handle_subscribe)
# v1.0 well-known
app.router.add_get("/.well-known/agent-card.json", self._handle_agent_card)
```

### Key Constraints

- Verify aiohttp handles colons in route patterns (`:send`, `:cancel`).
  aiohttp treats colons as literal characters in fixed segments, which is
  correct for the v1.0 REST binding.
- The same handler functions serve both v0.3 and v1.0 routes — the handler
  reads `A2A-Version` and serializes accordingly.
- `returnImmediately` in `SendMessageConfiguration`: when `true`, create the
  task, start `process_message` as a background `asyncio.Task`, and return
  the task immediately with `SUBMITTED` status.

---

## Acceptance Criteria

- [ ] `POST {base}/message:send` route registered and functional
- [ ] `POST {base}/message:stream` route registered and functional
- [ ] `POST {base}/tasks/{id}:cancel` route registered and functional
- [ ] `POST {base}/tasks/{id}:subscribe` route registered and functional
- [ ] `/.well-known/agent-card.json` serves the AgentCard
- [ ] `/.well-known/agent.json` still works (v0.3 compat)
- [ ] `A2A-Version: 1.0` → v1.0 serialization in response
- [ ] `A2A-Version: 0.3` or absent → v0.3 serialization in response
- [ ] Unknown version → HTTP 400 with error code -32009
- [ ] v1.0 responses have `Content-Type: application/a2a+json`
- [ ] `SendMessageConfiguration.historyLength` trims response history
- [ ] `SendMessageConfiguration.returnImmediately=true` returns task
      immediately with SUBMITTED status
- [ ] Existing v0.3 routes still work unchanged
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_a2a_v1_server.py
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop


class TestVersionNegotiation:
    async def test_v1_header_returns_v1_format(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent-card.json",
                                headers={"A2A-Version": "1.0"})
        data = await resp.json()
        assert "supportedInterfaces" in data

    async def test_no_header_returns_v03(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent.json")
        data = await resp.json()
        assert "url" in data
        assert "supportedInterfaces" not in data

    async def test_unsupported_version(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/message:send",
                                 headers={"A2A-Version": "2.0"},
                                 json={"message": {"role": "user", "parts": [{"text": "hi"}]}})
        assert resp.status == 400

    async def test_v1_content_type(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.get("/.well-known/agent-card.json",
                                headers={"A2A-Version": "1.0"})
        assert "application/a2a+json" in resp.content_type
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/a2a-protocol-compatibility.spec.md`
2. **Check dependencies** — TASK-1712 and TASK-1713 must be complete
3. **Verify** models updated by TASK-1712/1713 exist and match expected signatures
4. **Test** that aiohttp correctly routes URLs with colons (`:send`, `:cancel`)
5. **Run tests**
6. **Move this file** to `sdd/tasks/completed/`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 4.8) — 2026-07-10
**Notes**: Added v1.0 REST colon-routes (`message:send`, `message:stream`,
`tasks/{id}:cancel`, `tasks/{id}:subscribe`) alongside the v0.3 slash-routes;
added `/.well-known/agent-card.json`. Implemented `_get_request_version`
(A2A-Version header → 0.3/1.0, unsupported → HTTP 400 -32009),
`_content_type_for` (`application/a2a+json` for v1.0), and `_versioned_response`.
All task/card/stream handlers now serialize version-aware; SSE events use
`serialize_task_state`/`serialize_role`. `SendMessageConfiguration.historyLength`
trims response history; `returnImmediately` returns a SUBMITTED task and
processes in the background on the same task object (`process_message` gained an
optional `task=` param).
**Deviations from spec**: fixed a latent bug in `_build_skills_from_tools` where
`tool_manager=None` crashed `get_agent_card()` (now guards `is not None`) — the
new v1.0 well-known route exercises this path with the standard mock agent.
