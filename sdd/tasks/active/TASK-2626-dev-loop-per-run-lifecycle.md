# TASK-2626: Dev Loop Per-Run Checkpoint Lifecycle

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2625
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. `DevLoopRunner.run()` currently reuses one shared
`AgentsFlow` whose instance-owned `flow_id` is unrelated to each job's
`run_id`, so checkpoints have no per-job identity. This task makes
`build_dev_loop_flow` produce a NEW checkpoint-enabled explicit graph per run
(via `DevCheckpointCoordinator`), registers every Pydantic result type needed
for routing/restoration, and recovers the three priority nodes — bug intake,
research, development — without restoring live host/tool objects.

---

## Scope

- Refactor `build_dev_loop_flow` (`dev_loop/flow.py`) into a per-run factory:
  same explicit nodes/edges/predicates, plus checkpoint config (required mode,
  namespaced identity, retained declarative definition, allowlist projector).
  Retain the existing call shape for non-checkpoint callers.
- Wire `DevLoopRunner.run(brief, *, run_id=None, ...)`: when a caller supplies
  `run_id`, route through `DevCheckpointCoordinator.prepare()` for fresh vs.
  resumed execution; bind a fresh `SessionHost`/context either way; return the
  effective `run_id` to the caller (it is the recovery handle).
- Register dev-loop checkpoint types at import/composition time:
  `WorkBrief`, `FeatureBrief`, `ResearchOutput`, `PlannerOutput`,
  `DevelopmentOutput`, and any other node-result models routed between nodes
  (grep `models/__init__.py` exports and node `execute()` return types).
- Recovery behavior per spec §2/§5:
  - completed bug intake restores enriched brief + `bug_findings`, no
    re-reproduction or re-enrichment side effects;
  - completed research restores Jira key, excerpts, typed `ResearchOutput`,
    validated worktree — no research/Jira redispatch;
  - completed development restores `DevelopmentOutput` — no worker redispatch;
  - interrupted pool development rebuilds `TaskScheduler` from the on-disk
    per-spec index, dispatching only tasks not persisted `done`;
  - interrupted single-agent development reruns node-granular (documented, not
    claimed task-granular).
- Preserve gate parking, run bundles, and `resume_run()` (in-memory gate)
  behavior; recovered runs must be distinguishable in session timeline events.
- Unit tests for scheduler exclusion after restart and single-agent
  node-granularity.

**NOT in scope**: `dev_flow` (TASK-2627), example servers / CLI bootstrap
(TASK-2628).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/flow.py` | MODIFY | Per-run checkpoint-enabled factory |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | Coordinator integration in `run()`; fresh host binding; telemetry |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py` | MODIFY | Ensure all routed result models exported/registered |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | Only if registration needs model adjustments (no field semantics changes) |
| `packages/ai-parrot/tests/flows/dev_loop/test_recovery_lifecycle.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import (
    DevelopmentOutput, PlannerOutput, ResearchOutput, WorkBrief,
)
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py:21

from parrot.flows.dev_loop.task_scheduler import TaskScheduler
# verified: packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:43

# From TASK-2625: from parrot.flows.dev_loop.checkpoint import DevCheckpointCoordinator
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py:1028
class DevLoopRunner:
    async def run(self, brief: WorkBrief | FeatureBrief, *,
                  run_id: str | None = None, initial_task: str = "",
                  extra_shared: dict[str, Any] | None = None) -> FlowResult: ...

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:43
class TaskScheduler:  # constructor seeds _done from status "done" (line ~69)

# Node integration anchors (re-grep before editing — they drift):
#   nodes/bug_intake.py:85,119    — result + bug_findings/bug_brief projection
#   nodes/research.py:257,334,472,1228 — dispatch, Jira, worktree guard
#   nodes/development.py:142,190,533   — scheduler build / dispatch paths
#   flow.py (dev_loop) build_dev_loop_flow — explicit edges + predicates
```

### Does NOT Exist
- ~~`DevLoopRunner.resume_job()`~~ — `resume_run()` resumes an in-memory
  parked gate only; process-restart recovery goes through
  `DevCheckpointCoordinator.prepare()`.
- ~~Task-level single-agent checkpoints~~ — only pool mode has the persisted
  per-spec task-index continuation contract.
- ~~Mutating a shared flow's `flow_id` before `run_flow()`~~ — forbidden;
  per-run construction is mandatory (shared instances race).

---

## Implementation Notes

### Key Constraints
- Do NOT restore an in-memory `TaskScheduler` snapshot: pool restart rereads
  the on-disk per-spec index (task-index truth is on disk).
- Public runner call shapes must stay backward compatible (spec §5); `run_id`
  remains optional.
- Registration must be idempotent (module import + repeated runner
  construction).
- Preserve the runner's exactly-once semaphore release bookkeeping.

---

## Acceptance Criteria

- [ ] `run(run_id=...)` in a new runner resumes from the latest checkpoint;
  omitted/new `run_id` is a plain fresh run
- [ ] `test_scheduler_excludes_done_tasks_after_restart` — pool recovery
  dispatches only unfinished index entries
- [ ] `test_single_agent_recovery_is_node_granular` — interrupted single-agent
  development may rerun; no task-granular claim
- [ ] `test_registered_dev_models_round_trip` (dev-loop part) — restored
  outputs keep Pydantic types
- [ ] Completed bug-intake/research/development are not re-executed after
  restore (dispatcher call counters unchanged)
- [ ] Existing dev-loop suites pass:
  `pytest packages/ai-parrot/tests -k dev_loop -x -q`; `ruff check` clean

---

## Test Specification

```python
async def test_scheduler_excludes_done_tasks_after_restart(tmp_index):
    """Mark 2 of 5 tasks done in the on-disk index; restart; assert only 3 dispatched."""

async def test_single_agent_recovery_is_node_granular(checkpoint_store):
    """Interrupted single-agent development reruns whole node; worker dispatch
    count increments (documented at-least-once)."""

async def test_registered_dev_models_round_trip():
    for model in (ResearchOutput, PlannerOutput, DevelopmentOutput):
        assert type(round_trip(instance_of(model))) is model
```

Use dispatcher/execution counters; no vacuous cache assertions.

---

## Agent Instructions

1. Read spec §2, §3 Module 4, §5, §6, §7. 2. TASK-2622..2625 must be in
`sdd/tasks/completed/`; verify their merged APIs by grep. 3. Index →
`in-progress`; implement; move to completed; index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
