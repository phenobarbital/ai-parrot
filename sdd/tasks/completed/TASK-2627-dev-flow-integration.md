# TASK-2627: Proactive Dev Flow Recovery Integration

**Feature**: FEAT-480 — Dev Flow Node Checkpoint Recovery
**Spec**: `sdd/specs/dev-flow-node-caching.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2626
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5. With the coordinator (TASK-2625) and the dev-loop
lifecycle (TASK-2626) in place, apply the same per-run pattern to the
proactive `dev_flow`: workflow namespace `"dev-flow"`, its own explicit graph
factory, and restoration of the intake → ideation → planner → development
projections, including validation of planner-created SDD/worktree artifacts.

---

## Scope

- Make `build_dev_flow` (`dev_flow/flow.py`) a per-run checkpoint-enabled
  factory mirroring TASK-2626 (required mode, `"dev-flow/<run_id>"` identity,
  retained declarative definition, allowlist projector), preserving its
  explicit routing.
- Wire `DevFlowRunner.run(brief, *, run_id=None, ...)` through
  `DevCheckpointCoordinator.prepare(workflow="dev-flow", ...)`, binding a
  fresh host/context on both paths.
- Register `dev_flow` result models (`dev_flow/models.py` — grep exports and
  node return types: intake/ideation/planner/development outputs,
  `DevRequestBrief`).
- Restore projections: `planner_output` and its derived `research_output`
  bridge (see `planner.py` anchors), ideation/intake outputs, and
  `development_output`; validate planner-created spec/task/worktree artifacts
  before downstream dispatch.
- Ensure the fingerprint's workflow kind + topology version separate
  `dev-flow` runs from `dev-loop` runs with identical briefs.
- Unit tests for planner-restoration and namespace separation.

**NOT in scope**: example servers / CLI bootstrap and the cross-workflow
integration suite (TASK-2628).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py` | MODIFY | Per-run checkpoint-enabled factory + `register_checkpoint_type(DevRequestBrief/IdeationOutput)` |
| `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | MODIFY | Coordinator integration |
| `packages/ai-parrot/src/parrot/flows/dev_loop/checkpoint.py` | MODIFY (contract correction — see below) | Extend `_SHARED_DATA_ALLOWLIST` with dev-flow keys; lazy `_result_key_by_type()` |
| `packages/ai-parrot/tests/flows/dev_flow/test_recovery.py` | CREATE | Unit tests |

> **Contract correction**: `dev_flow/models.py` was listed as MODIFY in the
> original task, but registering checkpoint types there would repeat
> TASK-2626's discovered purity violation — `models.py` is asserted
> pydantic/typing-only by `test_lazy_import.py::test_models_module_is_pure`
> (and `dev_flow/models.py` imports `dev_loop/models.py`, so the same
> invariant applies transitively). `register_checkpoint_type(DevRequestBrief)`
> / `register_checkpoint_type(IdeationOutput)` were placed in `dev_flow/
> flow.py` instead, mirroring `dev_loop/flow.py`'s existing pattern for the
> other five models. `dev_loop/checkpoint.py` (not in the original file
> list) needed a small MODIFY instead: extending `_SHARED_DATA_ALLOWLIST`
> with the three dev-flow-only keys, and adding a lazily-resolved
> `_result_key_by_type()` (deferred `from parrot.flows.dev_flow.models
> import IdeationOutput` inside the function body) because a module-level
> import of `dev_flow.models` from `dev_loop/checkpoint.py` is a genuine
> import cycle: `dev_flow/__init__.py` → `dev_flow.models` →
> `dev_loop.models` → `dev_loop/__init__.py` (eager) → `dev_loop.commands`
> → `dev_loop.runner` → `dev_loop.checkpoint` → back to `dev_flow.models`
> (still initializing).

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/runner.py:37
class DevFlowRunner(DevLoopRunner):
    async def run(self, brief: DevRequestBrief | FeatureBrief, *,
                  run_id: str | None = None, initial_task: str = "",
                  extra_shared: dict[str, Any] | None = None) -> FlowResult: ...  # line 55

# From TASK-2625/2626 (verify merged code):
#   from parrot.flows.dev_loop.checkpoint import DevCheckpointCoordinator
#   register_checkpoint_type(...)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_flow/flow.py — build_dev_flow
#   explicit-edge proactive SDD flow (verify current node list before editing)

# Planner bridge anchors (re-grep before editing):
#   dev_flow planner node (planner.py):105 — execute; 173 — planner_output /
#   derived research_output projection
```

### Does NOT Exist
- ~~A dev_flow-specific coordinator class~~ — reuse
  `DevCheckpointCoordinator` with `workflow="dev-flow"`; do not fork it.
- ~~Shared checkpoint identity between dev_loop and dev_flow~~ — namespaces
  are disjoint by construction; a `dev-loop/<id>` checkpoint must never
  satisfy a `dev-flow/<id>` lookup.
- `DevFlowRunner` overrides little beyond `run()` — it inherits
  `DevLoopRunner`; check inherited behavior before duplicating logic.

---

## Implementation Notes

### Key Constraints
- Same rules as TASK-2626: fresh live objects, on-disk task-index truth,
  backward-compatible call shapes, idempotent registration.
- Planner-created artifacts (spec, task index, worktree) are validated with
  the same shared validator extracted in TASK-2625 — no duplicate validation
  logic.

---

## Acceptance Criteria

- [ ] `dev_flow` restart with same `run_id` skips completed
  intake/ideation/planner nodes and restores their projections
- [ ] Completed proactive development is not redispatched
- [ ] Same brief under `dev-loop` vs `dev-flow` namespaces never cross-hits
- [ ] Planner-created SDD/worktree artifacts are validated before downstream
  dispatch; missing artifacts fail explicitly
- [ ] `pytest packages/ai-parrot/tests -k dev_flow -x -q` passes; `ruff check` clean

---

## Test Specification

```python
async def test_dev_flow_restart_after_planner(checkpoint_store):
    """Planner/ideation skipped; planner_output + derived research_output
    restored; downstream continues on the original explicit graph."""

async def test_dev_flow_namespace_is_disjoint(checkpoint_store):
    """dev-loop/r1 checkpoint present; dev-flow prepare(run_id='r1') is a miss."""
```

---

## Agent Instructions

1. Read spec §2, §3 Module 5, §5. 2. TASK-2622..2626 in `sdd/tasks/completed/`;
grep merged APIs. 3. Index → `in-progress`; implement; move to completed;
index → `done`.

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5)
**Date**: 2026-08-31
**Notes**:
- `build_dev_flow()` gained `checkpoint`/`checkpoint_required`/
  `checkpoint_store`/`flow_id` params, wired into the `AgentsFlow(...)`
  constructor exactly as `build_dev_loop_flow` (TASK-2626):
  `checkpoint_definition=definition if checkpoint else None`,
  `checkpoint_shared_data=project_shared_data if checkpoint else None`.
  `checkpoint=False` (default) is byte-identical to pre-FEAT-480 behavior.
- `DevRequestBrief`/`IdeationOutput` registered via `register_checkpoint_type`
  at `dev_flow/flow.py` module scope (WorkBrief/FeatureBrief/ResearchOutput/
  PlannerOutput/DevelopmentOutput already covered transitively by the
  `from parrot.flows.dev_loop.flow import ...` import at the top of the file).
- `DevFlowRunner.run()` gained the same `recovery_enabled = run_id is not
  None and self._dev_loop_flow_kwargs is not None` gate as the base class,
  calling `self._checkpoint_coordinator.prepare(workflow="dev-flow", ...)`
  and using the returned `flow` (not `self.flow`) for the remainder of the
  run. Overrode `_dev_loop_flow_factory()` (closure builds via
  `build_dev_flow(**kwargs, checkpoint=True, checkpoint_required=True,
  checkpoint_store=self._checkpoint_store)`) and
  `_execution_policy_for_fingerprint()` (dev-flow's kwarg shape: no
  `development_pool_config`/`repos`, adds `ideation_max_rounds`).
- `dev_loop/checkpoint.py`'s `_SHARED_DATA_ALLOWLIST` extended with
  `dev_brief`/`feature_brief`/`ideation_output`; `_result_key_by_type()`
  added as a lazily-resolved superset of `_RESULT_KEY_BY_TYPE` (deferred
  import of `IdeationOutput` to break a real import cycle — see contract
  correction above).
- Namespace disjointness (dev-loop/r1 vs dev-flow/r1 never cross-hit) needed
  no new code — `DevCheckpointCoordinator.prepare()`'s existing
  `flow_id = f"{workflow}/{run_id}"` construction (TASK-2625) already
  guarantees it; covered by
  `test_dev_flow_namespace_is_disjoint_from_dev_loop`.
- 7 new tests in `test_recovery.py` using a lightweight custom 3-node
  `_StepNode` graph (`ideation → planner → development`, mirroring
  TASK-2626's own approach) plus `FakeCheckpointStore` — no full
  real-dispatcher end-to-end test against all 8 real `dev_flow` nodes was
  added, since no existing `dev_flow` test does this either (confirmed via
  grep) and the underlying generic recovery/checkpoint mechanics are
  already exhaustively covered by TASK-2622–2626's suites; TASK-2627's
  tests instead target exactly what this task changed.
- Verification: `pytest packages/ai-parrot/tests/flows -k dev_flow -q` →
  179 passed; `ruff check` clean on all 4 touched/created files; lint-delta
  check (pre-existing-style files `dev_flow/flow.py`/`runner.py`) shows no
  new lint categories. The 5 unrelated failures seen in a broader
  `packages/ai-parrot/tests/flows/{dev_flow,dev_loop,checkpoint}` run
  (`test_qa_codereview`, `test_secondopinion_brief`, `test_subagent_parity`,
  2× `test_durable_store::*postgres*`) were confirmed pre-existing on the
  `dev` baseline (3 fail identically on `dev`; 2 require a local Postgres
  that isn't running in this environment) — unrelated to this task's files.

**Deviations from spec**: none (see Codebase Contract correction above for
the file-list correction, which does not change scope or behavior).
