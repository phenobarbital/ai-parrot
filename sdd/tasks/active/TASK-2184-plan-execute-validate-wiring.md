# TASK-2184: plan_execute + plan_validate — acquisition front and pipeline wiring

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2180, TASK-2181, TASK-2182, TASK-2183
**Assigned-to**: unassigned

---

## Context

This task assembles the pieces into the two agent-facing entry tools:
`plan_execute` (acquire → validate → compile → run via TASK-2180's executor
path) and `plan_validate` (dry-run). It owns input arbitration
(`objective` XOR `plan_name`), the single bounded repair round, and the
structural-vs-manifest error split (spec Axis 4). Completes spec §3
Modules 2+5 tool surface.

---

## Scope

- Implement `plan_execute(objective=None, plan_name=None, params=None)` on
  `ExecutionPlanToolkit`:
  1. Arbitration: exactly one of `objective`/`plan_name`, else immediate
     tool error with usage guidance (no LLM call). `objective` without
     configured `planner_llm` ⇒ structural error naming the constructor
     arg. `plan_name` without configured `plans_dir` ⇒ same pattern.
     `params` with `objective` ⇒ error (params are a plan_name concept).
  2. Acquisition: `PlanFileStore.load(plan_name, params)`
     (`PlanLoadError` ⇒ tool error, message verbatim) or
     `PlanPlanner.author(objective)`.
  3. Validation: `validate_with_allowlist(plan, tool_manager,
     allowed_tools)`. On errors in objective mode: ONE
     `PlanPlanner.repair(plan_json, report)` then revalidate; still
     failing ⇒ tool error containing the full report. In plan_name mode:
     no repair — tool error with the report immediately.
  4. Execution: TASK-2180's `_run_plan(plan)` — returns
     `ExecutionManifest` (completed/partial/failed → SUCCESS payload) or
     `RunningSummary` on soft-timeout.
- Implement `plan_validate(objective=None, plan_name=None, params=None)`:
  same arbitration + acquisition + validation (including the repair round
  in objective mode), but NEVER executes. Response: the acquired plan JSON
  **verbatim** (both modes — user-confirmed decision enabling
  save-and-promote to `plans_dir`) + the full `ValidationReport`
  (issues with node_id/code/message/severity) + `ok` flag.
- Args schemas (`PlanExecuteArgs`, `PlanValidateArgs`) with docstrings
  that keep the LLM-facing tool descriptions short (≤3 lines each).
- Tests: full matrix of arbitration errors; partial-failure-is-success;
  repair-round happy/exhausted paths; dry-run never touches
  `ToolManager.execute_tool`.

**NOT in scope**: e2e BasicAgent tests and docs (TASK-2185); any change to
TASK-2180's executor path beyond calling it.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Add `plan_execute` / `plan_validate` + arbitration + repair orchestration |
| `packages/ai-parrot/src/parrot/tools/execution_plan/models.py` | MODIFY | Add `PlanExecuteArgs`, `PlanValidateArgs` |
| `packages/ai-parrot/tests/tools/execution_plan/test_execute_validate.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import ExecutionPlan            # TASK-2179
from parrot.bots.flows.plan.validator import ValidationReport
from .store import PlanFileStore, PlanLoadError             # TASK-2181
from .catalog import build_catalog, validate_with_allowlist # TASK-2182
from .planner import PlanPlanner, resolve_planner_client    # TASK-2183
```

### Existing Signatures to Use
```python
# Produced by the dependency tasks — RE-READ them as landed before wiring:
# .toolkit (TASK-2180): ExecutionPlanToolkit constructor stores
#   planner_llm/plans_dir raw; _run_plan(plan) -> ExecutionManifest | RunningSummary
# .store (TASK-2181):   PlanFileStore(plans_dir).load(name, params) -> ExecutionPlan
# .catalog (TASK-2182): validate_with_allowlist(plan, mgr, allowed) -> ValidationReport
# .planner (TASK-2183): PlanPlanner(planner_llm, catalog).author(objective);
#                       .repair(plan_json, report)

# Failure-semantics anchor (spec Axis 4):
# packages/ai-parrot/src/parrot/tools/manager.py:1594/:1614 —
#   execute_tool raises ValueError on tool error; PlanToolNode already
#   catches per node. plan_execute must NOT convert a partial manifest
#   into a tool error.
```

### Does NOT Exist
- ~~execution replan inside the tool~~ — forbidden (Axis 5). The ONLY
  internal LLM loop is the single pre-execution repair round.
- ~~repair in plan_name mode~~ — a persisted plan that fails validation is
  a broken file; report it, never "fix" it with the planner.
- ~~`fail_threshold` / error-rate knobs~~ — rejected in brainstorm.
- ~~implicit planner default model~~ — objective mode without
  `planner_llm` is a structural error, never a fallback.

---

## Implementation Notes

### Key Constraints
- Structural error responses use `ToolResult` error status with messages
  actionable by the AGENT (it will read them in-context); manifest
  payloads are success responses even at `status="failed"` (the plan RAN;
  what happened is data).
- `plan_validate` must be provably side-effect-free: assert in tests that
  the fake manager's `execute_tool` was never called and no run was
  registered.
- Keep tool descriptions terse — this toolkit's entire premise is a small
  prompt surface.
- Response of `plan_validate` in objective mode includes the generated
  plan verbatim — that is the promote-to-file workflow; do not truncate it.

### References in Codebase
- `sdd/specs/execution-plan-tool.spec.md` §2 Overview — the tool table is
  the behavioral contract; §5 has the matching acceptance criteria.

---

## Acceptance Criteria

- [ ] Arbitration matrix: both / neither / objective-without-planner /
  plan_name-without-plans_dir / params-with-objective each yield a tool
  error with guidance and zero LLM calls
- [ ] plan_name mode: `PlanLoadError` surfaces verbatim; validation
  failure returns the report with NO repair attempt
- [ ] objective mode: invalid first plan → exactly one repair → success
  path executes; two failures → tool error with full report, nothing
  executed
- [ ] Partial manifest returned as SUCCESS (`status="partial"`, per-node
  errors present); structural failures are the only tool errors
- [ ] `plan_validate` returns plan JSON verbatim + full report in both
  modes and never executes a tool or registers a run
- [ ] Soft-timeout path from `plan_execute` returns `RunningSummary`
  (delegated to `_run_plan`, asserted end-to-end here once)
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/execution_plan/test_execute_validate.py -v`
- [ ] `ruff check` clean

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_execute_validate.py
class TestArbitration:
    async def test_both_sources_error(...): ...
    async def test_neither_source_error(...): ...
    async def test_objective_without_planner_error(...): ...
    async def test_plan_name_without_plans_dir_error(...): ...
    async def test_params_with_objective_error(...): ...

class TestPlanExecute:
    async def test_plan_name_happy_path_manifest(...): ...
    async def test_objective_repair_round_then_execute(...): ...
    async def test_objective_repair_exhausted_tool_error(...): ...
    async def test_partial_manifest_is_success(...): ...

class TestPlanValidate:
    async def test_dry_run_returns_plan_verbatim_and_report(...): ...
    async def test_dry_run_never_executes(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2180/2181/2182/2183 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-read the landed signatures of all
   four dependency modules; they are the real contract, not this file's
   sketch
4. **Update status** in `sdd/tasks/index/execution-plan-tool.json` → `"in-progress"`
5. **Implement**, 6. **Verify**, 7. **Move this file** to
   `sdd/tasks/completed/`, 8. **Update index** → `"done"`, 9. **Completion Note**

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
