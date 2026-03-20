# TASK-028: AgentRegistry

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

The AgentRegistry is the presence system for FilesystemTransport. Each agent registers itself as a JSON file in `registry/<agent-id>.json`. Liveness is determined by PID checking (`os.kill(pid, 0)`), not TTL-based heartbeats, providing instant detection of crashed agents.

Implements **Module 2** from the spec (Section 7.2 of the proposal).

---

## Scope

- Implement `AgentRegistry` class with: `join()`, `leave()`, `heartbeat()`, `list_active()`, `resolve()`, `gc_stale()`
- Write-then-rename atomicity for all file writes
- PID-based liveness via `os.kill(pid, 0)`
- Resolution by `agent_id` or `name` (case-insensitive)
- `scope_to_cwd` filtering support
- Use `aiofiles` for async file I/O
- Write comprehensive unit tests

**NOT in scope**: Transport lifecycle, inbox, feed, channels

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/registry.py` | CREATE | `AgentRegistry` implementation |
| `tests/transport/filesystem/test_registry.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 7.2 for the complete reference implementation. Key points:

- `_write()`: write to `.tmp-{agent_id}.json`, then `tmp.rename(path)` (atomic POSIX)
- `_is_alive()`: `os.kill(pid, 0)` — `ProcessLookupError` = dead, `PermissionError` = alive (other user)
- `gc_stale()`: iterate all `*.json`, check `_is_alive()`, remove dead entries
- `resolve()`: iterate `list_active()`, match by `agent_id` exact or `name` case-insensitive

### Key Constraints
- All file writes must use write-then-rename pattern
- `aiofiles` for all async I/O
- Skip files starting with `.` (tmp files, locks)
- PID check handles `ProcessLookupError` and `PermissionError`
- Thread-safe for concurrent heartbeat/GC calls

### References in Codebase
- Proposal Section 7.2 — full `AgentRegistry` implementation
- Proposal Section 5.1 — registry JSON format

---

## Acceptance Criteria

- [ ] `join()` creates `registry/<agent-id>.json` with all required fields
- [ ] `leave()` removes the registry file
- [ ] `heartbeat()` updates `last_seen` and optional fields
- [ ] `list_active()` only returns agents with live PIDs
- [ ] `resolve()` finds by agent_id or name (case-insensitive)
- [ ] `gc_stale()` removes dead PID entries
- [ ] `scope_to_cwd` filtering works correctly
- [ ] Write-then-rename atomicity verified
- [ ] Tests pass: `pytest tests/transport/filesystem/test_registry.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_registry.py
import os
import pytest
from pathlib import Path
from parrot.transport.filesystem.config import FilesystemTransportConfig
from parrot.transport.filesystem.registry import AgentRegistry


@pytest.fixture
def registry(tmp_path):
    config = FilesystemTransportConfig(root_dir=tmp_path)
    return AgentRegistry(tmp_path / "registry", config)


class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_join_creates_file(self, registry, tmp_path):
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        assert (tmp_path / "registry" / "a1.json").exists()

    @pytest.mark.asyncio
    async def test_leave_removes_file(self, registry, tmp_path):
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        await registry.leave("a1")
        assert not (tmp_path / "registry" / "a1.json").exists()

    @pytest.mark.asyncio
    async def test_list_active_returns_live(self, registry):
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        agents = await registry.list_active()
        assert len(agents) == 1
        assert agents[0]["name"] == "AgentA"

    @pytest.mark.asyncio
    async def test_pid_detection_dead(self, registry):
        # Use a PID that definitely doesn't exist
        await registry.join("a1", "AgentA", 999999999, "host", "/cwd", "agent")
        agents = await registry.list_active()
        assert len(agents) == 0

    @pytest.mark.asyncio
    async def test_gc_stale(self, registry):
        await registry.join("a1", "AgentA", 999999999, "host", "/cwd", "agent")
        removed = await registry.gc_stale()
        assert "a1" in removed

    @pytest.mark.asyncio
    async def test_resolve_by_id(self, registry):
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        result = await registry.resolve("a1")
        assert result is not None
        assert result["agent_id"] == "a1"

    @pytest.mark.asyncio
    async def test_resolve_by_name_case_insensitive(self, registry):
        await registry.join("a1", "AgentA", os.getpid(), "host", "/cwd", "agent")
        result = await registry.resolve("agenta")
        assert result is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-026 is completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-028-agent-registry.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `AgentRegistry` with all 6 methods: `join()`, `leave()`, `heartbeat()`, `list_active()`, `resolve()`, `gc_stale()`. Uses write-then-rename atomicity via aiofiles. PID-based liveness detection handles `ProcessLookupError` and `PermissionError`. Supports `scope_to_cwd` filtering. 17 unit tests pass.

**Deviations from spec**: none
