# TASK-030: ActivityFeed

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

The ActivityFeed is a global append-only JSONL log of all system events (joins, leaves, messages, broadcasts, reservations). It provides observability for debugging and the CLI overlay. The feed auto-rotates when it exceeds `feed_retention` lines.

Implements **Module 4** from the spec (Section 7.4 of the proposal).

---

## Scope

- Implement `ActivityFeed` with: `emit()`, `tail()`, `_maybe_rotate()`
- Append-only JSONL format (one JSON object per line)
- Async-safe writes via `asyncio.Lock`
- Auto-rotation: when lines exceed `feed_retention`, keep only the most recent N
- Rotation uses write-then-rename for atomicity
- Write unit tests

**NOT in scope**: Transport orchestration, what events are emitted (that's the transport's job)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/feed.py` | CREATE | `ActivityFeed` implementation |
| `tests/transport/filesystem/test_feed.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 7.4 for the complete reference implementation. Key points:

- `emit()`: build JSON entry with `ts` (UTC ISO) + `event` type + data, append to file
- `tail(n)`: read file, return last N parsed JSON lines
- `_maybe_rotate()`: if lines > feed_retention, keep last N, write to tmp, rename

### Key Constraints
- `aiofiles` for all async I/O
- `asyncio.Lock` protects concurrent writes
- JSONL format: one `json.dumps()` line per event, terminated with `\n`
- Rotation: write to `.tmp` suffix, then rename (atomic)
- Handle missing file gracefully in `tail()` (return empty list)

### References in Codebase
- Proposal Section 7.4 — full `ActivityFeed` implementation
- Proposal Section 5.3 — feed JSONL format

---

## Acceptance Criteria

- [ ] `emit()` appends JSONL event with timestamp
- [ ] `tail(n)` returns last N events as dicts
- [ ] `tail()` on non-existent file returns empty list
- [ ] Feed rotates when exceeding `feed_retention` lines
- [ ] After rotation, most recent events are preserved
- [ ] Concurrent `emit()` calls are serialized via lock
- [ ] Tests pass: `pytest tests/transport/filesystem/test_feed.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_feed.py
import pytest
from pathlib import Path
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.feed import ActivityFeed


@pytest.fixture
def feed(tmp_path):
    config = FilesystemTransportConfig(root_dir=tmp_path, feed_retention=10)
    return ActivityFeed(tmp_path / "feed.jsonl", config)


class TestActivityFeed:
    @pytest.mark.asyncio
    async def test_emit_and_tail(self, feed):
        await feed.emit("test", {"key": "value"})
        entries = await feed.tail(5)
        assert len(entries) == 1
        assert entries[0]["event"] == "test"
        assert entries[0]["key"] == "value"
        assert "ts" in entries[0]

    @pytest.mark.asyncio
    async def test_tail_empty(self, tmp_path):
        config = FilesystemTransportConfig(root_dir=tmp_path)
        feed = ActivityFeed(tmp_path / "nonexistent.jsonl", config)
        entries = await feed.tail(10)
        assert entries == []

    @pytest.mark.asyncio
    async def test_rotation(self, feed):
        for i in range(15):
            await feed.emit("test", {"i": i})
        entries = await feed.tail(20)
        assert len(entries) <= 10
        assert entries[-1]["i"] == 14  # Most recent preserved
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-026 is completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-030-activity-feed.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented ActivityFeed with emit(), tail(), and _maybe_rotate(). Append-only JSONL format with asyncio.Lock for concurrent safety. Auto-rotation via write-then-rename when exceeding feed_retention lines. 8 unit tests pass covering emit/tail, empty tail, rotation, tail-n, multiple events, rotation preserving recent, concurrent emits, and parent directory creation.

**Deviations from spec**: none
