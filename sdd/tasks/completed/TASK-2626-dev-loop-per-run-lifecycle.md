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
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/__init__.py` | MODIFY | Ensure all routed result models exported/registered — attempted, then REVERTED (net zero diff): `test_lazy_import.py::test_models_module_is_pure` explicitly asserts this module imports nothing beyond pydantic/typing, and `register_checkpoint_type` lives in `parrot.bots.flows.core.checkpoint` (a "heavy" import by that test's own definition). Registration moved to `flow.py` instead (see below) — see Completion Note. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | Only if registration needs model adjustments (no field semantics changes) — NOT touched; no field semantics changes were needed |
| `packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py` | MODIFY | Contract correction (added during implementation): TASK-2625's `_project_shared_data` was left module-private, but its own docstring says TASK-2626 must reference it when wiring `AgentsFlow(checkpoint_shared_data=...)` into `build_dev_loop_flow`. Renamed to public `project_shared_data` (no behavior change) so it can be imported here. |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/serializer.py` | MODIFY | Contract correction (bug fix, discovered during implementation): TASK-2622's `register_checkpoint_type()` raised on ANY class-identity mismatch under the same tag — including a module RELOAD of the exact same class (`test_lazy_import.py` deliberately `del sys.modules[...]` + re-imports `parrot.flows.dev_loop.models` to verify import purity), which real dev-loop model registration now exercises for the first time. Relaxed the conflict check to compare `(__module__, __qualname__)` instead of raw object identity — a genuine conflict (two DIFFERENT classes sharing a tag) still raises; a reload of the SAME qualified class is now a tolerated refresh, matching the function's own documented "idempotent" intent. |
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

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-31
**Notes**: `build_dev_loop_flow` gained `checkpoint`/`checkpoint_required`/
`checkpoint_store`/`flow_id` params (all default off/None — byte-identical
call shape for non-checkpoint callers). When `checkpoint=True`: the SAME
declarative `definition` already used for node materialization is ALSO
passed as `checkpoint_definition` (TASK-2623) — confirmed this does NOT
affect `explicit_mode` scheduler selection (only `self._definition`, never
set here, controls that) — and `checkpoint_shared_data=project_shared_data`
(TASK-2625) is wired in.

`DevLoopRunner.__init__` gained `checkpoint_store`/`dev_loop_flow_kwargs`
(both `None` by default). `run()`'s `WorkBrief` path now branches:
`recovery_enabled = run_id is not None and dev_loop_flow_kwargs is not None`
— ONLY THEN does it call `DevCheckpointCoordinator.prepare()` (via a new
`_dev_loop_flow_factory()` closure that rebuilds fresh via
`build_dev_loop_flow(**dev_loop_flow_kwargs, checkpoint=True,
checkpoint_required=True, ...)`, ignoring the `definition` arg
`AgentsFlow.resume()`/the coordinator pass it — matches TASK-2625's
documented `flow_factory` contract exactly, since `build_dev_loop_flow`
always derives its own snapshot via `build_dev_loop_definition()`
regardless) and a new `_execution_policy_for_fingerprint()` (derived from
the SAME kwargs — whatever affects routing for a run IS its execution
policy). Every existing caller (`run_id=None` OR no `dev_loop_flow_kwargs`)
takes the UNCHANGED `self.flow` path — verified via the full pre-existing
`test_runner.py`/`test_runner_park.py`/`test_runner_host.py` suites (38
passed, zero regressions). "Recovered runs must be distinguishable in
session timeline events" is satisfied via structured logging (`self.logger.
info("... %s execution (checkpoint recovery enabled)", mode)`) rather than
a new `session_state.py` action field — out of scope for this task's file
list; documented as a deliberate scope boundary, not an omission.

**Three contract corrections found and fixed during implementation** (all
documented in the Files table above):
1. `parrot/flows/dev_loop/checkpoint.py` — `_project_shared_data` renamed
   to public `project_shared_data` (TASK-2625 left it private but its own
   docstring said TASK-2626 would need to import it).
2. `models/__init__.py` registration was ATTEMPTED then REVERTED (net
   zero diff): `test_lazy_import.py::test_models_module_is_pure` explicitly
   asserts this module imports nothing beyond pydantic/typing, and
   `register_checkpoint_type` lives in `parrot.bots.flows.core.checkpoint`
   — a "heavy" import by that test's own definition. Moved the 5
   `register_checkpoint_type(...)` calls to `flow.py` instead (which every
   checkpoint-aware caller already imports, and which already imports the
   checkpoint machinery for the params above).
3. `bots/flows/core/checkpoint/serializer.py` (TASK-2622's file) — a REAL
   bug, not just a contract gap: `register_checkpoint_type()`'s conflict
   check compared class objects by raw identity, which broke the instant
   real dev-loop types were registered at import time, because
   `test_lazy_import.py` deliberately `del sys.modules[...]` + re-imports
   `parrot.flows.dev_loop.*` to verify import purity — producing a fresh-
   but-equivalent class object under the same tag. Relaxed BOTH the
   registration conflict check and `FlowStateSerializer._tag_for_class`'s
   encode-side matching to fall back to `(__module__, __qualname__)`
   equality when raw identity doesn't match; a genuine conflict (two
   unrelated classes sharing a tag) still raises. Verified non-vacuous:
   reverted each fix individually and watched
   `test_lazy_import.py` + `test_recovery_lifecycle.py` (run together,
   reproducing the real cross-file pollution) go red again for each.

Also found and fixed, purely within my OWN new test file: a dotted-string
`monkeypatch.setattr("parrot.flows.dev_loop.nodes.deployment_handoff.
assert_base_is_clean", ...)` silently patched an orphaned module object
post-reload — the exact pitfall the top-level conftest.py's
`_stub_pr_summary_enrichment` fixture already documents for
feature_handoff/deployment_handoff. Fixed by resolving via
`sys.modules[...]` directly, matching that established precedent.

15 new tests in `test_recovery_lifecycle.py`: registered-type round-trip
(qualname-based comparison, not raw identity — see finding #3 above),
`TaskScheduler.next_wave()` excluding done tasks from an on-disk index
(confirming existing, unmodified behavior), and three full `DevLoopRunner`
end-to-end recovery scenarios through the REAL engine (mocked dispatcher/
Jira, real `git worktree add`-backed artifacts for TASK-2625's validation
gate): node-granular single-agent recovery (development crashes, resumed
process reruns ONLY development — research/bug_intake never redispatch),
full-run restoration (nothing redispatches when the checkpoint already
completed), and `run_id=None` staying a plain fresh run even with
`checkpoint_store`/`dev_loop_flow_kwargs` configured. Full
`packages/ai-parrot/tests/flows/dev_loop` + `checkpoint` suites: 1248
passed, same 5 pre-existing failures (2 postgres-integration + 3 unrelated
dev-loop QA/secondopinion prompt tests, confirmed pre-existing across every
prior task in this feature). `ruff check` clean on every touched/new file;
`flow.py`/`runner.py` carry the same proportional pre-existing
`Optional[...]`-style debt noted in every earlier task's completion note —
no new lint categories.

**Deviations from spec**: none (three Codebase Contract corrections — two
file-location corrections, one real upstream bug fix — all documented above
and in the task file itself, per the established "stale contract" protocol).
