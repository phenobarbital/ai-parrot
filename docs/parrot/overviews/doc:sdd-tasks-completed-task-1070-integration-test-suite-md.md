---
type: Wiki Overview
title: 'TASK-1070: Integration test suite for the new AgentsFlow (7 scenarios)'
id: doc:sdd-tasks-completed-task-1070-integration-test-suite-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Spec §3 Module 11 + §4 Integration Tests. Validates the new `AgentsFlow`
  executor end-to-end against the 7 scenarios enumerated in the spec. Replaces the
  deleted legacy integration tests (`test_fsm.py`, etc., removed by TASK-1069).
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
---

# TASK-1070: Integration test suite for the new AgentsFlow (7 scenarios)

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1067, TASK-1068, TASK-1069
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 11 + §4 Integration Tests. Validates the new `AgentsFlow` executor end-to-end against the 7 scenarios enumerated in the spec. Replaces the deleted legacy integration tests (`test_fsm.py`, etc., removed by TASK-1069).

The unit tests created by TASK-1060–1068 cover individual components. This task verifies the full pipeline: `FlowDefinition` → `from_definition()` → `run_flow()` → `FlowResult`, with mocked agents driving deterministic outputs.

---

## Scope

Create `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` with **all 7 integration scenarios** from Spec §4:

1. **`test_linear_flow`** — 3-node A→B→C with mocked agents; assert sequential execution, final `output` is scalar (single leaf).
2. **`test_branching_fan_out`** — A→{B, C}; assert B and C are scheduled as soon as A completes (NOT after a slow sibling); both run concurrently; verify via timing or per-node start timestamps.
3. **`test_branching_fan_in`** — {A, B}→C; assert C starts only after BOTH A and B complete; `DependencyResults` passed to C contains both upstream results.
4. **`test_conditional_routing_cel`** — A→B with a CEL predicate `result.value > 10`; assert routing fires on pass and short-circuits on fail (B remains unstarted when predicate is false).
5. **`test_retry_on_failure`** — A node with `max_retries=2` that fails once then succeeds; assert exactly one retry, final `FlowResult.status == "success"`.
6. **`test_decision_node_routing`** — `DecisionNode` returns `DecisionResult.final_decision = "approve"`; CEL predicate `result.final_decision == "approve"` on the outgoing edge routes to the approval branch; the rejection branch is skipped.
7. **`test_on_complete_hook_fires`** — `run_flow(on_complete=[record_hook])` — assert `record_hook` was awaited with `(ctx, result)` exactly once after termination.

Plus required fixtures in `packages/ai-parrot/tests/bots/flows/conftest.py` (or extend existing if it exists):

- `stub_agent_registry`: in-memory `AgentRegistry` (or stub matching its interface) populated with deterministic mock agents.
- `mock_agent_factory`: helper to create + register a mock agent with a scripted reply.
- `flow_context`: a `FlowContext` instance wired to the stub registry.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` | CREATE | The 7 integration scenarios |
| `packages/ai-parrot/tests/bots/flows/conftest.py` | CREATE or MODIFY | Shared fixtures |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

# After TASK-1060–1068:
from parrot.bots.flows.flow import (
    AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent,
    DecisionNode, InteractiveDecisionNode, SynthesisNode,
)
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
from parrot.bots.flows.core.context import FlowContext, AgentNotFoundError
from parrot.bots.flows.core.result import FlowResult, NodeExecutionInfo
from parrot.bots.flows.core.types import FlowStatus

from parrot.bots.flow.definition import (
    FlowDefinition, NodeDefinition, EdgeDefinition, NodePosition,
)
from parrot.bots.flow.decision_node import (
    DecisionResult, DecisionMode, DecisionNodeConfig,
)
```

### Existing Signatures (consume from prior tasks)

```python
# Verified by TASK-1067 + TASK-1068:
class AgentsFlow(PersistenceMixin):
    def __init__(self, name, *, definition=None, agent_registry=None, **kwargs): ...
    def add_node(self, node: Node): ...
    @classmethod
    def from_definition(cls, definition, *, agent_registry=None) -> "AgentsFlow": ...
    async def run_flow(self, ctx=None, *, on_complete=()) -> FlowResult: ...

# FlowResult shape — verified via core/result.py:273; confirm fields before constructing
# expectations:
class FlowResult(BaseModel):
    output: Any                              # scalar OR dict[node_id, Any]
    nodes: list[NodeExecutionInfo]
    responses: dict[str, Any]
    errors: dict[str, str]
    status: FlowStatus                       # "success" | "partial" | "failure" | ...
```

### Does NOT Exist (anti-hallucination)

- ~~`AgentsFlow.add_agent(...)`~~ — legacy API; gone after TASK-1069.
- ~~`AgentsFlow.task_flow(...)`~~ — legacy; gone.
- ~~`AgentsFlow.run_flow(use_old_polling=True)`~~ — no such kwarg.
- ~~`asyncio.gather` inside `run_flow`~~ — forbidden; the scheduler uses an `asyncio.Queue` consumer.

---

## Implementation Notes

### Pattern to Follow

```python
# packages/ai-parrot/tests/bots/flows/test_agents_flow.py
import asyncio
import time
import pytest
from unittest.mock import AsyncMock

from parrot.bots.flows.flow import AgentsFlow
from parrot.bots.flow.definition import (
    FlowDefinition, NodeDefinition, EdgeDefinition, NodePosition,
)


class MockAgent:
    def __init__(self, name, reply="ok", delay=0):
        self.name = name
        self.reply = reply
        self.delay = delay

    async def ask(self, question="", **kwargs):
        if self.delay:
            await asyncio.sleep(self.delay)
        return type("R", (), {"content": f"{self.name}:{self.reply}"})()


@pytest.fixture
def stub_registry():
    """Lightweight AgentRegistry stub matching the real getter method name (OQ-7)."""
    class Stub:
        def __init__(self): self.agents = {}
        def register(self, agent): self.agents[agent.name] = agent
        def get_agent(self, name):
            return self.agents.get(name)
    return Stub()


def _node(nid, ntype="agent", agent_ref=None):
    return NodeDefinition(
        node_id=nid, node_type=ntype, agent_ref=agent_ref,
        position=NodePosition(x=0, y=0),
    )


def _edge(s, t, condition=None):
    # Adjust EdgeDefinition kwargs per actual model fields
    return EdgeDefinition(source=s, target=t)


class TestLinearFlow:
    async def test_linear_flow(self, stub_registry):
        stub_registry.register(MockAgent("a"))
        stub_registry.register(MockAgent("b"))
        stub_registry.register(MockAgent("c"))
        d = FlowDefinition(
            name="linear",
            nodes=[
                _node("n1", agent_ref="a"),
                _node("n2", agent_ref="b"),
                _node("n3", agent_ref="c"),
            ],
            edges=[_edge("n1", "n2"), _edge("n2", "n3")],
        )
        flow = AgentsFlow.from_definition(d, agent_registry=stub_registry)
        result = await flow.run_flow()
        assert result.status == "success"
        # Single leaf → scalar output
        assert not isinstance(result.output, dict)


class TestBranchingFanOut:
    async def test_fan_out(self, stub_registry):
        """A→{B, C} — B and C should run concurrently."""
        stub_registry.register(MockAgent("a"))
        stub_registry.register(MockAgent("b", delay=0.5))
        stub_registry.register(MockAgent("c", delay=0.1))
        d = FlowDefinition(
            name="fan_out",
            nodes=[
                _node("a", agent_ref="a"),
                _node("b", agent_ref="b"),
                _node("c", agent_ref="c"),
            ],
            edges=[_edge("a", "b"), _edge("a", "c")],
        )
        flow = AgentsFlow.from_definition(d, agent_registry=stub_registry)
        start = time.perf_counter()
        result = await flow.run_flow()
        elapsed = time.perf_counter() - start
        # If B and C ran concurrently, total ≈ max(0.5, 0.1) = 0.5s plus a (small) A.
        # If they ran sequentially, total would be 0.5 + 0.1 = 0.6s.
        # Allow generous slack to avoid flakiness on slow CI.
        assert elapsed < 1.0
        assert isinstance(result.output, dict)
        assert set(result.output.keys()) == {"b", "c"}


class TestBranchingFanIn:
    async def test_fan_in(self, stub_registry):
        """{A, B}→C — C waits for both A and B."""
        ...  # construct and assert C's deps contain both upstream results


class TestConditionalRoutingCEL:
    async def test_cel_predicate_pass(self, stub_registry):
        """A→B with predicate `result.value > 10` (pass case)."""
        ...

    async def test_cel_predicate_fail(self, stub_registry):
        """A→B with predicate failing — B never runs."""
        ...


class TestRetry:
    async def test_retry_on_failure_then_success(self, stub_registry):
        """Node with max_retries=2: fails first, succeeds on retry. Status=success."""
        flaky_count = {"n": 0}
        class FlakyAgent:
            name = "flaky"
            async def ask(self, question="", **kwargs):
                flaky_count["n"] += 1
                if flaky_count["n"] == 1:
                    raise RuntimeError("transient")
                return type("R", (), {"content": "ok"})()
        stub_registry.register(FlakyAgent())
        # Build a 1-node flow with max_retries=2 (the field lives on the registered
        # AgentNode subclass; pass via NodeDefinition.metadata or a subclass field — verify).
        ...


class TestDecisionNodeRouting:
    async def test_decision_node_approve_branch(self, stub_registry):
        """DecisionNode → 'approve' branch when final_decision='approve'."""
        ...


class TestOnCompleteHook:
    async def test_hook_fires(self, stub_registry):
        stub_registry.register(MockAgent("a"))
        d = FlowDefinition(name="hook", nodes=[_node("n1", agent_ref="a")], edges=[])
        flow = AgentsFlow.from_definition(d, agent_registry=stub_registry)
        hook = AsyncMock()
        result = await flow.run_flow(on_complete=[hook])
        hook.assert_awaited_once()
        # Verify hook called with (ctx, result):
        args = hook.await_args.args
        assert len(args) == 2
        assert args[1] is result
```

### Key Constraints

- All tests are `async` — use `pytest-asyncio` (verify it's already in the project's test deps).
- Mock agents have deterministic outputs to keep assertions stable.
- For timing-sensitive tests (fan-out, fan-in), use generous slack to avoid CI flake.
- The CEL predicate format: verify exact syntax by reading existing usage in `parrot/bots/flow/cel_evaluator.py`.
- Some tests need `max_retries` configured on the materialized node. If `NodeDefinition` doesn't carry a `max_retries` field, set it via a `metadata` dict (verify NodeDefinition fields) or via a Node subclass override — coordinate with TASK-1067's retry implementation.
- DO NOT use `asyncio.gather` in tests to drive parallel `run_flow` calls — well, actually you CAN (it's not the executor's internal gather that's forbidden, only `asyncio.gather` INSIDE `run_flow`). For testing concurrent `AgentsFlow.run_flow()` calls, `asyncio.gather` at the test level is fine.

### References in Codebase

- Spec §4 Integration Tests — the 7 scenarios spelled out.
- TASK-1067 completed `test_scheduler.py` — for reference on mocking pattern.
- `parrot/bots/flow/cel_evaluator.py` — CEL syntax + usage examples.
- `packages/ai-parrot/tests/bots/flows/core/test_*.py` — pattern for unit tests against core types.

---

## Acceptance Criteria

- [ ] `tests/bots/flows/test_agents_flow.py` exists with all 7 named test cases above.
- [ ] All 7 pass: `pytest packages/ai-parrot/tests/bots/flows/test_agents_flow.py -v`.
- [ ] `test_linear_flow.output` is a scalar (single leaf rule).
- [ ] `test_branching_fan_out.output` is a dict with both leaf node_ids as keys.
- [ ] `test_branching_fan_out` proves concurrency: total elapsed < sequential lower bound.
- [ ] `test_branching_fan_in` proves C waits for both A and B (e.g., by recording call ordering).
- [ ] `test_conditional_routing_cel` covers BOTH pass and fail cases of the predicate.
- [ ] `test_retry_on_failure_then_success`: `flaky_count["n"] == 2` after the run; `result.status == "success"`.
- [ ] `test_decision_node_routing`: rejection branch never runs (result.responses doesn't contain its node_id).
- [ ] `test_on_complete_hook_fires`: the hook is awaited exactly once with `(ctx, result)` positionals.
- [ ] All tests use the stub `AgentRegistry` fixture; no real agent calls.
- [ ] `pytest packages/ai-parrot/tests/bots/flows/ -v` (full directory) passes.
- [ ] No linting errors.

---

## Test Specification

The test cases ARE the spec — see Pattern above. The 7 tests are mandatory for acceptance.

---

## Agent Instructions

1. Confirm TASK-1067, TASK-1068, TASK-1069 are in `sdd/tasks/completed/`.
2. Read the completed `parrot/bots/flows/flow.py` to confirm the actual `AgentsFlow` constructor signature, `run_flow` signature, and `FlowResult` field names.
3. Read `parrot/bots/flow/cel_evaluator.py` for CEL predicate syntax (used in the conditional-routing test).
4. Read `parrot/bots/flow/definition.py` (post TASK-1064) for `EdgeDefinition` field for predicates (may be a `condition: str` or `predicate: CELPredicate` field).
5. Implement the fixtures in `conftest.py` first.
6. Implement the 7 tests one at a time, running each before moving to the next.
7. Pay special attention to the retry test (verify how `max_retries` is configured) and the decision-node test (verify how the DecisionNode wrapper is materialized from FlowDefinition).
8. Run `pytest packages/ai-parrot/tests/bots/flows/ -v` — full directory must be green.
9. Move this task file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: All 14 integration tests pass across 7 scenarios. Fixed circular import between parrot.bots.flows.flow and parrot.bots.flow.__init__/loader (lazy imports via __getattr__ and inline import). Fixed retry FSM state: on retry, replace node with model_copy(update={"fsm": new_fsm}) so retried nodes get a fresh idle FSM. conftest.py created with StubRegistry and flow_context fixtures. test_agents_flow.py implements 14 tests across 7 scenario classes. Total: 149 tests passing (140 in tests/bots/flows/ + 9 in tests/bots/flow/).
**Deviations from spec**: Expanded from 7 tests to 14 for better coverage. RetryableAgentNode subclass created (AgentNode has no max_retries field natively). CEL predicate uses result.output field (AgentNode returns dict with "output" key). DecisionNode test uses mock patch on DecisionFlowNode constructor.
