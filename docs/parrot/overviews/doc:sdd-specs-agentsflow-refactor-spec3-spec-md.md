---
type: Wiki Overview
title: 'Feature Specification: AgentsFlow Refactor — DAG Engine on flows.core'
id: doc:sdd-specs-agentsflow-refactor-spec3-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 1. **Polling scheduler with full-graph scans.** `run_flow` polls with `await
  asyncio.sleep(0.1)` between iterations (fsm.py:814), and each iteration scans every
  node three times — `_get_ready_agents` (fsm.py:980), `_is_workflow_complete` (fsm.py:1007),
  `_has_active_agents` (fsm.p
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
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
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: mentions
- concept: mod:parrot.bots.flows.core.transition
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.nodes
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop.flow
  rel: mentions
- concept: mod:parrot.manager.manager
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
- concept: mod:parrot.registry.registry
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: AgentsFlow Refactor — DAG Engine on flows.core

**Feature ID**: FEAT-163
**Date**: 2026-05-11
**Author**: Jesus
**Status**: implemented
**Target version**: next minor
**Depends on**: FEAT-134 (`flow-primitives`, merged), FEAT-143 (`agent-crew-primitives-migration`, merged)

> **Note (FEAT-196, 2026-05-28)**: Code examples in this spec reference `parrot.bots.flow`
> (singular, deleted in FEAT-196). The new canonical paths are `parrot.bots.flows` (plural).
> This spec describes the FEAT-163 design work; the actual deletion of `parrot.bots.flow/`
> was completed by FEAT-196.
**Source**: `sdd/proposals/agentsflow-refactor-spec3.brainstorm.md` (Option C, 15 resolved questions; B-lite reconciliation for the `core.node.AgentNode` reuse)

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentsFlow` (`parrot/bots/flow/fsm.py`, 1815 lines) is the DAG executor for multi-agent workflows. The Dev Loop Flow PoC (`parrot/flows/dev_loop/flow.py`) — driving Claude Code agents as flow nodes — exposed three real defects that block the executor from being a viable foundation:

1. **Polling scheduler with full-graph scans.** `run_flow` polls with `await asyncio.sleep(0.1)` between iterations (fsm.py:814), and each iteration scans every node three times — `_get_ready_agents` (fsm.py:980), `_is_workflow_complete` (fsm.py:1007), `_has_active_agents` (fsm.py:987) — plus `_process_transitions` (fsm.py:1175). Batched `asyncio.gather` (fsm.py:1054) makes every downstream node wait for the slowest sibling in its batch.
2. **State conflation in `FlowNode`** (fsm.py:199). The dataclass mixes static definition (`agent`, `dependencies`, `outgoing_transitions`) with mutable per-run state (`result`, `response`, `error`, `execution_time`, `retry_count`, `fsm`, `transitions_processed`). `run_flow` lines 760–768 destructively reassign `node.fsm = AgentTaskMachine(...)` — the same flow instance cannot run twice concurrently.
3. **Duplication with `parrot/bots/flows/core/`.** Six symbols are duplicated verbatim between `parrot/bots/flow/fsm.py` and `parrot/bots/flows/core/*`: `AgentTaskMachine` (fsm.py:61 ↔ core/fsm.py:40), `TransitionCondition` (fsm.py:52 ↔ core/fsm.py:17), `AgentRef` (fsm.py:47 ↔ core/types.py:100), `DependencyResults` (fsm.py:48 ↔ core/types.py:30), `PromptBuilder` (fsm.py:49 ↔ core/types.py:103), `FlowTransition` (fsm.py:117 ↔ core/transition.py:28). `AgentCrew` (`parrot/bots/flows/crew/crew.py:87`) already consumes `flows.core`; `AgentsFlow` should too.

Two structural gaps compound the defects:

- **No `from_definition()` materializer.** `FlowDefinition` (Pydantic, `parrot/bots/flow/definition.py:288`) exists with a working SvelteFlow adapter (`parrot/bots/flow/svelteflow.py`), but nothing instantiates an executable `AgentsFlow` from it. The visual-editor → execution path is broken.
- **`DecisionFlowNode` does not fit the agent contract.** It returns `DecisionResult` (`parrot/bots/flow/decision_node.py:114`), not free-form agent output. Currently wedged into the flow via `add_agent(decision_node)`. There is no node-type taxonomy.

### Goals

- Replace `parrot/bots/flow/fsm.py` with a new executor at `parrot/bots/flows/flow.py` consuming only `parrot/bots/flows/core/*` and the preserved declarative modules.
- Event-driven scheduler: `asyncio.Queue[CompletionEvent]` with a single consumer; no `asyncio.gather` over the batch; per-node `asyncio.create_task` so fast nodes do not wait for slow siblings.
- **Promote `core.node.AgentNode` (and `StartNode`, `EndNode`, the `Node` ABC) from `@dataclass` to frozen Pydantic `BaseModel`s** with embedded `validate()` + a new `async execute(ctx, deps, **kwargs)` signature. FSM stays as a field on the node (Pydantic `frozen=True` blocks attribute reassignment but allows mutation of nested objects, so `node.fsm.start()` continues to work).
- **Same flow instance is safe to execute concurrently**: `AgentsFlow.run_flow()` materializes a fresh set of `AgentNode` (and other Node) instances per invocation, so concurrent calls do not share FSM state.
- Single `@register_node(name)` decorator that registers a `Node` subclass under `NODE_REGISTRY[name]` — one registration point, no separate executor map.
- `from_definition(definition: FlowDefinition)` materializer with **eager** agent resolution via `AgentRegistry` (`parrot/registry/registry.py:228`).
- Replace `SynthesisMixin` inheritance with `run_flow(on_complete=[...])` hooks plus a new declarative `SynthesisNode`. Both call the shared `synthesize_results` util backed by `SYNTHESIS_PROMPT` (`parrot/bots/flows/core/storage/synthesis.py:23`).
- Cycle detection moved from runtime (`_would_create_cycle` at fsm.py:1252) to a `FlowDefinition.model_validator` (`parrot/bots/flow/definition.py:338` adds cycle check).
- `FlowResult.output` semantics: dict of leaf-node outputs, collapsed to a scalar when exactly one leaf exists.
- **Migrate `parrot/bots/flows/crew/` (the new-home AgentCrew) to the modified `AgentNode` shape**: `CrewAgentNode` converted from `@dataclass` to frozen Pydantic; `execute_in_context()` updated to the new execute signature. Verified scope: ~20–30 LOC across `parrot/bots/flows/crew/nodes.py` (1 class) and `parrot/bots/flows/crew/crew.py` (instantiation site at line 223). `.fsm` access sites in crew.py are **not** touched (FSM stays on the node, so existing `node.fsm.<method>()` calls continue to work unchanged).
- Foundation for future specs (HITL pause/resume, scatter/gather, loops, swarm) — scheduler design must allow a node to yield its task slot without blocking the executor.

### Non-Goals (explicitly out of scope)

- **Dev Loop Flow migration** (`parrot/flows/dev_loop/flow.py`). Deferred to a follow-up spec.
- **Example migration** (`examples/crew/pizza_sushi_flow.py`, `interactive_pizza_sushi_flow.py`, `consensus_synthesis_flow.py`, `simple.py`). Deferred.
- **Relocation of supporting modules** (`decision_node.py`, `interactive_node.py`, `definition.py`, `svelteflow.py`, `actions.py`, `cel_evaluator.py`) from `parrot/bots/flow/` to `parrot/bots/flows/`. Follow-up cleanup spec.
- **`parrot/bots/orchestration/`** — the entire package is on a separate deletion track (legacy code that pre-dates FEAT-143). The `_CrewAgentNode` / `_AgentCrew` there is **not** updated by this spec; the package will be deleted whole in a separate change.
- **Removing `SynthesisMixin` from `AgentCrew`.** Only removed from the new `AgentsFlow`; `AgentCrew` parity is a future spec.
- **HITL pause/resume implementation.** This spec only ensures the scheduler does not preclude it. Implementation in a future HITL spec.
- **`ScatterNode`, `GatherNode`, `LoopNode`.** Future scatter/gather and iteration specs.
- **Multi-agent / swarm patterns.** Future swarm spec.
- **Redis-backed flow state persistence.** Future persistence spec.
- **Migration of legacy `AgentsFlow` API consumers** — Option A and Option B-full were rejected during brainstorm/spec-review (`sdd/proposals/agentsflow-refactor-spec3.brainstorm.md`).
- **Backward compatibility for the `AgentsFlow` public API.** None required.
- **Extracting `fsm` from `AgentNode` into a separate `NodeRunState` class** — that was Option B-full, rejected in favor of B-lite. FSM stays as a field on the node.

---

## 2. Architectural Design

### Overview

A new executor module at `parrot/bots/flows/flow.py` exporting `AgentsFlow(PersistenceMixin)`. It consumes primitives from `parrot.bots.flows.core` exclusively. The legacy `parrot/bots/flow/fsm.py` is **deleted** at the end of the spec.

**Two-layer separation** (B-lite — the brainstorm's "hard split" achieved by re-materialization, not by class duplication):

1. **Declarative layer** (existing, preserved in `parrot/bots/flow/`):
   `FlowDefinition`, `NodeDefinition`, `EdgeDefinition`, `FlowMetadata` (Pydantic). Plus the SvelteFlow adapter, the CEL evaluator, action definitions. This is what visual editors, JSON files, and programmatic builders produce.

2. **Materialized / runtime layer** (modified in `parrot/bots/flows/core/node.py`, extended in `parrot/bots/flows/flow.py`):
   - `Node` ABC (in core/node.py) → frozen Pydantic `BaseModel`. Action-hook lists (`_pre_actions`, `_post_actions`) become `PrivateAttr(default_factory=list)` so the existing imperative `add_pre_action`/`add_post_action` API continues to work on frozen models.
   - `AgentNode` (in core/node.py) → frozen Pydantic. Fields: `agent: AgentLike`, `node_id: str`, `dependencies: set[str]`, `successors: set[str]`, `fsm: Optional[AgentTaskMachine] = None`. `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`. `execute()` signature changes from `(prompt, *, timeout, **ctx)` to `(ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any`. Prompt derivation moves inside `execute()` via an overridable `_build_prompt(ctx, deps)` method (default reads `ctx.get_input_for_agent(self.agent.name, self.dependencies)`).
   - `StartNode`, `EndNode` (in core/node.py) → same Pydantic-frozen treatment.
   - New `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode` (in flow.py) — wrap `DecisionFlowNode`, `InteractiveDecisionNode` (legacy), and the new synthesis util respectively. Each is a `Node` subclass registered via `@register_node(...)`.

   The user's canonical pattern from the brainstorm (carried verbatim) now reads:

   ```python
   # Source: brainstorm Code Context (user-provided, adapted to B-lite)
   @register_node("agent")
   class AgentNode(Node):          # the existing core.node.AgentNode, modified
       agent: AgentLike
       node_id: str
       dependencies: set[str] = Field(default_factory=set)
       successors: set[str] = Field(default_factory=set)
       fsm: Optional[AgentTaskMachine] = None

       model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

       def validate_spec(self) -> None:                       # method, not Pydantic validator
           if not getattr(self.agent, "name", None):
               raise ValueError("agent must have a name")

       async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any:
           prompt = self._build_prompt(ctx, deps)
           return await self.agent.ask(question=prompt, _trusted_source=True, **kwargs)
   ```

**Per-run state** lives where it naturally belongs:

- `fsm` lives on the AgentNode instance (mutates internally on `.start()` / `.succeed()` / `.fail()`).
- `attempts`, `started_at`, `finished_at`, the `asyncio.Task` handle, `result`, `error` — kept in scheduler-internal dicts keyed by `node_id` (no new public class).
- Concurrent-run safety: `AgentsFlow.run_flow()` calls an internal `_materialize_nodes()` that builds a fresh dict of Node instances from the stored `FlowDefinition` on every invocation. Two concurrent `run_flow()` calls on the same `AgentsFlow` get two independent node sets.

**Event-driven scheduler:**

`AgentsFlow.run_flow(ctx, on_complete=[...])`:
1. Materialize a fresh `nodes: dict[node_id, Node]` from the stored `FlowDefinition`.
2. Initialize scheduler dicts: `attempts: dict[node_id, int]`, `tasks: dict[node_id, asyncio.Task]`, counters (`active_count`, `completed_count`, `failed_count`).
3. Enqueue nodes with zero dependencies into the ready set; spawn each via `asyncio.create_task(_run_node(node))`.
4. `_run_node(node)`: call `node.fsm.start()`, run pre-actions, call `node.execute(ctx, deps, **kwargs)`, run post-actions, call `node.fsm.succeed()` (or `.fail()`), push `CompletionEvent(node_id, result | error)` to `completion_queue: asyncio.Queue`.
5. The scheduler coroutine drains `completion_queue`: updates result/error in scheduler dicts, evaluates outgoing transitions via `CELPredicateEvaluator`, spawns downstream tasks, updates incremental counters. No full-graph scans.
6. Loop terminates when `active_count == 0` and `completion_queue.empty()`.
7. Fire `on_complete` hooks in declaration order (awaited; exceptions caught + logged, do not fail the flow).
8. Aggregate `FlowResult` (`parrot/bots/flows/core/result.py:273`):
   - `output`: scalar from the single leaf node, or `dict[node_id → output]` when multiple leaves exist.
   - `nodes`: list of `NodeExecutionInfo`.
   - `responses`: `dict[node_id → response]`.
   - `errors`: `dict[node_id → error_str]` for failed nodes.
   - `status`: derived via `determine_run_status(success_count, failure_count)` (`parrot/bots/flows/core/result.py:162`).

### Component Diagram

```
                parrot/bots/flows/flow.py  (NEW)
                ──────────────────────────────────
                │ AgentsFlow(PersistenceMixin)    │
                │   ├─ NODE_REGISTRY              │
                │   ├─ @register_node decorator   │
                │   ├─ DecisionNode (new wrapper) │
                │   ├─ InteractiveDecisionNode    │
                │   ├─ SynthesisNode              │
                │   ├─ Scheduler (asyncio.Queue)  │
                │   ├─ from_definition()          │
                │   └─ run_flow(on_complete=[])   │
                └──────────────────────────────────┘
                            │ consumes + MODIFIES
                            ▼
   parrot/bots/flows/core/    (EXISTING, MODIFIED in this spec)
   ───────────────────────────────────────────────────────────
   │ node.py (MOD): Node ABC, AgentNode, StartNode, EndNode   │
   │   → frozen Pydantic, new execute(ctx, deps, **kwargs)    │
   │   → fsm stays as field; PrivateAttr for action lists     │
   │ fsm.py        — AgentTaskMachine, TransitionCondition    │
   │ types.py      — AgentRef, FlowStatus, DependencyResults, │
   │                 PromptBuilder, AgentLike                 │
   │ transition.py — FlowTransition                           │
   │ result.py     — FlowResult, NodeResult,                  │
   │                 NodeExecutionInfo,                       │
   │                 build_node_metadata,                     │
   │                 determine_run_status                     │
   │ context.py (MOD): FlowContext — adds resolve_agent()     │
   │ storage/      — ExecutionMemory, PersistenceMixin,       │
   │                 SynthesisMixin (kept; not inherited      │
   │                 by AgentsFlow),                          │
   │                 SYNTHESIS_PROMPT,                        │
   │                 synthesize_results (NEW util)            │
   └───────────────────────────────────────────────────────────┘
                ▲                          ▲
                │ also imports             │ uses
                │                          │
        parrot/bots/flows/crew/   parrot/bots/flow/ (LEGACY, preserved)
        ──────────────────────    ─────────────────────────────────
        │ crew.py (MOD)      │    │ definition.py (MOD: cycle      │
        │   CrewAgentNode    │    │   detection model_validator)   │
        │   updated for      │    │ decision_node.py — DecisionResult,│
        │   new AgentNode    │    │   DecisionMode, DecisionFlowNode  │
        │   shape +          │    │ interactive_node.py             │
        │   execute(ctx,...) │    │ actions.py — ACTION_REGISTRY    │
        │   .fsm sites       │    │ cel_evaluator.py                │
        │   UNCHANGED        │    │ svelteflow.py                   │
        │ nodes.py (MOD)     │    │ fsm.py — DELETED at spec end    │
        └──────────────────────┘    └─────────────────────────────────┘
                            │ resolves agent_ref via
                            ▼
        parrot/registry/registry.py:228 — AgentRegistry
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.flows.core.fsm` | uses | `AgentTaskMachine`, `TransitionCondition` imported (no duplication) |
| `parrot.bots.flows.core.types` | uses | `AgentRef`, `DependencyResults`, `PromptBuilder`, `FlowStatus`, `AgentLike` |
| `parrot.bots.flows.core.transition` | uses | `FlowTransition` |
| `parrot.bots.flows.core.node` | **modifies** | `Node`, `AgentNode`, `StartNode`, `EndNode` reshaped to frozen Pydantic; new `execute(ctx, deps, **kwargs)` signature |
| `parrot.bots.flows.core.result` | uses | `FlowResult`, `NodeResult`, `NodeExecutionInfo`, `build_node_metadata`, `determine_run_status` |
| `parrot.bots.flows.core.context` | extends | `FlowContext` gains `resolve_agent(agent_ref)` helper backed by `AgentRegistry` |
| `parrot.bots.flows.core.storage` | uses | `PersistenceMixin` kept; `SynthesisMixin` NOT inherited by AgentsFlow |
| `parrot.bots.flows.core.storage.synthesis` | extends | `SYNTHESIS_PROMPT` consumed; new `synthesize_results(ctx, result)` util added in the same module |
| `parrot.bots.flows.crew.crew` | **modifies** | `CrewAgentNode` instantiation site at crew.py:223 updated for new constructor shape |
| `parrot.bots.flows.crew.nodes` | **modifies** | `CrewAgentNode` dataclass → frozen Pydantic; `execute_in_context()` signature updated; `_format_prompt` logic migrates into a `_build_prompt(ctx, deps)` override |
| `parrot.bots.flow.definition` | extends | New `@model_validator(mode="after")` for cycle detection on `FlowDefinition` |
| `parrot.bots.flow.actions` | uses | `ACTION_REGISTRY`, `register_action` for pre/post-action hooks |
| `parrot.bots.flow.cel_evaluator` | uses | `CELPredicateEvaluator` for transition predicates |
| `parrot.bots.flow.decision_node` | wraps | `DecisionFlowNode` + `DecisionResult` consumed by a new `DecisionNode(Node)` wrapper in `flow.py` |
| `parrot.bots.flow.interactive_node` | wraps | Same pattern as `DecisionNode` |
| `parrot.bots.flow.svelteflow` | uses | Round-trip target for visual editor; no changes |
| `parrot.registry.registry` | uses | `AgentRegistry` for eager agent resolution at `from_definition()` time |
| `parrot.bots.flow.fsm` | **deletes** | Entire file removed at end of spec |
| `parrot.bots.flow.loader` | **modifies** | Update its `from .fsm import AgentsFlow, TransitionCondition` to point at new locations |
| `parrot.flows.dev_loop.flow` | independent (deferred) | Out of scope; broken at end of spec; documented follow-up |
| `parrot.bots.orchestration.*` | **untouched** | Entire package on a separate deletion track. Do not modify here. |
| `parrot.manager.manager.BotManager` | independent | `get_bot` not used by the new executor (resolver is `AgentRegistry`) |

### Data Models

```python
# parrot/bots/flows/core/node.py — modified shape.

class Node(BaseModel, ABC):
    """Abstract base for all flow nodes (frozen, Pydantic)."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    node_id: str
    _pre_actions: list = PrivateAttr(default_factory=list)
    _post_actions: list = PrivateAttr(default_factory=list)

    @property
    @abstractmethod
    def name(self) -> str: ...

    def add_pre_action(self, action: ActionCallback) -> None: ...
    def add_post_action(self, action: ActionCallback) -> None: ...
    async def run_pre_actions(self, prompt: str = "", **ctx) -> None: ...
    async def run_post_actions(self, result=None, **ctx) -> None: ...


class AgentNode(Node):
    """Graph node wrapping an AgentLike agent + AgentTaskMachine FSM."""
    agent: AgentLike
    node_id: str
    dependencies: set[str] = Field(default_factory=set)
    successors: set[str] = Field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = None

    def model_post_init(self, __context) -> None:
        if self.fsm is None:
            object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.agent.name))

    @property
    def name(self) -> str:
        return self.agent.name

    def _build_prompt(self, ctx: FlowContext, deps: DependencyResults) -> str:
        """Default prompt derivation. Subclasses may override."""
        return ctx.get_input_for_agent(self.agent.name, self.dependencies)

    async def execute(
        self,
        ctx: FlowContext,
        deps: DependencyResults,
        **kwargs,
    ) -> Any:
        prompt = self._build_prompt(ctx, deps)
        await self.run_pre_actions(prompt=prompt, **kwargs)
        # ... call self.agent.ask(question=prompt, ...) ...
        # ... await self.run_post_actions(result=response, **kwargs) ...
        # FSM transitions are managed externally by the scheduler.
```

```python
# parrot/bots/flows/flow.py — sketch.

NODE_REGISTRY: dict[str, type[Node]] = {}

def register_node(name: str) -> Callable[[type[Node]], type[Node]]:
    """Decorator. Registers a Node subclass under `name` in NODE_REGISTRY.

    Raises ValueError on duplicate `name`. Raises TypeError if the class
    is not a Node subclass.
    """
    ...

# Built-ins registered by this spec:
#   @register_node("agent")               → AgentNode (from core.node)
#   @register_node("start")               → StartNode (from core.node)
#   @register_node("end")                 → EndNode   (from core.node)
#   @register_node("decision")            → DecisionNode (NEW, in flow.py)
#   @register_node("interactive_decision")→ InteractiveDecisionNode (NEW, in flow.py)
#   @register_node("synthesis")           → SynthesisNode (NEW, in flow.py)


@dataclass
class CompletionEvent:
    node_id: str
    result: Any = None
    error: BaseException | None = None
```

### New Public Interfaces

```python
# parrot/bots/flows/flow.py
class AgentsFlow(PersistenceMixin):
    def __init__(
        self,
        name: str,
        *,
        definition: FlowDefinition | None = None,
        agent_registry: AgentRegistry | None = None,
        **kwargs,
    ): ...

    def add_node(self, node: Node) -> None:
        """Programmatic builder: add a Node instance to the graph."""

    @classmethod
    def from_definition(
        cls,
        definition: FlowDefinition,
        *,
        agent_registry: AgentRegistry | None = None,
    ) -> "AgentsFlow":
        """Materialize an executable flow from a FlowDefinition.

        Eagerly resolves every NodeDefinition.agent_ref against AgentRegistry.
        Raises AgentNotFoundError on the first unresolved ref. The flow stores
        the FlowDefinition; node instances are re-materialized fresh inside
        each run_flow() call (concurrent-run safety).
        """

    async def run_flow(
        self,
        ctx: FlowContext | None = None,
        *,
        on_complete: list[Callable[[FlowContext, FlowResult], Awaitable[None]]] = (),
    ) -> FlowResult:
        """Run the flow. Internally materializes a fresh node set per call."""

# parrot/bots/flows/core/storage/synthesis.py — new util alongside existing SYNTHESIS_PROMPT
async def synthesize_results(ctx: FlowContext, result: FlowResult) -> str:
    """Shared util. Builds an LLM prompt from SYNTHESIS_PROMPT, calls ctx's
    synthesis client, returns the summary string. Used by both the on_complete
    hook and SynthesisNode.execute()."""

# parrot/bots/flow/definition.py — new model_validator
class FlowDefinition(BaseModel):
    ...
    @model_validator(mode="after")
    def _validate_acyclic(self) -> "FlowDefinition":
        """Detect cycles in the (nodes, edges) graph. Raises ValueError on cycle."""

# parrot/bots/flows/core/context.py — extension
class FlowContext:
    ...
    def resolve_agent(self, agent_ref: AgentRef) -> AgentLike:
        """Resolve an agent_ref string against the bound AgentRegistry.

        Raises AgentNotFoundError if not registered.
        """
```

---

## 3. Module Breakdown

### Module 1: Reshape `core.node` — Node ABC and built-in subclasses
- **Path**: `parrot/bots/flows/core/node.py`

…(truncated)…
