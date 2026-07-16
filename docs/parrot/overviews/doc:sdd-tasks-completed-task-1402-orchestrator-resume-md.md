---
type: Wiki Overview
title: 'TASK-1402: Orchestrator resume() — Crash Recovery'
id: doc:sdd-tasks-completed-task-1402-orchestrator-resume-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: reconstructed from the incomplete execution metadata.
relates_to:
- concept: mod:parrot.autonomous.ledger
  rel: mentions
- concept: mod:parrot.autonomous.orchestrator
  rel: mentions
---

# TASK-1402: Orchestrator resume() — Crash Recovery

**Feature**: FEAT-212 — Typed Event Ledger & Crash Resume
**Spec**: `sdd/specs/FEAT-212-event-ledger-resume.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1400
**Assigned-to**: unassigned

---

## Context

> Implements Module 4 of FEAT-212. Adds a `resume(ledger)` method to
> `AutonomousOrchestrator` that reads incomplete executions from the ledger
> and re-enqueues them via `inject_job()`. Called optionally during `start()`
> when configured (opt-in via `resume_on_start` parameter). This closes the
> crash recovery loop: events are captured → persisted → on restart, incomplete
> work is detected and re-queued.

---

## Scope

- Add `async def resume(self, ledger: EventLedger) -> int` to `AutonomousOrchestrator`.
  - Call `ledger.find_incomplete()` to get list of `IncompleteExecution`.
  - For each, call `self.inject_job(...)` with the appropriate parameters
    reconstructed from the incomplete execution metadata.
  - Return the count of re-enqueued jobs.
  - Log each re-enqueue at INFO level.
- Modify `AutonomousOrchestrator.start()` to accept an optional `ledger` parameter
  (or `resume_on_start` config flag) and call `resume(ledger)` when provided.
  The change must be **additive** — existing callers of `start()` without arguments
  must continue to work identically.
- Write unit tests with a mock ledger + mock `inject_job`.

**NOT in scope**: LedgerRecorder (TASK-1401), wiring (TASK-1403),
modifying `find_incomplete()` logic (TASK-1400).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py` | MODIFY | Add `resume()` method, modify `start()` to optionally call it |
| `packages/ai-parrot-server/tests/test_ledger_resume.py` | CREATE | Unit tests for resume logic |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From ledger module (TASK-1399/1400)
from parrot.autonomous.ledger import EventLedger, IncompleteExecution

# Already in orchestrator.py
import logging
from typing import Optional, List
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
class AutonomousOrchestrator:                     # line 112
    async def start(self): ...                    # line 202

    async def inject_job(
        self,
        target_type: Literal["agent", "crew"],
        target_id: str,
        task: str,
        *,
        priority: int = 5,
        schedule_at: Optional[datetime] = None,
        callback_url: Optional[str] = None,
        **kwargs,
    ) -> str: ...                                  # line 620 (returns job_id)

    self._execution_history: List[ExecutionResult] = []  # line 193 (in-memory only)

# ExecutionRequest dataclass (line 47-48):
@dataclass
class ExecutionRequest:
    request_id: str                               # line 54 (uuid4)
    target_type: ExecutionTarget                   # line 57
    target_id: str = ""                            # line 58
    task: str = ""                                 # line 61
    user_id: Optional[str] = None                  # line 72
    session_id: Optional[str] = None               # line 73
    metadata: Optional[Dict[str, Any]] = None      # line 74
    callback_url: Optional[str] = None             # line 77
    priority: int = 5                              # line 81

# IncompleteExecution (from TASK-1399 — Pydantic model):
# Expected fields: trace_id, agent_id, event_class, event_data, timestamp, last_seq
```

### Does NOT Exist
- ~~`AutonomousOrchestrator.resume()`~~ — does NOT exist yet; this task creates it.
- ~~`AutonomousOrchestrator.recover()`~~ — does not exist.
- ~~`_execution_history` as a persistent ledger~~ — in-memory only (List[ExecutionResult]).
- ~~`AutonomousOrchestrator.replay()`~~ — does not exist; resume RE-ENQUEUES, does not replay.

---

## Implementation Notes

### Pattern to Follow
```python
async def resume(self, ledger: EventLedger) -> int:
    """Re-enqueue incomplete executions found in the ledger.

    Returns the number of jobs re-enqueued.
    """
    incomplete = await ledger.find_incomplete()
    if not incomplete:
        self.logger.info("resume: no incomplete executions found")
        return 0

    count = 0
    for exec_info in incomplete:
        try:
            # Reconstruct job parameters from the incomplete execution
            target_type = exec_info.event_data.get("target_type", "agent")
            target_id = exec_info.agent_id or exec_info.event_data.get("target_id", "")
            task = exec_info.event_data.get("task", "")
            job_id = await self.inject_job(
                target_type=target_type,
                target_id=target_id,
                task=task or f"resume:{exec_info.trace_id}",
            )
            self.logger.info(
                "resume: re-enqueued trace_id=%s as job=%s",
                exec_info.trace_id, job_id,
            )
            count += 1
        except Exception:
            self.logger.exception(
                "resume: failed to re-enqueue trace_id=%s", exec_info.trace_id,
            )
    return count
```

### Key Constraints
- `resume()` is **additive** — it does NOT modify any existing method behavior.
- `start()` modification must be backward-compatible: `start()` without arguments
  must work exactly as before. Only call `resume()` if a ledger is provided AND
  resume is enabled (opt-in configurable per spec §8).
- Idempotency: re-enqueuing does not guarantee idempotent execution — that's the
  agent/tool's responsibility (stated in spec non-goals).
- `inject_job` signature uses `target_type: Literal["agent", "crew"]` — map from
  the incomplete execution's metadata.
- Log at INFO level for each re-enqueue, EXCEPTION for failures.

---

## Acceptance Criteria

- [ ] `AutonomousOrchestrator.resume(ledger)` calls `find_incomplete()` and
      `inject_job()` for each result, returning the count.
- [ ] `start()` optionally calls `resume()` when a ledger is provided and
      resume is enabled (opt-in).
- [ ] Existing callers of `start()` without arguments work identically (no regression).
- [ ] Resume handles empty `find_incomplete()` gracefully (returns 0).
- [ ] Resume handles `inject_job` failures gracefully (logs, continues with next).
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/test_ledger_resume.py -v`
- [ ] No linting errors on orchestrator.py

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_ledger_resume.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.autonomous.ledger import IncompleteExecution, InMemoryLedgerBackend, LedgerEvent
from datetime import datetime, timezone


@pytest.fixture
def fake_orchestrator():
    from parrot.autonomous.orchestrator import AutonomousOrchestrator
    orch = MagicMock(spec=AutonomousOrchestrator)
    orch.inject_job = AsyncMock(return_value="job-1")
    orch.logger = MagicMock()
    # Bind the real resume method
    from parrot.autonomous.orchestrator import AutonomousOrchestrator as RealOrch
    orch.resume = RealOrch.resume.__get__(orch, RealOrch)
    return orch


@pytest.fixture
def ledger_with_incomplete():
    ledger = InMemoryLedgerBackend()
    return ledger


class TestOrchestratorResume:
    @pytest.mark.asyncio
    async def test_resume_reenqueues_incomplete(self, fake_orchestrator, ledger_with_incomplete):
        """resume() calls inject_job for each incomplete execution."""
        ledger = ledger_with_incomplete
        now = datetime.now(timezone.utc)
        # Seed an open execution
        await ledger.append(LedgerEvent(
            event_id="e1", event_class="BeforeInvokeEvent",
            agent_id="bot-1", trace_id="open-t1", timestamp=now,
            event_data={"target_type": "agent", "target_id": "bot-1", "task": "do stuff"},
        ))
        count = await fake_orchestrator.resume(ledger)
        assert count == 1
        fake_orchestrator.inject_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_returns_zero_when_nothing_incomplete(self, fake_orchestrator):
        """resume() returns 0 when no incomplete executions."""
        ledger = InMemoryLedgerBackend()
        count = await fake_orchestrator.resume(ledger)
        assert count == 0
        fake_orchestrator.inject_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_continues_on_inject_failure(self, fake_orchestrator, ledger_with_incomplete):
        """If inject_job raises, resume logs and continues with next."""
        ledger = ledger_with_incomplete
        now = datetime.now(timezone.utc)
        await ledger.append(LedgerEvent(
            event_id="e1", event_class="BeforeInvokeEvent",
            agent_id="bot-1", trace_id="t1", timestamp=now,
            event_data={"target_type": "agent"},
        ))
        await ledger.append(LedgerEvent(
            event_id="e2", event_class="BeforeInvokeEvent",
            agent_id="bot-2", trace_id="t2", timestamp=now,
            event_data={"target_type": "agent"},
        ))
        fake_orchestrator.inject_job = AsyncMock(
            side_effect=[Exception("fail"), "job-2"]
        )
        count = await fake_orchestrator.resume(ledger)
        assert count == 1  # one succeeded
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/FEAT-212-event-ledger-resume.spec.md` for full context
2. **Check dependencies** — verify TASK-1400 is complete (`EventLedger` + `find_incomplete` exist)
3. **Verify the Codebase Contract** — confirm `inject_job` signature, `start()` location
4. **Read `orchestrator.py`** carefully before modifying — it's 1236 lines
5. **Update status** in `sdd/tasks/index/event-ledger-resume.json` → `"in-progress"`
6. **Implement** following the scope, codebase contract, and notes above
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-1402-orchestrator-resume.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-06-01
**Notes**: Added AutonomousOrchestrator.resume(ledger) method and modified start()
to accept optional ledger + resume_on_start=True opt-in flag. Added EventLedger to
TYPE_CHECKING imports. 10 tests pass, including backward compatibility tests for
start() without arguments. resume() handles inject_job failures gracefully.

**Deviations from spec**: None. All acceptance criteria met.
