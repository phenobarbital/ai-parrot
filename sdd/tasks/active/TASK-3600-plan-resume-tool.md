# TASK-3600: `plan_resume(run_id)` — continue an interrupted checkpointed run in any process

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3599, TASK-3595
**Assigned-to**: unassigned

---

## Context

Third toolkit task. Implements goals D3–D5 / AC3 / AC9 / AC13 via the `plan_resume` tool of
spec §3 **Module 6**.

`plan_resume` resolves the run, refuses when not resumable (`run_not_resumable`,
`checkpoint_unavailable`, `artifacts_unavailable`, `scope_mismatch`, `policy_mismatch`), takes
the root lease through `PlanContinuation`, restores the exact artifact versions of completed
nodes within `max_restore_bytes` (AC13), and rebuilds the flow through
`PlanFlow.resume(run_id, agent_registry=..., store=continuation.flow_store(), durable_store=...,
flow_factory=..., seed_context=...)`. The factory calls `build_plan_flow` with **fresh live
dependencies** and current permissions (AC9); the seed context gets the validated
`plan_run` envelope explicitly (supplied seed contexts do not inherit shared data —
`flow.py:1645-1652`). Completed results — including returned `ArtifactRef(status="error")` —
stay in the completed frontier; resume is not a free repair round (R6). No planner is ever
called (D1, AC2).

---

## Scope

- `toolkit.py`: `@tool_schema(PlanResumeArgs) async def plan_resume(self, run_id: str) -> ToolResult`,
  helpers `_assert_policy(run)` (allowlist intersection + fingerprint), `_resume_flow_factory(run)`,
  `_seed_context(run)`, `_run_continuation(run, flow, ctx)` (shared later by `plan_repair`).
- Write `test_checkpoint_resume.py` (spec §4 unit part of "Fresh process recovery" /
  "In-memory downgrade" using the fake store; the integration matrix is TASK-3602).

**NOT in scope**:
- `plan_repair` (TASK-3601).
- Changes to `PlanContinuation` / `LeaseDelegatingStore` (TASK-3595) or `PlanFlow` (TASK-3594).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | MODIFY | Add `plan_resume` and continuation helpers |
| `packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py` | CREATE | Resume refusals, exact-version restore, no re-dispatch, fresh factory contract |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from .checkpoint import PlanContinuation, PlanFlow, build_plan_flow, degraded_lock   # TASK-3594/3595
from .memory import RestoreError                                                      # TASK-3591
from .models import PlanResumeArgs, PlanRun, PlanRunError, PLAN_RUN_SHARED_KEY        # TASK-3590
from .runs import plan_fingerprint, project_run, register_plan_checkpoint_types       # TASK-3593
from parrot.bots.flows.flow.definition import FlowDefinition                          # verified: tests/flows/checkpoint/test_required_persistence.py:31
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:1421
@classmethod async def resume(cls, flow_id: str, checkpoint_id: Optional[int] = None, *, agent_registry: AgentRegistry,
    store: Optional[Union[str, CheckpointStore]] = None, durable_store: Optional[Union[str, CheckpointStore]] = None,
    flow_factory: Optional[Callable[[FlowDefinition], "AgentsFlow"]] = None, seed_context: Optional[FlowContext] = None,
    expected_input: Optional[CheckpointInputMetadata] = None) -> "AgentsFlow"
#   builds FlowCheckpointer(store=ephemeral_store, durable_store=durable, starting_checkpoint_id=checkpoint.checkpoint_id) (:1548-1557)
#   acquires lease with a fresh holder (:1559) → through LeaseDelegatingStore this is a hand-off
#   flow = flow_factory(checkpoint.definition) (:1562); validates known ids (:1564-1573)
#   seed_context supplied → ONLY mark_completed(node_id, result=decoded, response=...) per completion_order (:1645-1652) — NO shared_data copy
#   flow.flow_id = flow_id (:1631); flow._resume_seed_context = seed_ctx (:1664); returns the flow, does NOT run it
# packages/ai-parrot/src/parrot/bots/flows/core/context.py
class FlowContext.__init__(..., initial_task: str, agent_registry=...)   # :56; .shared_data dict; .results; .errors; mark_completed (:177)
# TASK-3595: PlanContinuation(run, *, store, durable_store=None, ttl=60); async with → .flow_store(*extra_ids), .raise_if_lease_lost()
# TASK-3594: build_plan_flow(plan, *, run, tool_manager, working_memory, agent_registry, permission_context, step_mapping, store, durable_store) -> PlanFlow
# TASK-3592: self._memory_binding.prepare() / .restore(refs) / .artifact_mode / .scope
```

### Does NOT Exist
- ~~`AgentsFlow.resume(node_factories=...)`~~ — use `flow_factory` (a callable taking the checkpointed `FlowDefinition`).
- ~~`expected_input=CheckpointInputMetadata(workflow="execution-plan")`~~ — invalid Literal; compare `metadata.plan_fingerprint` yourself (`policy_mismatch`).
- ~~automatic shared_data seeding for supplied `seed_context`~~ — set `ctx.shared_data[PLAN_RUN_SHARED_KEY]` explicitly.
- ~~`plan_resume(run_id, allowed_tools=..., scope=...)`~~ — `PlanResumeArgs` has `run_id` only (§2).
- ~~re-running a node whose result is `ArtifactRef(status="error")`~~ — it is in `completion_order`, so `mark_completed` seeds it; only `plan_repair` can replace it (R6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.resume",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/context.py#FlowContext.mark_completed",
    "sym:packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py#ExecutionPlanToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Order inside `plan_resume`: resolve → `_assert_policy` → resumable check → `prepare()` memory →
  `async with PlanContinuation(run, store=..., durable_store=...)` → re-resolve under lease
  (revision) → `restore(completed refs)` → `PlanFlow.resume(...)` → run with soft timeout →
  terminal response. Any `PlanRunError`/`RestoreError` ⇒ `self._error(...)`, nothing dispatched.
- Not resumable reasons (map to codes): `checkpoint_enabled=False` ⇒ `checkpoint_unavailable`;
  `resume_level == "process"` and `process_id != process_identity()` ⇒ `artifacts_unavailable`;
  status `completed` or no pending nodes ⇒ `run_not_resumable`; `metadata.active_child_run_id`
  set ⇒ resume the **child** id instead (lineage) — or `run_not_resumable` if the child is terminal.
- `_assert_policy`: `set(run.metadata.allowed_tools) <= set(self.allowed_tools or tool_manager.list_tools())`
  must hold for every tool the plan uses (intersect, never widen) and
  `plan_fingerprint(run.metadata.plan) == run.metadata.plan_fingerprint`; else `policy_mismatch`.
- Degraded runs (`checkpoint_enabled=False`) are never resumable across processes; within the
  process `plan_resume` returns `checkpoint_unavailable` (there is no frontier to seed).
- Soft timeout applies to resume too (AC14); reuse the `asyncio.wait` structure of `_run_plan`.
- Restore only `status in ("ok","partial")` refs with `versions` (memory-mode runs in the same
  process still have their catalog; `restore` is a no-op when keys are already local).

### References in Codebase
- `flow.py:1421-1665` — resume in full; read it once end-to-end.
- `toolkit.py::_run_plan` (after TASK-3599) — soft-timeout and response construction to reuse.

---

## Implementation Blueprint

### Steps (in order)
1. `_assert_policy`, `_resume_flow_factory`, `_seed_context` — *why*: three pure helpers, each testable alone.
2. `_run_continuation(run, flow, ctx, *, continuation)` — *why*: `plan_repair` (TASK-3601) runs its child through the same code, so put the soft-timeout + terminal projection here.
3. `plan_resume` — *why*: it is a thin ordering of the helpers under the lease.
4. Tests with the fake store: build a run via `_run_plan` with a gated tool, "kill" the toolkit (new instance, new `WorkingMemoryToolkit`), resume, assert counters.

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — helpers)
```python
# BEFORE — insert ABOVE `    # ── Agent-facing tools ─` (verified pre-3598: toolkit.py:385; re-verify)
    def _assert_policy(self, run: PlanRun) -> None:
        """Current host policy may narrow, never widen, the recorded allowlist; fingerprint must match."""
        current = set(self.allowed_tools) if self.allowed_tools is not None else set(self._tool_manager.list_tools())
        needed = {node.tool for node in run.metadata.plan.nodes}
        if not needed <= (set(run.metadata.allowed_tools) & current):
            raise PlanRunError("policy_mismatch", "current tool policy no longer permits every tool this run uses")
        if plan_fingerprint(run.metadata.plan) != run.metadata.plan_fingerprint:
            raise PlanRunError("policy_mismatch", "effective plan fingerprint does not match the recorded run")

    def _resume_flow_factory(self, run: PlanRun, *, store: Optional[CheckpointStore]) -> Callable[[FlowDefinition], PlanFlow]:
        """Rebuild through build_plan_flow with FRESH live dependencies and current permissions (AC9)."""
        def _factory(_definition: FlowDefinition) -> PlanFlow:
            return build_plan_flow(run.metadata.plan, run=run.metadata, tool_manager=self._tool_manager,
                                   working_memory=self._working_memory, agent_registry=self._get_agent_registry(),
                                   permission_context=self.permission_context, step_mapping=self.plan_step_mapping,
                                   store=store, durable_store=self._durable_store)
        return _factory

    def _seed_context(self, run: PlanRun) -> FlowContext:
        """Seed context with the validated envelope — supplied seeds get no shared_data from resume()."""
        ctx = FlowContext(initial_task=run.metadata.plan.objective, agent_registry=self._get_agent_registry())
        ctx.shared_data[PLAN_RUN_SHARED_KEY] = run.metadata.model_dump(mode="json")
        return ctx
```
**Why**: §2 "Revalidate allowed tools and input/definition fingerprints before any dispatch";
"The factory calls the same `make_tool_node_factory` with fresh live dependencies".

### `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` (MODIFY — the tool)
```python
# AFTER — insert below the rewritten `plan_artifacts` method (end of that method), keeping the agent-facing section together
    @tool_schema(PlanResumeArgs)
    async def plan_resume(self, run_id: str) -> ToolResult:
        """Resume an interrupted checkpointed run without authoring a plan or replaying completions."""
        try:
            run = await self._resolver.resolve(run_id)
            self._assert_policy(run)
            if not run.resumable:
                raise PlanRunError(run.recovery_reason or "run_not_resumable", f"run {run_id!r} cannot be resumed",
                                   envelope=self._resolver.envelope(run))
            await self._memory_binding.prepare()
            async with PlanContinuation(run, store=self._checkpoint_store, durable_store=self._durable_store) as cont:
                run = await self._resolver.resolve(run_id)          # revision re-read under the lease
                await self._memory_binding.restore([r for r in run.refs if r.status in ("ok", "partial") and r.versions])
                store = cont.flow_store()
                flow = await PlanFlow.resume(run.metadata.run_id, agent_registry=self._get_agent_registry(), store=store,
                                             durable_store=self._durable_store, flow_factory=self._resume_flow_factory(run, store=store),
                                             seed_context=self._seed_context(run))
                cont.raise_if_lease_lost()
                return await self._run_continuation(run, flow, continuation=cont)
        except RestoreError as exc:
            return self._error(PlanRunError(exc.code, str(exc)), run_id=run_id)
        except PlanRunError as exc:
            return self._error(exc, run_id=run_id)

    async def _run_continuation(self, run: PlanRun, flow: PlanFlow, *, continuation: Any) -> ToolResult:
        """Run a rebuilt flow under the held lease with soft-timeout semantics; project the result."""
        # FILL IN: mirror _run_plan's task/asyncio.wait(soft_timeout) structure using flow.run_flow() (the seed context is
        # consumed by run_flow itself); on completion re-resolve via self._resolver.resolve(run.metadata.run_id) and return
        # PlanRunManifest / PlanRunSummary with the envelope; a CheckpointPersistenceError → checkpoint_write_failed;
        # continuation.lease_lost → run_busy. NOTE: the lease is held for the awaited part only when the run finishes within
        # soft_timeout; if it does not, the background task must hold the continuation open until terminal (keep a reference
        # in self._run_tasks and exit the `async with` from the task's finally) — bounded by AC14 and "serialize the entire continuation".
        raise NotImplementedError
```
**Why**: the ordering is the §2 continuation contract; `PlanFlow.resume` is inherited from
`AgentsFlow.resume` and, through `LeaseDelegatingStore`, its internal `acquire_lease` becomes a
hand-off instead of a `FlowLockedError`.

### `packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py` (CREATE)
```python
"""FEAT-585 — plan_resume: refusals, exact-version restore, no re-dispatch, fresh factory (unit level, fake store)."""
from __future__ import annotations
import asyncio
import pytest
from parrot.tools.execution_plan import ExecutionPlanToolkit
from parrot.tools.working_memory.tool import WorkingMemoryToolkit
from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

async def _interrupted_run(store) -> str: ...   # A→B→C, gate C on an asyncio.Event, soft_timeout tiny, cancel the run task after B checkpointed → run_id

async def test_resume_unknown_and_not_resumable_codes(): ...
async def test_resume_refuses_process_scoped_artifacts_in_new_process(): ...   # memory mode, new toolkit: artifacts_unavailable
async def test_resume_refuses_policy_widening_and_fingerprint_drift(): ...     # policy_mismatch
async def test_resume_does_not_redispatch_completed_and_completes_rest(): ...  # same process: dispatch_counts A==1,B==1,C==1 after resume
async def test_resume_preserves_error_refs_in_frontier(): ...                  # node with ArtifactRef(status="error") not re-run (R6)
async def test_resume_uses_fresh_factory_and_lease_handoff(): ...              # new CountingToolManager sees the dispatch; store._leases empty afterwards
async def test_resume_never_calls_planner(): ...                               # planner_llm=ScriptedPlannerClient with calls == []
```

### FILL IN checklist
- [ ] `toolkit.py::_run_continuation` — body; AC14 + lease lifetime
- [ ] `test_checkpoint_resume.py` — `_interrupted_run` and bodies

---

## Acceptance Criteria

- [ ] AC-1 — `plan_resume` on an unknown id / completed run / memory-mode run from another process returns the matching code with the envelope; nothing is dispatched.
- [ ] AC-2 — Resuming an interrupted A→B→C run dispatches only C; A and B counters are unchanged; the terminal manifest lists all three in order (AC3).
- [ ] AC-3 — A node that returned `ArtifactRef(status="error")` is not re-dispatched by resume (R6).
- [ ] AC-4 — Policy widening or fingerprint drift ⇒ `policy_mismatch`; another scope ⇒ `scope_mismatch` (AC9).
- [ ] AC-5 — The planner client receives zero calls during resume (AC2); the root lease is released afterwards.
- [ ] `ruff check` clean; all previous execution_plan test files pass.
- [ ] Dependency suites still pass (files created by upstream tasks, so not listed under Validation Commands): `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpointed_execution.py -q`; `pytest packages/ai-parrot/tests/tools/execution_plan/test_continuation_conflict.py -q`

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_resume.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Recovery capabilities" (resume paragraphs), "Plan memory binding" (restore), §3 Module 6, AC3/AC9/AC13/AC14.
2. Read `flow.py:1421-1665` end to end; re-verify `toolkit.py` anchors after TASK-3599.
3. Implement, run Validation Commands.
4. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
