---
type: Wiki Overview
title: 'TASK-1426: Eval lifecycle events (`parrot/eval/events.py`)'
id: doc:sdd-tasks-completed-task-1426-eval-events-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Read-only observability events for eval runs, joining the FEAT-176 lifecycle
  taxonomy (already merged
relates_to:
- concept: mod:parrot.core.events.evb
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.base
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.registry
  rel: mentions
- concept: mod:parrot.core.events.lifecycle.trace
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
---

# TASK-1426: Eval lifecycle events (`parrot/eval/events.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 11 (brainstorm §7)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1425
**Assigned-to**: unassigned

---

## Context

Read-only observability events for eval runs, joining the FEAT-176 lifecycle taxonomy (already merged
on `dev`). Implements spec §3 Module 11. A new orchestration-layer event group — NOT bot-lifecycle
events, and NOT interceptors (observers cannot abort a run).

---

## Scope

- Create `parrot/eval/events.py` with `LifecycleEvent` subclasses: `EvalRunStarted`,
  `EvalRolloutStarted`, `EvalRolloutCompleted`, `EvalRolloutFailed`, `EvalRunCompleted`.
- Wire emission into `EvalRunner` (TASK-1425): emit via `EventRegistry.emit(event)` and/or dual-emit
  to `EventBus` when an `event_bus` is configured (per-subscriber opt-in; read-only).
- Propagate `TraceContext` into the trajectory's `trace_context` so one run is one distributed trace.
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: OTel span export (FEAT-177 covers it), any interceptor/abort capability.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/events.py` | CREATE | Eval `LifecycleEvent` subclasses |
| `packages/ai-parrot/src/parrot/eval/runner.py` | MODIFY | Emit events at the 7-step seams |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export event classes |
| `packages/ai-parrot/tests/eval/test_eval_events.py` | CREATE | Subscriber receives events |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.events.lifecycle.base import LifecycleEvent       # core/events/lifecycle/base.py:21
from parrot.core.events.lifecycle.registry import EventRegistry    # core/events/lifecycle/registry.py:90
from parrot.core.events.lifecycle.trace import TraceContext        # core/events/lifecycle/trace.py:15
from parrot.core.events.evb import EventBus                        # core/events/evb.py:72
```

### Existing Signatures to Use
```python
# core/events/lifecycle/base.py:21
class LifecycleEvent(ABC): ...        # subclass this for each eval event
# core/events/lifecycle/registry.py
class EventRegistry:                  # line 90
    def subscribe(self, ...): ...     # line 121
    async def emit(self, event: LifecycleEvent) -> None: ...  # line 235 (never raises; model-B isolation)
# core/events/lifecycle/trace.py:15
class TraceContext:
    @classmethod
    def new_root(cls) -> "TraceContext": ...   # line 45
    def child(self) -> "TraceContext": ...     # line 62
```
> Read `LifecycleEvent` (base.py) for required fields/abstract members before subclassing — match the
> existing event subclasses' shape (see `core/events/lifecycle/events/` and `meta.py`).

### Does NOT Exist
- ~~An eval-specific event scope already in the taxonomy~~ — this task adds it.
- ~~Interceptor/abort hooks for eval~~ — explicitly out of scope (read-only observability).

---

## Implementation Notes

### Key Constraints
- Model-B error isolation is provided by `EventRegistry.emit` (never raises) — do not add try/except
  that swallows real run errors; only the event dispatch is isolated.
- Dual-emit to `EventBus` is per-subscriber opt-in (FEAT-176 convention).
- `TraceContext.new_root()` per run; `.child()` per rollout; store as
  `trajectory.trace_context = {"traceparent": ...}`.

### References in Codebase
- `core/events/lifecycle/events/` + `meta.py:15` (`SubscriberErrorEvent`) — event subclass pattern.
- `sdd/specs/FEAT-176-lifecycle-events-system.md` — taxonomy + scopes.

---

## Acceptance Criteria

- [ ] `from parrot.eval import EvalRunStarted, EvalRunCompleted` (and the rollout events) resolves.
- [ ] Each event is a `LifecycleEvent` subclass.
- [ ] A subscriber registered on `EventRegistry` receives `EvalRunStarted` →
      `EvalRolloutCompleted`/`EvalRolloutFailed` → `EvalRunCompleted` during a run.
- [ ] A raising subscriber does NOT break the run (model-B isolation).
- [ ] `trajectory.trace_context` is populated (one run = one trace).
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_eval_events.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/events.py`

---

## Test Specification

```python
import pytest
# Subscribe a collector to EventRegistry, run EvalRunner over a 1-task fake dataset,
# assert the event sequence and that a raising subscriber doesn't abort the run.
```

---

## Agent Instructions

Standard SDD flow: read `LifecycleEvent` first, verify the contract, set index `in-progress`,
implement, run tests + ruff, move to `completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
