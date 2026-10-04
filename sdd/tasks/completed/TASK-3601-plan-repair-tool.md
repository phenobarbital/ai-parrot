# TASK-3601: `plan_repair(run_id)` — bounded, allowlisted runtime repair with persisted attempt accounting

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3600, TASK-3596, TASK-3597
**Assigned-to**: unassigned

---

## Context

Fourth and last toolkit task. Implements goals D1 / D2 and AC2 / AC7 / AC8 / AC16 via the
`plan_repair` tool of spec §3 **Module 6**.

Only the agent's explicit `plan_repair` call invokes the planner. Under the root lease it:
computes eligible ids (`no_repairable_nodes` if none), checks `max_repair_rounds`
(`repair_limit_reached` **without** consuming an attempt or calling a planner — including
`max_repair_rounds=0`), checks the planner is configured (`planner_unavailable`, no attempt
consumed), **persists the attempt number and allocated child id in the root checkpoint
before calling the planner** (so invalid output, cancellation or a crash after this point
consumes the attempt), makes one `replan` call plus at most one `repair_delta` correction,
validates with `validate_delta`, persists the accepted child definition and initial child
checkpoint, seeds successful parent refs as completed, makes the child the active
continuation in the root lineage, and runs it. A root/child inconsistency found on a later call
is reconciled under the root lease into either resuming the accepted child or
`repair_interrupted` — never another autonomous planner call.

---

## Scope

- `toolkit.py`: `@tool_schema(PlanRepairArgs) async def plan_repair(self, run_id: str) -> ToolResult`,
  helpers `_write_root_envelope(run, metadata, *, store)` (awaited checkpoint update of the root's
  `plan_run` document), `_author_delta(run, eligible)` (replan + ≤1 correction), `_child_metadata(run, merged_plan, child_id)`,
  `_seed_child_context(run, child_meta)` (mark protected nodes completed with their refs),
  `_reconcile_lineage(run)`.
- Write `test_runtime_repair.py` (spec §4 `test_attempt_accounting`, `test_delta_structural_correction`
  toolkit side, `test_partial_is_not_error` toolkit side, and `Repair budget`).

**NOT in scope**:
- Delta validation rules (TASK-3596) or planner prompts (TASK-3597).
- The cross-process crash matrix / concurrency integration tests (TASK-3603).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Add `plan_repair` and lineage/attempt helpers |
| `packages/ai-parrot/tests/tools/execution_plan/test_runtime_repair.py` | CREATE | Attempt accounting, budget, correction, lineage |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from .repair import eligible_repair_nodes, merge_delta, protected_node_ids, validate_delta   # TASK-3596
from .models import PlanDelta, PlanRepairArgs, PlanRunMetadata, PlanRun, PlanRunError         # TASK-3590
from .planner import PlanAuthoringError, PlanPlanner                                           # verified: planner.py:56, :127 (+ replan/repair_delta from TASK-3597)
from .checkpoint import PlanContinuation, build_plan_flow                                      # TASK-3594/3595
from parrot.bots.flows.core.checkpoint import FlowCheckpointer                                 # verified: checkpoint/__init__.py:8
from parrot.bots.flows.plan import build_manifest                                              # verified: plan/__init__.py:35
```

### Existing Signatures to Use
```python
# TASK-3597: PlanPlanner.replan(plan, manifest, *, eligible_node_ids) -> PlanDelta ; PlanPlanner.repair_delta(delta_json, report, *, plan, eligible_node_ids) -> PlanDelta
# TASK-3596: eligible_repair_nodes(run) -> frozenset[str]; validate_delta(delta, *, run, tool_manager, allowed_tools) -> ValidationReport; merge_delta(plan, delta) -> ExecutionPlan
# TASK-3595: PlanContinuation(run, *, store, durable_store=None).flow_store(*extra_flow_ids) — pass the child id so the child flow's lease acquire is a hand-off too
# TASK-3594: build_plan_flow(...) ; PlanFlow ; plan_run_projector
# TASK-3600: self._run_continuation(run, flow, *, continuation) ; self._seed_context(run) ; self._assert_policy(run)
# TASK-3593: project_run(checkpoint, metadata=...) ; select_latest(store, durable, flow_id) ; PlanRunResolver.resolve follows metadata.active_child_run_id
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:565-591 _acquire_from_objective — how PlanPlanner is constructed:
#   catalog = build_catalog(self._tool_manager, self.allowed_tools); planner = PlanPlanner(self.planner_llm, catalog); self.planner_llm None → structural error
# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py:92 FlowCheckpointer(flow_id, flow_name, definition, store, *, durable_store=None,
#   serializer=None, include_responses=False, durable=False, history_limit=10, memory_refs=None, starting_checkpoint_id=0, shared_data_projector=None, input_metadata=None)
#   async def checkpoint(self, ctx, *, status="running") -> FlowCheckpoint (:268) — awaited required write; use it to persist the root envelope update
# packages/ai-parrot/src/parrot/bots/flows/core/context.py:177 FlowContext.mark_completed(node_id, result=None, response=None, metadata=None)
```

### Does NOT Exist
- ~~`PlanPlanner.repair(delta_json, ...)` for deltas~~ — its parser expects an `ExecutionPlan` (`planner.py:243`); use `repair_delta`.
- ~~`CheckpointStore.update(flow_id, patch)`~~ — a checkpoint is immutable; write a NEW root checkpoint (next `checkpoint_id`) whose `shared_data.plan_run` carries the incremented attempt/child ids. Build it with a `FlowCheckpointer` bound to the root definition and `starting_checkpoint_id=run.checkpoint_id`, on a `FlowContext` seeded with the root's `completion_order`/results (so the record stays complete), through `continuation.flow_store()` so the revision check applies.
- ~~`max_repair_rounds` from a tool argument or `plan.metadata`~~ — `PlanRepairArgs` has `run_id` only; the limit is `run.metadata.max_repair_rounds` snapshot (host-only, §8 D1). `PlanMetadata` has no such field (`models.py:257-265`) and `extra="forbid"` rejects one.
- ~~an automatic retry when the corrected delta is still invalid~~ — after `replan` + one `repair_delta`, an invalid delta is `delta_invalid`; the attempt is consumed.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_runtime_repair.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit._acquire_from_objective",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/planner.py#PlanPlanner",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py#FlowCheckpointer",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/context.py#FlowContext.mark_completed"
  ]
}
```

---

## Implementation Notes

### Ordered contract for `plan_repair` (normative; each step's failure code in brackets)
1. `run = resolve(run_id)`; if `run.metadata.active_child_run_id` → `_reconcile_lineage` (child terminal & consolidated ⇒ treat the consolidated run as the current root state; child running/interrupted ⇒ `repair_interrupted` or resume it via the TASK-3600 path — never re-plan).
2. `_assert_policy(run)` [`policy_mismatch`/`scope_mismatch`].
3. `run.status not in ("failed","partial")` ⇒ [`run_not_repairable`]; `run.checkpoint_enabled is False` ⇒ [`checkpoint_unavailable`] (§8 D2: no checkpoint ⇒ refuse).
4. `eligible = eligible_repair_nodes(run)`; empty ⇒ [`no_repairable_nodes`] — no attempt consumed.
5. `metadata.repair_attempts_used >= metadata.max_repair_rounds` ⇒ [`repair_limit_reached`] — no attempt consumed, no planner.
6. `self.planner_llm is None` ⇒ [`planner_unavailable`] — no attempt consumed.
7. `async with PlanContinuation(run, ...)` [`run_busy`]; re-resolve under lease (revision).
8. Allocate `child_id = str(uuid.uuid4())`; `metadata.repair_attempts_used += 1`, `repair_children.append(child_id)`;
   **`await _write_root_envelope(...)`** [`checkpoint_write_failed`]. From here the attempt is spent.
9. `delta = await _author_delta(run, eligible)`: `replan`; on `PlanAuthoringError` or `validate_delta(...).ok is False` ⇒ one `repair_delta`; still invalid ⇒ [`delta_invalid`] (attempt consumed).
10. `merged = merge_delta(run.metadata.plan, delta)`; `child_meta = _child_metadata(...)` (`run_id=child_id`, `root_run_id`, `parent_run_id=run.metadata.run_id`, `plan=merged`, `source="repair"`, same allowlist/scope/fingerprint recomputed, `max_repair_rounds`, `repair_attempts_used`).
11. Build child flow via `build_plan_flow(merged, run=child_meta, ..., store=cont.flow_store(child_id), durable_store=...)`; child ctx = `_seed_context`-style context with `shared_data.plan_run = child_meta` and `mark_completed(pid, result=ref)` for every protected node (their refs seed the completed frontier).
12. `metadata.active_child_run_id = child_id`; **`await _write_root_envelope(...)`** (child accepted) — then run the child via `_run_continuation`.
13. Response: consolidated `PlanRunManifest`/`PlanRunSummary` for the ROOT id (resolver follows lineage), counters recomputed (AC7).

### References in Codebase
- `toolkit.py:565-591` — planner construction and the existing author/repair round shape.
- `flow.py:1645-1652` — `mark_completed` seeding idiom for protected nodes.

---

## Implementation Blueprint

### Steps (in order)
1. `_write_root_envelope` — *why*: it is the persistence primitive every attempt-accounting guarantee rests on.
2. `_author_delta` — *why*: encapsulates "one call + at most one correction" so the count is provable.
3. `_child_metadata`, `_seed_child_context`, `_reconcile_lineage` — *why*: pure helpers.
4. `plan_repair` — *why*: the ordered contract above, step by step.
5. Tests with `ScriptedPlannerClient` counting calls.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — helpers)
```python
# BEFORE — insert ABOVE `    # ── Agent-facing tools ─` (re-verify the anchor after TASK-3600)
    async def _write_root_envelope(self, run: PlanRun, metadata: PlanRunMetadata, *, store: CheckpointStore) -> int:
        """Persist an updated root ``plan_run`` document as a NEW root checkpoint; return its id."""
        register_plan_checkpoint_types()
        latest = await select_latest(store, self._durable_store, run.metadata.root_run_id)
        if latest is None:
            raise PlanRunError("checkpoint_unavailable", "root checkpoint vanished during continuation")
        checkpointer = FlowCheckpointer(flow_id=run.metadata.root_run_id, flow_name=latest.flow_name, definition=latest.definition,
                                        store=store, durable_store=self._durable_store, durable=self._durable_store is not None,
                                        starting_checkpoint_id=latest.checkpoint_id, shared_data_projector=plan_run_projector)
        ctx = self._seed_context(run)
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = metadata.model_dump(mode="json")
        # FILL IN: replay latest.context.completion_order into ctx via mark_completed(node_id, result=serializer.from_safe(...))
        # so the new record is complete, then `cp = await checkpointer.checkpoint(ctx, status=latest.status)`; map
        # CheckpointPersistenceError → PlanRunError("checkpoint_write_failed"); return cp.checkpoint_id — bounded by AC8.
        raise NotImplementedError

    async def _author_delta(self, run: PlanRun, eligible: "frozenset[str]") -> PlanDelta:
        """One replan call, then at most one structural correction; anything else is delta_invalid."""
        planner = PlanPlanner(self.planner_llm, build_catalog(self._tool_manager, self.allowed_tools))
        manifest = build_manifest(run.metadata.plan, run.refs)
        allowed = self.allowed_tools if self.allowed_tools is not None else self._tool_manager.list_tools()
        try:
            delta = await planner.replan(run.metadata.plan, manifest, eligible_node_ids=eligible)
            report = validate_delta(delta, run=run, tool_manager=self._tool_manager, allowed_tools=allowed)
            if report.ok:
                return delta
            delta_json = delta.model_dump(mode="json")
        except PlanAuthoringError as exc:
            delta_json, report = {"error": str(exc)[:300]}, ValidationReport(issues=[])
        try:
            delta = await planner.repair_delta(delta_json, report, plan=run.metadata.plan, eligible_node_ids=eligible)
        except PlanAuthoringError as exc:
            raise PlanRunError("delta_invalid", f"corrected delta unparseable: {exc}") from exc
        report = validate_delta(delta, run=run, tool_manager=self._tool_manager, allowed_tools=allowed)
        if not report.ok:
            raise PlanRunError("delta_invalid", f"corrected delta still invalid:\n{report}")
        return delta
```
**Why**: `_write_root_envelope` writes a new immutable checkpoint through the delegating store,
so the revision check of TASK-3595 protects it; `_author_delta` makes the "≤ 2 planner calls
per round" bound structural (§2, AC8). Import `ValidationReport` from
`parrot.bots.flows.plan.validator` and `select_latest` from `.runs`.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — the tool)
```python
# AFTER — insert below `plan_resume` (TASK-3600)
    @tool_schema(PlanRepairArgs)
    async def plan_repair(self, run_id: str) -> ToolResult:
        """Spend one permitted repair attempt on failed/blocked IDs; never restart a whole run implicitly."""
        try:
            run = await self._resolver.resolve(run_id)
            run = await self._reconcile_lineage(run)                       # may raise repair_interrupted
            self._assert_policy(run)
            envelope = self._resolver.envelope(run)
            if not run.checkpoint_enabled:
                raise PlanRunError("checkpoint_unavailable", "runs without a checkpoint cannot be repaired (§8 D2)", envelope=envelope)
            if run.status not in ("failed", "partial"):
                raise PlanRunError("run_not_repairable", f"run status is {run.status!r}", envelope=envelope)
            eligible = eligible_repair_nodes(run)
            if not eligible:
                raise PlanRunError("no_repairable_nodes", "no error or undispatched nodes to replace (partial fan-out is not error)", envelope=envelope)
            if run.metadata.repair_attempts_used >= run.metadata.max_repair_rounds:
                raise PlanRunError("repair_limit_reached", f"{run.metadata.repair_attempts_used}/{run.metadata.max_repair_rounds} rounds used", envelope=envelope)
            if self.planner_llm is None:
                raise PlanRunError("planner_unavailable", "plan_repair requires planner_llm", envelope=envelope)
            await self._memory_binding.prepare()
            async with PlanContinuation(run, store=self._checkpoint_store, durable_store=self._durable_store) as cont:
                run = await self._resolver.resolve(run_id)
                child_id = str(uuid.uuid4())
                metadata = run.metadata.model_copy(update={"repair_attempts_used": run.metadata.repair_attempts_used + 1,
                                                           "repair_children": [*run.metadata.repair_children, child_id]})
                await self._write_root_envelope(run, metadata, store=cont.flow_store())   # attempt reserved BEFORE any LLM call
                delta = await self._author_delta(run, eligible)
                cont.raise_if_lease_lost()
                # FILL IN: merged = merge_delta(...); child_meta = self._child_metadata(run, merged, child_id); restore protected refs
                # via self._memory_binding.restore(...); child_flow = build_plan_flow(merged, run=child_meta, ..., store=cont.flow_store(child_id), ...);
                # child_ctx = self._seed_child_context(run, child_meta) (mark_completed for protected nodes with their refs);
                # metadata = metadata.model_copy(update={"active_child_run_id": child_id}); await self._write_root_envelope(run, metadata, store=cont.flow_store());
                # return await self._run_continuation(<child PlanRun view>, child_flow, continuation=cont) projected for the ROOT id —
                # bounded by §2 "Persist the accepted child definition and initial child checkpoint before dispatch" and AC7.
                raise NotImplementedError
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)
```
**Why**: the eight refusal branches come before the lease and consume nothing (§2, §8 D1/D2);
the first `_write_root_envelope` is the "persist before LLM" guarantee of AC8.

### `packages/ai-parrot/tests/tools/execution_plan/test_runtime_repair.py` (CREATE)
```python
"""FEAT-585 — plan_repair attempt accounting, budget, correction, lineage (fake store, scripted planner)."""
from __future__ import annotations
import pytest
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanRecoveryConfig
from ._recovery_fakes import CountingToolManager, ScriptedPlannerClient, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

async def _failed_run(store, planner, **kw) -> tuple[ExecutionPlanToolkit, str]: ...   # A ok, B error (tool raises), C blocked

async def test_refusals_consume_nothing(): ...                    # completed run, no eligible, limit 0, planner None → codes; planner.calls == []; attempts unchanged
async def test_attempt_persisted_before_planner_call(): ...       # planner raises on first call → checkpoint shows attempts_used 1, child id allocated
async def test_invalid_output_consumes_attempt_after_one_correction(): ...  # 2 planner calls total, delta_invalid, attempts_used 1
async def test_successful_repair_runs_only_replacements_and_consolidates(): ...   # A dispatched once total; B,C once more; nodes_total unchanged; root status completed
async def test_partial_fanout_not_repairable(): ...               # no_repairable_nodes
async def test_default_two_rounds_survive_a_consumed_attempt(): ... # first attempt crashes after reservation (planner raises), second succeeds, third → repair_limit_reached
async def test_zero_rounds_disables_without_planner_call(): ...   # PlanRecoveryConfig(max_repair_rounds=0)
async def test_plan_supplied_budget_is_rejected(): ...            # ExecutionPlan(metadata={"max_repair_rounds": 5}) → pydantic ValidationError (extra forbid)
```

### FILL IN checklist
- [ ] `toolkit.py::_write_root_envelope` — completion replay + awaited write; AC8
- [ ] `toolkit.py::plan_repair` — child build/seed/run tail; AC7
- [ ] `toolkit.py::_child_metadata`, `_seed_child_context`, `_reconcile_lineage` — write per the Implementation Notes
- [ ] `test_runtime_repair.py` — `_failed_run` and bodies

---

## Acceptance Criteria

- [ ] AC-1 — Every refusal (`run_not_repairable`, `no_repairable_nodes`, `repair_limit_reached`, `planner_unavailable`, `checkpoint_unavailable`) returns with zero planner calls and unchanged `repair_attempts_used` (AC16).
- [ ] AC-2 — The root checkpoint carries `repair_attempts_used+1` and the child id **before** the first planner call; a planner exception afterwards leaves the attempt consumed (AC8).
- [ ] AC-3 — A malformed/invalid delta gets exactly one correction call; still invalid ⇒ `delta_invalid`, 2 planner calls total.
- [ ] AC-4 — A successful repair dispatches only replacement nodes, preserves ok/skipped/partial refs, and the consolidated root manifest's counters equal one `build_manifest` over the final refs (AC7).
- [ ] AC-5 — `max_repair_rounds=0` ⇒ `repair_limit_reached` with no planner call; default 2 permits a second attempt after a consumed one; a plan-level budget field is rejected at model validation (AC16).
- [ ] `ruff check` clean; every execution_plan test file passes.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py -q`; `pytest packages/ai-parrot/tests/tools/execution_plan/test_delta_validation.py -q`; `pytest packages/ai-parrot/tests/tools/execution_plan/test_delta_planner.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_runtime_repair.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §1 D1/D2, §2 "Repair validation, execution and concurrency" in full, §8 D1/D2, AC7/AC8/AC16.
2. Re-verify `toolkit.py` anchors after TASK-3600; implement the ordered contract exactly.
3. Run Validation Commands.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker orchestration (native Claude Sonnet 5 agent, subagent id ab927f963824f46cf, attempt_uid=117620740abb4664b5108efecc5ff1f6)
**Date**: 2026-09-22
**Notes**: Clean delivery — 8/8 own tests pass (`test_runtime_repair.py`), dependency suites (`test_delta_validation.py`, `test_delta_planner.py`) pass. Merged commit-clean (lint residual_count=0). Review recorded (coder-review:c602035c90c9217cd92c2fc6), no fix commits needed.
The coder independently identified and correctly worked around the known, ledger-filed pre-existing blocker (`issue:7552079c55a1`) — did not attempt to fix `flow.py`, left `test_checkpoint_resume.py` untouched, and confirmed the two known failures reproduce exactly as predicted. It also caught and fixed a real bug in the task's own blueprint pseudocode: `_reconcile_lineage`'s described check (`run.metadata.active_child_run_id`) can never be truthy after `PlanRunResolver.resolve()` (which always returns the terminal-most leaf's own metadata — that's its own exit condition), so the coder substituted the working-equivalent signal `run.metadata.parent_run_id is not None and run.status == "running"`, verified via its own test.
Local verification (this session): full `tests/tools/execution_plan/` → 170 passed, 5 failed — all 5 failures are the SAME pre-existing ledger-issue:7552079c55a1 symptom already documented on TASK-3600/TASK-3602 (2 in `test_checkpoint_resume.py`, 3 in `test_integration_recovery.py`); no new regressions from this task.
Merge-tier validation launched (`102a3ed1-a205-40ff-837e-79b1e65a0b93:TASK-3601:merge`); expected to follow the established baseline pattern.

**Deviations from spec**: the `_reconcile_lineage` signal substitution above (functionally equivalent, verified by test) and the manual lease-ownership pattern (matching `plan_resume`'s own established idiom, avoiding a double-`__aexit__` that a literal `async with PlanContinuation(...)` would cause) — both corrections to the blueprint's shorthand pseudocode, not deviations from the task's ordered contract or acceptance criteria.
