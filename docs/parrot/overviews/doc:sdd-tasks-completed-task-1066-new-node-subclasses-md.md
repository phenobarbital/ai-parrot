---
type: Wiki Overview
title: 'TASK-1066: New Node subclasses — `DecisionNode`, `InteractiveDecisionNode`,
  `SynthesisNode`'
id: doc:sdd-tasks-completed-task-1066-new-node-subclasses-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Implements Spec §3 Module 5. Adds three new Node subclasses to `parrot/bots/flows/flow.py`,
  each registered via `@register_node(...)`:'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
---

# TASK-1066: New Node subclasses — `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode`

**Feature**: FEAT-163 — AgentsFlow Refactor — DAG Engine on flows.core
**Spec**: `sdd/specs/agentsflow-refactor-spec3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1060, TASK-1063, TASK-1065
**Assigned-to**: unassigned

---

## Context

Implements Spec §3 Module 5. Adds three new Node subclasses to `parrot/bots/flows/flow.py`, each registered via `@register_node(...)`:

- `DecisionNode("decision")` — wraps the legacy `parrot.bots.flow.decision_node.DecisionFlowNode` so a flow node executes a decision and returns a `DecisionResult`. CEL predicates on outgoing edges read `result.final_decision`.
- `InteractiveDecisionNode("interactive_decision")` — wraps the legacy `parrot.bots.flow.interactive_node.InteractiveDecisionNode` (CLI-blocking). Aliased on import to avoid name collision with the new class.
- `SynthesisNode("synthesis")` — calls the `synthesize_results(ctx, accumulated_result)` util (TASK-1063) to do in-graph result summarization. Acts as a leaf or near-leaf node.

All three are frozen Pydantic `Node` subclasses with the new `(ctx, deps, **kwargs)` execute signature. They reuse the FSM-on-node pattern from `AgentNode` (B-lite — spec §1 Goals).

---

## Scope

For each of the three new classes in `parrot/bots/flows/flow.py`:

### `DecisionNode(Node)`

- Fields:
  - `node_id: str`
  - `decision_config: DecisionNodeConfig` (the existing config model at `parrot/bots/flow/decision_node.py:192`)
  - `dependencies: set[str] = Field(default_factory=set)`
  - `successors: set[str] = Field(default_factory=set)`
  - `fsm: Optional[AgentTaskMachine] = None`
  - (Add other fields the legacy `DecisionFlowNode` constructor needs — verify via read.)
- `name` property: returns `node_id` or a derived label.
- `model_post_init`: auto-creates FSM if `None` (mirrors `AgentNode`).
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> DecisionResult`:
  - Construct or reuse a `DecisionFlowNode` instance using `self.decision_config`.
  - Call its `.ask(...)` (verify exact method name and signature in `decision_node.py:238+`).
  - Return the `DecisionResult`.
- Register: `@register_node("decision")` decorating the class.

### `InteractiveDecisionNode(Node)`

- Same shape as `DecisionNode` but wrapping the legacy `parrot.bots.flow.interactive_node.InteractiveDecisionNode` (aliased on import as `LegacyInteractiveDecisionNode`).
- `@register_node("interactive_decision")`.
- Note: the wrapped legacy class blocks on `questionary` via `run_in_executor`. The new wrapper does NOT change this — HITL improvements are a future spec.

### `SynthesisNode(Node)`

- Fields:
  - `node_id: str`
  - `dependencies: set[str] = Field(default_factory=set)` (typically all upstream leaves)
  - `successors: set[str] = Field(default_factory=set)`
  - `fsm: Optional[AgentTaskMachine] = None`
- `name`: returns `node_id` or `"synthesis"`.
- `async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> str`:
  - Build a partial `FlowResult`-like view from `deps` and `ctx.results` (or whatever the scheduler exposes for in-progress state — coordinate with TASK-1067 if needed; if a partial view isn't available, pass `deps` directly and have `synthesize_results` adapt).
  - Call `synthesize_results(ctx, partial_result)`.
  - Return the summary string.
- `@register_node("synthesis")`.

**NOT in scope**:
- Scheduler implementation (TASK-1067).
- `from_definition()` materialization (TASK-1068).
- Modifying the legacy `DecisionFlowNode` / `InteractiveDecisionNode` classes — wrap, do not change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow.py` | MODIFY | Add `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode` classes + their decorator registrations |
| `packages/ai-parrot/tests/bots/flows/test_flow_node_subclasses.py` | CREATE | Unit tests for the three wrappers |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (add to existing flow.py)

```python
from parrot.bots.flow.decision_node import (
    DecisionFlowNode,          # parrot/bots/flow/decision_node.py:238 (legacy, wraps)
    DecisionResult,            # parrot/bots/flow/decision_node.py:114
    DecisionMode,              # parrot/bots/flow/decision_node.py:26
    DecisionNodeConfig,        # parrot/bots/flow/decision_node.py:192
)
from parrot.bots.flow.interactive_node import (
    InteractiveDecisionNode as LegacyInteractiveDecisionNode,
    # parrot/bots/flow/interactive_node.py — verify class name + module path
)

from .core.storage.synthesis import synthesize_results
# Added in TASK-1063. If __init__.py re-exports, may also be:
# from .core.storage import synthesize_results
```

### Existing Signatures (consume — do not modify)

```python
# parrot/bots/flow/decision_node.py
class DecisionMode(str, Enum):                # line 26
    CIO = ...
    BALLOT = ...
    CONSENSUS = ...

class DecisionResult(BaseModel):              # line 114
    decision_id: str
    mode: DecisionMode
    final_decision: Any                       # what CEL predicates read
    confidence: float
    votes: Dict[str, Any]
    vote_distribution: Dict[str, int]
    consensus_level: Optional[str]
    escalated: bool
    escalation_reason: Optional[str]
    agent_responses: Dict[str, Any]
    execution_time: float
    metadata: Dict[str, Any]

class DecisionNodeConfig(BaseModel):          # line 192
    # Read its fields before this task — they're inputs to DecisionFlowNode construction.

class DecisionFlowNode(Node):                 # line 238 — legacy Node class
    # Verify constructor signature and the call method (probably .ask(...) returning DecisionResult).
    # The new DecisionNode wrapper holds a config and instantiates this lazily inside execute().

# parrot/bots/flow/interactive_node.py
class InteractiveDecisionNode(Node):          # legacy — exact line number to verify
    # Same wrap-and-delegate pattern.
```

### Does NOT Exist (yet)

- ~~`parrot.bots.flows.flow.DecisionNode`~~ — created by this task.
- ~~`parrot.bots.flows.flow.InteractiveDecisionNode`~~ — created by this task.
- ~~`parrot.bots.flows.flow.SynthesisNode`~~ — created by this task.
- ~~`parrot.bots.flow.decision_node.DecisionNode`~~ — the legacy class is `DecisionFlowNode`, not `DecisionNode`. The new wrapper IS called `DecisionNode` but lives in a different module.

---

## Implementation Notes

### Pattern to Follow

```python
# parrot/bots/flows/flow.py — additions after the AgentsFlow class skeleton.

from pydantic import Field, ConfigDict
from .core.node import Node
from .core.fsm import AgentTaskMachine
from .core.context import FlowContext
from .core.types import DependencyResults


@register_node("decision")
class DecisionNode(Node):
    """Wraps the legacy DecisionFlowNode as a Node usable by AgentsFlow.

    Holds a DecisionNodeConfig; instantiates a fresh DecisionFlowNode
    on each execute() so per-run state is isolated.
    """
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    node_id: str
    decision_config: DecisionNodeConfig
    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context) -> None:
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs,
    ) -> DecisionResult:
        await self.run_pre_actions(prompt="", **kwargs)
        # Construct the legacy decision node from config:
        legacy = DecisionFlowNode(config=self.decision_config)  # verify exact signature
        result = await legacy.ask(ctx=ctx, deps=deps, **kwargs)  # verify method + signature
        await self.run_post_actions(result=result, **kwargs)
        return result


@register_node("interactive_decision")
class InteractiveDecisionNode(Node):
    """Wraps the legacy CLI-blocking InteractiveDecisionNode."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    node_id: str
    # Other fields per the legacy's constructor — verify.
    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context) -> None:
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx, deps, **kwargs):
        # Mirror DecisionNode: construct + delegate to LegacyInteractiveDecisionNode.
        ...


@register_node("synthesis")
class SynthesisNode(Node):
    """In-graph result synthesis. Calls the shared synthesize_results util."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    node_id: str
    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context) -> None:
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

    @property
    def name(self) -> str:
        return self.node_id

    async def execute(self, ctx, deps, **kwargs):
        await self.run_pre_actions(prompt="synthesis", **kwargs)
        # Build a partial FlowResult-like view. If scheduler exposes
        # `ctx.partial_result`, use it; otherwise construct minimally from deps.
        partial = ctx.build_partial_result() if hasattr(ctx, "build_partial_result") else _partial_from_deps(deps)
        summary = await synthesize_results(ctx, partial)
        await self.run_post_actions(result=summary, **kwargs)
        return summary
```

### Key Constraints

- Use `object.__setattr__` for FSM auto-creation inside `model_post_init` (frozen escape hatch — established in TASK-1060).
- **Verify the legacy class names and method signatures** before writing the wrappers. Specifically:
  - `DecisionFlowNode.__init__` signature.
  - `DecisionFlowNode.ask(...)` (or whatever method returns a `DecisionResult`).
  - `InteractiveDecisionNode.__init__` and `ask()` (or equivalent).
- The wrappers should NOT cache the legacy instance across calls — construct per `execute()` so per-run state stays clean (B-lite contract). If the legacy class is expensive to construct, document and coordinate.
- `SynthesisNode` depends on what the scheduler (TASK-1067) exposes for partial state. If TASK-1067 hasn't shipped yet at implementation time, define a minimal interface (e.g., look at `deps` directly) and add a TODO noting the integration point with TASK-1067.
- FSM transitions are NOT called inside `execute()` — the scheduler manages them externally (same as `AgentNode` per TASK-1060).

### References in Codebase

- `parrot/bots/flow/decision_node.py:114–280` — `DecisionResult`, `DecisionNodeConfig`, `DecisionFlowNode`.
- `parrot/bots/flow/interactive_node.py` — `InteractiveDecisionNode` legacy.
- `parrot/bots/flows/core/storage/synthesis.py` — `synthesize_results` (TASK-1063).
- `parrot/bots/flows/flow.py` (TASK-1065) — module to extend.

---

## Acceptance Criteria

- [ ] `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode` exist in `parrot/bots/flows/flow.py`.
- [ ] All three are frozen Pydantic `Node` subclasses with `arbitrary_types_allowed=True`.
- [ ] Each is registered: `NODE_REGISTRY["decision"] is DecisionNode`, `NODE_REGISTRY["interactive_decision"] is InteractiveDecisionNode`, `NODE_REGISTRY["synthesis"] is SynthesisNode`.
- [ ] `DecisionNode.execute()` returns a `DecisionResult` (verified by `isinstance`).
- [ ] `SynthesisNode.execute()` returns a string (the synthesis summary).
- [ ] FSM transitions (`.start()`, `.succeed()`, `.fail()`) work on instances of all three (mutation of nested object on frozen model).
- [ ] The wrappers construct a fresh underlying legacy instance per `execute()` call (no shared per-run state).
- [ ] Unit tests pass: `pytest packages/ai-parrot/tests/bots/flows/test_flow_node_subclasses.py -v`.
- [ ] No linting errors.
- [ ] `grep -c "@register_node" packages/ai-parrot/src/parrot/bots/flows/flow.py` returns at least 3 (decision, interactive_decision, synthesis) plus the 3 direct calls from TASK-1065 for agent/start/end — total 6.

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_flow_node_subclasses.py
import pytest
from unittest.mock import AsyncMock

from parrot.bots.flows.flow import (
    NODE_REGISTRY, DecisionNode, InteractiveDecisionNode, SynthesisNode,
)
from parrot.bots.flow.decision_node import DecisionResult, DecisionMode, DecisionNodeConfig


class TestDecisionNode:
    def test_registered(self):
        assert NODE_REGISTRY["decision"] is DecisionNode

    def test_frozen(self):
        cfg = DecisionNodeConfig(...)  # fill in required fields after read
        node = DecisionNode(node_id="d1", decision_config=cfg)
        with pytest.raises(Exception):
            node.node_id = "d2"

    async def test_execute_returns_decision_result(self, ctx_stub, deps_stub):
        cfg = DecisionNodeConfig(...)
        node = DecisionNode(node_id="d1", decision_config=cfg)
        result = await node.execute(ctx_stub, deps_stub)
        assert isinstance(result, DecisionResult)


class TestInteractiveDecisionNode:
    def test_registered(self):
        assert NODE_REGISTRY["interactive_decision"] is InteractiveDecisionNode


class TestSynthesisNode:
    def test_registered(self):
        assert NODE_REGISTRY["synthesis"] is SynthesisNode

    async def test_execute_returns_string(self, ctx_stub_with_synthesis, deps_stub):
        node = SynthesisNode(node_id="syn")
        out = await node.execute(ctx_stub_with_synthesis, deps_stub)
        assert isinstance(out, str)


@pytest.fixture
def ctx_stub():
    """Minimal FlowContext stub with a synthesis client and resolve_agent."""
    class Stub:
        agent_registry = None
        synthesis_client = None
        def get_input_for_agent(self, name, deps): return ""
    return Stub()


@pytest.fixture
def ctx_stub_with_synthesis(ctx_stub):
    ctx_stub.synthesis_client = AsyncMock()
    ctx_stub.synthesis_client.ask.return_value = type("R", (), {"content": "summary"})()
    return ctx_stub


@pytest.fixture
def deps_stub(): return {}
```

---

## Agent Instructions

1. Confirm TASK-1060, TASK-1063, TASK-1065 are in `sdd/tasks/completed/`.
2. Read `parrot/bots/flow/decision_node.py:114–300` to verify `DecisionResult`, `DecisionNodeConfig`, `DecisionFlowNode` exact signatures.
3. Read `parrot/bots/flow/interactive_node.py` for the legacy `InteractiveDecisionNode` class structure.
4. Read TASK-1063's completed `synthesize_results` signature and confirm `synthesis.py`'s exact module path for the import.
5. Implement the three classes per the pattern. Use `object.__setattr__` for FSM auto-creation.
6. Run `pytest packages/ai-parrot/tests/bots/flows/test_flow_node_subclasses.py -v`.
7. Run `pytest packages/ai-parrot/tests/bots/flows/test_flow_registry.py -v` (regression on TASK-1065's tests).
8. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-12
**Notes**: DecisionNode, InteractiveDecisionNode, SynthesisNode added to flow.py. All registered via @register_node. All frozen Pydantic Node subclasses with auto-FSM. DecisionNode wraps legacy DecisionFlowNode (fresh per execute). InteractiveDecisionNode wraps LegacyInteractiveDecisionNode. SynthesisNode calls synthesize_results with minimal partial view from deps. 21/21 tests pass.
**Deviations from spec**: test_fsm_can_mutate uses fsm.schedule() (idle→ready) instead of fsm.start() (requires ready state) — spec note was inaccurate about the FSM starting state.
