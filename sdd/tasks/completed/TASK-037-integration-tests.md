# TASK-037: Integration Tests

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-033, TASK-034
**Assigned-to**: claude-session

---

## Context

This task creates comprehensive integration tests that verify the complete FilesystemTransport system works end-to-end: multi-agent conversations, broadcast channels, reservation conflicts, presence lifecycle, feed completeness, and hook dispatching.

Implements the Integration Tests from spec Section 4.

---

## Scope

- Write integration tests covering all major scenarios:
  - Two-agent bidirectional conversation
  - Three-agent broadcast via channels
  - Reservation conflict between two agents
  - Full presence lifecycle (join → heartbeat → stop)
  - Activity feed captures all event types
  - FilesystemHook dispatches to mock agent
- All tests use `tmp_path` (no real `.parrot/` directory)
- Tests use `use_inotify=False` for deterministic behavior
- Mark integration tests with `@pytest.mark.integration`

**NOT in scope**: Performance benchmarks, CLI tests (those are in TASK-035)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/transport/filesystem/test_integration.py` | CREATE | Integration test suite |
| `tests/transport/filesystem/conftest.py` | CREATE | Shared fixtures |

---

## Implementation Notes

### Shared Fixtures (conftest.py)
```python
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
```

### Key Constraints
- All tests must be `@pytest.mark.asyncio`
- Use `asyncio.wait_for()` with timeouts to prevent hanging tests
- Integration tests use `@pytest.mark.integration` marker
- Tests must clean up (fixtures with yield + stop)
- No mocking of filesystem — these are real integration tests

### References in Codebase
- Spec Section 4 — full test specification
- Proposal Section 13 — testing strategy and critical test cases

---

## Acceptance Criteria

- [ ] Two-agent bidirectional conversation test passes
- [ ] Three-agent broadcast test passes
- [ ] Reservation conflict test (all-or-nothing) passes
- [ ] Presence lifecycle test passes
- [ ] Feed captures all event types (join, message, broadcast, reserve, release, leave)
- [ ] Hook dispatch test passes
- [ ] All tests pass: `pytest tests/transport/filesystem/test_integration.py -v`
- [ ] No tests hang (all have timeouts)

---

## Test Specification

```python
# tests/transport/filesystem/test_integration.py
import asyncio
import pytest
from parrot.transport.filesystem.transport import FilesystemTransport
from parrot.transport.filesystem.feed import ActivityFeed

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestTwoAgentConversation:
    async def test_bidirectional_exchange(self, transport_a, transport_b):
        """A sends to B, B replies to A."""
        await transport_a.send("AgentB", "ping")
        async for msg in transport_b.messages():
            assert msg["content"] == "ping"
            await transport_b.send("AgentA", "pong", reply_to=msg["msg_id"])
            break
        async for msg in transport_a.messages():
            assert msg["content"] == "pong"
            break


class TestBroadcast:
    async def test_three_agents_channel(self, fs_config):
        agents = []
        for name in ["A", "B", "C"]:
            t = FilesystemTransport(agent_name=f"Agent{name}", config=fs_config)
            await t.start()
            agents.append(t)
        try:
            await agents[0].broadcast("Hello everyone!", channel="crew")
            for agent in agents:
                msgs = []
                async for msg in agent.channel_messages("crew"):
                    msgs.append(msg)
                assert len(msgs) >= 1
                assert msgs[0]["content"] == "Hello everyone!"
        finally:
            for t in agents:
                await t.stop()


class TestReservationConflict:
    async def test_all_or_nothing(self, transport_a, transport_b):
        ok1 = await transport_a.reserve(["file_a.csv", "file_b.csv"])
        assert ok1 is True
        ok2 = await transport_b.reserve(["file_b.csv", "file_c.csv"])
        assert ok2 is False


class TestPresenceLifecycle:
    async def test_join_heartbeat_leave(self, fs_config):
        t = FilesystemTransport(agent_name="LifecycleAgent", config=fs_config)
        await t.start()
        agents = await t.list_agents()
        assert any(a["name"] == "LifecycleAgent" for a in agents)
        await t.stop()
        # After stop, a new transport should not see the old agent
        t2 = FilesystemTransport(agent_name="Observer", config=fs_config)
        await t2.start()
        agents = await t2.list_agents()
        names = {a["name"] for a in agents}
        assert "LifecycleAgent" not in names
        await t2.stop()


class TestFeedCompleteness:
    async def test_all_events_captured(self, fs_config):
        t = FilesystemTransport(agent_name="FeedAgent", config=fs_config)
        await t.start()
        await t.broadcast("hi", channel="general")
        await t.reserve(["test.csv"], reason="testing")
        await t.release(["test.csv"])
        await t.stop()

        feed = ActivityFeed(fs_config.root_dir / "feed.jsonl", fs_config)
        events = await feed.tail(20)
        event_types = {e["event"] for e in events}
        assert "join" in event_types
        assert "broadcast" in event_types
        assert "reserve" in event_types
        assert "release" in event_types
        assert "leave" in event_types
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-033 and TASK-034 are completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-037-integration-tests.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Created conftest.py with shared fixtures (fs_config, transport_a, transport_b) and test_integration.py with 14 integration tests covering all acceptance criteria: bidirectional messaging, message ordering, 3-agent broadcast, multiple broadcasts, reservation conflict (all-or-nothing), release-reacquire, disjoint reservations, presence lifecycle, status updates, whois, feed completeness (all 6 event types), message_sent feed event, hook dispatch, and hook prefix filtering. All 110 tests across the full filesystem transport suite pass.

**Deviations from spec**: Used actual event names from code (`agent_joined`, `agent_left`, `message_sent`, `reservation_acquired`, `reservation_released`) instead of spec's simplified names (`join`, `leave`, `reserve`, `release`). Used `msg["id"]` instead of spec's `msg["msg_id"]` to match actual inbox message format. Added 8 extra tests beyond the spec's 6 scenarios for more thorough coverage.
