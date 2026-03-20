# TASK-033: FilesystemTransport (Main Orchestrator)

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-026, TASK-027, TASK-028, TASK-029, TASK-030, TASK-031, TASK-032
**Assigned-to**: claude-session

---

## Context

The `FilesystemTransport` is the top-level orchestrator that composes all managers (Registry, Inbox, Feed, Channel, Reservation) into a unified API. It manages the agent lifecycle (start/stop), presence heartbeat loop, and exposes the public interface for sending, broadcasting, discovering agents, and managing reservations.

It should inherit from `AbstractTransport` (TASK-027).

Implements **Module 7** from the spec (Section 7.1 of the proposal).

---

## Scope

- Implement `FilesystemTransport` inheriting from `AbstractTransport`
- Compose all managers: `AgentRegistry`, `InboxManager`, `ActivityFeed`, `ChannelManager`, `ReservationManager`
- Lifecycle: `start()` registers presence + starts heartbeat task, `stop()` deregisters + cancels tasks
- Async context manager: `__aenter__` / `__aexit__`
- Public API: `send()`, `broadcast()`, `messages()`, `channel_messages()`, `list_agents()`, `whois()`, `reserve()`, `release()`, `set_status()`
- Background `_presence_loop()` for heartbeat and GC
- Write integration-level unit tests (two transports communicating)

**NOT in scope**: Hook integration (TASK-034), CLI (TASK-035)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/transport.py` | CREATE | `FilesystemTransport` implementation |
| `tests/transport/filesystem/test_transport.py` | CREATE | Unit + integration tests |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 7.1 for the complete reference implementation. Key points:

- Constructor: creates all managers from config + root_dir paths
- `start()`: `root_dir.mkdir()`, registry join, inbox setup, feed emit "join", start presence task
- `stop()`: cancel presence task, release reservations, registry leave, feed emit "leave"
- `send()`: resolve target via registry, deliver via inbox, emit feed event
- `broadcast()`: publish to channel, emit feed event
- `messages()`: delegate to `inbox.poll()`
- `_presence_loop()`: heartbeat + gc_stale every `presence_interval`

### Key Constraints
- Inherit from `AbstractTransport` (from `parrot.transport.base`)
- All methods are async
- `send()` raises `ValueError` if target agent not found in registry
- Agent ID generated as `{name.lower()}-{uuid4().hex[:8]}` if not provided
- Background task must handle `CancelledError` gracefully
- Presence loop: catch all exceptions to avoid killing the loop

### References in Codebase
- Proposal Section 7.1 — full `FilesystemTransport` implementation
- `parrot/transport/base.py` — `AbstractTransport` (TASK-027)

---

## Acceptance Criteria

- [ ] `FilesystemTransport` inherits from `AbstractTransport`
- [ ] `start()` registers agent and starts heartbeat
- [ ] `stop()` deregisters agent and cancels background tasks
- [ ] Async context manager works: `async with FilesystemTransport(...) as t:`
- [ ] `send()` delivers message to target agent's inbox
- [ ] `send()` raises `ValueError` for unknown agents
- [ ] `broadcast()` publishes to channel
- [ ] `messages()` yields incoming messages
- [ ] `list_agents()` returns active agents
- [ ] `reserve()` / `release()` delegate to ReservationManager
- [ ] `set_status()` updates registry entry
- [ ] Two transports can exchange messages (integration test)
- [ ] Tests pass: `pytest tests/transport/filesystem/test_transport.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_transport.py
import pytest
from pathlib import Path
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.transport import FilesystemTransport


@pytest.fixture
def fs_config(tmp_path):
    return FilesystemTransportConfig(
        root_dir=tmp_path,
        presence_interval=0.1,
        poll_interval=0.05,
        use_inotify=False,
        stale_threshold=1.0,
        message_ttl=60.0,
        feed_retention=100,
    )


@pytest.fixture
async def transport_a(fs_config):
    t = FilesystemTransport(agent_name="AgentA", config=fs_config)
    await t.start()
    yield t
    await t.stop()


@pytest.fixture
async def transport_b(fs_config):
    t = FilesystemTransport(agent_name="AgentB", config=fs_config)
    await t.start()
    yield t
    await t.stop()


class TestFilesystemTransport:
    @pytest.mark.asyncio
    async def test_start_stop(self, fs_config):
        t = FilesystemTransport(agent_name="TestAgent", config=fs_config)
        await t.start()
        agents = await t.list_agents()
        assert any(a["name"] == "TestAgent" for a in agents)
        await t.stop()

    @pytest.mark.asyncio
    async def test_send_and_receive(self, transport_a, transport_b):
        await transport_a.send("AgentB", "Hello from A")
        msgs = []
        async for msg in transport_b.messages():
            msgs.append(msg)
            break
        assert msgs[0]["content"] == "Hello from A"
        assert msgs[0]["from_name"] == "AgentA"

    @pytest.mark.asyncio
    async def test_discovery(self, transport_a, transport_b):
        agents = await transport_a.list_agents()
        names = {a["name"] for a in agents}
        assert "AgentA" in names
        assert "AgentB" in names

    @pytest.mark.asyncio
    async def test_broadcast(self, transport_a):
        await transport_a.broadcast("Hello channel!", channel="general")
        msgs = []
        async for msg in transport_a.channel_messages("general"):
            msgs.append(msg)
        assert len(msgs) >= 1
        assert msgs[-1]["content"] == "Hello channel!"

    @pytest.mark.asyncio
    async def test_send_unknown_agent_raises(self, transport_a):
        with pytest.raises(ValueError, match="not found"):
            await transport_a.send("NonExistent", "hello")

    @pytest.mark.asyncio
    async def test_set_status(self, transport_a):
        await transport_a.set_status("busy", "Processing data...")
        info = await transport_a.whois("AgentA")
        assert info["status"] == "busy"
        assert info["status_message"] == "Processing data..."

    @pytest.mark.asyncio
    async def test_context_manager(self, fs_config):
        async with FilesystemTransport(agent_name="CtxAgent", config=fs_config) as t:
            agents = await t.list_agents()
            assert any(a["name"] == "CtxAgent" for a in agents)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-026 through TASK-032 are completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-033-filesystem-transport.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented FilesystemTransport as the top-level orchestrator inheriting from AbstractTransport. Composes all managers (AgentRegistry, InboxManager, ActivityFeed, ChannelManager, ReservationManager). Full lifecycle with start/stop and async context manager. Background presence heartbeat loop with graceful CancelledError handling. Public API: send(), broadcast(), messages(), channel_messages(), list_agents(), whois(), reserve(), release(), set_status(). Activity feed events emitted for joins, leaves, messages, broadcasts, and reservations. Updated __init__.py exports. 15 transport-level tests + 73 total tests across the module all pass.

**Deviations from spec**: The registry stores status messages as "message" (not "status_message"). Tests adapted accordingly.
