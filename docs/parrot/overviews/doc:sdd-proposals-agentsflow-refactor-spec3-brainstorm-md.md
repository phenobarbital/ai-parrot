---
type: Wiki Overview
title: 'Brainstorm: AgentsFlow Refactor — DAG Engine on flows.core'
id: doc:sdd-proposals-agentsflow-refactor-spec3-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The grounded audit (see research doc + Explore verification) shows three
  real defects, not the originally-assumed "global FSM" problem:'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.fsm
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.transition
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Brainstorm: AgentsFlow Refactor — DAG Engine on flows.core

**Date**: 2026-05-11
**Author**: Jesus
**Status**: exploration
**Recommended Option**: C
**Depends on**: `flow-primitives` (FEAT-134, merged), `agent-crew-primitives-migration` (FEAT-143, merged)
**Source**: `sdd/proposals/agents-flow-refactor.research.md` (research audit + Q&A in this session)

---

## Problem Statement

`AgentsFlow` (in `parrot/bots/flow/fsm.py`, 1815 lines) is the DAG executor for multi-agent workflows. The Dev Loop Flow (`parrot/flows/dev_loop/flow.py`) was built as a proof-of-concept driving Claude Code agents as flow nodes. **It does not work as intended**, and the problems surfaced during that PoC are what triggered this refactor.

The grounded audit (see research doc + Explore verification) shows three real defects, not the originally-assumed "global FSM" problem:

1. **Polling scheduler with full-graph scans**. `run_flow` uses `await asyncio.sleep(0.1)` between iterations (line 814), and each iteration scans every node three times — `_get_ready_agents` (line 980), `_is_workflow_complete` (line 1007), `_has_active_agents` (line 987), plus `_process_transitions` (line 1175). Batched `asyncio.gather` at line 1054 makes every downstream node wait for the slowest sibling in its batch — the real parallelism limit.
2. **State conflation in `FlowNode`** (line 198). The dataclass mixes static definition (`agent`, `dependencies`, `outgoing_transitions`) with mutable per-run state (`result`, `response`, `error`, `execution_time`, `retry_count`, `fsm`, `transitions_processed`). The reset block in `run_flow` (lines 760-768) reassigns `node.fsm = AgentTaskMachine(...)` destructively — same flow definition cannot run twice concurrently.
3. **Duplication with `parrot/bots/flows/core/`** (the post-FEAT-134 primitives). Six symbols are duplicated verbatim: `AgentTaskMachine` (fsm.py:61 ↔ core/fsm.py:40), `TransitionCondition` (fsm.py:52 ↔ core/fsm.py:17), `AgentRef` (fsm.py:47 ↔ core/types.py:100), `DependencyResults` (fsm.py:48 ↔ core/types.py:30), `PromptBuilder` (fsm.py:49 ↔ core/types.py:103), `FlowTransition` (fsm.py:116 ↔ core/transition.py:28). `AgentCrew` (in `parrot/bots/flows/crew/crew.py`) already consumes from `flows.core`; `AgentsFlow` should too.

Two structural gaps compound the defects:

- **No `from_definition()` materializer**. `FlowDefinition` (Pydantic, in `parrot/bots/flow/definition.py`) exists with a working SvelteFlow adapter (`svelteflow.py`), but nothing instantiates an executable `AgentsFlow` from it. The visual-editor → execution path is broken.
- **`DecisionNode` / `InteractiveDecisionNode` do not fit the agent contract**. They return `DecisionResult` (richer than the audit's truncated subset — see Code Context), not free-form agent output. Currently wedged into the flow via `add_agent(decision_node)`. There is no node-type taxonomy.

**Affected:** developers building agent workflows (currently blocked on the dev_loop PoC); future specs that depend on a working executor (HITL with checkpoint/resume, scatter/gather, loops, swarm).

---

## Constraints & Requirements

- **Architectural**: new executor MUST consume primitives from `parrot.bots.flows.core` only (no duplication). This is a standing decision — `AgentCrew` and `AgentsFlow` share the same core.
- **Module location**: new executor lives at `parrot/bots/flows/flow.py`. The legacy `parrot/bots/flow/fsm.py` is deleted at the end of the spec.
- **Supporting modules** (`decision_node.py`, `interactive_node.py`, `definition.py`, `svelteflow.py`, `actions.py`, `cel_evaluator.py`) stay in `parrot/bots/flow/` for now. A follow-up cleanup spec relocates them into `parrot/bots/flows/`.
- **Migration scope in THIS spec**: new executor + new integration tests covering linear / branching / fan-in / CEL predicate / retry / decision-node routing. **Dev Loop Flow migration is deferred to a follow-up spec.** Examples deferred.
- **Backward compatibility**: none required for the public AgentsFlow API. Dev Loop is a broken PoC that this refactor exists to unblock; existing tests are rewritten, not preserved.
- **Foundation for future specs**: scheduler must be event-driven so future HITL nodes can pause/resume without holding tasks in `asyncio.gather`. Future specs (scatter/gather, loops) need to plug in new node types via a registry.
- **Timeline**: 3–4 weeks, ~8–12 SDD tasks.

---

## Options Explored

### Option A: Minimal Surgery

Patch `parrot/bots/flow/fsm.py` in place: eliminate the six duplicated symbols by importing from `flows.core`, update imports to `FlowResult` / `NodeResult` / `NodeExecutionInfo`, add a `from_definition()` classmethod, introduce a small `EXECUTOR_REGISTRY` for `DecisionNode` integration. Leave the polling scheduler and `FlowNode` state conflation as-is.

✅ **Pros:**
- Fastest to deliver (1–2 weeks).
- Lowest risk — no scheduler rewrite, no API churn beyond import paths.
- Eliminates duplication immediately.

❌ **Cons:**
- Leaves the polling scheduler and full-graph scans in place — Dev Loop's actual symptoms (slow node startup, batched waits) are not addressed.
- `FlowNode` state conflation persists — same flow instance still cannot run concurrently.
- Future specs (HITL pause/resume, scatter/gather) will need to revisit the scheduler again. Net effort is higher across the program.

📊 **Effort:** Low

📦 **Libraries / Tools:** none new — uses existing `flows.core` primitives.

🔗 **Existing Code to Reuse:** the whole of `parrot/bots/flow/fsm.py` (in-place patches only).

---

### Option B: Scheduler Rewrite In Place

Inside `parrot/bots/flow/fsm.py`: replace the polling loop with an event-driven scheduler (queue of completion events), split `FlowNode` into `NodeSpec` (frozen) + `NodeRunState` (per-run), introduce a node-type registry with a fold-in `@register_node` decorator, add `from_definition()`. Update imports to `flows.core`. New code coexists with legacy structures during the refactor.

✅ **Pros:**
- Same end-state architecture as Option C.
- Existing tests / examples / Dev Loop continue to import `from parrot.bots.flow.fsm import AgentsFlow` while the migration happens.

❌ **Cons:**
- Reviews are noisier — new and legacy code share a 1815-line file during the work.
- Diff is harder to read; risk of accidentally preserving a legacy quirk.
- File name (`fsm.py`) becomes a lie: the new executor isn't an FSM, it's a DAG engine.

📊 **Effort:** Medium-High (3–4 weeks)

📦 **Libraries / Tools:** none new.

🔗 **Existing Code to Reuse:** `parrot/bots/flows/core/*`, `parrot/bots/flow/definition.py`, `parrot/bots/flow/actions.py`, `parrot/bots/flow/cel_evaluator.py`, `parrot/bots/flow/decision_node.py`, `parrot/bots/flow/interactive_node.py`, `parrot/bots/flow/svelteflow.py`.

---

### Option C: Clean Rewrite at `parrot/bots/flows/flow.py` (Recommended)

Build the new executor from zero at `parrot/bots/flows/flow.py`, consuming only `parrot/bots/flows/core/*` and the preserved declarative modules (which stay in `parrot/bots/flow/` for this spec). At the end of the spec, delete `parrot/bots/flow/fsm.py`. No backward compat for the AgentsFlow API.

The new executor has:

- **Hard spec/state split**: `NodeSpec` (frozen, Pydantic — agent_ref, dependencies, transitions, max_retries) + `NodeRunState` (per-execution: FSM, result, error, attempts).
- **Event-driven scheduler**: single `asyncio.Queue[CompletionEvent]` consumer. Node completion pushes `(node_id, result | error)` onto the queue; the consumer drains, updates internal ready/active/completed/failed sets incrementally, dispatches downstream nodes. Tasks are spawned per-node via `asyncio.create_task`, not gathered — fast nodes do not wait for slow siblings.
- **Single `@register_node(name)` decorator** that wraps a `NodeSpec` subclass embedding both `validate()` and `async execute(ctx, deps)` — one registration point, no separate executor map.
- **`AgentRegistry`-based agent resolution**: `FlowContext.resolve_agent(agent_ref)` calls into `parrot/registry/registry.py`. `from_definition(definition: FlowDefinition)` no longer needs an explicit resolver argument.
- **Hooks instead of `SynthesisMixin`**: `run_flow(on_complete=[...])` accepts a list of async callables. `synthesize_results` becomes a shared util importable as a hook AND from a new `SynthesisNode` DAG node. `PersistenceMixin` is kept.
- **`FlowResult.output` semantics**: dict of leaf-node outputs; scalar when there's exactly one leaf.

✅ **Pros:**
- Clean diff — new module reviewable on its own merits.
- File name (`flow.py`) matches the abstraction.
- Same end-state as Option B at the same cost, with lower cognitive load.
- Foundation for HITL pause/resume is built in: the queue-based scheduler doesn't hold pending nodes in `asyncio.gather`, so a node can yield its slot and be resumed later.

❌ **Cons:**
- Existing tests for `AgentsFlow` and `AgentCrewFSM` are rewritten, not migrated.
- Dev Loop Flow remains broken until its own follow-up spec. (Mitigation: Dev Loop was non-functional anyway — this is the point of the refactor.)
- Examples (`examples/crew/pizza_sushi_flow.py`, etc.) break and are not fixed in this spec.

📊 **Effort:** Medium-High (3–4 weeks, ~8–12 SDD tasks)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `asyncio` (stdlib) | Event-driven scheduling via `Queue` + `create_task` | Already used throughout AI-Parrot. |
| `pydantic` (existing) | Frozen `NodeSpec` subclasses, declarative validation | Same version the rest of the framework uses. |
| `celpy` (existing) | CEL predicate evaluation on transition conditions | Already wrapped by `parrot/bots/flow/cel_evaluator.py`. |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flows/core/fsm.py` — `AgentTaskMachine`, `TransitionCondition`.
- `parrot/bots/flows/core/types.py` — `AgentRef`, `DependencyResults`, `PromptBuilder`, `FlowStatus`, `ActionCallback`, `AgentLike`.
- `parrot/bots/flows/core/transition.py` — `FlowTransition`.
- `parrot/bots/flows/core/node.py` — `Node` ABC, `AgentNode`, `StartNode`, `EndNode`.
- `parrot/bots/flows/core/result.py` — `FlowResult`, `NodeResult`, `NodeExecutionInfo`, `build_node_metadata`, `determine_run_status`.
- `parrot/bots/flows/core/context.py` — `FlowContext`.
- `parrot/bots/flows/core/storage/` — `PersistenceMixin` (kept), `ExecutionMemory`.
- `parrot/bots/flow/definition.py` — `FlowDefinition`, `NodeDefinition`, `EdgeDefinition`, `FlowMetadata`, action models.
- `parrot/bots/flow/svelteflow.py` — `to_svelteflow()` and inverse adapter.
- `parrot/bots/flow/actions.py` — `ACTION_REGISTRY`, `@register_action`, built-in actions.
- `parrot/bots/flow/cel_evaluator.py` — `CELPredicateEvaluator`.
- `parrot/bots/flow/decision_node.py` — `DecisionNode`, `DecisionResult`, `DecisionMode` (consumed via `@register_node`).
- `parrot/bots/flow/interactive_node.py` — `InteractiveDecisionNode` (consumed via `@register_node`).
- `parrot/registry/registry.py` — `AgentRegistry` for resolver-less agent_ref lookup.

---

## Recommendation

**Option C** is recommended for the reasons established during research and confirmed in Q&A:

- The user has explicitly approved breaking the AgentsFlow API. There are no production consumers worth preserving — Dev Loop Flow is the broken PoC that motivated the refactor, examples are demo-only, and tests will be rewritten.
- Option B costs the same as C in calendar time, but yields a noisier diff and a misnamed file (`fsm.py`). The new code is not an FSM.
- Option A leaves the real defects (polling, scans, state conflation) in place. Future specs would have to revisit the scheduler — net program cost is higher than Option C.
- The new executor must consume `flows.core` per the standing architectural decision; Option C is the cleanest expression of that boundary.

What we are trading off: any tests / examples / notebooks against the current `AgentsFlow` API break. This is acceptable because Dev Loop migration is an explicit follow-up spec, and examples are documentation-grade.

---

## Feature Description

### User-Facing Behavior

Developers construct flows in three ways, all producing the same executable:

1. **Programmatic**: instantiate node specs, wire dependencies, call `flow.run_flow()`.
2. **Declarative**: build a `FlowDefinition` (Pydantic), call `AgentsFlow.from_definition(definition)`.
3. **Visual**: design in SvelteFlow, export JSON, round-trip through `FlowDefinition`, then `from_definition()`.

`run_flow()` returns a `FlowResult` with:

- `output`: scalar when the DAG has one leaf, dict of leaf outputs otherwise.
- `nodes`: list of `NodeExecutionInfo` (timings, status, errors).
- `responses`: `dict[node_id, response]`.
- `errors`: `dict[node_id, error_str]` for failed nodes.
- `status`: derived via `determine_run_status(success_count, failure_count)`.

Optional: `on_complete=[...]` hooks for cross-cutting work (synthesis, metric emission, custom persistence). A `SynthesisNode` is provided so callers who prefer to declare summarization as a DAG node can do so.

### Internal Behavior

**Construction phase** (`AgentsFlow.from_definition(definition)` or programmatic):
1. Validate the `FlowDefinition` (cycles, dangling references, type-correct edges).
2. Materialize each `NodeDefinition` into a `NodeSpec` subclass via the `@register_node` registry, keyed by node type.
3. Resolve each `agent_ref` lazily via `FlowContext.resolve_agent` (calls `AgentRegistry`) at execution time, not at construction.
4. Build the static dependency graph from `EdgeDefinition` instances.

**Execution phase** (`run_flow(context, on_complete=[...])`):
1. Create a fresh `NodeRunState` for every node in the graph (frozen `NodeSpec`s are reused across runs).
2. Initialize `ready_queue` with nodes that have no dependencies.
3. Spawn an `asyncio.Task` per ready node (no gather). Each task: runs pre-actions, calls `spec.execute(ctx, deps)`, runs post-actions, pushes `(node_id, result | error)` to `completion_queue`.
4. The scheduler coroutine drains `completion_queue`:
   - Updates `NodeRunState` (status, result, timing).
   - Evaluates outgoing transitions via `CELPredicateEvaluator`.
   - For each newly-ready downstream node, spawns its task.
   - Tracks `active_count` incrementally; loop terminates when `active_count == 0` and `completion_queue.empty()`.
5. Fire `on_complete` hooks after the loop terminates.
6. Aggregate `FlowResult`: leaves = nodes with no outgoing edges → output is scalar (single leaf) or dict (multiple leaves).

### Edge Cases & Error Handling

- **Cycles**: caught at `FlowDefinition` validation time via a `model_validator` (moved out of the executor). Any definition — JSON, programmatic, or SvelteFlow round-trip — fails fast on construction.
- **Dangling `agent_ref`**: `FlowContext.resolve_agent` raises `AgentNotFoundError` at execution time (lazy resolution is intentional — registry may be populated after construction).
- **Node failure**: `NodeSpec.execute` raises → `NodeRunState.status = failed`, error pushed to queue. Retries honored via `max_retries` on the spec. After retries exhausted, downstream nodes whose CEL predicates require this node's success are short-circuited as `skipped`.
- **Decision routing**: `DecisionNode.execute` returns a `DecisionResult`; CEL predicates on outgoing edges read `result.final_decision`. The richer fields (`confidence`, `votes`, `escalated`) are available to predicates but not interpreted by the scheduler.
- **HITL future**: when a node yields control (e.g., waiting on external decision), its task ends without pushing to `completion_queue`. The scheduler simply doesn't see a completion. A future HITL spec will introduce an external trigger that pushes a synthetic completion event when the human decision lands. The scheduler design does not preclude this.
- **`PersistenceMixin`**: keeps current semantics — checkpoint after each completion event, resume from last checkpoint.

---

## Capabilities

### New Capabilities
- `agents-flow-dag-engine`: the new executor at `parrot/bots/flows/flow.py` (this spec).
- `node-type-registry`: `@register_node` decorator + `NODE_REGISTRY` table.
- `flow-definition-cycle-detection`: cycle validation moved into `FlowDefinition.model_validator`.
- `flow-on-complete-hooks`: `run_flow(on_complete=[...])` for cross-cutting work.
- `synthesis-node`: declarative `SynthesisNode` for in-graph result summarization (shares util with the on_complete hook).

### Modified Capabilities
- `agents-flow` (the broader capability): rewritten executor, broken API contract.
- `flow-definition`: cycle detection added to validator.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flow/fsm.py` | **deleted** at end of spec | All symbols migrated or replaced. |
| `parrot/bots/flows/flow.py` | **new** | The executor. |
| `parrot/bots/flows/core/*` | **depends on** | Consumed verbatim. No changes in this spec. |
| `parrot/bots/flow/definition.py` | **modifies** | Adds cycle-detection `model_validator`. Otherwise preserved in place. |
| `parrot/bots/flow/decision_node.py` | **modifies (light)** | `DecisionNode` becomes a `@register_node("decision")` `NodeSpec`. May need a thin wrapper. |
| `parrot/bots/flow/interactive_node.py` | **modifies (light)** | Same pattern as `DecisionNode`. |
| `parrot/bots/flow/svelteflow.py` | **depends on** | Preserved. Round-trip target for visual editor. |
| `parrot/bots/flow/actions.py` | **depends on** | `ACTION_REGISTRY` consumed; pre/post-action contract preserved. |
| `parrot/bots/flow/cel_evaluator.py` | **depends on** | Consumed verbatim. |
| `parrot/bots/flows/core/storage/` | **depends on** | `PersistenceMixin` kept. `SynthesisMixin` no longer inherited by the new executor (kept in place for AgentCrew compatibility — a future spec removes it from AgentCrew too). |
| `parrot/registry/registry.py` | **depends on** | `AgentRegistry` used for `agent_ref` resolution. |
| `parrot/manager/manager.py` | **independent** | `BotManager.get_bot` is no longer the resolver — registry is. |
| `parrot/flows/dev_loop/flow.py` | **broken; deferred** | Migration in a follow-up spec. |
| `examples/crew/*flow*.py` | **broken; deferred** | Migration in a follow-up spec. |
| Existing tests (`test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py`, `test_decision_node.py`) | **deleted/rewritten** | Replaced by new integration tests against the new API. |

---

## Code Context

### User-Provided Code

The user proposed the following `@register_node` pattern during Q&A. This is the canonical shape for node-type registration in the new executor:

```python
# Source: user-provided (sdd-brainstorm session 2026-05-11)
@register_node("agent")
class AgentNode(NodeSpec):
    agent_ref: str
    instruction: Optional[str] = None

    def validate(self) -> None:
        if not self.agent_ref:
            raise ValueError("agent_ref required")

    async def execute(self, ctx: FlowContext, deps: DependencyResults) -> Any:
        agent = ctx.resolve_agent(self.agent_ref)
        return await agent.invoke(...)
```

Key properties of this pattern:
- The decorated class **is** the `NodeSpec`.
- Validation is a method on the spec, not a separate registry.
- Execution is an async method on the spec — single registration point.
- `ctx.resolve_agent` delegates to `AgentRegistry`.

For `SynthesisNode` and the `on_complete` hook:

```python
# Source: user-provided (sdd-brainstorm session 2026-05-11)
# Shared util used by both invocation paths:
async def synthesize_results(ctx: FlowContext, result: FlowResult) -> str:
    ...  # uses SYNTHESIS_PROMPT

# As a hook:
await flow.run_flow(on_complete=[synthesize_results])

# As an in-graph node:
@register_node("synthesis")
class SynthesisNode(NodeSpec):
    async def execute(self, ctx, deps):
        return await synthesize_results(ctx, ...)
```

### Verified Codebase References

#### Classes & Signatures (verified by Explore agent)

```python
# From parrot/bots/flow/fsm.py:278
class AgentsFlow(PersistenceMixin, SynthesisMixin):
    ...

# From parrot/bots/flow/fsm.py:198 (the conflated FlowNode)
@dataclass
class FlowNode:
    agent: AgentLike            # static
    fsm: AgentTaskMachine       # runtime — reassigned at line 763
    dependencies: list[str]     # static
    outgoing_transitions: list[FlowTransition]  # static
    result: Any                 # runtime
    response: str               # runtime
    error: str | None           # runtime
    execution_time: float       # runtime
    retry_count: int            # runtime
    transitions_processed: bool = False  # runtime; line 225

# From parrot/bots/flows/core/fsm.py:40
class AgentTaskMachine:
    ...

# From parrot/bots/flows/core/fsm.py:17
class TransitionCondition:
    ...

# From parrot/bots/flows/core/transition.py:28
class FlowTransition:
    ...

# From parrot/bots/flows/core/result.py:273
class FlowResult(BaseModel):
    ...
# From parrot/bots/flows/core/result.py:39
class NodeResult(BaseModel):
    ...
# From parrot/bots/flows/core/result.py:190
class NodeExecutionInfo(BaseModel):
    ...

# From parrot/bots/flows/crew/crew.py:87
class AgentCrew(PersistenceMixin, SynthesisMixin):
    ...
# (no from_definition() classmethod — verified absent)

# From parrot/bots/flow/decision_node.py:114
class DecisionResult(BaseModel):
    decision_id: str
    mode: DecisionMode
    final_decision: Any
    confidence: float
    votes: dict
    vote_distribution: dict
    consensus_level: str
    escalated: bool
    escalation_reason: str | None
    agent_responses: list
    execution_time: float
    metadata: dict

# From parrot/bots/flow/decision_node.py:26
class DecisionMode(Enum):
    CIO = ...
    BALLOT = ...
    CONSENSUS = ...

# From parrot/bots/flow/definition.py:288
class FlowDefinition(BaseModel):
    # validate_node_ids at line 338 — references only, NOT cycles
    ...
# From parrot/bots/flow/definition.py:143
class NodeDefinition(BaseModel):
    agent_ref: Optional[str]  # present, used by from_definition

# From parrot/bots/flow/actions.py
ACTION_REGISTRY: Dict[str, Type[BaseAction]]  # line 46
def register_action(name: str): ...  # line 49

# From parrot/bots/flow/cel_evaluator.py:50
class CELPredicateEvaluator:
    ...

# From parrot/manager/manager.py:86
class BotManager:
    async def get_bot(self, ...) -> Any:  # line 601 (NOT get_agent)
        ...

# From parrot/registry/registry.py
class AgentRegistry:
    # used by FlowContext.resolve_agent in the new executor
    ...
```

#### Verified Imports

```python
# Imports the new parrot/bots/flows/flow.py will use:
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
from parrot.bots.flows.core.types import (
    AgentRef, DependencyResults, PromptBuilder, FlowStatus, ActionCallback, AgentLike,
)
from parrot.bots.flows.core.transition import FlowTransition
from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
from parrot.bots.flows.core.result import (
    FlowResult, NodeResult, NodeExecutionInfo,
    build_node_metadata, determine_run_status,
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.storage import PersistenceMixin, ExecutionMemory
from parrot.bots.flow.definition import FlowDefinition, NodeDefinition, EdgeDefinition
from parrot.bots.flow.actions import ACTION_REGISTRY, register_action
from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator
from parrot.bots.flow.decision_node import DecisionNode, DecisionResult, DecisionMode
from parrot.bots.flow.interactive_node import InteractiveDecisionNode
from parrot.bots.flow.svelteflow import to_svelteflow  # + inverse
from parrot.registry.registry import AgentRegistry
```

#### Key Attributes & Constants

- `DecisionResult.final_decision` → `Any` — what CEL predicates read on decision edges (parrot/bots/flow/decision_node.py:114).

…(truncated)…
