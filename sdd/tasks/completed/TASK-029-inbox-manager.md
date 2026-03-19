# TASK-029: InboxManager

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

The InboxManager handles point-to-point message delivery between agents. It uses write-then-rename for atomic delivery, ensures exactly-once processing by moving messages to `.processed/` before yielding, and supports both inotify (via watchdog) and polling fallback.

Implements **Module 3** from the spec (Section 7.3 of the proposal).

---

## Scope

- Implement `InboxManager` with: `setup()`, `deliver()`, `poll()`
- Write-then-rename atomic delivery (write to `.tmp-`, rename to final)
- Exactly-once delivery: move to `.processed/` before yielding
- TTL-based message expiration (filter expired messages silently)
- Messages polled in chronological order (by mtime)
- Optional inotify/watchdog integration with silent fallback to polling
- Write comprehensive unit tests

**NOT in scope**: Transport orchestration, registry, channels, feed

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/inbox.py` | CREATE | `InboxManager` implementation |
| `tests/transport/filesystem/test_inbox.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 7.3 for the complete reference implementation. Key points:

- `deliver()`: write msg to `inbox/<to_agent>/.tmp-msg-<uuid>.json`, then rename to `msg-<uuid>.json`
- `poll()`: AsyncGenerator that yields messages, sorted by `st_mtime`
- Before yield: move file to `.processed/` (or unlink if `keep_processed=False`)
- `_start_watcher()`: try to import watchdog, create Observer + Handler, fallback silently

### Key Constraints
- `aiofiles` for all async I/O
- UUID-based message IDs: `msg-{uuid.uuid4().hex}`
- Message JSON format must match spec Section 5.2
- Watchdog handler must use `loop.call_soon_threadsafe()` to bridge thread→async
- Poll loop: if inotify available, `wait_for(event.wait(), timeout=...)`, else `asyncio.sleep(poll_interval)`

### References in Codebase
- Proposal Section 7.3 — full `InboxManager` implementation
- Proposal Section 5.2 — inbox message JSON format

---

## Acceptance Criteria

- [ ] `deliver()` creates atomic message file via write-then-rename
- [ ] `poll()` yields messages in chronological order
- [ ] Messages moved to `.processed/` before yield (exactly-once)
- [ ] Expired messages (past `expires_at`) are silently filtered
- [ ] Large messages read completely (no partial reads)
- [ ] Watchdog integration works when available, silent fallback otherwise
- [ ] Tests pass: `pytest tests/transport/filesystem/test_inbox.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_inbox.py
import pytest
from pathlib import Path
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.inbox import InboxManager


@pytest.fixture
def fs_config(tmp_path):
    return FilesystemTransportConfig(
        root_dir=tmp_path, poll_interval=0.05, use_inotify=False, message_ttl=60.0
    )


@pytest.fixture
def inbox(tmp_path, fs_config):
    mgr = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
    mgr.setup()
    return mgr


class TestInboxManager:
    @pytest.mark.asyncio
    async def test_delivery_is_atomic(self, inbox):
        """Large message reads complete, no partial reads."""
        big_content = "x" * 100_000
        await inbox.deliver("agent-a", "AgentA", "agent-b", big_content, "msg", {}, None)
        msgs = []
        async for msg in inbox.poll():
            msgs.append(msg)
            break
        assert len(msgs) == 1
        assert msgs[0]["content"] == big_content

    @pytest.mark.asyncio
    async def test_exactly_once(self, inbox):
        """Message not processed twice."""
        await inbox.deliver("a", "A", "agent-b", "hello", "msg", {}, None)
        first = []
        async for msg in inbox.poll():
            first.append(msg)
            break
        assert len(first) == 1
        # Second poll should find nothing
        import asyncio
        second = []
        async def check():
            async for msg in inbox.poll():
                second.append(msg)
                break
        try:
            await asyncio.wait_for(check(), timeout=0.2)
        except asyncio.TimeoutError:
            pass
        assert len(second) == 0

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, tmp_path, fs_config):
        """Expired messages are filtered out."""
        fs_config.message_ttl = 0.001  # Expire almost immediately
        inbox = InboxManager(tmp_path / "inbox", "agent-b", fs_config)
        inbox.setup()
        await inbox.deliver("a", "A", "agent-b", "expired", "msg", {}, None)
        import asyncio
        await asyncio.sleep(0.1)  # Let it expire
        msgs = []
        async def check():
            async for msg in inbox.poll():
                msgs.append(msg)
                break
        try:
            await asyncio.wait_for(check(), timeout=0.3)
        except asyncio.TimeoutError:
            pass
        assert len(msgs) == 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-026 is completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-029-inbox-manager.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented InboxManager with all required features: atomic write-then-rename delivery, exactly-once processing via .processed/ directory, TTL-based expiration, chronological polling, and optional watchdog/inotify integration with silent fallback. 8 unit tests pass covering atomic delivery, exactly-once semantics, TTL expiration, poll ordering, message format, keep_processed toggle, directory creation, and recipient dir auto-creation.

**Deviations from spec**: none
