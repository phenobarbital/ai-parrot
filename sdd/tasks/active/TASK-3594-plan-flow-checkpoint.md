# TASK-3594: `PlanFlow` — required checkpoint barriers, plan-only projection, `build_plan_flow`

**Feature**: FEAT-585 — Plan-then-Execute Hardening
**Spec**: `sdd/specs/plan-then-execute-hardening.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3590, TASK-3593
**Assigned-to**: unassigned

---

## Context

Implements the flow half of spec §3 **Module 4** and AC6 / AC9.

`ExecutionPlanToolkit._run_plan` currently calls `AgentsFlow.from_definition(..., checkpoint=False)`
(`toolkit.py:196-212`), so no plan run is ever checkpointed. `AgentsFlow.from_definition`
has **no** `checkpoint_required` / `checkpoint_shared_data` parameters (`flow.py:550-564`) —
those belong to the constructor (`flow.py:313-315`) — but `from_definition` builds the
flow with `cls(...)` (`flow.py:661`), so a subclass constructor can force them. This task
adds the toolkit-local `PlanFlow(AgentsFlow)` that, when checkpointing is enabled, forces
required barriers, projects only the `plan_run` envelope into `shared_data`, excludes raw
responses, writes an initial checkpoint before dispatch and a terminal checkpoint before
its lease is released — delegating all scheduling to the existing scheduler.

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` with
  `plan_run_projector(ctx)`, `PlanFlow(AgentsFlow)` (`__init__`, `_run_flow_scheduler`
  override), and `build_plan_flow(...)`.
- Write `packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_lifecycle.py`
  (spec §4 `test_checkpoint_lifecycle`, and the pre-dispatch half of `test_checkpoint_outage`).

**NOT in scope**:
- `PlanContinuation` and the lease-delegating store adapter (TASK-3595, appends to this file).
- Calling `build_plan_flow` from the toolkit (TASK-3599) or `PlanFlow.resume` wiring (TASK-3600).
- Any edit to `bots/flows/flow/flow.py` or the checkpoint package (AC1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` | CREATE | `plan_run_projector`, `PlanFlow`, `build_plan_flow` |
| `packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_lifecycle.py` | CREATE | Fresh + resumed barrier options, start/terminal records, no raw responses, cancellation releases lease |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `3028213ee` on 2026-09-21.

### Verified Imports
```python
from parrot.bots.flows.flow.flow import AgentsFlow                          # verified: flow.py:296 (class), :550 (from_definition), :1421 (resume)
from parrot.bots.flows.core.context import FlowContext                      # verified: context.py:56
from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpointer, CheckpointPersistenceError  # verified: checkpoint/__init__.py:8-15, :26
from parrot.bots.flows.core.types import FlowResult                         # verified: used by flow.py run_flow return annotation
from parrot.bots.flows.plan import ExecutionPlan, PlanToolNode, ensure_tool_node_registered, make_tool_node_factory, to_flow_definition  # verified: plan/__init__.py
from parrot.registry.registry import AgentRegistry                          # verified: toolkit.py:32
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY, PlanRunMetadata   # TASK-3590
from parrot.tools.execution_plan.runs import register_plan_checkpoint_types           # TASK-3593
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:296
class AgentsFlow.__init__(self, name: str, *, definition=None, agent_registry=None, on_node_event=None,
    checkpoint: bool = False, checkpoint_retention=None, checkpoint_history=None, checkpoint_include_responses: bool = False,
    checkpoint_definition=None, checkpoint_shared_data: Optional[Callable[[FlowContext], Dict[str, Any]]] = None,   # :313
    checkpoint_input=None, checkpoint_required: bool = False,                                                       # :315
    durable: bool = False, checkpoint_store=None, durable_store=None, flow_id: Optional[str] = None, ...)          # :316-319
    self._checkpoint_enabled = checkpoint (:371); self._checkpoint_shared_data_arg (:380); self._checkpoint_required (:386)
    self._checkpoint_store_arg (:388); self._durable_store_arg (:389); self._checkpointer: Optional[FlowCheckpointer] = None (:390)
@classmethod from_definition(cls, definition, *, agent_registry=None, node_factories=None, checkpoint=None, checkpoint_retention=None,
    checkpoint_history=None, checkpoint_include_responses=None, durable=None, checkpoint_store=None, durable_store=None, flow_id=None)  # :550-564
    → flow = cls(name=..., definition=..., agent_registry=..., checkpoint=..., ..., flow_id=flow_id) (:661-680) → so PlanFlow.from_definition returns a PlanFlow
async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult                     # :1226
    checkpointer, listener = await self._ensure_checkpointer(ctx) (:1290) … try: return await self._run_flow_scheduler(ctx, on_complete=on_complete) (:1300)
    finally: … await checkpointer.aclose() (:1309)   ← lease released HERE, after the scheduler returns
async def _ensure_checkpointer(self, ctx) -> Tuple[Optional[FlowCheckpointer], Optional[listener]]  # :1322 — acquires lease (:1382-1383)
async def _run_flow_scheduler(self, ctx: FlowContext, *, on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = ()) -> FlowResult  # :1680
    required = bool(self._checkpoint_required and checkpointer is not None)   # :1709 — required-mode awaited per-node barrier

# packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py
class FlowCheckpointer: async def checkpoint(self, ctx: FlowContext, *, status: str = "running") -> FlowCheckpoint  # :268 — awaited, raises CheckpointPersistenceError
                        lease_lost -> bool (:139); raise_if_lease_lost() (:143); async def release_lease() (:435); async def aclose() (:458)

# packages/ai-parrot/src/parrot/bots/flows/plan/compile.py:38 / :100-106
def to_flow_definition(plan: ExecutionPlan) -> FlowDefinition   # FlowMetadata(checkpoint=plan.metadata.checkpoint, durable=plan.metadata.durable, ...)
# packages/ai-parrot/src/parrot/bots/flows/plan/node.py:1072
def make_tool_node_factory(tool_manager, working_memory, *, permission_context=None, plan_run_id=None, step_mapping=None)
# packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py:190-212 — the current from_definition call to replace (in TASK-3599)
```

### Does NOT Exist
- ~~`AgentsFlow.from_definition(checkpoint_required=..., checkpoint_shared_data=...)`~~ — constructor-only; force them in `PlanFlow.__init__`.
- ~~`AgentsFlow.resume(node_factories=...)`~~ — resume takes `flow_factory=` (`flow.py:1429`).
- ~~a hook between "scheduler done" and "lease released"~~ — none exists; that is why `_run_flow_scheduler` is overridden (it runs inside `run_flow`'s `try`, before `aclose()`).
- ~~`FlowContext.shared_data` auto-populated from the checkpoint for a supplied `seed_context`~~ — `flow.py:1645-1652` only calls `mark_completed`; TASK-3600 must set `shared_data[PLAN_RUN_SHARED_KEY]` explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_lifecycle.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow",
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow.from_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/flow/flow.py#AgentsFlow._run_flow_scheduler",
    "sym:packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/checkpointer.py#FlowCheckpointer.checkpoint",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/compile.py#to_flow_definition",
    "sym:packages/ai-parrot/src/parrot/bots/flows/plan/node.py#make_tool_node_factory"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `PlanFlow.__init__(name, **kwargs)`: **only** when `kwargs.get("checkpoint")` is truthy,
  set `checkpoint_required=True`, `checkpoint_shared_data=plan_run_projector`,
  `checkpoint_include_responses=False`. With `checkpoint=False` the flow behaves exactly like
  `AgentsFlow` (fresh execution without checkpointing, §2 "connection outage causes fresh
  execution").
- `plan_run_projector(ctx)` returns `{PLAN_RUN_SHARED_KEY: ctx.shared_data[PLAN_RUN_SHARED_KEY]}`
  when present, else `{}` — never the whole `shared_data` (spec §7 "Snapshotting a live
  shared-data mapping can persist unwanted objects").
- `_run_flow_scheduler` override: if `self._checkpointer` is set, `await checkpointer.checkpoint(ctx, status="running")`
  **before** delegating (initial checkpoint), then `result = await super()._run_flow_scheduler(...)`,
  then `await checkpointer.checkpoint(ctx, status="completed" if <no ctx.errors> else "failed")`
  before returning. A `CheckpointPersistenceError` from the initial write propagates
  (TASK-3599 maps it to `checkpoint_write_failed`). On `asyncio.CancelledError` do not
  write; re-raise (the base `run_flow` `finally` releases the lease).
- The scheduler's own per-node required barrier (`flow.py:1709`) stays; you add only the
  start/terminal records.
- `build_plan_flow` calls `ensure_tool_node_registered(PlanToolNode)`,
  `register_plan_checkpoint_types()`, `to_flow_definition(plan)`, then
  `PlanFlow.from_definition(definition, agent_registry=..., node_factories={"tool": factory},
  checkpoint=<enabled>, durable=<durable_store is not None>, checkpoint_store=store,
  durable_store=durable_store, flow_id=run.run_id)`. `enabled = store is not None and plan.metadata.checkpoint`.
- Regression tests must verify `_checkpoint_required` and `_checkpoint_shared_data_arg` on a
  fresh flow AND on one produced by `PlanFlow.resume(...)` (the factory route).

### References in Codebase
- `tests/flows/checkpoint/test_required_persistence.py` — how required mode is tested (`FakeCheckpointStore`, failing store via `AsyncMock`).
- `tests/flows/checkpoint/test_required_barrier.py` — scheduler barrier expectations.
- `_recovery_fakes.SerializingFakeCheckpointStore` (TASK-3593) — the store to use here.

---

## Implementation Blueprint

### Steps (in order)
1. Write `plan_run_projector` + `PlanFlow.__init__` — *why*: the constructor is the only place the two missing `from_definition` options can be forced.
2. Override `_run_flow_scheduler` — *why*: it is the one seam inside the lease lifetime (`run_flow:1300` vs `aclose:1309`).
3. Write `build_plan_flow` — *why*: TASK-3599 and TASK-3600 both need one compile-and-bind function so fresh and resumed flows share the factory contract (AC9).
4. Tests with `SerializingFakeCheckpointStore` — *why*: the first checkpoint must contain typed refs = none yet, `plan_run` envelope, and `responses is None`.

### `packages/ai-parrot/src/parrot/tools/execution_plan/checkpoint.py` (CREATE)
```python
"""PlanFlow — plan-specific checkpoint policy around the existing AgentsFlow scheduler (FEAT-585 M4)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, Tuple

from parrot.bots.flows.core.checkpoint import CheckpointStore
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.types import FlowResult
from parrot.bots.flows.flow.flow import AgentsFlow
from parrot.bots.flows.plan import ExecutionPlan, PlanToolNode, ensure_tool_node_registered, make_tool_node_factory, to_flow_definition
from parrot.registry.registry import AgentRegistry

from .models import PLAN_RUN_SHARED_KEY, PlanRunMetadata
from .runs import register_plan_checkpoint_types

__all__ = ("PlanFlow", "build_plan_flow", "plan_run_projector")
_logger = logging.getLogger(__name__)


def plan_run_projector(ctx: FlowContext) -> Dict[str, Any]:
    """Project ONLY the validated ``plan_run`` envelope into the checkpoint's shared_data."""
    envelope = ctx.shared_data.get(PLAN_RUN_SHARED_KEY)
    return {PLAN_RUN_SHARED_KEY: envelope} if isinstance(envelope, dict) else {}


class PlanFlow(AgentsFlow):
    """Apply plan-specific checkpoint policy around the existing scheduler."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        """Force required persistence and plan-only projection when checkpointing is enabled."""
        if kwargs.get("checkpoint"):
            kwargs["checkpoint_required"] = True
            kwargs["checkpoint_shared_data"] = plan_run_projector
            kwargs["checkpoint_include_responses"] = False
        super().__init__(name, **kwargs)

    async def _run_flow_scheduler(
        self, ctx: FlowContext, *,
        on_complete: Tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
    ) -> FlowResult:
        """Checkpoint start/terminal state inside the lease lifetime; delegate scheduling."""
        checkpointer = self._checkpointer
        if checkpointer is not None:
            await checkpointer.checkpoint(ctx, status="running")   # initial record BEFORE any dispatch
        try:
            result = await super()._run_flow_scheduler(ctx, on_complete=on_complete)
        except asyncio.CancelledError:
            raise                                                   # run_flow's finally releases the lease
        if checkpointer is not None:
            # FILL IN: terminal status — "failed" when ctx.errors is non-empty, else "completed"; awaited
            # (propagate CheckpointPersistenceError) — bounded by AC6 "no falsely durable terminal success".
            raise NotImplementedError
        return result


def build_plan_flow(plan: ExecutionPlan, *, run: PlanRunMetadata, tool_manager: Any, working_memory: Any,
                    agent_registry: AgentRegistry, permission_context: Any, step_mapping: Mapping[str, str],
                    store: Optional[CheckpointStore], durable_store: Optional[CheckpointStore]) -> PlanFlow:
    """Compile with the existing factory, bind the run ID and checkpoint projection."""
    ensure_tool_node_registered(PlanToolNode)
    register_plan_checkpoint_types()
    definition = to_flow_definition(plan)
    factory = make_tool_node_factory(tool_manager, working_memory, permission_context=permission_context,
                                     plan_run_id=run.run_id, step_mapping=dict(step_mapping))
    enabled = store is not None and plan.metadata.checkpoint
    flow = PlanFlow.from_definition(definition, agent_registry=agent_registry, node_factories={"tool": factory},
                                    checkpoint=enabled, durable=enabled and durable_store is not None,
                                    checkpoint_store=store, durable_store=durable_store, flow_id=run.run_id)
    _logger.debug("built PlanFlow run_id=%s checkpoint=%s durable=%s", run.run_id, enabled, durable_store is not None)
    return flow
```
**Why this shape**: `from_definition` returns `cls(...)`, so `PlanFlow.from_definition` gives a
`PlanFlow` whose constructor already forced the two options `from_definition` cannot pass.
`flow_id=run.run_id` gives the flow the same id as the run (§2 "give the same ID to its
AgentsFlow"). Keep the file under ~150 lines: TASK-3595 appends the continuation classes.

### `packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_lifecycle.py` (CREATE)
```python
"""FEAT-585 M4 — PlanFlow barrier options, start/terminal records, no raw responses."""
from __future__ import annotations

import pytest

from parrot.tools.execution_plan.checkpoint import PlanFlow, build_plan_flow, plan_run_projector
from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY
from ._recovery_fakes import CountingToolManager, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio


def test_fresh_flow_forces_required_and_projector(): ...          # PlanFlow(name, checkpoint=True): _checkpoint_required is True,
                                                                  # _checkpoint_shared_data_arg is plan_run_projector, include_responses False
def test_disabled_flow_is_plain(): ...                            # checkpoint=False → _checkpoint_required False, no projector
async def test_resumed_flow_keeps_options(): ...                  # run A→B with store; PlanFlow.resume(flow_id, agent_registry=..., store=store,
                                                                  # flow_factory=lambda d: build_plan_flow(...)) → same two attributes hold
async def test_initial_and_terminal_records(): ...                # store.put_calls >= 2; first checkpoint status running with 0 results and the
                                                                  # plan_run envelope in shared_data; last status completed; responses is None
async def test_projector_excludes_other_shared_data(): ...        # ctx.shared_data has extra keys → snapshot shared_data has only plan_run
async def test_initial_write_failure_propagates_before_dispatch(): ...  # store.failures=[1] → CheckpointPersistenceError; tool dispatch_counts empty
async def test_cancellation_releases_lease(): ...                 # cancel mid-run → store._leases empty afterwards
```
**Why**: §2 "Regression tests must verify those options on both fresh and resumed flows";
AC6 "Required checkpoint failures … prevent further dispatch".

### FILL IN checklist
- [ ] `checkpoint.py::PlanFlow._run_flow_scheduler` — terminal status derivation + awaited write; AC6
- [ ] `test_checkpoint_lifecycle.py` — bodies (build `PlanRunMetadata` via a small helper; `ctx.shared_data[PLAN_RUN_SHARED_KEY] = metadata.model_dump(mode="json")` before `run_flow`)

---

## Acceptance Criteria

- [ ] AC-1 — `PlanFlow(name, checkpoint=True)` has `_checkpoint_required is True`, `_checkpoint_shared_data_arg is plan_run_projector`, `_checkpoint_include_responses is False`; with `checkpoint=False` none of those are set.
- [ ] AC-2 — A flow produced by `PlanFlow.resume(..., flow_factory=build_plan_flow-based)` satisfies AC-1 (AC9).
- [ ] AC-3 — A run over `SerializingFakeCheckpointStore` writes an initial `running` checkpoint before any tool dispatch and a terminal one whose `context.responses is None` and whose `shared_data` has only `plan_run`.
- [ ] AC-4 — A failing initial write raises `CheckpointPersistenceError` and dispatches zero tools (AC6).
- [ ] AC-5 — Cancelling the run releases the lease.
- [ ] `ruff check` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/tools/execution_plan/test_checkpoint_lifecycle.py -q`
- `pytest packages/ai-parrot/tests/flows/checkpoint/test_required_persistence.py -q`
- `pytest packages/ai-parrot/tests/flows/checkpoint/test_required_barrier.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Recovery capabilities" (PlanFlow paragraph), §3 Module 4, §7 Known Risks (first two bullets).
2. Verify anchors (`flow.py:296-320`, `:550-564`, `:661-680`, `:1290-1310`, `:1680`, `:1709`), implement, run Validation Commands.
3. Move this file to `sdd/tasks/completed/`, update the per-spec index, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
