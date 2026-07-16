---
type: Wiki Overview
title: 'TASK-1425: `EvalRunner` + `EvalReport` (`parrot/eval/runner.py`)'
id: doc:sdd-tasks-completed-task-1425-eval-runner-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The orchestrator that ties all five axes together. Implements spec §3 Module
  9: `EvalRunConfig`,'
relates_to:
- concept: mod:parrot.core.events.evb
  rel: mentions
- concept: mod:parrot.eval
  rel: mentions
- concept: mod:parrot.eval.evaluators.base
  rel: mentions
- concept: mod:parrot.eval.models
  rel: mentions
- concept: mod:parrot.eval.rollout
  rel: mentions
- concept: mod:parrot.eval.sandbox.base
  rel: mentions
---

# TASK-1425: `EvalRunner` + `EvalReport` (`parrot/eval/runner.py`)

**Feature**: FEAT-217 — Generic Agent Evaluation Harness
**Spec**: `sdd/specs/generic-evaluation-harness.spec.md`
**Spec section**: §3 Module 9 (brainstorm §6, §13.6)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1415, TASK-1417, TASK-1419, TASK-1421, TASK-1423
**Assigned-to**: unassigned

---

## Context

The orchestrator that ties all five axes together. Implements spec §3 Module 9: `EvalRunConfig`,
`EvalRunner` (the 7-step per-attempt flow), and `EvalReport` aggregation (`pass^k` headline +
`pass@1`, per-tag breakdown, latency/cost percentiles, raw trajectories retained).

---

## Scope

- Create `parrot/eval/runner.py` with:
  - `EvalRunConfig` (Pydantic) per spec §2: `k`, `max_concurrency`, `sandbox_pool_size`, `fail_fast`,
    `seed`.
  - `EvalReport` (Pydantic): `run_id` (optional, set by sink), `dataset_name`, `config`, aggregate
    metrics, `results: list[EvalResult]`.
  - `EvalRunner.__init__(*, dataset, agent_factory, rollout, evaluator, sandbox_provider, config,
    event_bus=None, sink=None)` and `async run() -> EvalReport`.
- Per `(task, attempt)` flow under an `asyncio.Semaphore(max_concurrency)`:
  1. `sandbox = await provider.acquire(task.sandbox_spec or SandboxSpec(kind="noop"))`
  2. `await sandbox.reset(seed_state)`
  3. `t0 = perf_counter(); bot = await agent_factory(sandbox)` → `setup_latency_ms`
  4. `trajectory = await rollout.run(bot, task, sandbox)` → rollout `latency_ms`
  5. `trajectory.final_state = await sandbox.snapshot()`
  6. `result = await evaluator.evaluate(task, trajectory, sandbox)`
  7. `await provider.release(sandbox)`
  Wrap per-attempt errors → `trajectory.error` + a failed `EvalResult`; honor `fail_fast`.
- Aggregation: `pass@1` = mean(attempt-1 passed); `pass^k` = fraction of tasks where ALL k attempts
  passed; per-metric mean/median; per-`tag` breakdown; p50/p95 of `cost_usd`/`latency_ms`/`setup_latency_ms`.
- Emit eval events if `event_bus` is provided (events themselves are TASK-1426; here just call hooks
  defensively / leave a clear seam).
- Persist via `sink.persist(report)` if a sink is provided.
- Export from `parrot/eval/__init__.py`.

**NOT in scope**: concrete event classes (TASK-1426), `PostgresEvalSink` (TASK-1427), CI gate CLI.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/eval/runner.py` | CREATE | Runner + config + report |
| `packages/ai-parrot/src/parrot/eval/__init__.py` | MODIFY | Export runner names |
| `packages/ai-parrot/tests/eval/test_runner.py` | CREATE | Unit tests (fakes for all axes) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio
from time import perf_counter
import statistics
from pydantic import BaseModel, Field
from parrot.eval.models import EvalTask, EvalDataset, Trajectory, EvalResult   # TASK-1415
from parrot.eval.sandbox.base import Sandbox, SandboxProvider, SandboxSpec, AgentFactory  # TASK-1417
from parrot.eval.rollout import RolloutStrategy            # TASK-1423
from parrot.eval.evaluators.base import AbstractEvaluator  # TASK-1421
# Optional:
from parrot.core.events.evb import EventBus                # core/events/evb.py:72
```

### Existing Signatures to Use
```python
# core/events/evb.py
class EventBus:                       # line 72
    async def publish(self, event) -> int: ...   # line 185
    async def emit(self, event_type: str, payload: dict, **kwargs) -> int: ...  # line 291
```

### Does NOT Exist
- ~~`pass@k` (any-of-k) as the headline~~ — headline is `pass^k` (all-of-k). Compute both, label clearly.
- ~~A built-in eval runner in `parrot`~~ — this task creates it.

---

## Implementation Notes

### Key Constraints
- Bound concurrency with one `asyncio.Semaphore`; gather attempts; `InMemoryStateSandbox` is fresh
  per attempt (no pool needed — `sandbox_pool_size` only matters for pooled sandboxes, unused here).
- `seed` is best-effort (task selection/order + handed to the user simulator) — do NOT promise
  determinism of agent output (spec D6).
- Keep `EvalReport` JSON-serializable (Pydantic) so the sink can persist it directly.
- Retain raw `Trajectory` per attempt (spec acceptance criterion / D5).

---

## Acceptance Criteria

- [ ] `from parrot.eval import EvalRunner, EvalRunConfig, EvalReport` resolves.
- [ ] `run()` executes `k` attempts per task with a fresh sandbox+bot each, recording
      `setup_latency_ms` separately from rollout `latency_ms`.
- [ ] `pass^k` = fraction of tasks with ALL k attempts passed; `pass@1` reported separately.
- [ ] Per-attempt failures are isolated (recorded as failed results, `trajectory.error` set);
      `fail_fast=True` stops early.
- [ ] Raw trajectories retained in the report.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/eval/test_runner.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/eval/runner.py`

---

## Test Specification

```python
import pytest
from parrot.eval import EvalRunner, EvalRunConfig, EvalDataset, EvalTask
# Use fake rollout/evaluator/provider that pass deterministically, plus a flaky one for pass^k.

async def test_pass_k_all_must_pass():
    # task passes attempts [True, False] with k=2 -> pass^k excludes it, pass@1 includes it
    ...
```

---

## Agent Instructions

Standard SDD flow: verify the contract, set index `in-progress`, implement, run tests + ruff, move to
`completed/`, set index `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*
