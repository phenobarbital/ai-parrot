# TASK-035: CLI Overlay (HITL)

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-028, TASK-030, TASK-033
**Assigned-to**: claude-session

---

## Context

The CLI overlay allows a human operator to observe the FilesystemTransport system in real-time: see which agents are active, read the activity feed, and send messages to agents. It reads directly from the filesystem — no running process or daemon required.

Implements **Module 9** from the spec (Section 9 of the proposal).

---

## Scope

- Implement `CrewCLI` class with `get_state()` and `render_text()` methods
- Implement CLI commands via `click`:
  - Default: snapshot of current state (agents + feed)
  - `--watch`: live mode, refresh every second
  - `--send AGENT MESSAGE`: send a message to an agent
  - `--feed N`: show last N events from the activity feed
- Optional `rich` integration for formatted output (graceful fallback to plain text)
- Register as `python -m parrot.transport.filesystem.cli`
- Write basic tests for state rendering

**NOT in scope**: Interactive TUI with input prompt, Tab completion, scroll (deferred to future iteration)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/cli.py` | CREATE | CLI overlay implementation |
| `parrot/transport/filesystem/__main__.py` | CREATE | `python -m` entry point |
| `tests/transport/filesystem/test_cli.py` | CREATE | Unit tests for state rendering |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 9.3 for the reference implementation. Key points:

- `CrewCLI(root_dir)`: creates Registry + Feed readers from the filesystem
- `get_state()`: reads agents + feed into a dict
- `render_text(state)`: formats as human-readable text with status icons
- `main()`: click command with options for watch, send, feed

### Key Constraints
- `click` for CLI argument parsing
- `rich` is optional — detect at import, fallback to plain text
- `--send` creates a temporary `FilesystemTransport` with name `human-cli`
- Watch mode uses `click.clear()` + `asyncio.sleep(1.0)` loop
- `__main__.py` just calls `main()`

### References in Codebase
- Proposal Section 9 — full CLI spec and layout
- Proposal Section 9.3 — reference implementation

---

## Acceptance Criteria

- [ ] `python -m parrot.transport.filesystem.cli --root .parrot` shows state snapshot
- [ ] `--watch` mode refreshes every second
- [ ] `--send AgentName "message"` delivers message and confirms
- [ ] `--feed 20` shows last 20 events
- [ ] Works without `rich` installed (plain text fallback)
- [ ] Tests pass: `pytest tests/transport/filesystem/test_cli.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_cli.py
import pytest
from parrot.transport.filesystem.cli import CrewCLI


class TestCrewCLI:
    @pytest.mark.asyncio
    async def test_get_state_empty(self, tmp_path):
        cli = CrewCLI(tmp_path)
        state = await cli.get_state()
        assert state["agents"] == []
        assert state["feed"] == []

    def test_render_text_empty(self, tmp_path):
        cli = CrewCLI(tmp_path)
        text = cli.render_text({"agents": [], "feed": []})
        assert "0 agentes" in text

    def test_render_text_with_agents(self, tmp_path):
        cli = CrewCLI(tmp_path)
        state = {
            "agents": [{"name": "AgentA", "status": "active", "model": "test"}],
            "feed": [],
        }
        text = cli.render_text(state)
        assert "AgentA" in text
        assert "1 agentes" in text
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-028, TASK-030, TASK-033 are completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-035-cli-overlay.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented CrewCLI with get_state() and render_text()/render_rich(). Click-based CLI with --root, --watch, --send, --feed options. Optional rich integration with plain text fallback. __main__.py entry point for `python -m parrot.transport.filesystem`. 6 tests pass covering empty state, agent rendering, feed rendering, live agent state, and multiple agents.

**Deviations from spec**: none
