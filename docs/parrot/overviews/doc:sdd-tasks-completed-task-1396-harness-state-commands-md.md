---
type: Wiki Overview
title: 'TASK-1396: Harness-state commands (/health, /status)'
id: doc:sdd-tasks-completed-task-1396-harness-state-commands-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from aiogram.types import Message # verified: wrapper.py:22'
relates_to:
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
---

# TASK-1396: Harness-state commands (/health, /status)

**Feature**: FEAT-210 — Telegram Operator Commands
**Spec**: `sdd/specs/FEAT-210-telegram-operator-commands.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1394, TASK-1395
**Assigned-to**: unassigned

---

## Context

> Spec Module 3. Implements `/health` and `/status` — the two commands that
> project harness infrastructure state (heartbeat ticks from FEAT-209,
> active sub-agents from FEAT-208). Both consume external features that may
> not be merged yet, so degradation is mandatory. This task extends the
> `OperatorCommandsMixin` created in TASK-1395.

---

## Scope

- Add `handle_health(self, message)` to `OperatorCommandsMixin`:
  - Projects heartbeat liveness: last tick time, tick count, agent health states.
  - Consumes `HeartbeatManager.get_all_states()` (FEAT-209).
  - Degrades to "heartbeat not configured" if HeartbeatManager is absent.
- Add `handle_status(self, message)` to `OperatorCommandsMixin`:
  - Composite view: heartbeat state + active ephemeral sub-agents.
  - Consumes HeartbeatManager (FEAT-209) for heartbeat section.
  - Consumes ephemeral sub-agent status (FEAT-208) for sub-agent section.
  - Each section degrades independently if its source is absent.
- Add formatting helpers: `_format_heartbeat_health()`, `_format_status()`.
- All imports of FEAT-208/209 components are guarded with try/except ImportError.
- Write unit tests with fakes for HeartbeatManager and sub-agent APIs.

**NOT in scope**: `/context`, `/memory`, `/model`, `/mission` (TASK-1395), `/thread` (TASK-1397), wiring (TASK-1398).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/telegram/operator_commands.py` | MODIFY | Add handle_health, handle_status, format helpers to OperatorCommandsMixin |
| `packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_harness.py` | CREATE | Unit tests for /health and /status with fakes |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from aiogram.types import Message                          # verified: wrapper.py:22
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/telegram/wrapper.py:60
class TelegramAgentWrapper:
    self.app            # line 94 — aiohttp web.Application; heartbeat/bot_manager may be stored here
    self.config         # line 89 — TelegramAgentConfig
    self.router         # line 95 — aiogram Router

    def _is_operator(self, chat_id: int) -> bool:          # TASK-1394
    async def _send_safe_message(self, message, text, parse_mode=None):  # line 2579

# operator_commands.py (created by TASK-1395)
class OperatorCommandsMixin:
    # Extend this class with handle_health, handle_status
    ...
```

### FEAT-209 Interface (guarded import — may not exist at implementation time)
```python
# parrot/autonomous/heartbeat.py (FEAT-209 — NOT yet merged)
# Import MUST be guarded: try: ... except ImportError: HeartbeatManager = None
class HeartbeatManager:
    def get_all_states(self) -> list["HeartbeatState"]: ...

class HeartbeatState:
    agent_name: str
    tick_count: int
    last_tick: datetime
    # ... other fields TBD by FEAT-209
```

### FEAT-208 Interface (guarded import — may not exist at implementation time)
```python
# Ephemeral sub-agent status (FEAT-208 — NOT yet merged)
# Access pattern TBD; likely via self.app or a manager on the agent
# Import MUST be guarded
```

### Does NOT Exist
- ~~`HeartbeatManager`~~ — FEAT-209, not yet merged; MUST guard imports
- ~~`self.heartbeat`~~ — no such attribute on TelegramAgentWrapper; access via `self.app.get('heartbeat_manager')` or similar
- ~~`self.bot_manager`~~ — no such attribute; sub-agent manager access pattern TBD by FEAT-208
- ~~`self.agent.health`~~ — health state is NOT on the agent; it's on HeartbeatManager
- ~~`self.status`~~ — no status attribute on the wrapper

---

## Implementation Notes

### Pattern to Follow
```python
# Guarded import pattern for FEAT-209
try:
    from parrot.autonomous.heartbeat import HeartbeatManager, HeartbeatState
except ImportError:
    HeartbeatManager = None
    HeartbeatState = None

class OperatorCommandsMixin:
    async def handle_health(self, message: Message) -> None:
        chat_id = message.chat.id
        if not self._is_operator(chat_id):
            await message.answer("⛔ Operator-only command.")
            return
        hb = self.app.get('heartbeat_manager') if hasattr(self, 'app') and self.app else None
        if hb is None or HeartbeatManager is None:
            await self._send_safe_message(message, "ℹ️ Heartbeat not configured.")
            return
        states = hb.get_all_states()
        text = self._format_heartbeat_health(states)
        await self._send_safe_message(message, text)
```

### Key Constraints
- ALL imports of FEAT-208/FEAT-209 modules MUST be guarded (try/except ImportError)
- Degradation messages must be user-friendly ("not configured" / "not available"), not tracebacks
- `/status` has two independent sections — each degrades separately
- Use `self.app.get(...)` for runtime discovery of managers (not attributes on self)
- Tests use fakes/mocks — never import actual FEAT-208/209 code

### References in Codebase
- `wrapper.py:94` — `self.app` (where managers may be stored)
- `wrapper.py:2579` — `_send_safe_message()`
- FEAT-209 spec `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md` for HeartbeatManager interface

---

## Acceptance Criteria

- [ ] `handle_health` projects heartbeat state when HeartbeatManager available
- [ ] `handle_health` degrades with "heartbeat not configured" when absent
- [ ] `handle_status` shows composite view (heartbeat + sub-agents)
- [ ] `handle_status` degrades each section independently
- [ ] Non-operator chat_ids rejected by both handlers
- [ ] All FEAT-208/209 imports are guarded (try/except ImportError)
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_harness.py -v`

---

## Test Specification

```python
# packages/ai-parrot-integrations/tests/integrations/telegram/test_operator_commands_harness.py
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestHandleHealth:
    async def test_degrades_without_heartbeat(self, op_wrapper):
        """No HeartbeatManager → 'not configured' message."""
        ...

    async def test_projects_heartbeat_state(self, op_wrapper):
        """HeartbeatManager present → shows tick count, last tick, agent states."""
        ...

    async def test_non_operator_blocked(self, op_wrapper):
        """Non-operator gets rejection."""
        ...


class TestHandleStatus:
    async def test_degrades_both_absent(self, op_wrapper):
        """No heartbeat, no sub-agents → both sections show 'not configured'."""
        ...

    async def test_heartbeat_only(self, op_wrapper):
        """HeartbeatManager present, sub-agents absent → heartbeat shown, sub-agents degrade."""
        ...

    async def test_full_status(self, op_wrapper):
        """Both present → composite view with heartbeat and sub-agent info."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-210-telegram-operator-commands.spec.md` for full context
2. **Check dependencies** — verify TASK-1394 and TASK-1395 are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `operator_commands.py` exists with `OperatorCommandsMixin` (from TASK-1395)
   - Confirm `_is_operator` exists on the wrapper (from TASK-1394)
   - Check if FEAT-209 `HeartbeatManager` is available (`grep -r HeartbeatManager parrot/`)
   - Check if FEAT-208 sub-agent APIs are available
4. **Update status** in `sdd/tasks/index/telegram-operator-commands.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1396-harness-state-commands.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
