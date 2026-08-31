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
| `packages/ai-parrot/src/parrot/flows/dev_flow/flow.py` | MODIFY | Per-run checkpoint-enabled factory |
| `packages/ai-parrot/src/parrot/flows/dev_flow/runner.py` | MODIFY | Coordinator integration |
| `packages/ai-parrot/src/parrot/flows/dev_flow/models.py` | MODIFY | Registration/exports for routed result models |
| `packages/ai-parrot/tests/flows/dev_flow/test_recovery.py` | CREATE | Unit tests |

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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
