---
type: Wiki Overview
title: 'TASK-1393: Heartbeat export & integration tests'
id: doc:sdd-tasks-completed-task-1393-heartbeat-export-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: add `HeartbeatManager`, `HeartbeatConfig`, `HeartbeatState`,
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.heartbeat
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
- concept: mod:parrot.autonomous.redis_jobs
  rel: mentions
- concept: mod:parrot.autonomous.scheduler
  rel: mentions
- concept: mod:parrot.autonomous.webhooks
  rel: mentions
---

# TASK-1393: Heartbeat export & integration tests

**Feature**: FEAT-209 — Autonomous Agent Heartbeat
**Spec**: `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1392
**Assigned-to**: unassigned

---

## Context

> Spec Module 3. Wires the heartbeat into the public API surface by updating
> `__init__.py` exports, and adds an integration test that drives
> `HeartbeatManager` with a real (but fake-backed) `AutonomousOrchestrator`
> instance. Also documents optional app wiring for `on_startup`/`on_shutdown`.

---

## Scope

- Update `packages/ai-parrot/src/parrot/autonomous/__init__.py`:
  add `HeartbeatManager`, `HeartbeatConfig`, `HeartbeatState`,
  `HeartbeatStrategy`, `DefaultHeartbeatStrategy` to `_AUTONOMOUS_CLASSES` dict.
- Write an integration test: `HeartbeatManager` + real strategy +
  fake orchestrator → verify a tick calls `execute_agent` and records the action.
- Add a short docstring/comment in `heartbeat.py` documenting optional app
  wiring (`on_startup`/`on_shutdown`) — deferred to feature #6.

**NOT in scope**: Actual app wiring in `app.py` (deferred to feature #6),
Telegram/health endpoint (feature #6), ledger persistence (feature #4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/autonomous/__init__.py` | MODIFY | Add heartbeat classes to lazy-import dict |
| `packages/ai-parrot-server/tests/test_heartbeat_integration.py` | CREATE | Integration test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.

### Verified Imports
```python
# From heartbeat.py (created by TASK-1391 + TASK-1392)
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatState,
    HeartbeatStrategy,
    DefaultHeartbeatStrategy,
    HeartbeatManager,
)

# Orchestrator for integration test
from parrot.autonomous.orchestrator import (
    AutonomousOrchestrator,   # line 112
    ExecutionResult,           # line 99
    ExecutionTarget,           # line 40
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/autonomous/__init__.py
# The lazy-loader dict — ADD entries here, do NOT restructure.
_AUTONOMOUS_CLASSES: dict[str, str] = {
    "AutonomousOrchestrator": "parrot.autonomous.orchestrator",
    "ExecutionTarget": "parrot.autonomous.orchestrator",
    "ExecutionRequest": "parrot.autonomous.orchestrator",
    "ExecutionResult": "parrot.autonomous.orchestrator",
    "TriggerMode": "parrot.autonomous.scheduler",
    "AgentTriggerConfig": "parrot.autonomous.scheduler",
    "AutonomousJob": "parrot.autonomous.scheduler",
    "RedisJobInjector": "parrot.autonomous.redis_jobs",
    "WebhookEndpoint": "parrot.autonomous.webhooks",
    "WebhookListener": "parrot.autonomous.webhooks",
}
# ^ Add 5 new entries mapping to "parrot.autonomous.heartbeat"
```

### Does NOT Exist
- ~~`parrot.autonomous.__init__.py` in ai-parrot-server~~ — does NOT exist. The lazy loader is in the `ai-parrot` (core) package at `packages/ai-parrot/src/parrot/autonomous/__init__.py`.
- ~~`app.py` wiring for heartbeat~~ — does NOT exist yet; just document the pattern, don't implement.
- ~~`HeartbeatManager.wire_app()`~~ — no such method; wiring is manual in `on_startup`.

---

## Implementation Notes

### Pattern to Follow
```python
# In packages/ai-parrot/src/parrot/autonomous/__init__.py
# Add these entries to _AUTONOMOUS_CLASSES:
_AUTONOMOUS_CLASSES: dict[str, str] = {
    # ... existing entries ...
    "HeartbeatConfig": "parrot.autonomous.heartbeat",
    "HeartbeatState": "parrot.autonomous.heartbeat",
    "HeartbeatStrategy": "parrot.autonomous.heartbeat",
    "DefaultHeartbeatStrategy": "parrot.autonomous.heartbeat",
    "HeartbeatManager": "parrot.autonomous.heartbeat",
}
```

### Key Constraints
- Only add to `_AUTONOMOUS_CLASSES` — do NOT restructure the lazy-loader mechanism.
- The integration test should use short intervals (0.05s) to run fast.
- The integration test should NOT require a running Redis, database, or external service.
- Use a mock/fake orchestrator in the integration test — but construct `HeartbeatManager` and `DefaultHeartbeatStrategy` as real instances (not mocks).

### References in Codebase
- `packages/ai-parrot/src/parrot/autonomous/__init__.py` — lazy-loader pattern to extend.
- `packages/ai-parrot-server/tests/` — existing test structure for file placement.

---

## Acceptance Criteria

- [ ] `from parrot.autonomous import HeartbeatManager, HeartbeatConfig, HeartbeatState, HeartbeatStrategy, DefaultHeartbeatStrategy` works.
- [ ] Integration test: `HeartbeatManager` with `DefaultHeartbeatStrategy` + fake orchestrator → tick calls `execute_agent`, state reflects action.
- [ ] No breaking changes: existing imports from `parrot.autonomous` still work.
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_heartbeat_integration.py -v`
- [ ] All heartbeat tests pass together: `pytest packages/ai-parrot-server/tests/ -k heartbeat -v`
- [ ] No linting errors.

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_heartbeat_integration.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from parrot.autonomous.heartbeat import (
    HeartbeatConfig,
    HeartbeatManager,
    DefaultHeartbeatStrategy,
)


@pytest.fixture
def fake_orchestrator():
    """Minimal orchestrator fake for integration testing."""
    orch = MagicMock()
    orch.execute_agent = AsyncMock(return_value=MagicMock(
        success=True, result="done"
    ))
    return orch


class TestHeartbeatIntegration:
    @pytest.mark.asyncio
    async def test_heartbeat_drives_orchestrator(self, fake_orchestrator):
        """Real HeartbeatManager + real DefaultHeartbeatStrategy
        drives the orchestrator and records state correctly."""
        async def always_pending():
            return True

        strategy = DefaultHeartbeatStrategy(has_pending_work=always_pending)
        mgr = HeartbeatManager(fake_orchestrator, strategy=strategy)
        mgr.register(HeartbeatConfig(
            agent_name="integration-agent",
            interval=0.05,
            mission="check everything",
        ))

        await mgr.start()
        await asyncio.sleep(0.3)
        await mgr.stop()

        state = mgr.get_state("integration-agent")
        assert state.tick_count > 0
        assert state.action_count > 0
        assert state.last_action_at is not None
        assert state.running is False
        assert fake_orchestrator.execute_agent.called
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-209-autonomous-agent-heartbeat.spec.md` for full context
2. **Check dependencies** — verify TASK-1391 and TASK-1392 are completed
3. **Verify the Codebase Contract** — before writing ANY code:
   - `read packages/ai-parrot/src/parrot/autonomous/__init__.py`
   - Confirm `HeartbeatManager` etc. exist in `heartbeat.py` (from prior tasks)
4. **Update status** in `sdd/tasks/index/autonomous-agent-heartbeat.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1393-heartbeat-export-integration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Added 5 heartbeat entries to `_AUTONOMOUS_CLASSES` in
`packages/ai-parrot/src/parrot/autonomous/__init__.py` (lazy-loader dict, no structural
change). Created `test_heartbeat_integration.py` with 11 tests: 5 integration tests
(real HeartbeatManager + real DefaultHeartbeatStrategy + fake orchestrator) and 6 export
contract tests verifying `from parrot.autonomous import Heartbeat*`. All 48 heartbeat
tests pass. No linting errors. No breaking changes to existing autonomous exports.

**Deviations from spec**: none
