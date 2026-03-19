# TASK-034: FilesystemHook Integration

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-033
**Assigned-to**: claude-session

---

## Context

The `FilesystemHook` integrates the FilesystemTransport with AI-Parrot's autonomous hooks system. It follows the `BaseHook` pattern exactly as `WhatsAppRedisHook` does: listens to the inbox, filters messages, dispatches to the target agent via the orchestrator's callback, and optionally sends responses back.

This task also adds `FILESYSTEM = "filesystem"` to the `HookType` enum and creates the `FilesystemHookConfig` model.

Implements **Module 8** from the spec (Section 8.1 of the proposal).

---

## Scope

- Add `FILESYSTEM = "filesystem"` to `HookType` enum in `parrot/autonomous/hooks/models.py`
- Create `FilesystemHookConfig` Pydantic model in `parrot/autonomous/hooks/models.py`
- Implement `FilesystemHook(BaseHook)` with: `start()`, `stop()`, `_listen_loop()`, `_dispatch()`
- Follow `WhatsAppRedisHook` pattern: config-driven init, listen loop, event dispatch via `on_event()`
- Support `command_prefix` and `allowed_agents` filtering
- Write unit tests

**NOT in scope**: CLI overlay, transport internals, YAML config loading (that's TASK-036)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/autonomous/hooks/models.py` | MODIFY | Add `FILESYSTEM` to `HookType`, add `FilesystemHookConfig` |
| `parrot/transport/filesystem/hook.py` | CREATE | `FilesystemHook` implementation |
| `tests/transport/filesystem/test_hook.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
Follow `WhatsAppRedisHook` exactly:

```python
class FilesystemHook(BaseHook):
    hook_type = HookType.FILESYSTEM

    def __init__(self, config: FilesystemHookConfig, **kwargs):
        super().__init__(
            name=config.name,
            enabled=config.enabled,
            target_type=config.target_type,
            target_id=config.target_id,
            metadata=config.metadata,
            **kwargs,
        )
        self._config = config
        self._transport = None
        self._listen_task = None

    async def start(self):
        self._transport = FilesystemTransport(
            agent_name=self._config.target_id or self._config.name,
            config=self._config.transport,
        )
        await self._transport.start()
        self._listen_task = asyncio.create_task(self._listen_loop())

    async def stop(self):
        # Cancel task, stop transport

    async def _listen_loop(self):
        async for msg in self._transport.messages():
            await self._dispatch(msg)

    async def _dispatch(self, msg):
        # Filter by prefix/allowed_agents
        # Build HookEvent via self._make_event()
        # await self.on_event(event)
```

### Key Constraints
- Must extend `BaseHook` (not create a new base)
- Use `self._make_event()` to build `HookEvent` (from BaseHook)
- Use `self.on_event()` to dispatch to orchestrator
- Handle `CancelledError` in listen loop
- `command_prefix` filtering: skip messages not starting with prefix, strip prefix before dispatch
- `allowed_agents` filtering: skip messages from agents not in the list

### References in Codebase
- `parrot/autonomous/hooks/whatsapp_redis.py` — `WhatsAppRedisHook` (primary reference)
- `parrot/autonomous/hooks/base.py` — `BaseHook` ABC
- `parrot/autonomous/hooks/models.py` — `HookType`, `HookEvent`, config models

---

## Acceptance Criteria

- [ ] `HookType.FILESYSTEM` exists in the enum
- [ ] `FilesystemHookConfig` validates correctly
- [ ] `FilesystemHook` extends `BaseHook`
- [ ] `start()` creates transport and begins listening
- [ ] `stop()` cancels listener and stops transport
- [ ] Messages dispatched as `HookEvent` via `on_event()`
- [ ] `command_prefix` filtering works
- [ ] `allowed_agents` filtering works
- [ ] Tests pass: `pytest tests/transport/filesystem/test_hook.py -v`
- [ ] No breaking changes to existing hooks

---

## Test Specification

```python
# tests/transport/filesystem/test_hook.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from parrot.autonomous.hooks.models import HookType, FilesystemHookConfig
from parrot.transport.filesystem.hook import FilesystemHook


class TestFilesystemHookConfig:
    def test_defaults(self):
        config = FilesystemHookConfig()
        assert config.name == "filesystem_hook"
        assert config.enabled is True
        assert config.command_prefix == ""
        assert config.allowed_agents is None


class TestFilesystemHook:
    @pytest.mark.asyncio
    async def test_hook_type(self):
        config = FilesystemHookConfig(target_id="TestAgent")
        hook = FilesystemHook(config=config)
        assert hook.hook_type == HookType.FILESYSTEM

    @pytest.mark.asyncio
    async def test_start_stop(self, tmp_path):
        config = FilesystemHookConfig(
            target_id="TestAgent",
            transport={"root_dir": str(tmp_path), "use_inotify": False},
        )
        hook = FilesystemHook(config=config)
        await hook.start()
        assert hook._transport is not None
        await hook.stop()

    @pytest.mark.asyncio
    async def test_dispatch_emits_event(self, tmp_path):
        config = FilesystemHookConfig(
            target_id="TestAgent",
            transport={"root_dir": str(tmp_path), "use_inotify": False},
        )
        hook = FilesystemHook(config=config)
        callback = AsyncMock()
        hook.set_callback(callback)

        await hook.start()
        # Send a message to the hook's transport inbox
        from parrot.transport.filesystem.transport import FilesystemTransport
        from parrot.transport.filesystem.config import FilesystemTransportConfig
        sender_cfg = FilesystemTransportConfig(root_dir=tmp_path, use_inotify=False)
        async with FilesystemTransport(agent_name="Sender", config=sender_cfg) as sender:
            await sender.send(config.target_id, "test message")

        await asyncio.sleep(0.3)  # Let the listen loop pick it up
        await hook.stop()

        assert callback.called
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Read `parrot/autonomous/hooks/whatsapp_redis.py`** as the primary pattern reference
3. **Check dependencies** — verify TASK-033 is completed
4. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-034-filesystem-hook.md`
8. **Update index** status to `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Added FILESYSTEM to HookType enum. Created FilesystemHookConfig model in models.py. Implemented FilesystemHook extending BaseHook following WhatsAppRedisHook pattern: config-driven init, start/stop lifecycle with transport creation, _listen_loop polling inbox, _dispatch with command_prefix and allowed_agents filtering, HookEvent emission via on_event(). 9 tests pass covering config defaults/custom, hook type, start/stop, event dispatch, prefix filtering, agent filtering, stop-without-start, and BaseHook inheritance. 82 total tests across the module all pass. No breaking changes to existing hooks.

**Deviations from spec**: FilesystemHookConfig.transport accepts a dict (serialized to FilesystemTransportConfig at start time) for easier YAML/JSON config loading.
