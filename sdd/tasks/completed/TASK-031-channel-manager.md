# TASK-031: ChannelManager

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

The ChannelManager provides broadcast communication via JSONL append-only files. Each channel is a separate `.jsonl` file. Agents publish messages and poll from an offset. No subscription state is maintained — offset tracking is the caller's responsibility.

Implements **Module 5** from the spec (Section 7.5 of the proposal).

---

## Scope

- Implement `ChannelManager` with: `publish()`, `poll()`, `list_channels()`
- Each channel is a JSONL file in `channels/<name>.jsonl`
- Publish appends JSON line (async-safe via `asyncio.Lock`)
- Poll reads from a given offset (line number, 0-based)
- List channels by scanning `*.jsonl` files
- Write unit tests

**NOT in scope**: Transport orchestration, subscription management, channel creation commands

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/channel.py` | CREATE | `ChannelManager` implementation |
| `tests/transport/filesystem/test_channel.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 7.5 for the complete reference implementation.

### Key Constraints
- `aiofiles` for all async I/O
- `asyncio.Lock` for publish serialization
- JSONL format with `ts`, `from_agent`, `from_name`, `content`, `payload`
- `poll()` is an AsyncGenerator
- Handle non-existent channel file gracefully (return/empty)
- Channel names are sanitized (no path traversal)

### References in Codebase
- Proposal Section 7.5 — full `ChannelManager` implementation

---

## Acceptance Criteria

- [ ] `publish()` appends message as JSONL line
- [ ] `poll()` yields messages from given offset
- [ ] `list_channels()` returns available channel names
- [ ] Polling non-existent channel returns nothing
- [ ] Concurrent publishes are serialized
- [ ] Tests pass: `pytest tests/transport/filesystem/test_channel.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_channel.py
import pytest
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.channel import ChannelManager


@pytest.fixture
def channels(tmp_path):
    config = FilesystemTransportConfig(root_dir=tmp_path)
    return ChannelManager(tmp_path / "channels", config)


class TestChannelManager:
    @pytest.mark.asyncio
    async def test_publish_and_poll(self, channels):
        await channels.publish("general", "a1", "AgentA", "Hello!", {})
        msgs = []
        async for msg in channels.poll("general", since_offset=0):
            msgs.append(msg)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "Hello!"

    @pytest.mark.asyncio
    async def test_poll_with_offset(self, channels):
        await channels.publish("general", "a1", "A", "msg1", {})
        await channels.publish("general", "a1", "A", "msg2", {})
        msgs = []
        async for msg in channels.poll("general", since_offset=1):
            msgs.append(msg)
        assert len(msgs) == 1
        assert msgs[0]["content"] == "msg2"

    @pytest.mark.asyncio
    async def test_list_channels(self, channels):
        await channels.publish("general", "a1", "A", "hi", {})
        await channels.publish("crew", "a1", "A", "hi", {})
        result = await channels.list_channels()
        assert set(result) == {"general", "crew"}

    @pytest.mark.asyncio
    async def test_poll_nonexistent_channel(self, channels):
        msgs = []
        async for msg in channels.poll("nonexistent"):
            msgs.append(msg)
        assert msgs == []
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-026 is completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-031-channel-manager.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented ChannelManager with publish(), poll(), and list_channels(). JSONL append-only format with asyncio.Lock for concurrent safety. Channel name sanitization via regex to prevent path traversal. Offset-based polling with caller-managed offsets. 9 unit tests pass covering publish/poll, offset, listing, non-existent channels, ordering, payloads, invalid names, and concurrent writes.

**Deviations from spec**: none
