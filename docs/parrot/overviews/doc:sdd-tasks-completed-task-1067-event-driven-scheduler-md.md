---
type: Wiki Overview
title: 'TASK-1067: Implement event-driven scheduler — `run_flow`, `_materialize_nodes`,
  completion queue, `on_complete` hooks, `FlowResult` aggregation'
id: doc:sdd-tasks-completed-task-1067-event-driven-scheduler-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Spec §3 Module 6 — the heart of the new executor. Replaces the
  legacy polling loop (`await asyncio.sleep(0.1)` + full-graph scans) with an event-driven
  design:'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
---

# TASK-1067: Implement event-driven scheduler — `run_flow`, `_materialize_nodes`, completion queue, `on_complete` hooks, `FlowResult` aggregation

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1060, TASK-1061, TASK-1065, TASK-1066
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 6 — the heart of the new executor. Replaces the legacy polling loop (`await asyncio.sleep(0.1)` + full-graph scans) with an event-driven design:

- Single `asyncio.Queue[CompletionEvent]` consumer.
- Per-node `asyncio.create_task` dispatch (NOT `asyncio.gather` over a batch — fast nodes do not wait for slow siblings).
- Incremental counters (no `_get_ready_agents` / `_is_workflow_complete` / `_has_active_agents` full scans).
- Fresh node set re-materialized inside every `run_flow()` call so concurrent execution of the same `AgentsFlow` instance is safe (B-lite — spec §1 Goals).
- `on_complete=[...]` hooks awaited after termination; exceptions caught + logged but do not fail the flow.
- `FlowResult.output` is scalar when one leaf, dict when many.

The scheduler manages FSM lifecycle externally: `node.fsm.start()` before dispatch, `.succeed()` / `.fail()` on completion. Nodes never call FSM transitions inside their own `execute()`.

---

## Scope

Replace `AgentsFlow.run_flow`'s placeholder `NotImplementedError` (from TASK-1065) with the full implementation in `parrot/bots/flows/flow.py`:

1. **`_materialize_nodes()` private helper**:
   - Re-instantiates `self._nodes: dict[str, Node]` from `self._definition` (a `FlowDefinition`) on every call.
   - For each `NodeDefinition`, look up `NODE_REGISTRY[node_def.node_type]`, construct an instance with the definition's fields.
   - Agent already resolved at `from_definition()` time (TASK-1068) and stored on `self._resolved_agents` (or similar) — pass it to `AgentNode` instances.
   - Build a dependency adjacency map.

2. **Scheduler state** (local to `run_flow` — not instance attributes, so concurrent runs are isolated):
   ```python
   nodes: dict[str, Node]                               # from _materialize_nodes()
   attempts: dict[str, int]                             # retry counter per node
   tasks: dict[str, asyncio.Task]                       # in-flight tasks
   completion_queue: asyncio.Queue[CompletionEvent]
   ready: set[str]                                      # nodes ready to dispatch
   completed: set[str]
   failed: set[str]
   results: dict[str, Any]                              # node_id → execute() return value
   errors: dict[str, BaseException]
   active_count: int                                    # incrementally maintained
   ```

3. **`_run_node(node, deps_dict)` task wrapper**:
   - Calls `node.fsm.start()`.
   - Awaits `node.execute(ctx, deps_dict, **kwargs)` inside a try/except.
   - On success: `node.fsm.succeed()`, push `CompletionEvent(node_id, result=...)` to queue.
   - On exception: `node.fsm.fail()`, push `CompletionEvent(node_id, error=exc)` to queue.
   - Exceptions never escape this wrapper.

4. **Scheduler main loop** (inside `run_flow`):
   - Initialize: find entry nodes (zero dependencies), put them in `ready`, spawn tasks via `asyncio.create_task(_run_node(node, {}))`, increment `active_count`.
   - Loop: `event = await completion_queue.get()`.
   - On event:
     - Update `results` / `errors`, decrement `active_count`, move `node_id` to `completed` / `failed`.
     - Apply retry logic: if `error is not None` and `attempts[node_id] < node.max_retries` (verify field name / default), increment `attempts`, re-dispatch the node.
     - Evaluate outgoing transitions: for each edge `node_id → downstream`, use `CELPredicateEvaluator` to check the predicate against `results[node_id]`. If predicate passes AND all `downstream.dependencies` are in `completed`, spawn the downstream task.
     - Skip-on-failure: if a node failed and a downstream's predicate is "success-only", mark the downstream as `skipped`.
   - Termination: `active_count == 0 and completion_queue.empty()`.

5. **`on_complete` hooks**:
   - After main loop, iterate `on_complete` in declaration order. Each is `await`ed inside a try/except — exceptions logged at WARNING level but do NOT change `FlowResult.status`.

6. **`FlowResult` aggregation** (using `build_node_metadata`, `determine_run_status` from `core.result`):
   - `nodes`: list of `NodeExecutionInfo` per executed node.
   - `responses`: `dict[node_id → response]` from `results`.
   - `errors`: `dict[node_id → str(error)]` from `errors`.
   - `status`: `determine_run_status(len(completed), len(failed))`.
   - `output`: scalar from the single leaf node's result, or `dict[leaf_id → result]` when multiple leaves. **A leaf** = a node with no outgoing edges in `self._definition.edges` (or no `successors` on the materialized node).

7. **Logging**: log at INFO when entry nodes dispatch, when a node completes, when a node fails. Log at DEBUG for queue events.

**NOT in scope**:
- `from_definition()` — TASK-1068.
- Cycle detection (already at `FlowDefinition` validator — TASK-1064).
- HITL pause/resume (future spec — but the scheduler design must NOT preclude it; specifically, the scheduler holds NO `asyncio.gather` on the task set, so a node that takes long does not block other nodes' tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow.py` | MODIFY | Replace `run_flow` placeholder; add `_materialize_nodes`, `_run_node`, scheduler internals |
| `packages/ai-parrot/tests/bots/flows/test_scheduler.py` | CREATE | Unit tests for scheduler edge cases (see §Test Specification) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (additions to flow.py)

```python
import asyncio
from typing import Awaitable, Callable, Optional

from .core.result import (
    FlowResult,                                          # core/result.py:273
    NodeResult,                                          # core/result.py:39
    NodeExecutionInfo,                                   # core/result.py:190
    build_node_metadata,                                 # core/result.py:527
    determine_run_status,                                # core/result.py:162
)
from .core.types import FlowStatus                      # core/types.py:38
from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator
# (verify exact import path of CELPredicateEvaluator before use.)
```

### Existing Signatures (consume — do not modify)

```python
# parrot/bots/flows/core/result.py
def determine_run_status(success_count: int, failure_count: int) -> FlowStatus: ...  # line 162

def build_node_metadata(...) -> NodeExecutionInfo: ...  # line 527
# Read the function signature before assuming param names.

class FlowResult(BaseModel):                            # line 273
    # Read fields: output, nodes, responses, errors, status, summary?
    # Confirm before constructing.

class NodeResult(BaseModel):                            # line 39
class NodeExecutionInfo(BaseModel):                     # line 190

# parrot/bots/flow/cel_evaluator.py
class CELPredicateEvaluator:                            # confirm exact line
    def __init__(self, ...): ...
    def evaluate(self, predicate: str, context: dict) -> bool: ...
    # OR similar — verify the actual method name and signature.

# After TASK-1060:
class Node(BaseModel, ABC):                             # core/node.py:34 (modified)
    async def run_pre_actions(self, prompt="", **ctx) -> None: ...
    async def run_post_actions(self, result=None, **ctx) -> None: ...

class AgentNode(Node):                                  # core/node.py:144 (modified)
    fsm: Optional[AgentTaskMachine]
    async def execute(self, ctx, deps, **kwargs) -> Any: ...
    # Has `max_retries`? — verify; if not, scheduler holds the counter in its own dict and reads
    # `self.max_retries` from the registered Node subclass field. Default 0.
```

### Does NOT Exist (yet)

- ~~`AgentsFlow._materialize_nodes`~~ — added by this task.
- ~~`AgentsFlow._run_node`~~ — added by this task.
- ~~`AgentsFlow._aggregate_result`~~ — added by this task.
- ~~`asyncio.gather` anywhere in `run_flow`~~ — explicitly forbidden by acceptance criterion.
- ~~`Node.max_retries`~~ field — only AgentNode/its subclasses may have this; verify (and add as optional field to the relevant Node subclass if missing — but coordinate with TASK-1060 if so).

---

## Implementation Notes

### Pattern to Follow

```python
async def run_flow(
    self,
    ctx: FlowContext | None = None,
    *,
    on_complete: tuple[Callable[[FlowContext, FlowResult], Awaitable[None]], ...] = (),
) -> FlowResult:
    ctx = ctx or FlowContext(agent_registry=self._agent_registry)
    nodes = self._materialize_nodes()           # fresh per call
    edges = self._definition.edges if self._definition else []

    completion_queue: asyncio.Queue[CompletionEvent] = asyncio.Queue()
    attempts: dict[str, int] = {nid: 0 for nid in nodes}
    tasks: dict[str, asyncio.Task] = {}
    completed: set[str] = set()
    failed: set[str] = set()
    results: dict[str, Any] = {}
    errors: dict[str, BaseException] = {}
    active_count = 0

    cel = CELPredicateEvaluator()  # one per run

    def _deps_for(node_id: str) -> dict[str, Any]:
        return {dep: results[dep] for dep in nodes[node_id].dependencies if dep in results}

    def _spawn(node_id: str) -> None:
        nonlocal active_count
        node = nodes[node_id]
        deps = _deps_for(node_id)
        node.fsm.start() if str(node.fsm.current_state.id) == "ready" else node.fsm.schedule()
        tasks[node_id] = asyncio.create_task(
            self._run_node(node, ctx, deps, completion_queue)
        )
        active_count += 1

    # Initial dispatch — entry nodes (no dependencies)
    for nid, node in nodes.items():
        if not node.dependencies:
            _spawn(nid)

    # Main loop
    while active_count > 0 or not completion_queue.empty():
        event = await completion_queue.get()
        active_count -= 1
        nid = event.node_id

        if event.error is not None:
            # Retry?
            max_r = getattr(nodes[nid], "max_retries", 0)
            if attempts[nid] < max_r:
                attempts[nid] += 1
                self.logger.info(f"Retrying {nid} (attempt {attempts[nid]}/{max_r})")
                _spawn(nid)
                continue
            errors[nid] = event.error
            failed.add(nid)
            self.logger.warning(f"Node {nid} failed: {event.error}")
        else:
            results[nid] = event.result
            completed.add(nid)

        # Evaluate outgoing transitions
        for edge in edges:
            if edge.source != nid:
                continue
            tgt = edge.target
            if tgt in completed or tgt in failed or tgt in tasks:
                continue
            if not _predicate_passes(cel, edge, results.get(nid)):
                continue
            if all(d in completed for d in nodes[tgt].dependencies):
                _spawn(tgt)

    # on_complete hooks
    aggregated = self._aggregate_result(nodes, results, errors, completed, failed)
    for hook in on_complete:
        try:
            await hook(ctx, aggregated)
        except Exception as e:
            self.logger.warning(f"on_complete hook raised: {e}")
    return aggregated


async def _run_node(self, node, ctx, deps, queue: asyncio.Queue) -> None:
    try:
        result = await node.execute(ctx, deps)
        node.fsm.succeed()
        await queue.put(CompletionEvent(node_id=node.node_id, result=result))
    except BaseException as e:
        try:
            node.fsm.fail()
        except Exception:
            pass
        await queue.put(CompletionEvent(node_id=node.node_id, error=e))


def _aggregate_result(self, nodes, results, errors, completed, failed) -> FlowResult:
    # Build NodeExecutionInfo per node via build_node_metadata
    node_infos = [build_node_metadata(node_id=nid, ...) for nid in (completed | failed)]
    # Identify leaves: nodes with no outgoing edge whose target lies in `nodes`.
    edges = self._definition.edges if self._definition else []
    has_successor = {e.source for e in edges}
    leaves = [nid for nid in nodes if nid not in has_successor]
    if len(leaves) == 1 and leaves[0] in results:
        output = results[leaves[0]]
    else:
        output = {nid: results[nid] for nid in leaves if nid in results}
    return FlowResult(
        output=output,
        nodes=node_infos,
        responses=results,
        errors={k: str(v) for k, v in errors.items()},
        status=determine_run_status(len(completed), len(failed)),
        # add other fields per FlowResult's actual constructor
    )
```

### Key Constraints

- **FORBIDDEN**: `asyncio.gather` over the per-batch task set. `grep` check is part of acceptance criteria.
- **FORBIDDEN**: `await asyncio.sleep(...)` inside the main loop (only the queue `.get()` may block).
- **FORBIDDEN**: full-graph scans (`for nid, node in nodes.items(): if ...check-state...`). Use the incremental `completed` / `failed` sets and `active_count` counter.
- FSM transitions must run BEFORE dispatch (`node.fsm.start()`) and AFTER execute (`node.fsm.succeed()` / `.fail()`) — managed by `_run_node`, NOT by Node.execute itself.
- FSM state names ("idle", "ready", "running", "completed", "failed") are AgentTaskMachine's internal states; verify by reading `core/fsm.py:40`. The transitions `.schedule()` → ready, `.start()` → running, `.succeed()` → completed, `.fail()` → failed are the public interface.
- `_materialize_nodes()` MUST construct new Node instances every call — concurrent run safety depends on this.
- CEL predicate evaluation: read `parrot/bots/flow/cel_evaluator.py` to confirm the exact method signature. If a node's outgoing edge has no predicate, the transition is always taken.
- `max_retries` field on Node subclasses: confirm whether AgentNode (after TASK-1060) has it. If not, default to 0 and document; do NOT add it here (coordinate retroactively with TASK-1060 if needed).

### References in Codebase

- `parrot/bots/flow/fsm.py:686–870` — legacy `run_flow` (polling). DO NOT copy structure; only consult for understanding state transitions and final aggregation shape.
- `parrot/bots/flow/fsm.py:1054` — legacy `asyncio.gather` (the anti-pattern being replaced).
- `parrot/bots/flow/cel_evaluator.py` — `CELPredicateEvaluator` class.
- `parrot/bots/flows/core/result.py:162, :273, :527` — result aggregation primitives.
- `parrot/bots/flows/crew/crew.py:567–650, 1102–1213` — FSM transition call patterns (mirror in `_run_node`).

---

## Acceptance Criteria

- [ ] `run_flow` no longer raises `NotImplementedError`.
- [ ] `_materialize_nodes` exists and is called inside every `run_flow()` invocation (verify via test that two concurrent `run_flow()` calls on the same `AgentsFlow` produce independent FSM state).
- [ ] No `asyncio.gather` in `flow.py` — `grep -n "asyncio.gather" packages/ai-parrot/src/parrot/bots/flows/flow.py` returns nothing.
- [ ] No `await asyncio.sleep` inside the main loop — the only blocking point is `completion_queue.get()`.
- [ ] No full-graph scans — readiness driven entirely by the completion event handler.
- [ ] `node.fsm.start()` / `.succeed()` / `.fail()` are called by `_run_node`, not by `Node.execute`.
- [ ] `FlowResult.output` is a scalar when exactly one leaf produces a result; a dict otherwise.
- [ ] `on_complete=[hook1, hook2]` runs both hooks in order, awaiting each.
- [ ] A hook raising an exception does NOT change `FlowResult.status` (caught + logged).
- [ ] A linear A→B→C flow with mocked agents runs end-to-end (integration test in TASK-1070 will cover this; basic smoke test here).
- [ ] Concurrent `await asyncio.gather(flow.run_flow(), flow.run_flow())` does NOT corrupt FSM state.
- [ ] Retry: a node with `max_retries=2` failing once then succeeding produces success status; assertion verifies one retry happened.
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/bots/flows/test_scheduler.py -v`.
- [ ] No linting errors.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_scheduler.py
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.bots.flows.flow import AgentsFlow, register_node, NODE_REGISTRY, CompletionEvent
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.core.context import FlowContext


# Build a minimal in-memory FlowDefinition for testing — adjust to actual model fields.
def make_linear_def():
    from parrot.bots.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition, NodePosition
    return FlowDefinition(
        name="linear",
        nodes=[
            NodeDefinition(node_id="a", node_type="agent", position=NodePosition(x=0, y=0), agent_ref="agent_a"),
            NodeDefinition(node_id="b", node_type="agent", position=NodePosition(x=1, y=0), agent_ref="agent_b"),
        ],
        edges=[EdgeDefinition(source="a", target="b")],
    )


class TestSchedulerBasics:
    async def test_run_flow_no_asyncio_gather(self):
        import inspect
        from parrot.bots.flows import flow
        src = inspect.getsource(flow)
        assert "asyncio.gather" not in src

    async def test_run_flow_linear(self, linear_flow_with_mocked_agents):
        result = await linear_flow_with_mocked_agents.run_flow()
        assert result.status == "success"
        # output is scalar for a single-leaf linear flow
        assert not isinstance(result.output, dict)

    async def test_run_flow_concurrent_same_instance(self, linear_flow_with_mocked_agents):
        """Concurrent run_flow calls do not share FSM state."""
        r1, r2 = await asyncio.gather(
            linear_flow_with_mocked_agents.run_flow(),
            linear_flow_with_mocked_agents.run_flow(),
        )
        assert r1.status == "success"
        assert r2.status == "success"


class TestOnCompleteHooks:
    async def test_hook_fires(self, linear_flow_with_mocked_agents):
        hook = AsyncMock()
        await linear_flow_with_mocked_agents.run_flow(on_complete=[hook])
        hook.assert_awaited_once()

    async def test_hook_exception_does_not_fail_flow(self, linear_flow_with_mocked_agents):
        async def broken_hook(ctx, result): raise RuntimeError("boom")
        result = await linear_flow_with_mocked_agents.run_flow(on_complete=[broken_hook])
        assert result.status == "success"


class TestOutputSemantics:
    async def test_scalar_single_leaf(self, linear_flow_with_mocked_agents):
        result = await linear_flow_with_mocked_agents.run_flow()
        assert not isinstance(result.output, dict)

    async def test_dict_multiple_leaves(self, fan_out_flow):
        result = await fan_out_flow.run_flow()
        assert isinstance(result.output, dict)
        assert len(result.output) == 2  # two leaves


# Fixtures wire mocked agents + materialize a flow.
# (Implementation details depend on FlowDefinition / AgentRegistry stub.)
```

---

## Agent Instructions

1. Confirm TASK-1060, TASK-1061, TASK-1065, TASK-1066 are in `sdd/tasks/completed/`.
2. Read the legacy `parrot/bots/flow/fsm.py:686–870` carefully to understand state transitions and aggregation shape. **DO NOT** copy the polling/scan structure — extract only the semantics.
3. Read `parrot/bots/flow/cel_evaluator.py` end-to-end; confirm `CELPredicateEvaluator` method names.
4. Read `parrot/bots/flows/core/result.py:162, :273, :527` to confirm `FlowResult` constructor + helper functions.
5. Read `parrot/bots/flows/crew/crew.py:567–650` to mirror FSM transition style.
6. Implement `_materialize_nodes`, `_run_node`, `_aggregate_result`, and the new `run_flow` body.
7. Run `pytest packages/ai-parrot/tests/bots/flows/test_scheduler.py -v` until all green.
8. Run `grep -n "asyncio.gather\|asyncio.sleep" packages/ai-parrot/src/parrot/bots/flows/flow.py` — both should return zero matches in `run_flow`.
9. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: Full event-driven scheduler implemented — asyncio.Queue[CompletionEvent], asyncio.create_task per node, no asyncio.gather. _materialize_nodes creates fresh Node copies (model_copy with new FSM) for concurrent safety. _aggregate_result unwraps AgentNode's execution-metadata dict to extract scalar output for single-leaf flows. FlowStatus enum coercion from determine_run_status string literal. 14/14 tests pass including concurrent safety test.
**Deviations from spec**: _materialize_nodes in programmatic mode uses model_copy(update={fsm:...}) rather than re-materializing from FlowDefinition (no definition bound). FSM transitions called schedule()+start() by _run_node (not just start()), because FSM begins in idle state not ready.
