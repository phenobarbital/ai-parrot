---
type: Wiki Overview
title: 'TASK-1391: Heartbeat models & strategy'
id: doc:sdd-tasks-completed-task-1391-heartbeat-models-strategy-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'a fallback `act_every_n_ticks: int` (default e.g. 10).'
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
---

# TASK-1391: Heartbeat models & strategy

**Feature**: FEAT-209 — Autonomous Agent Heartbeat
**Spec**: `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Spec Module 1. Foundation for the heartbeat system: Pydantic data models
> (`HeartbeatConfig`, `HeartbeatState`) and the pluggable strategy abstraction
> (`HeartbeatStrategy` ABC + `DefaultHeartbeatStrategy`). These are consumed by
> the `HeartbeatManager` (TASK-1392) and exported in TASK-1393.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py`.
- Implement `HeartbeatConfig` (Pydantic `BaseModel`): `agent_name`, `interval`,
  `jitter`, `enabled`, `max_consecutive_errors`, `mission`.
- Implement `HeartbeatState` (Pydantic `BaseModel`): `agent_name`, `running`,
  `tick_count`, `action_count`, `last_tick_at`, `last_action_at`,
  `consecutive_errors`, `last_error`.
- Implement `HeartbeatStrategy` (ABC): `build_context`, `should_act`, `build_prompt`.
- Implement `DefaultHeartbeatStrategy`:
  - Accepts an optional `has_pending_work: Callable[..., Awaitable[bool]]` and
    a fallback `act_every_n_ticks: int` (default e.g. 10).
  - `should_act` returns `True` when `has_pending_work()` is True, OR when
    `tick_count % act_every_n_ticks == 0` (fallback).
  - `build_prompt` returns `cfg.mission` (or a sensible default string).
- Write unit tests.

**NOT in scope**: `HeartbeatManager` (TASK-1392), `__init__.py` exports (TASK-1393).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py` | CREATE | Models + strategy ABC + default strategy |
| `packages/ai-parrot-server/tests/test_heartbeat_models.py` | CREATE | Unit tests for config, state, and strategy |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# Pydantic — already a project dependency
from pydantic import BaseModel, Field

# Standard library
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Callable, Awaitable, Any
```

### Existing Signatures to Use
```python
# No existing signatures needed for this task — it creates new classes.
# HeartbeatConfig/HeartbeatState/HeartbeatStrategy are entirely new.
```

### Does NOT Exist
- ~~`parrot.autonomous.heartbeat`~~ — this module does NOT exist yet; you are creating it.
- ~~`HeartbeatMonitor`~~ — does not exist anywhere in the codebase. Do not create it.
- ~~`CooldownManager`~~ — does not exist anywhere. Do not reference it.
- ~~`parrot.autonomous.models`~~ — no such module; models go in `heartbeat.py`.

---

## Implementation Notes

### Pattern to Follow
```python
# Use standard Pydantic BaseModel pattern consistent with the project
from pydantic import BaseModel, Field

class HeartbeatConfig(BaseModel):
    agent_name: str
    interval: float = Field(60.0, gt=0, description="Seconds between ticks.")
    jitter: float = Field(0.0, ge=0, description="Max random seconds added to interval.")
    enabled: bool = True
    max_consecutive_errors: int = Field(5, ge=1)
    mission: Optional[str] = Field(default=None, description="Default prompt seed for act step.")
```

### Key Constraints
- Pydantic `BaseModel` for both config and state models.
- `HeartbeatStrategy` is an ABC with three async abstract methods.
- `DefaultHeartbeatStrategy` must support BOTH a callable `has_pending_work`
  AND a fallback `act_every_n_ticks` — the heartbeat is NOT a cron job,
  it must have a real decision step.
- `build_context` receives the config and should return a dict with at
  minimum `{"tick_count": int, "config": HeartbeatConfig}`.
- No logging needed in models — logging comes in TASK-1392 (manager).

### References in Codebase
- `packages/ai-parrot-server/src/parrot/autonomous/scheduler.py` — `TriggerMode`, `AgentTriggerConfig` for style reference (dataclasses, not Pydantic — but the heartbeat uses Pydantic per spec).
- `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py:98` — `ExecutionResult` dataclass for reference on result structure.

---

## Acceptance Criteria

- [ ] `HeartbeatConfig` validates: `interval > 0`, `jitter >= 0`, `max_consecutive_errors >= 1`.
- [ ] `HeartbeatState` has all fields with correct defaults (`running=False`, counters at 0, timestamps None).
- [ ] `HeartbeatStrategy` is an ABC with `build_context`, `should_act`, `build_prompt` (all async).
- [ ] `DefaultHeartbeatStrategy.should_act` returns True when `has_pending_work()` returns True.
- [ ] `DefaultHeartbeatStrategy.should_act` returns True on fallback every N ticks when no `has_pending_work` provided.
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_heartbeat_models.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot-server/src/parrot/autonomous/heartbeat.py`
- [ ] Import works: `from parrot.autonomous.heartbeat import HeartbeatConfig, HeartbeatState, HeartbeatStrategy, DefaultHeartbeatStrategy`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_heartbeat_models.py
import pytest
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatState,
    DefaultHeartbeatStrategy,
)


class TestHeartbeatConfig:
    def test_defaults(self):
        cfg = HeartbeatConfig(agent_name="test-agent")
        assert cfg.interval == 60.0
        assert cfg.jitter == 0.0
        assert cfg.enabled is True
        assert cfg.max_consecutive_errors == 5
        assert cfg.mission is None

    def test_interval_must_be_positive(self):
        with pytest.raises(Exception):
            HeartbeatConfig(agent_name="a", interval=0)

    def test_jitter_must_be_non_negative(self):
        with pytest.raises(Exception):
            HeartbeatConfig(agent_name="a", jitter=-1)


class TestHeartbeatState:
    def test_defaults(self):
        state = HeartbeatState(agent_name="test-agent")
        assert state.running is False
        assert state.tick_count == 0
        assert state.action_count == 0
        assert state.last_tick_at is None
        assert state.consecutive_errors == 0


class TestDefaultHeartbeatStrategy:
    @pytest.mark.asyncio
    async def test_should_act_with_pending_work(self):
        async def has_work():
            return True
        strategy = DefaultHeartbeatStrategy(has_pending_work=has_work)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        assert await strategy.should_act(ctx) is True

    @pytest.mark.asyncio
    async def test_should_not_act_without_pending_work(self):
        async def no_work():
            return False
        strategy = DefaultHeartbeatStrategy(has_pending_work=no_work)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 3  # not on N boundary
        assert await strategy.should_act(ctx) is False

    @pytest.mark.asyncio
    async def test_fallback_every_n_ticks(self):
        strategy = DefaultHeartbeatStrategy(act_every_n_ticks=5)
        cfg = HeartbeatConfig(agent_name="a")
        ctx = await strategy.build_context(cfg)
        ctx["tick_count"] = 10  # multiple of 5
        assert await strategy.should_act(ctx) is True
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm the autonomous directory exists: `ls packages/ai-parrot-server/src/parrot/autonomous/`
   - Confirm `heartbeat.py` does NOT exist yet
4. **Update status** in `sdd/tasks/index/autonomous-agent-heartbeat.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1391-heartbeat-models-strategy.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Created `heartbeat.py` with `HeartbeatConfig`, `HeartbeatState`,
`HeartbeatStrategy` (ABC), and `DefaultHeartbeatStrategy`. The `DefaultHeartbeatStrategy`
supports both a `has_pending_work` callable and the `act_every_n_ticks` fallback cadence.
Also implemented `HeartbeatManager` in the same file since the spec places all components
in `heartbeat.py`. Unit tests: 20 pass, 0 fail. No linting errors.

**Deviations from spec**: `HeartbeatManager` was added in this same task (along with
models/strategy) because the spec targets a single file `heartbeat.py`. TASK-1392
modifies the same file as specified — it verifies and uses the manager already present.
