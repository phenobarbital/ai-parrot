---
type: Wiki Overview
title: 'TASK-1392: HeartbeatManager loop & lifecycle'
id: doc:sdd-tasks-completed-task-1392-heartbeat-manager-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: record action in state.
relates_to:
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
---

# TASK-1392: HeartbeatManager loop & lifecycle

**Feature**: FEAT-209 — Autonomous Agent Heartbeat
**Spec**: `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1391
**Assigned-to**: unassigned

---

## Context

> Spec Module 2. The core heartbeat engine: `HeartbeatManager` manages a
> per-agent asyncio loop that implements the wake → assess → maybe act cycle.
> Uses `AutonomousOrchestrator.execute_agent` to act, and the strategy from
> TASK-1391 for the assess step. This is the largest task in the feature.

---

## Scope

- Add `HeartbeatManager` class to `packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py` (file created by TASK-1391).
- `__init__(self, orchestrator, *, strategy=None)`: stores orchestrator ref, default strategy, agents dict, states dict, tasks dict.
- `register(self, cfg: HeartbeatConfig) -> None`: registers an agent config, creates initial `HeartbeatState(running=False)`.
- `async start(self) -> None`: for each registered+enabled agent, spawns an `asyncio.Task` running `_heartbeat_loop`.
- `async stop(self) -> None`: cancels all tasks cleanly (handles `CancelledError`), sets `running=False`.
- `_heartbeat_loop(self, cfg: HeartbeatConfig) -> None` (private async):
  - `while self._running`: sleep `interval ± jitter`, then:
  - Per-agent `asyncio.Lock`: if `lock.locked()`, skip (don't overlap ticks).
  - Under lock: `ctx = strategy.build_context(cfg)`, enrich with `tick_count` from state.
  - If `strategy.should_act(ctx)`: `prompt = strategy.build_prompt(ctx)`,
    `result = await orchestrator.execute_agent(cfg.agent_name, prompt)`,
    record action in state.
  - On success: reset `consecutive_errors`, update `last_action_at`, increment `action_count`.
  - On exception (not `CancelledError`): increment `consecutive_errors`, record `last_error`.
  - If `consecutive_errors >= max_consecutive_errors`: pause the agent (stop its loop task or skip ticks).
  - Always: increment `tick_count`, update `last_tick_at`.
  - `except CancelledError: raise` (clean cancellation pattern from `_presence_loop`).
- `get_state(self, agent_name: str) -> Optional[HeartbeatState]`
- `get_all_states(self) -> list[HeartbeatState]`
- Write comprehensive unit tests.

**NOT in scope**: `DefaultHeartbeatStrategy` (TASK-1391), `__init__.py` exports (TASK-1393).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py` | MODIFY | Add HeartbeatManager class |
| `packages/ai-parrot-server/tests/test_heartbeat_manager.py` | CREATE | Unit tests for manager lifecycle, loop, skip-when-busy, backoff |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# From TASK-1391 (heartbeat.py — created in prior task)
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatState,
    HeartbeatStrategy,
    DefaultHeartbeatStrategy,
)

# Orchestrator — the act step calls this
from parrot.autonomous.orchestrator import (      # verified: orchestrator.py
    AutonomousOrchestrator,                        # line 112
    ExecutionResult,                               # line 99
    ExecutionTarget,                               # line 40 (Enum: AGENT/CREW/FLOW)
)

# Standard library
import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:                         # line 112
    async def execute_agent(
        self, agent_name: str, task: str, *,          # line 358
        method_name=None, user_id=None,
        session_id=None, **kwargs
    ) -> ExecutionResult: ...

@dataclass
class ExecutionResult:                                 # line 99
    request_id: str
    target_type: ExecutionTarget
    target_id: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict = field(default_factory=dict)
    completed_at: datetime = field(default_factory=datetime.now)

# Reference pattern — packages/ai-parrot-server/src/parrot/autonomous/transport/filesystem/transport.py:296
async def _presence_loop(self) -> None:
    while True:
        try:
            await asyncio.sleep(self._config.presence_interval)  # :300
            await self._registry.heartbeat(self._agent_id)       # :301
            await self._registry.gc_stale()                      # :302
        except asyncio.CancelledError:
            raise                                                # :303-304
        except Exception as exc:
            logger.warning("Presence loop error: %s", exc)       # :305-306
```

### Does NOT Exist
- ~~`AutonomousOrchestrator.heartbeat()`~~ — no such method. The heartbeat is your new manager.
- ~~`AutonomousOrchestrator.schedule_heartbeat()`~~ — does not exist.
- ~~`execute_agent(..., prompt=...)`~~ — the parameter is `task: str` (positional), NOT `prompt`.
- ~~`HeartbeatMonitor`~~ — does not exist. The class is `HeartbeatManager`.
- ~~`asyncio.Lock.acquire(blocking=False)`~~ — use `lock.locked()` to check without acquiring.

---

## Implementation Notes

### Pattern to Follow
```python
# Mirror _presence_loop (transport.py:296) for the main loop structure:
async def _heartbeat_loop(self, cfg: HeartbeatConfig) -> None:
    state = self._states[cfg.agent_name]
    lock = self._locks[cfg.agent_name]
    state.running = True
    while self._running:
        try:
            sleep_time = cfg.interval
            if cfg.jitter > 0:
                sleep_time += random.uniform(0, cfg.jitter)
            await asyncio.sleep(sleep_time)

            if lock.locked():
                continue  # skip if previous tick still running

            async with lock:
                ctx = await self._strategy.build_context(cfg)
                ctx["tick_count"] = state.tick_count
                if await self._strategy.should_act(ctx):
                    prompt = await self._strategy.build_prompt(ctx)
                    result = await self._orchestrator.execute_agent(
                        cfg.agent_name, prompt  # 'task' positional, not 'prompt='
                    )
                    # record action...
            # update tick...
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.warning("Heartbeat tick error for %s: %s", cfg.agent_name, exc)
            # backoff...
    state.running = False
```

### Key Constraints
- `execute_agent` takes `task` as a positional parameter, NOT `prompt`.
- Per-agent `asyncio.Lock` — check `lock.locked()` before attempting to acquire (skip-if-busy pattern).
- `CancelledError` must be re-raised, never swallowed — this is how `stop()` works.
- Backoff: after `max_consecutive_errors`, set `state.running = False` and cancel the agent's task (or skip all future ticks).
- Use `self.logger = logging.getLogger(__name__)`.
- State is in-memory only — acceptable per spec.
- Jitter: `random.uniform(0, cfg.jitter)` added to interval.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/autonomous/transport/filesystem/transport.py:296` — `_presence_loop` (reference pattern for loop structure).
- `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:358` — `execute_agent` signature.
- `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:99` — `ExecutionResult` for result inspection.

---

## Acceptance Criteria

- [ ] `HeartbeatManager` registers agents and creates initial `HeartbeatState(running=False)`.
- [ ] `start()` spawns one `asyncio.Task` per enabled agent.
- [ ] `stop()` cancels all tasks cleanly (no uncaught `CancelledError`).
- [ ] Loop ticks at `interval ± jitter` and calls `execute_agent` when `should_act` is True.
- [ ] Skip-if-busy: overlapping ticks for the same agent are skipped (per-agent lock).
- [ ] Backoff: `consecutive_errors` increments on failure; agent pauses after `max_consecutive_errors`.
- [ ] `get_state` / `get_all_states` return correct tick/action counts and timestamps.
- [ ] Errors in the tick do NOT kill the loop (caught, logged, backoff applied).
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_heartbeat_manager.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_heartbeat_manager.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatManager,
    HeartbeatState,
    DefaultHeartbeatStrategy,
)


@pytest.fixture
def fake_orchestrator():
    """Orchestrator mock that records execute_agent calls."""
    orch = MagicMock()
    orch.execute_agent = AsyncMock(return_value=MagicMock(
        success=True, result="ok"
    ))
    return orch


@pytest.fixture
def always_act_strategy():
    """Strategy where should_act always returns True."""
    strategy = MagicMock()
    strategy.build_context = AsyncMock(return_value={"tick_count": 0})
    strategy.should_act = AsyncMock(return_value=True)
    strategy.build_prompt = AsyncMock(return_value="do something")
    return strategy


class TestHeartbeatManager:
    def test_register_creates_state(self, fake_orchestrator):
        mgr = HeartbeatManager(fake_orchestrator)
        cfg = HeartbeatConfig(agent_name="agent-1")
        mgr.register(cfg)
        state = mgr.get_state("agent-1")
        assert state is not None
        assert state.running is False
        assert state.tick_count == 0

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self, fake_orchestrator, always_act_strategy):
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="a", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.2)
        await mgr.stop()
        state = mgr.get_state("a")
        assert state.tick_count > 0
        assert state.action_count > 0

    @pytest.mark.asyncio
    async def test_loop_skips_when_busy(self, fake_orchestrator):
        """If a tick is still running, the next tick skips (no overlap)."""
        slow_strategy = MagicMock()
        slow_strategy.build_context = AsyncMock(return_value={"tick_count": 0})
        slow_strategy.should_act = AsyncMock(return_value=True)
        slow_strategy.build_prompt = AsyncMock(return_value="slow task")

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(0.3)
            return MagicMock(success=True)
        fake_orchestrator.execute_agent = slow_execute

        mgr = HeartbeatManager(fake_orchestrator, strategy=slow_strategy)
        mgr.register(HeartbeatConfig(agent_name="slow", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.5)
        await mgr.stop()
        # With 0.05s interval and 0.3s execution, many ticks should be skipped
        state = mgr.get_state("slow")
        assert state.action_count <= 2  # most ticks skipped

    @pytest.mark.asyncio
    async def test_backoff_on_consecutive_errors(self, fake_orchestrator, always_act_strategy):
        fake_orchestrator.execute_agent = AsyncMock(side_effect=RuntimeError("boom"))
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(
            agent_name="err", interval=0.05, max_consecutive_errors=3
        ))
        await mgr.start()
        await asyncio.sleep(0.5)
        await mgr.stop()
        state = mgr.get_state("err")
        assert state.consecutive_errors >= 3
        assert state.last_error is not None

    @pytest.mark.asyncio
    async def test_stop_cancels_cleanly(self, fake_orchestrator, always_act_strategy):
        mgr = HeartbeatManager(fake_orchestrator, strategy=always_act_strategy)
        mgr.register(HeartbeatConfig(agent_name="x", interval=0.05))
        await mgr.start()
        await asyncio.sleep(0.1)
        await mgr.stop()  # should not raise
        assert mgr.get_state("x").running is False

    def test_get_all_states(self, fake_orchestrator):
        mgr = HeartbeatManager(fake_orchestrator)
        mgr.register(HeartbeatConfig(agent_name="a"))
        mgr.register(HeartbeatConfig(agent_name="b"))
        states = mgr.get_all_states()
        assert len(states) == 2
        names = {s.agent_name for s in states}
        assert names == {"a", "b"}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md` for full context
2. **Check dependencies** — verify TASK-1391 is completed (models & strategy exist in `heartbeat.py`)
3. **Verify the Codebase Contract** — before writing ANY code:
   - `grep -n "class AutonomousOrchestrator" packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`
   - `grep -n "async def execute_agent" packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py`
   - Confirm `HeartbeatConfig`, `HeartbeatState`, `HeartbeatStrategy` exist in `heartbeat.py` (from TASK-1391)
4. **Update status** in `sdd/tasks/index/autonomous-agent-heartbeat.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1392-heartbeat-manager.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: `HeartbeatManager` was fully implemented in TASK-1391 (same `heartbeat.py` file).
This task added the comprehensive manager unit test suite (`test_heartbeat_manager.py`):
17 tests covering registration, lifecycle (start/stop), loop ticking, skip-if-busy,
backoff on errors, jitter, disabled agents, and clean cancellation. All 17 tests pass.

**Deviations from spec**: `heartbeat.py` was not modified (the manager was already
complete from TASK-1391). Only the test file was created as specified.
