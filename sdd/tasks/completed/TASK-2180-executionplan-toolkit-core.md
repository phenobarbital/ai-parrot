# TASK-2180: ExecutionPlanToolkit core — constructor, run registry, executor path

**Feature**: FEAT-419 — ExecutionPlanToolkit — deterministic tool-call DAGs for a BasicAgent
**Spec**: `sdd/specs/execution-plan-tool.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2179
**Assigned-to**: unassigned

---

## Context

The toolkit is the agent-facing wrapper around the frozen `plan/` module.
This task builds its core: the `AbstractToolkit` subclass with constructor
dependency injection, the bounded run registry, the soft-timeout execution
path over `AgentsFlow`, and the two read-only tools (`plan_status`,
`plan_artifacts`). The plan-acquisition front (`plan_execute`/
`plan_validate`) is TASK-2184. Implements spec §3 Module 2.

---

## Scope

- Implement `parrot/tools/execution_plan/models.py`: `RunRecord`,
  `RunningSummary` (Pydantic v2, `extra="forbid"`) per spec §2 Data Models.
- Implement `parrot/tools/execution_plan/toolkit.py`:
  `ExecutionPlanToolkit(AbstractToolkit)` with the full constructor
  signature from spec §2 New Public Interfaces (`tool_manager`,
  `working_memory`, `planner_llm`, `plans_dir`, `allowed_tools`,
  `soft_timeout=60.0`, `permission_context`, `on_node_event`,
  `max_completed_runs=50`). Store `planner_llm`/`plans_dir` raw for
  TASK-2183/2181 to consume.
- Implement the internal executor path `_run_plan(plan: ExecutionPlan)`:
  `ensure_tool_node_registered(PlanToolNode)` (lazily, first call) →
  `to_flow_definition(plan)` → `AgentsFlow.from_definition(defn,
  agent_registry=<empty registry>, node_factories={"tool":
  make_tool_node_factory(...)})` → attach `on_node_event` listener if set →
  `run_flow(ctx)` as an `asyncio.Task` registered under a fresh `run_id` →
  await up to `soft_timeout` → full `ExecutionManifest` (via
  `build_manifest`) or `RunningSummary`. Timeout must NOT cancel the task.
- Run registry: `{run_id: RunRecord}` shared toolkit state; completed/failed
  records evicted oldest-first beyond `max_completed_runs`; in-flight runs
  never evicted.
- Implement tools `plan_status(run_id)` and `plan_artifacts(run_id)` with
  `AbstractToolArgsSchema` args models; unknown `run_id` ⇒ tool error
  listing known run ids.
- Unit tests with a fake ToolManager and a real in-memory
  `WorkingMemoryToolkit`.

**NOT in scope**: `plan_execute`/`plan_validate` (TASK-2184), plan file
store (TASK-2181), planner (TASK-2183), catalog/allowlist (TASK-2182).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/execution_plan/__init__.py` | CREATE | Package exports |
| `packages/ai-parrot/src/parrot/tools/execution_plan/models.py` | CREATE | `RunRecord`, `RunningSummary`, args schemas for status/artifacts |
| `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` | CREATE | Toolkit class + run registry + executor path |
| `packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.plan import (        # exists after TASK-2179
    ExecutionManifest, ExecutionPlan, PlanToolNode,
    build_manifest, ensure_tool_node_registered, make_tool_node_factory,
    to_flow_definition,
)
from parrot.bots.flows.flow.flow import AgentsFlow
from ..abstract import AbstractToolkit  # parrot/tools/abstract.py — check the
#   actual toolkit base import path used by an existing toolkit (e.g.
#   working_memory) and mirror it exactly.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
#   from_definition REQUIRES agent_registry unconditionally (:494-498),
#   even for plans with zero agent nodes — pass an EMPTY registry. Find the
#   AgentRegistry type from from_definition's signature/imports and
#   instantiate it empty; do NOT pass None.
#   node_factories: dict[str, Callable[[NodeDefinition, set, set], Node]]
#   async def run_flow(ctx, *, on_complete=())            # :896
# sdd/artifacts/plan/node.py (→ parrot/bots/flows/plan/node.py)
#   make_tool_node_factory(...) — read its exact signature in the landed
#   module before wiring; it closes over tool_manager, working_memory,
#   permission_context.
#   build_manifest(...) — read exact signature there too.
# sdd/artifacts/plan/compile.py:141 — ensure_tool_node_registered(node_cls):
#   idempotent; raises ValueError if "tool" is registered to another class.
#   Call lazily (first _run_plan), NEVER at import time.
# packages/ai-parrot/src/parrot/tools/working_memory/tool.py:208
#   async def store_result(key, data, data_type="auto", ...) — used by the
#   node, not by the toolkit directly; the toolkit only holds the instance.
```

### Does NOT Exist
- ~~`plan_execute` / `plan_validate`~~ — TASK-2184; do not stub them as
  LLM-visible tools in this task.
- ~~`max_concurrent_runs`~~ — explicitly NOT a v1 knob; do not add it.
- ~~persistent run registry~~ — in-RAM only; lost on restart by design.
- ~~`AgentsFlow.from_definition(agent_registry=None)` tolerance~~ — it
  raises ValueError; an empty registry instance is mandatory.
- ~~cancelling the flow task on soft-timeout~~ — forbidden; the run
  continues in background.

---

## Implementation Notes

### Pattern to Follow
- Toolkit-with-shared-state: FEAT-207 (`SkillFileToolkit`,
  `WorkingMemoryToolkit`) — one instance initialized with dependencies; its
  tools share the run registry. Read one of those toolkits first and mirror
  structure, `_execute` conventions, and how tools/args schemas are declared.
- Live deps travel through the `node_factories` closure, never through
  `NodeDefinition.config`.

### Key Constraints
- Async-first; `asyncio.shield`-style wait (e.g. `asyncio.wait({task},
  timeout=soft_timeout)`) so timeout does not cancel.
- `run_id` generation: short, unique, no `Date.now`-style collision risk —
  `uuid4().hex[:8]` prefixed `run_`.
- Bounded responses: `plan_status` returns counts + manifest (when done);
  never payloads.
- `self.logger` at run start/finish/evict; Google-style docstrings — tool
  docstrings become LLM tool descriptions, keep them ≤3 lines.

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` — toolkit
  structure reference.
- `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py:494-570` —
  from_definition + node_factories consumption.

---

## Acceptance Criteria

- [ ] `ExecutionPlanToolkit` constructible with only
  `tool_manager` + `working_memory`; all other args optional with spec
  defaults
- [ ] Fast plan (programmatic `ExecutionPlan`, fake tools) →
  `_run_plan` returns a full `ExecutionManifest` within `soft_timeout`
- [ ] Slow plan → `RunningSummary` with `run_id`; the run completes in
  background; `plan_status(run_id)` then returns the final manifest
- [ ] Induced node failures → manifest `status="partial"` and the internal
  call does NOT raise
- [ ] Registry eviction: >50 completed runs → oldest evicted; in-flight
  never evicted; unknown `run_id` → tool error naming known ids
- [ ] `"tool"` registered in `NODE_REGISTRY` only after the first
  `_run_plan`, not at import
- [ ] Tests pass: `pytest packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py -v`
- [ ] `ruff check` clean on the new package

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/execution_plan/test_toolkit_core.py
import pytest

@pytest.fixture
def fake_tool_manager():
    """ToolManagerLike: get_tool/list_tools/execute_tool with a fast tool,
    a slow (asyncio.sleep) tool, and an error-raising tool; records calls."""

@pytest.fixture
def wm_toolkit():
    """Real WorkingMemoryToolkit over an in-memory catalog."""

class TestExecutorPath:
    async def test_manifest_within_soft_timeout(...): ...
    async def test_soft_timeout_returns_running_summary_and_completes(...): ...
    async def test_partial_failure_is_manifest_not_exception(...): ...
    async def test_payloads_only_in_working_memory(...):
        """Every ctx.results value is an ArtifactRef; bodies only in WM."""

class TestRunRegistry:
    async def test_eviction_bounds(...): ...
    async def test_unknown_run_id_tool_error(...): ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2179 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `make_tool_node_factory` and
   `build_manifest` signatures in the LANDED module before wiring
4. **Update status** in `sdd/tasks/index/execution-plan-tool.json` → `"in-progress"`
5. **Implement**, 6. **Verify**, 7. **Move this file** to
   `sdd/tasks/completed/`, 8. **Update index** → `"done"`, 9. **Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-07
**Notes**: Implemented `ExecutionPlanToolkit` core in
`packages/ai-parrot/src/parrot/tools/execution_plan/{__init__,models,
toolkit}.py`: constructor wiring (only `tool_manager`+`working_memory`
required, spec defaults for the rest), `RunRecord`/`RunningSummary`
(models.py, plain `BaseModel`, `extra="forbid"`; the live `asyncio.Task`
handle is kept OUT of the pydantic model in a separate toolkit-internal
dict per spec's "non-serialized runtime handle" note), `PlanStatusArgs`/
`PlanArtifactsArgs` (`AbstractToolArgsSchema` subclasses), the
`_run_plan()` executor path (`ensure_tool_node_registered` called lazily
on first run only, `to_flow_definition` → `AgentsFlow.from_definition`
with a lazily-created cached empty `AgentRegistry` + `node_factories=
{"tool": make_tool_node_factory(...)}` → background `asyncio.Task` →
`asyncio.wait(..., timeout=soft_timeout)` → full manifest or
`RunningSummary`, never cancelling the task), an internal
`on_node_event` progress listener updating `RunRecord.nodes_done`, and
bounded run-registry eviction (oldest completed/failed beyond
`max_completed_runs`, in-flight never evicted). `plan_status`/
`plan_artifacts` tools implemented per spec. 9/9 new unit tests pass
(`pytest packages/ai-parrot/tests/tools/execution_plan/ -v`); the
relocated TASK-2179 plan/ suite (62 tests) still passes alongside it.

**Found-and-fixed pre-existing bug (outside this task's declared file
list — flagged for explicit review):**
`packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`'s
`AgentsFlow._materialize_nodes()` definition-driven branch (used by
`from_definition()`) constructs `StartNode`/`EndNode` via
`cls(node_id=nid, dependencies=deps, successors=succs)` with no `fsm` —
those classes declare no `fsm` field (only `AgentNode` does) — yet
`_run_node()` unconditionally calls `node.fsm.schedule()/.start()/
.succeed()/.fail()` for every dispatched node, crashing on
`AttributeError: 'StartNode' object has no attribute 'fsm'` the instant
any `from_definition()`-built flow with start/end sentinel nodes is
actually `run_flow()`'d. Confirmed via `git grep` that NO existing test
or production caller in the repo (dev_loop/dev_flow's own
`from_definition()` usages use only "agent"/"decision" node types, never
"start"/"end") ever combined `from_definition()` + `run_flow()` with
start/end sentinels before — `plan/compile.py::to_flow_definition()`
(FEAT-419, frozen module, cannot be changed) is the first caller to do
so unconditionally. Fixed by mirroring the EXACT same
`model_copy(update={"fsm": AgentTaskMachine(...)})` patch the
programmatic (`add_node`) branch of `_materialize_nodes()` already
applies, just applied to the definition-driven "start"/"end"
construction too. Verified non-regressive: the full pre-existing
`pytest packages/ai-parrot/tests/bots/flows/` suite (301 tests) still
passes after the fix.

**Unrelated, pre-existing test-isolation hazard observed (not fixed,
out of scope):** running `packages/ai-parrot/tests/bots/flows/
test_storage_parity.py::...test_no_legacy_storage_import_in_test_
orchestrator` (which does `import tests.test_orchestrator_agent`) in the
same pytest session BEFORE this feature's tests causes
`sys.modules["parrot.bots.flows.core.node"]` (and the `flow.py` module
that already cached a reference to its `Node` class) to end up bound to
two different module/class objects, breaking `issubclass()` checks in
`register_node()` for any class imported before that point. Reproduced
and confirmed via `git blame`-free bisection that this is triggered by
`test_orchestrator_agent.py`'s import chain / `packages/ai-parrot/tests/
conftest.py`'s documented sys.modules stubbing (FEAT-268 note in that
conftest), not by anything in FEAT-419. Does not affect either this
task's or TASK-2179's own specified test commands (each scoped to its
own package); only appears when combining unrelated test directories in
one session. Flagging for a separate ticket rather than fixing here.

**Deviations from spec**: none
