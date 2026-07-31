---
type: Wiki Overview
title: 'TASK-1715: A2AServer — v1.0 JSON-RPC Methods & Error Codes'
id: doc:sdd-tasks-completed-task-1715-a2a-v1-jsonrpc-errors-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The A2A v1.0.0 spec defines 11 JSON-RPC methods with PascalCase names
relates_to:
- concept: mod:parrot.a2a.models
  rel: mentions
---

# TASK-1715: A2AServer — v1.0 JSON-RPC Methods & Error Codes

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1714
**Assigned-to**: unassigned

---

## Context

The A2A v1.0.0 spec defines 11 JSON-RPC methods with PascalCase names
(`SendMessage`, `GetTask`, `CancelTask`, etc.) and a specific error code table
(-32001 through -32009). The current implementation only handles 3 methods
(`message/send`, `tasks/get`, `tasks/list`) with ad-hoc error codes.

This task upgrades the JSON-RPC handler to support all v1.0 methods while
maintaining backward compatibility with v0.3 method names.

Implements spec §3 Module 3 (JSON-RPC/error part).

---

## Scope

- Refactor `_handle_jsonrpc()` to dispatch all 11 v1.0 methods:
  1. `SendMessage` (alias: `message/send`)
  2. `SendStreamingMessage` (new — returns SSE via JSON-RPC)
  3. `GetTask` (alias: `tasks/get`)
  4. `ListTasks` (alias: `tasks/list`)
  5. `CancelTask` (new JSON-RPC binding)
  6. `SubscribeToTask` (new — returns SSE via JSON-RPC)
  7. `CreateTaskPushNotificationConfig` (new)
  8. `GetTaskPushNotificationConfig` (new)
  9. `ListTaskPushNotificationConfigs` (new)
  10. `DeleteTaskPushNotificationConfig` (new)
  11. `GetExtendedAgentCard` (new)
- Implement the A2A error code table as constants and helper:
  - `-32001`: TaskNotFoundError (HTTP 404)
  - `-32002`: TaskNotCancelableError (HTTP 400)
  - `-32003`: PushNotificationNotSupportedError (HTTP 400)
  - `-32004`: UnsupportedOperationError (HTTP 400)
  - `-32005`: ContentTypeNotSupportedError (HTTP 400)
  - `-32006`: InvalidAgentResponseError (HTTP 500)
  - `-32007`: ExtendedAgentCardNotConfiguredError (HTTP 400)
  - `-32008`: ExtensionSupportRequiredError (HTTP 400)
  - `-32009`: VersionNotSupportedError (HTTP 400)
- Update existing error responses across all handlers to use the error table.
- Implement `GetExtendedAgentCard`: if `capabilities.extendedAgentCard` is true,
  return the full AgentCard with security details; otherwise return error -32007.
- Push notification methods (7-10) delegate to the `PushNotificationStore`
  from TASK-1716. If push notifications are not enabled, return error -32003.

**NOT in scope**:
- REST route changes (TASK-1714)
- Push notification store implementation (TASK-1716) — this task wires it

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | Refactor JSON-RPC handler, add error codes |
| `packages/ai-parrot/src/parrot/a2a/models.py` | MODIFY | Add A2A error code constants |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.a2a.models import (
    Task, TaskState, TaskStatus, Message, AgentCard,
    A2AError,  # created in TASK-1712
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/a2a/server.py

async def _handle_jsonrpc(self, request):                  # line 1228
    # Current implementation at lines 1229-1263:
    # Only handles: "message/send", "tasks/get", "tasks/list"
    # Returns JSON-RPC 2.0 envelope with result or error
    data = await request.json()
    method = data.get("method")
    params = data.get("params", {})
    req_id = data.get("id")

async def _handle_cancel_task(self, request):              # line 1184
    # Terminal states check at line 1195:
    terminal_states = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}
```

### Does NOT Exist

- ~~`A2AServer._jsonrpc_dispatch`~~ — no dispatch table exists; must be created
- ~~`A2AServer.A2A_ERROR_CODES`~~ — no error code constants exist
- ~~`A2AServer._handle_push_notification_create()`~~ — must be created
- ~~`A2AServer._handle_push_notification_get()`~~ — must be created
- ~~`A2AServer._handle_push_notification_list()`~~ — must be created
- ~~`A2AServer._handle_push_notification_delete()`~~ — must be created
- ~~`A2AServer._handle_get_extended_card()`~~ — must be created

---

## Implementation Notes

### Error Code Table Pattern

```python
# A2A Protocol v1.0 error codes
A2A_ERRORS = {
    "TaskNotFoundError":                    (-32001, 404),
    "TaskNotCancelableError":               (-32002, 400),
    "PushNotificationNotSupportedError":    (-32003, 400),
    "UnsupportedOperationError":            (-32004, 400),
    "ContentTypeNotSupportedError":         (-32005, 400),
    "InvalidAgentResponseError":            (-32006, 500),
    "ExtendedAgentCardNotConfiguredError":  (-32007, 400),
    "ExtensionSupportRequiredError":        (-32008, 400),
    "VersionNotSupportedError":             (-32009, 400),
}

def _a2a_error_response(self, error_name: str, message: str, req_id=None):
    code, http_status = A2A_ERRORS[error_name]
    return web.json_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message}
    }, status=http_status)
```

### JSON-RPC Dispatch Pattern

```python
_JSONRPC_METHODS = {
    # v1.0 PascalCase
    "SendMessage": "_rpc_send_message",
    "GetTask": "_rpc_get_task",
    "ListTasks": "_rpc_list_tasks",
    "CancelTask": "_rpc_cancel_task",
    # ...
    # v0.3 compat aliases
    "message/send": "_rpc_send_message",
    "tasks/get": "_rpc_get_task",
    "tasks/list": "_rpc_list_tasks",
}
```

### Key Constraints

- The JSON-RPC response format must be valid JSON-RPC 2.0:
  `{"jsonrpc": "2.0", "id": <id>, "result": <result>}` or
  `{"jsonrpc": "2.0", "id": <id>, "error": {"code": <int>, "message": <str>}}`.
- Standard JSON-RPC errors (-32700, -32600, -32601, -32602, -32603) must also
  be handled correctly.
- Push notification methods (7-10) will delegate to `self._push_store` — if
  `self._push_store is None`, return error -32003.

---

## Acceptance Criteria

- [ ] JSON-RPC handler dispatches all 11 v1.0 method names
- [ ] Old v0.3 method names (`message/send`, `tasks/get`, `tasks/list`) still work
- [ ] Unknown method returns `-32601` (MethodNotFound)
- [ ] Error responses use correct A2A error codes (-32001 to -32009)
- [ ] `TaskNotFoundError` returns code -32001
- [ ] `TaskNotCancelableError` returns code -32002
- [ ] `VersionNotSupportedError` returns code -32009
- [ ] `GetExtendedAgentCard` returns card when `extendedAgentCard=true`
- [ ] `GetExtendedAgentCard` returns error -32007 when not configured
- [ ] Push notification methods return -32003 when not supported
- [ ] All HTTP error responses updated to use A2A error code table
- [ ] No linting errors

---

## Test Specification

```python
class TestJsonRpcV1Methods:
    async def test_send_message_pascal_case(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1,
            "method": "SendMessage",
            "params": {"message": {"role": "user", "parts": [{"text": "hi"}]}}
        })
        data = await resp.json()
        assert "result" in data

    async def test_v03_method_compat(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1,
            "method": "message/send",
            "params": {"message": {"role": "user", "parts": [{"text": "hi"}]}}
        })
        data = await resp.json()
        assert "result" in data

    async def test_unknown_method(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1, "method": "DoesNotExist", "params": {}
        })
        data = await resp.json()
        assert data["error"]["code"] == -32601

    async def test_task_not_found_error_code(self, aiohttp_client, a2a_app):
        client = await aiohttp_client(a2a_app)
        resp = await client.post("/a2a/rpc", json={
            "jsonrpc": "2.0", "id": 1,
            "method": "GetTask", "params": {"id": "nonexistent"}
        })
        data = await resp.json()
        assert data["error"]["code"] == -32001
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for the full error code table and JSON-RPC method list
2. **Check dependencies** — TASK-1714 must be complete
3. **Read server.py** to see current state after TASK-1714 changes
4. **Implement** the dispatch table and error code system
5. **Run tests**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Opus 4.8) — 2026-07-10
**Notes**: Added `A2A_ERROR_CODES` table (-32001..-32009 + HTTP status) to
models.py. Refactored `_handle_jsonrpc` into a `_JSONRPC_METHODS` dispatch
covering all 11 v1.0 PascalCase methods plus v0.3 slash aliases; added
`_rpc_*` implementations (send/get/list/cancel/subscribe, push CRUD,
GetExtendedAgentCard) and `_A2ARpcError` → numeric-code mapping. Standard
JSON-RPC errors (-32700/-32600/-32601/-32603) handled. REST error responses
(get/cancel/subscribe/push) now use the A2A error table via `_a2a_http_error`.
`GetExtendedAgentCard` → -32007 when not configured; push methods → -32003
when unsupported. 38 unit tests pass (incl. e2e regression); ruff clean.
**Deviations from spec**: `SendStreamingMessage`/`SubscribeToTask` over JSON-RPC
return the (final/current) task rather than a live SSE stream — JSON-RPC over a
single POST cannot stream in this handler; SSE remains available on the REST
`:stream`/`:subscribe` routes. Push-config create validation errors map to
`UnsupportedOperationError` (-32004).
