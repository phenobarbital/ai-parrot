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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-09
**Notes**:
- `setup()`: added v1.0 colon-syntax routes (`message:send`, `message:stream`,
  `tasks/{id}:cancel`, `tasks/{id}:subscribe`) reusing the SAME handlers as
  the v0.3 slash routes (confirmed aiohttp routes colons in fixed path
  segments correctly — no routing conflicts, verified via the new tests).
  Added `/.well-known/agent-card.json` (v1.0) alongside the existing
  `/.well-known/agent.json` (v0.3), both wired to `_handle_agent_card`.
- Added `_get_request_version()` (raises `web.HTTPBadRequest` with
  `{"error": {"code": -32009, ...}}` for unsupported versions — the -32009
  constant matches the A2A error table TASK-1715 formalizes),
  `_content_type_for()` (`application/a2a+json` for v1.0, `application/json`
  for v0.3), and `_state_str()` (thin wrapper around
  `TaskStatus(state=X).to_dict(version=)["state"]` so SSE handlers building
  raw event dicts don't need to reach into `models.py` private helpers).
- All REST handlers (`_handle_agent_card`, `_handle_send_message`,
  `_handle_stream_message` + its two streaming helpers, `_handle_get_task`,
  `_handle_list_tasks`, `_handle_cancel_task`, `_handle_subscribe`) now call
  `_get_request_version()` first (so `HTTPBadRequest` propagates before
  entering any `try/except Exception` block that would otherwise swallow it
  as a 500) and pass `version=` through to every `to_dict()` call, including
  nested `Message`/`Artifact` serialization inside SSE payloads.
- `process_message()` gained an optional `task: Optional[Task] = None`
  parameter (default preserves existing behavior for all current callers —
  verified via the full existing A2A regression suite) so the
  `returnImmediately` path can hand it a pre-created `SUBMITTED` task,
  schedule `process_message(message, task=task)` as a background
  `asyncio.Task`, and return the same task object immediately.
- `SendMessageConfiguration` is parsed from `data.get("configuration")` in
  `_handle_send_message`; `historyLength` trims `task.history`,
  `returnImmediately` triggers the background-processing path described above.
- `_handle_list_tasks`'s `status` query-param filter was changed from
  `t.status.state.value == state` to `t.status.state == parse_task_state(state)`
  — the literal `.value` comparison silently broke for v0.3 lowercase query
  values once `TaskState.value` became SCREAMING_SNAKE in TASK-1712; using
  the existing `parse_task_state()` compat helper keeps the filter working
  for both wire formats. No test covered this before (verified via grep), so
  this is a necessary correctness fix, not scope creep.
- **Bug fix required to make the task's own prescribed test fixture work**:
  `_build_skills_from_tools()` checked `hasattr(self.agent, 'tool_manager')`
  without an `is not None` guard (unlike the equivalent, already-correct
  guard in `_find_tool()`). Both this task's own test spec pattern and
  TASK-1719's prescribed `mock_agent` fixture set `agent.tool_manager = None`
  explicitly — with the old code, `get_agent_card()` (called by
  `_handle_agent_card`) crashed with `AttributeError: 'NoneType' object has
  no attribute 'list_tools'` for any such agent, because no prior test ever
  called `get_agent_card()` over HTTP. Added the same `is not None` guard
  used elsewhere in the file. Documented inline at the fix site.
- New test file `packages/ai-parrot-server/tests/unit/test_a2a_v1_server.py`
  (14 tests): well-known discovery (both URIs/versions + content-type),
  version negotiation (-32009 on unsupported version), v1.0 REST routes
  (`message:send`, `tasks/{id}:cancel`, `tasks/{id}:subscribe`),
  `SendMessageConfiguration` (`returnImmediately`, `historyLength`), and
  `GetTask` 404/200. `ruff check` clean.
- Regression: full existing A2A suites (`test_a2a_tools.py`,
  `test_a2a_credential_gate.py`, `test_a2a_identity.py`,
  `test_a2a_resume_trigger.py`, `test_a2a_bridge_e2e.py` — 60 tests total)
  still pass; none of them exercise the HTTP layer (all call
  `process_message()` directly), so route/handler changes carried zero
  regression risk for them, confirmed empirically.
- `_handle_jsonrpc()` was deliberately left untouched (its own task,
  TASK-1715, explicitly owns the JSON-RPC method dispatch and error-code
  refactor) — it will keep emitting `to_dict()`'s new default v1.0 format
  until TASK-1715 wires version negotiation into it. No test currently
  exercises `_handle_jsonrpc` over HTTP (verified via grep), so this is a
  safe, explicitly-scoped deferral, not a regression.
**Deviations from spec**: the `_build_skills_from_tools()` None-guard fix and
the `_handle_list_tasks` status-filter fix are both outside the task's
literal "Scope" bullets but were required for (a) the task's own prescribed
test fixtures to run at all, and (b) not silently breaking status filtering
after the TASK-1712 enum rename. Both are minimal, guard-only changes with no
behavioral surface beyond fixing a crash / restoring existing filtering
semantics.
