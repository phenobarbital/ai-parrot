# TASK-1716: Push Notification Config Store

**Feature**: FEAT-272 — A2A Protocol v1.0.0 Compatibility
**Spec**: `sdd/specs/a2a-protocol-compatibility.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1712
**Assigned-to**: unassigned

---

## Context

The A2A v1.0.0 spec defines four push notification configuration operations
(Create/Get/List/Delete) that allow clients to register webhook URLs for
receiving task updates. This requires a store for `TaskPushNotificationConfig`
objects, keyed by task ID and config ID.

This task creates the store and wires it into `A2AServer`. Actual webhook
delivery (HTTP POST to client URLs) is out of scope — only the CRUD and
config management.

Implements spec §3 Module 4.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/a2a/push_notifications.py`:
  - `PushNotificationStore` class with in-memory dict backend.
  - Methods: `create()`, `get()`, `list_for_task()`, `delete()`.
  - SSRF validation stub: `_validate_webhook_url(url)` that rejects
    private/loopback IP ranges.
- Wire the store into `A2AServer.__init__()`:
  - Accept `push_store: Optional[PushNotificationStore]` parameter.
  - If `capabilities.push_notifications` is true and no store provided,
    auto-create an in-memory store.
- Add REST routes in `A2AServer.setup()` for push notification CRUD:
  - `POST {base}/tasks/{task_id}/pushNotificationConfigs` → create
  - `GET {base}/tasks/{task_id}/pushNotificationConfigs/{config_id}` → get
  - `GET {base}/tasks/{task_id}/pushNotificationConfigs` → list
  - `DELETE {base}/tasks/{task_id}/pushNotificationConfigs/{config_id}` → delete
- Implement the four HTTP handler methods.

**NOT in scope**:
- Actual webhook delivery (HTTP POST to client URLs)
- Redis-backed persistent store (follow-up)
- SSRF validation beyond basic private IP rejection

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/a2a/push_notifications.py` | CREATE | PushNotificationStore |
| `packages/ai-parrot-server/src/parrot/a2a/server.py` | MODIFY | Wire store, add routes and handlers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# From TASK-1712:
from parrot.a2a.models import (
    TaskPushNotificationConfig,  # created in TASK-1712
    AuthenticationInfo,          # created in TASK-1712
)
from aiohttp import web
```

### Existing Signatures to Use

```python
# packages/ai-parrot-server/src/parrot/a2a/server.py

class A2AServer:                                           # line 50
    def __init__(self, agent, *, base_path="/a2a", ...):   # line 84
    def setup(self, app, url=None) -> None:                # line 171
    # self._tasks: Dict[str, Task] — in-memory task store  # line 137
    # self.capabilities: AgentCapabilities                  # line 132
```

### Does NOT Exist

- ~~`parrot.a2a.push_notifications`~~ — module must be created
- ~~`PushNotificationStore`~~ — class must be created
- ~~`A2AServer._push_store`~~ — attribute must be added

---

## Implementation Notes

### Store Pattern

```python
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import uuid
import ipaddress
from urllib.parse import urlparse

from parrot.a2a.models import TaskPushNotificationConfig, AuthenticationInfo


class PushNotificationStore:
    """In-memory store for push notification configurations."""

    def __init__(self):
        # task_id -> {config_id -> config}
        self._configs: Dict[str, Dict[str, TaskPushNotificationConfig]] = {}

    async def create(
        self, config: TaskPushNotificationConfig
    ) -> TaskPushNotificationConfig:
        self._validate_webhook_url(config.url)
        if not config.id:
            config.id = str(uuid.uuid4())
        task_configs = self._configs.setdefault(config.task_id, {})
        task_configs[config.id] = config
        return config

    async def get(
        self, task_id: str, config_id: str
    ) -> Optional[TaskPushNotificationConfig]:
        return self._configs.get(task_id, {}).get(config_id)

    async def list_for_task(
        self, task_id: str
    ) -> List[TaskPushNotificationConfig]:
        return list(self._configs.get(task_id, {}).values())

    async def delete(self, task_id: str, config_id: str) -> bool:
        task_configs = self._configs.get(task_id, {})
        return task_configs.pop(config_id, None) is not None

    def _validate_webhook_url(self, url: str) -> None:
        """Reject private/loopback IPs (basic SSRF protection)."""
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError(f"Invalid scheme: {parsed.scheme}")
        hostname = parsed.hostname
        if hostname:
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback:
                    raise ValueError(f"Private/loopback IP not allowed: {hostname}")
            except ValueError:
                pass  # hostname, not IP — allow
```

### Key Constraints

- The store is per-process in-memory. Task data is already in-memory
  (`self._tasks`), so this is consistent.
- Each push config has a unique `id` (UUID) and is scoped to a `task_id`.
- SSRF validation is basic — reject obviously private IPs. DNS rebinding
  and other advanced attacks are out of scope.

---

## Acceptance Criteria

- [ ] `PushNotificationStore` created with CRUD methods
- [ ] `create()` assigns UUID if config has no id
- [ ] `create()` rejects private/loopback URLs
- [ ] `get()` returns config or None
- [ ] `list_for_task()` returns all configs for a task
- [ ] `delete()` removes config and returns bool
- [ ] REST routes registered in `A2AServer.setup()`
- [ ] HTTP handlers return correct responses
- [ ] Push notification routes gated on `capabilities.push_notifications`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot-server/tests/unit/test_a2a_push_notifications.py
import pytest
from parrot.a2a.push_notifications import PushNotificationStore
from parrot.a2a.models import TaskPushNotificationConfig


@pytest.fixture
def store():
    return PushNotificationStore()


class TestPushNotificationStore:
    async def test_create_assigns_id(self, store):
        config = TaskPushNotificationConfig(
            id="", task_id="task-1", url="https://example.com/hook"
        )
        result = await store.create(config)
        assert result.id != ""

    async def test_get_returns_config(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://example.com/hook"
        )
        await store.create(config)
        found = await store.get("task-1", "cfg-1")
        assert found is not None
        assert found.url == "https://example.com/hook"

    async def test_list_for_task(self, store):
        for i in range(3):
            await store.create(TaskPushNotificationConfig(
                id=f"cfg-{i}", task_id="task-1", url=f"https://example.com/hook{i}"
            ))
        configs = await store.list_for_task("task-1")
        assert len(configs) == 3

    async def test_delete(self, store):
        await store.create(TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="https://example.com/hook"
        ))
        assert await store.delete("task-1", "cfg-1") is True
        assert await store.get("task-1", "cfg-1") is None

    async def test_reject_private_ip(self, store):
        config = TaskPushNotificationConfig(
            id="cfg-1", task_id="task-1", url="http://127.0.0.1/hook"
        )
        with pytest.raises(ValueError, match="Private/loopback"):
            await store.create(config)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for push notification requirements
2. **Check dependencies** — TASK-1712 must be complete (for model types)
3. **Create** `push_notifications.py` as a new module
4. **Wire** the store into `A2AServer`
5. **Run tests**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-09
**Notes**:
- Created `packages/ai-parrot-server/src/parrot/a2a/push_notifications.py`
  with `PushNotificationStore` (in-memory `Dict[task_id, Dict[config_id,
  TaskPushNotificationConfig]]`), async `create()`/`get()`/`list_for_task()`/
  `delete()`, and `_validate_webhook_url()`.
- **Bug fix vs. the task's own snippet**: the Implementation Notes' suggested
  `_validate_webhook_url()` raises `ValueError("Private/loopback IP not
  allowed")` INSIDE a `try` block whose own `except ValueError: pass`
  immediately swallows that same exception — so the literal snippet would
  never actually reject a private IP, contradicting the task's own
  `test_reject_private_ip` acceptance test. Rewrote the control flow so the
  `ipaddress.ip_address()` parse-failure path (a DNS hostname, not an IP
  literal — allowed) is isolated from the is_private/is_loopback check (which
  now raises unguarded). Verified against the task's own prescribed test:
  `test_reject_private_ip` passes.
- Wired `push_store: Optional[PushNotificationStore] = None` into
  `A2AServer.__init__()`: explicit `push_store` takes precedence; else, if
  `capabilities.push_notifications` is true, an in-memory store is
  auto-created; else `self._push_store = None`. This also makes the
  `getattr(self, "_push_store", None)` lookups added in TASK-1715's `_rpc_*`
  push methods start resolving to a real store (verified: TASK-1715's own
  `test_push_notification_not_supported` tests still correctly report -32003
  because their fixture's `AgentCapabilities()` defaults
  `push_notifications=False`).
- Added the four REST routes in `setup()`
  (`POST/GET/GET/DELETE .../tasks/{task_id}/pushNotificationConfigs[/{config_id}]`)
  and their handlers (`_handle_push_config_create` returns HTTP 201,
  `_handle_push_config_get`/`_list`/`_delete`), all gated on
  `self._push_store is None` → `_rest_error_response("PushNotificationNotSupportedError", ...)`
  (-32003 / HTTP 400).
- New test file `packages/ai-parrot-server/tests/unit/test_a2a_push_notifications.py`
  (16 tests): store CRUD (including the corrected SSRF rejection for
  loopback and RFC 1918 private ranges, and an explicit "public hostname is
  allowed" case), invalid-scheme rejection, `A2AServer` wiring (auto-create
  vs. disabled vs. explicit-store-precedence), and a full REST CRUD
  roundtrip test (create → get → list → delete → 404 after delete) plus the
  disabled-capability -32003 path.
- Regression: full TASK-1712 through 1716 test suite (83 tests across
  `test_a2a_v1_jsonrpc_errors.py`, `test_a2a_v1_server.py`,
  `test_a2a_push_notifications.py`, `test_a2a_credential_gate.py`,
  `test_a2a_identity.py`, `test_a2a_resume_trigger.py`,
  `test_a2a_bridge_e2e.py`) all pass. `ruff check` clean on all touched files.
**Deviations from spec**: the SSRF-check control-flow fix described above
(the task's own snippet had a self-swallowing exception bug that contradicted
its own acceptance test) — implemented the clearly-intended behavior instead
of the literal (broken) snippet.
