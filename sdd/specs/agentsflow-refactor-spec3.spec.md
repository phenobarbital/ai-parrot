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
- **Responsibility**: Convert `Node` ABC, `AgentNode`, `StartNode`, `EndNode` from `@dataclass` to frozen Pydantic `BaseModel` (`ConfigDict(frozen=True, arbitrary_types_allowed=True)`). Move `_pre_actions`/`_post_actions` to `PrivateAttr(default_factory=list)`. Change `AgentNode.execute()` signature from `(prompt, *, timeout, **ctx)` to `(ctx, deps, **kwargs)`. Add overridable `_build_prompt(ctx, deps)`. Use `model_post_init` for FSM auto-creation.
- **Depends on**: existing `core.fsm.AgentTaskMachine`, `core.types.{AgentLike, ActionCallback, DependencyResults}`, `core.context.FlowContext` (forward ref).

### Module 2: `FlowContext.resolve_agent` helper
- **Path**: `parrot/bots/flows/core/context.py`
- **Responsibility**: Extend `FlowContext` (currently at line 26) with `resolve_agent(self, agent_ref: AgentRef) -> AgentLike` that delegates to the bound `AgentRegistry`. Add `agent_registry` to context init.
- **Depends on**: `parrot.registry.registry.AgentRegistry`. Module 1 (forward type ref).

### Module 3: Migrate `parrot/bots/flows/crew/` to the new AgentNode shape
- **Path**: `parrot/bots/flows/crew/nodes.py` + `parrot/bots/flows/crew/crew.py`
- **Responsibility**:
  - `CrewAgentNode(_CoreAgentNode)`: convert from `@dataclass` to Pydantic; move the `_format_prompt(input_data)` logic into a `_build_prompt(ctx, deps)` override (cleaner — derives `input_data` directly from `ctx.get_input_for_agent(...)` then formats). Delete `execute_in_context(context, timeout)` — callers now call `node.execute(ctx, deps)`. If timeout is needed, pass via `**kwargs`.
  - `crew.py:223` instantiation site: update kwargs to match new Pydantic constructor (named-field assignment continues to work; verify no `field(default_factory=...)` references in caller code).
  - `.fsm` access sites in `crew.py` (12 locations: lines 567–570, 586–587, 649–650, 1102–1104, 1202–1203, 1212–1213): **untouched** — FSM stays on the node, existing pattern continues to work.
- **Depends on**: Module 1.

### Module 4: `NODE_REGISTRY` & `@register_node` decorator
- **Path**: `parrot/bots/flows/flow.py` (top of file)
- **Responsibility**: Define `NODE_REGISTRY: dict[str, type[Node]]`. Implement `@register_node(name)` decorator validating that the decorated class is a `Node` subclass; raise `ValueError` on duplicate name; raise `TypeError` on non-Node class. Apply the decorator to `AgentNode`, `StartNode`, `EndNode` (imported from `core.node`) at module load.
- **Depends on**: Module 1.

### Module 5: New Node subclasses — `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode`
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**:
  - `DecisionNode(Node)`: wraps the legacy `parrot.bots.flow.decision_node.DecisionFlowNode`. Fields: configuration for the decision (mode, voters, escalation policy). `execute(ctx, deps, **kwargs)` delegates to the underlying `DecisionFlowNode.ask(...)` and returns its `DecisionResult`. CEL predicates downstream read `result.final_decision`.
  - `InteractiveDecisionNode(Node)`: similar wrapper for `parrot.bots.flow.interactive_node.InteractiveDecisionNode`.
  - `SynthesisNode(Node)`: `execute(ctx, deps, **kwargs)` calls `synthesize_results(ctx, accumulated_result_so_far)` (Module 7) and returns its string. Used inside the DAG for in-graph summarization.
- **Depends on**: Modules 1, 4; existing `decision_node.py`, `interactive_node.py`; Module 7 (for SynthesisNode).

### Module 6: Event-driven Scheduler
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**: Implement `AgentsFlow.__init__`, `add_node`, `run_flow`. Inside `run_flow`: materialize fresh node set from stored `FlowDefinition` (concurrent-safe), build scheduler dicts, manage `completion_queue: asyncio.Queue`, spawn per-node tasks (`asyncio.create_task`), drain events, evaluate transitions via `CELPredicateEvaluator`, maintain incremental counters, terminate on quiescence, fire `on_complete` hooks, aggregate `FlowResult` (scalar vs dict output rule). FSM transitions called directly on the node: `node.fsm.start()`, `node.fsm.succeed()` / `.fail()`. No `asyncio.gather` over the batch; no full-graph scans.
- **Depends on**: Modules 1, 4, 5; `parrot.bots.flow.cel_evaluator.CELPredicateEvaluator`; `core.result.{FlowResult, NodeResult, NodeExecutionInfo, build_node_metadata, determine_run_status}`.

### Module 7: Synthesis util
- **Path**: `parrot/bots/flows/core/storage/synthesis.py` (extend existing file)
- **Responsibility**: Add `async def synthesize_results(ctx: FlowContext, result: FlowResult) -> str` reusing existing `SYNTHESIS_PROMPT` (synthesis.py:23). The function builds a prompt, calls the synthesis LLM client available via `ctx`, returns the summary string. `SynthesisMixin` (synthesis.py:34) stays in place for AgentCrew.
- **Depends on**: existing `SYNTHESIS_PROMPT`; `core.context.FlowContext`; `core.result.FlowResult`.

### Module 8: `from_definition()` materializer with eager agent resolution
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**: `AgentsFlow.from_definition(definition, agent_registry=None)`: walk `FlowDefinition.nodes`, look up node class via `NODE_REGISTRY[node_def.node_type]`, **eagerly** call `agent_registry.get_agent(agent_ref)` for every node with a non-empty `agent_ref` (raising `AgentNotFoundError` on the first miss). The materialized flow stores the `FlowDefinition` (not the instantiated Node set), so each `run_flow()` call re-instantiates a fresh set. Build edge index. Return the executable `AgentsFlow`.
- **Depends on**: Modules 1, 4, 5; `parrot.bots.flow.definition.FlowDefinition`; `parrot.registry.registry.AgentRegistry`.

### Module 9: Cycle detection in `FlowDefinition`
- **Path**: `parrot/bots/flow/definition.py`
- **Responsibility**: Add `@model_validator(mode="after")` to `FlowDefinition` (alongside existing `validate_node_ids` at definition.py:338). Build adjacency list from `self.edges`, run DFS / Kahn's algorithm, raise `ValueError("Cycle detected: <node_ids>")` on cycle.
- **Depends on**: existing `FlowDefinition` (definition.py:288), `EdgeDefinition` (definition.py:187).

### Module 10: Legacy `fsm.py` deletion + loader update
- **Path**: `parrot/bots/flow/fsm.py` (deleted); `parrot/bots/flow/loader.py` (modified)
- **Responsibility**: Delete `parrot/bots/flow/fsm.py` entirely. Update `parrot/bots/flow/loader.py`: replace `from .fsm import AgentsFlow, TransitionCondition` with `from parrot.bots.flows.flow import AgentsFlow` + `from parrot.bots.flows.core.fsm import TransitionCondition`. Delete the broken legacy tests (`test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py`, `test_decision_node.py` — verify exact list at impl time).
- **Depends on**: Modules 1–8 stable.

### Module 11: Integration test suite
- **Path**: `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` (or `tests/bots/flows/...` matching existing convention; verify at impl time).
- **Responsibility**: 7 integration tests against the new `AgentsFlow` API — see §4.
- **Depends on**: Modules 1–9.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_node_frozen_blocks_reassignment` | 1 | `node.node_id = "new"` raises (frozen Pydantic). |
| `test_node_fsm_state_mutates` | 1 | `node.fsm.start()` works on a frozen node (nested mutation allowed). |
| `test_node_action_lists_use_privateattr` | 1 | `node.add_pre_action(cb)` succeeds on a frozen node; `node._pre_actions` contains `cb`. |
| `test_agent_node_new_execute_signature` | 1 | `AgentNode.execute(ctx, deps)` is callable; legacy `(prompt, *, timeout)` form raises. |
| `test_agent_node_build_prompt_default` | 1 | Default `_build_prompt(ctx, deps)` calls `ctx.get_input_for_agent(...)`. |
| `test_flow_context_resolve_agent_ok` | 2 | `ctx.resolve_agent("name")` returns the registered agent. |
| `test_flow_context_resolve_agent_missing` | 2 | Unregistered ref raises `AgentNotFoundError`. |
| `test_crew_agent_node_pydantic_construct` | 3 | `CrewAgentNode(agent=..., node_id=..., dependencies=..., successors=...)` constructs via Pydantic kwargs. |
| `test_crew_agent_node_build_prompt_override` | 3 | `CrewAgentNode._build_prompt(ctx, deps)` formats input_data into the legacy crew prompt shape (parity with old `_format_prompt`). |
| `test_register_node_decorator_registers` | 4 | `@register_node("foo")` adds the class to `NODE_REGISTRY["foo"]`. |
| `test_register_node_rejects_duplicate` | 4 | Re-registering `"foo"` raises `ValueError`. |
| `test_register_node_rejects_non_node` | 4 | Decorating a non-`Node` class raises `TypeError`. |
| `test_decision_node_wraps_decisionflownode` | 5 | `DecisionNode.execute` returns a `DecisionResult` from the wrapped `DecisionFlowNode`. |
| `test_synthesis_node_calls_util` | 5 | `SynthesisNode.execute` calls `synthesize_results` and returns its string. |
| `test_scheduler_no_asyncio_gather` | 6 | Grep / inspect the scheduler code: no `asyncio.gather` over the per-batch task set. |
| `test_scheduler_incremental_counters` | 6 | Spy on the counter logic: `active_count` decrements on each completion; no full-graph scan called. |
| `test_run_flow_output_scalar_single_leaf` | 6 | Linear DAG returns `FlowResult.output` as a scalar. |
| `test_run_flow_output_dict_multiple_leaves` | 6 | Branching DAG with two leaves returns `FlowResult.output` as `dict[node_id → value]`. |
| `test_run_flow_concurrent_same_instance` | 6 | Two concurrent `await flow.run_flow(...)` calls on the same `AgentsFlow` instance do NOT share FSM state (separate `_materialize_nodes()` per call). |
| `test_on_complete_hook_runs` | 6 | Hook in `on_complete=[...]` is awaited exactly once after the flow terminates. |
| `test_on_complete_hook_exception_does_not_fail_flow` | 6 | Hook raising `RuntimeError` is caught + logged; `FlowResult.status` reflects success. |
| `test_synthesize_results_util_uses_prompt` | 7 | `synthesize_results(ctx, result)` calls into the synthesis prompt template; returns a string. |
| `test_from_definition_eager_resolve_ok` | 8 | All `agent_ref`s resolvable → returns an executable `AgentsFlow`. |
| `test_from_definition_eager_resolve_missing` | 8 | One unresolvable `agent_ref` → raises `AgentNotFoundError` at construction (before `run_flow`). |
| `test_flowdefinition_rejects_cycle` | 9 | `FlowDefinition` with `A → B → A` raises `ValueError` at model validation. |
| `test_flowdefinition_accepts_dag` | 9 | A valid acyclic graph constructs without error. |
| `test_loader_imports_from_new_location` | 10 | After Module 10, `parrot.bots.flow.loader` imports `AgentsFlow` from the new path. |

### Integration Tests

(One file, e.g. `tests/bots/flows/test_agents_flow.py`. Match the convention in `tests/bots/flows/core/`.)

| Test | Description |
|---|---|
| `test_linear_flow` | 3-node A→B→C with mocked agents; assert sequential execution, final `output` is scalar. |
| `test_branching_fan_out` | A→{B, C}; assert B and C start as soon as A completes (not after a slow sibling); both run concurrently. |
| `test_branching_fan_in` | {A, B}→C; assert C starts only after both A and B complete; `DependencyResults` contains both. |
| `test_conditional_routing_cel` | A→B with a CEL predicate `result.value > 10`; assert routing fires correctly on pass, short-circuits on fail. |
| `test_retry_on_failure` | A node with `max_retries=2` that fails once then succeeds; assert one retry, final status success. |
| `test_decision_node_routing` | `DecisionNode` returns `DecisionResult.final_decision = "approve"`; CEL predicate `result.final_decision == "approve"` routes to the approval branch. |
| `test_on_complete_hook_fires` | `run_flow(on_complete=[record_hook])` — assert `record_hook` was awaited with `(ctx, result)` exactly once. |

### Test Data / Fixtures

```python
# packages/ai-parrot/tests/bots/flows/conftest.py — additions
@pytest.fixture
def stub_agent_registry():
    """In-memory AgentRegistry pre-populated with deterministic mock agents."""
    ...

@pytest.fixture
def mock_agent_factory(stub_agent_registry):
    """Returns a function that creates and registers a mock agent with a scripted reply."""
    ...

@pytest.fixture
def flow_context(stub_agent_registry):
    """FlowContext wired to the stub registry."""
    return FlowContext(agent_registry=stub_agent_registry)
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true.

- [ ] **New module exists**: `parrot/bots/flows/flow.py` exports `AgentsFlow`, `NODE_REGISTRY`, `register_node`, `DecisionNode`, `InteractiveDecisionNode`, `SynthesisNode`, `CompletionEvent`.
- [ ] **Legacy file deleted**: `parrot/bots/flow/fsm.py` no longer exists. `parrot/bots/flow/loader.py` updated.
- [ ] **No duplication**: `AgentTaskMachine`, `TransitionCondition`, `AgentRef`, `DependencyResults`, `PromptBuilder`, `FlowTransition` are imported from `parrot.bots.flows.core.*` only — `grep` confirms no local redefinition in `parrot/bots/flows/flow.py`.
- [ ] **Inheritance**: `AgentsFlow` inherits from `PersistenceMixin` only (NOT `SynthesisMixin`).
- [ ] **Scheduler is event-driven**: no `await asyncio.sleep(...)` in `run_flow`'s main loop; no `asyncio.gather` over the batch; per-node `asyncio.create_task` + single `asyncio.Queue` consumer.
- [ ] **No full-graph scans**: equivalents of `_get_ready_agents` / `_is_workflow_complete` / `_has_active_agents` are NOT re-introduced; readiness/termination is event-driven and counters are incremental.
- [ ] **`core.node.Node`, `AgentNode`, `StartNode`, `EndNode` are frozen Pydantic** (`model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`). `node.field = x` raises; `node.fsm.start()` works.
- [ ] **`AgentNode.execute` signature** is `(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any`. Default prompt derivation lives in `_build_prompt(ctx, deps)`, overridable by subclasses.
- [ ] **Concurrent-run safety**: `await asyncio.gather(flow.run_flow(), flow.run_flow())` on the same `AgentsFlow` instance produces independent FSM state — covered by `test_run_flow_concurrent_same_instance`.
- [ ] **`@register_node` decorator**: single decorator registers a `Node` subclass; duplicate registration raises `ValueError`; non-`Node` registration raises `TypeError`.
- [ ] **`from_definition()` works and is eager**: `AgentsFlow.from_definition(flow_def)` materializes an executable flow; an unresolved `agent_ref` raises `AgentNotFoundError` at `from_definition` time, not at `run_flow` time.
- [ ] **`FlowResult.output` semantics**: scalar when exactly one leaf; dict when multiple leaves.
- [ ] **`on_complete` hooks**: `run_flow(on_complete=[…])` accepts and awaits each hook after termination; hook exceptions are caught and logged, do not fail the flow.
- [ ] **`SynthesisMixin` replaced**: `synthesize_results(ctx, result)` util added in `parrot/bots/flows/core/storage/synthesis.py`; `SynthesisNode` calls the same util; old `SynthesisMixin` is no longer inherited by `AgentsFlow` (kept for `AgentCrew`).
- [ ] **Cycle detection**: `FlowDefinition` rejects cyclic graphs at model validation (new `@model_validator(mode="after")` in `parrot/bots/flow/definition.py`); the runtime cycle check `_would_create_cycle` is gone with `fsm.py`.
- [ ] **Decision nodes**: `DecisionFlowNode` and `InteractiveDecisionNode` (legacy) consumed via new `DecisionNode` / `InteractiveDecisionNode` wrappers registered with `@register_node`. Their `DecisionResult` output flows through CEL predicates unchanged.
- [ ] **AgentCrew migrated (flows/crew only)**: `parrot/bots/flows/crew/nodes.py:CrewAgentNode` converted to Pydantic; `_format_prompt` logic moved into `_build_prompt(ctx, deps)` override; `execute_in_context` removed; instantiation site at `parrot/bots/flows/crew/crew.py:223` updated. **AgentCrew tests still pass** (regression check).
- [ ] **`parrot/bots/orchestration/` untouched** — verified by `git diff`. Out of scope per non-goal.
- [ ] **All ~27 unit tests pass.**
- [ ] **All 7 integration tests pass.**
- [ ] **No new external dependencies introduced** (verified by `git diff pyproject.toml`).
- [ ] **Documentation**: a docstring at the top of `parrot/bots/flows/flow.py` summarizes the architecture and links the brainstorm doc.
- [ ] **Out-of-scope migrations documented**: `parrot/flows/dev_loop/flow.py` and `examples/crew/*flow*.py` are explicitly listed as known-broken in the PR description.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was verified
> via `grep` / `read` against the working tree on 2026-05-11.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist.
>
> **Filesystem note**: this is a monorepo. Python import paths
> `parrot.X.Y` resolve to filesystem paths
> `packages/ai-parrot/src/parrot/X/Y.py`. Below, paths shown without the
> `packages/ai-parrot/src/` prefix are Python-package-relative.

### Verified Imports (use these verbatim)

```python
# Imports the new parrot/bots/flows/flow.py will use:
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
# (parrot/bots/flows/core/fsm.py:17, :40 — verified)

from parrot.bots.flows.core.types import (
    AgentRef, DependencyResults, PromptBuilder, FlowStatus, ActionCallback, AgentLike,
)
# (parrot/bots/flows/core/types.py:27, :30, :38, :55, :100, :103 — verified)

from parrot.bots.flows.core.transition import FlowTransition
# (parrot/bots/flows/core/transition.py:28 — verified)

from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
# (parrot/bots/flows/core/node.py:34, :144, :250, :305 — verified; MODIFIED by this spec)

from parrot.bots.flows.core.result import (
    FlowResult, NodeResult, NodeExecutionInfo,
    build_node_metadata, determine_run_status,
)
# (parrot/bots/flows/core/result.py:39, :162, :190, :273, :527 — verified)

from parrot.bots.flows.core.context import FlowContext
# (parrot/bots/flows/core/context.py:26 — verified; EXTENDED by this spec with resolve_agent)

from parrot.bots.flows.core.storage import (
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)
# (parrot/bots/flows/core/storage/__init__.py — re-exports verified)

from parrot.bots.flows.core.storage.synthesis import SYNTHESIS_PROMPT
# (parrot/bots/flows/core/storage/synthesis.py:23 — verified)
# synthesize_results: ADDED by this spec in the same module.

from parrot.bots.flow.definition import (
    FlowDefinition, NodeDefinition, EdgeDefinition, NodePosition, FlowMetadata,
)
# (parrot/bots/flow/definition.py:288, :124, :187, :118, :246 — verified)

from parrot.bots.flow.actions import ACTION_REGISTRY, register_action
# (parrot/bots/flow/actions.py:46, :49 — verified)

from parrot.bots.flow.cel_evaluator import CELPredicateEvaluator
# (parrot/bots/flow/cel_evaluator.py — class exists)

from parrot.bots.flow.decision_node import (
    DecisionMode, DecisionResult, DecisionFlowNode, DecisionNodeConfig,
)
# (parrot/bots/flow/decision_node.py:26, :114, :238, :192 — verified)
# NOTE: the legacy class is DecisionFlowNode, NOT "DecisionNode".

from parrot.bots.flow.interactive_node import InteractiveDecisionNode as LegacyInteractiveDecisionNode
# (parrot/bots/flow/interactive_node.py — verified)
# Aliased on import to avoid colliding with the new flow.py InteractiveDecisionNode wrapper.

from parrot.bots.flow.svelteflow import to_svelteflow
# (parrot/bots/flow/svelteflow.py — verified)

from parrot.registry.registry import AgentRegistry
# (parrot/registry/registry.py:228 — verified)
```

### Existing Class Signatures (current shape — to be MODIFIED by this spec)

```python
# parrot/bots/flows/core/node.py — current shape (MODIFIED in Module 1)
@dataclass
class Node(ABC):                                         # line 34
    node_id: str
    _pre_actions: list                                   # initialized in _init_node
    _post_actions: list

@dataclass
class AgentNode(Node):                                   # line 144
    agent: AgentLike
    node_id: str
    dependencies: Set[str] = field(default_factory=set)
    successors: Set[str] = field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = field(default=None)

    async def execute(self, prompt: str, *, timeout=None, **ctx) -> Dict[str, Any]: ...
    # NEW signature: (self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any

class StartNode(Node):                                   # line 250
class EndNode(Node):                                     # line 305

# parrot/bots/flows/crew/nodes.py — current shape (MODIFIED in Module 3)
@dataclass
class CrewAgentNode(_CoreAgentNode):
    def _format_prompt(self, input_data: Dict[str, Any]) -> str: ...
    async def execute_in_context(self, context: FlowContext, timeout=None) -> Any: ...
    # After Module 3: Pydantic; _format_prompt becomes _build_prompt(ctx, deps); execute_in_context removed.

# parrot/bots/flow/fsm.py — TO DELETE at end of spec
class TransitionCondition(str, Enum):                    # line 52  (duplicate)
class AgentTaskMachine(StateMachine):                    # line 61  (duplicate)
class FlowTransition:                                    # line 117 (duplicate)
class FlowNode(Node):                                    # line 199 (replaced by modified AgentNode)
class AgentsFlow(PersistenceMixin, SynthesisMixin):      # line 278 (replaced; new inherits PersistenceMixin only)

# parrot/bots/flows/core/fsm.py — source of truth
class TransitionCondition(str, Enum):                    # line 17
class AgentTaskMachine(StateMachine):                    # line 40

# parrot/bots/flows/core/transition.py
class FlowTransition:                                    # line 28

# parrot/bots/flows/core/result.py
class NodeResult:                                        # line 39
def determine_run_status(...) -> ...:                    # line 162
class NodeExecutionInfo:                                 # line 190
class FlowResult:                                        # line 273
def build_node_metadata(...) -> ...:                     # line 527

# parrot/bots/flows/core/context.py
class FlowContext:                                       # line 26 — EXTEND with resolve_agent()

# parrot/bots/flows/core/storage/synthesis.py
SYNTHESIS_PROMPT = """Based on the research findings ..."""  # line 23
class SynthesisMixin:                                    # line 34 — KEPT for AgentCrew, NOT inherited by new AgentsFlow

# parrot/bots/flows/core/storage/__init__.py
# re-exports: ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin

# parrot/bots/flows/crew/crew.py  — reference pattern + MODIFIED in Module 3
class AgentCrew(PersistenceMixin, SynthesisMixin):       # line 87
# Imports from `..core.storage`, `..core.context`, `..core.types`, `..core.fsm`, `..core.result`.
# Lines 567–570, 586–587, 649–650, 1102–1104, 1202–1203, 1212–1213 access `node.fsm.*` — UNCHANGED by this spec.

# parrot/bots/flow/definition.py
class NodePosition(BaseModel):                           # line 118
class NodeDefinition(BaseModel):                         # line 124
#   agent_ref: Optional[str]                             # field present
class EdgeDefinition(BaseModel):                         # line 187
class FlowMetadata(BaseModel):                           # line 246
class FlowDefinition(BaseModel):                         # line 288
#   @model_validator(mode="after") validate_node_ids     # line 338 — existing: references only
#                                                        # ADD: new model_validator for cycles

# parrot/bots/flow/decision_node.py
class DecisionMode(str, Enum):                           # line 26
class DecisionType(str, Enum):                           # line 34
class VoteWeight(str, Enum):                             # line 43
class DecisionResult(BaseModel):                         # line 114
#   decision_id: str                                     # default_factory=uuid4
#   mode: DecisionMode
#   final_decision: Any                                  # what CEL predicates read
#   confidence: float (0..1, default 1.0)
#   votes: Dict[str, Any]
#   vote_distribution: Dict[str, int]
#   consensus_level: Optional[str]
#   escalated: bool
#   escalation_reason: Optional[str]
#   agent_responses: Dict[str, Any]
#   execution_time: float
#   metadata: Dict[str, Any]
class DecisionNodeConfig(BaseModel):                     # line 192
class DecisionFlowNode(Node):                            # line 238 — the legacy class name is DecisionFlowNode

# parrot/registry/registry.py
class AgentRegistry:                                     # line 228 — single resolver source

# parrot/bots/flow/actions.py
ACTION_REGISTRY: Dict[str, Type["BaseAction"]]           # line 46
def register_action(action_type: str)                    # line 49
class BaseAction(ABC):                                   # line 71
# Built-in actions: LogAction (112), NotifyAction (160), WebhookAction (206),
# MetricAction (261), SetContextAction (297), ValidateAction (366), TransformAction (421).
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `AgentsFlow.__init__` | `PersistenceMixin.__init__` | super() chain | `parrot/bots/flows/core/storage/persistence.py` (existing) |
| `AgentsFlow.run_flow` | `AgentTaskMachine` | per-node FSM instance on the materialized node | `parrot/bots/flows/core/fsm.py:40` |
| `AgentsFlow.run_flow` | `CELPredicateEvaluator.evaluate` | transition predicate eval | `parrot/bots/flow/cel_evaluator.py` |
| `AgentsFlow.from_definition` | `AgentRegistry.get_agent` (method name to verify) | eager resolution per `agent_ref` | `parrot/registry/registry.py:228` |
| `AgentNode.execute` (modified) | `FlowContext.resolve_agent` (or direct `self.agent`) | new execute signature | `parrot/bots/flows/core/context.py:26` (extended) |
| `AgentNode.execute` (modified) | `self.agent.ask(question=prompt, ...)` | actual agent call | existing `AgentLike` protocol at `core/types.py:55` |
| `DecisionNode.execute` | `DecisionFlowNode.ask` | delegated call | `parrot/bots/flow/decision_node.py:238` |
| `SynthesisNode.execute` | `synthesize_results` util | shared util | `parrot/bots/flows/core/storage/synthesis.py` (added in Module 7) |
| `run_flow` aggregation | `build_node_metadata`, `determine_run_status` | result assembly | `parrot/bots/flows/core/result.py:527`, `:162` |
| `FlowDefinition` cycle validator | `EdgeDefinition.source`/`target` | DFS over adjacency list | `parrot/bots/flow/definition.py:187, :288` |
| `CrewAgentNode._build_prompt` (modified) | `ctx.get_input_for_agent(...)` | derives input_data | `parrot/bots/flows/core/context.py` (existing method on FlowContext) |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.bots.flow.decision_node.DecisionNode`~~ — the legacy class is `DecisionFlowNode`. The new wrapper in `parrot/bots/flows/flow.py` IS called `DecisionNode` (different module path).
- ~~`AgentsFlow.from_definition()` (current)~~ — does not exist on the legacy `AgentsFlow`. Added in this spec.
- ~~`AgentCrew.from_definition()`~~ — does not exist either. Out of scope.
- ~~`BotManager.get_agent()`~~ — the method is `BotManager.get_bot()` (`parrot/manager/manager.py:601`). The new executor does NOT use `BotManager`.
- ~~`FlowDefinition` cycle validator (current)~~ — `validate_node_ids` at definition.py:338 only checks reference integrity, NOT acyclicity. Added in this spec.
- ~~`SynthesisMixin` on the new `AgentsFlow`~~ — explicitly dropped. Still inherited by `AgentCrew` (`parrot/bots/flows/crew/crew.py:87`) and unchanged there.
- ~~`parrot.models.crew.AgentResult`~~ — present in legacy import list at `fsm.py:33`. The new module does not import it.
- ~~`parrot.models.crew.build_agent_metadata`~~ — superseded by `parrot.bots.flows.core.result.build_node_metadata` (result.py:527).
- ~~`parrot.bots.flows.crew.py`~~ — it is a package: `parrot/bots/flows/crew/crew.py`.
- ~~`parrot.bots.flows.synthesis`~~ — does not exist. Synthesis util lives at `parrot/bots/flows/core/storage/synthesis.py` alongside `SYNTHESIS_PROMPT` and `SynthesisMixin`.
- ~~`DecisionResult.reasoning`, `DecisionResult.raw_response`~~ — not real fields. Use the verified fields listed above.
- ~~A new `NodeSpec` ABC~~ — was in earlier draft; B-lite collapses it. There is no `NodeSpec` class. The "spec" role is played by `FlowDefinition`/`NodeDefinition`; the "node" role is played by the modified `core.node.AgentNode` and friends.
- ~~A new `NodeRunState` class~~ — rejected with B-full. Per-run state lives on the Node instance (FSM) and in scheduler-internal dicts (attempts, timings).
- ~~`AgentNodeSpec`, `DecisionNodeSpec`, etc.~~ — earlier draft used `…Spec` suffixes to avoid name collision. B-lite eliminates the collision (the registered class IS the modified `AgentNode`).
- ~~`asyncio.gather` in the new scheduler~~ — explicitly forbidden by acceptance criterion.
- ~~Generic `AgentsFlow.add_node()` on the legacy file~~ — legacy has `add_agent`, `add_start_node`, `add_end_node` separately. The new executor introduces a polymorphic `add_node(node: Node)`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Imports from `flows.core`** — mirror `AgentCrew`'s relative-import style:
  ```python
  from .core.fsm import AgentTaskMachine
  from .core.node import AgentNode, StartNode, EndNode, Node
  from .core.storage import PersistenceMixin
  ```
  (Same package depth as `parrot/bots/flows/crew/crew.py` — confirmed by reading its top-of-file imports.)
- **Pydantic frozen for Node and subclasses** — `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)`. `arbitrary_types_allowed` needed for `AgentLike` (Protocol), `AgentTaskMachine` (StateMachine subclass), and other non-Pydantic types.
- **`PrivateAttr(default_factory=list)`** for `_pre_actions` / `_post_actions` — survives `frozen=True` because `PrivateAttr` is initialized via `__init__` but not exposed in model schema or validation.
- **`model_post_init(__context)`** for AgentNode FSM auto-creation when `fsm=None` (replaces dataclass `__post_init__`). Use `object.__setattr__(self, "fsm", ...)` to bypass frozen-attribute protection within the post-init hook.
- **`asyncio.Queue` over polling** — the queue is a `Queue[CompletionEvent]`; no timeouts; the scheduler awaits `queue.get()` directly. Termination via incremental counters.
- **Per-node `asyncio.create_task`** — store the task on the scheduler dict for cancellation; do NOT call `asyncio.gather` on the task set.
- **Exception isolation** — task wrappers catch all exceptions, attach them to `CompletionEvent.error`, push to queue. Node exceptions never escape the executor.
- **Logging** — `self.logger = logging.getLogger(__name__)` at module top.
- **CEL evaluator reuse** — instantiate `CELPredicateEvaluator` once per `AgentsFlow`; pass results dict from scheduler state for predicate evaluation.
- **Materialize per run** — `_materialize_nodes(definition)` is called inside every `run_flow()` invocation. It instantiates Node subclasses from `NODE_REGISTRY[node_def.node_type]` using `NodeDefinition` fields (agent already resolved at `from_definition` time, stored alongside the definition).

### Known Risks / Gotchas

- **`DecisionFlowNode` vs new `DecisionNode`**: the legacy class is `DecisionFlowNode` at `decision_node.py:238`. The new wrapper class is `DecisionNode` (different module: `parrot.bots.flows.flow`). Any code that imports `DecisionNode` from `parrot.bots.flow.decision_node` is wrong — there is no such class.
- **`InteractiveDecisionNode` naming clash**: the legacy class lives at `parrot/bots/flow/interactive_node.py:InteractiveDecisionNode`. The new wrapper is also called `InteractiveDecisionNode` but in `parrot/bots/flows/flow.py`. Inside the new flow.py, import the legacy with an alias: `from parrot.bots.flow.interactive_node import InteractiveDecisionNode as LegacyInteractiveDecisionNode`.
- **`AgentNode.execute` signature is a breaking change**: any caller of `core.node.AgentNode.execute(prompt, ...)` outside `parrot/bots/flows/crew/` must be updated (verify with `grep` at impl time). AgentCrew is updated in Module 3; the legacy `fsm.py` is deleted in Module 10.
- **Pydantic frozen vs FSM mutation**: `frozen=True` blocks `node.fsm = something_new`, but `node.fsm.start()` works because `.start()` mutates the FSM's internal state without reassigning the field. This is the foundation of B-lite — confirm with `test_node_fsm_state_mutates`.
- **Concurrent runs of same instance**: safety relies on `_materialize_nodes()` running fresh per `run_flow()` call. If a future change adds shared state on `AgentsFlow` itself (not on per-run materialized nodes), the concurrent-safety guarantee breaks. Document this invariant in the executor docstring.
- **`PrivateAttr` is initialized eagerly**: `_pre_actions: list = PrivateAttr(default_factory=list)` creates a fresh list per instance. If the underlying `AgentLike` is shared across nodes, that's fine — actions are per-Node-instance.
- **AgentCrew regression risk**: the migration in Module 3 changes `CrewAgentNode` constructor shape (`@dataclass` → Pydantic). Existing AgentCrew tests must continue passing — `.fsm` access sites in `crew.py` are explicitly untouched to minimize risk.
- **`parrot/bots/orchestration/`**: do NOT modify. It's on a separate deletion track (legacy pre-FEAT-143). If any merge during this spec accidentally touches it, revert.
- **Cycle detection at construction vs build**: putting the cycle validator on `FlowDefinition` means programmatic builders need to trigger model validation. `FlowDefinition.model_validate(dict_data)` and direct `FlowDefinition(...)` both trigger validators; only `model_construct(...)` bypasses them. Document this.
- **Eager agent resolution + dynamic registries**: callers that register agents AFTER constructing `FlowDefinition` will hit `AgentNotFoundError`. Mitigation: `from_definition()` accepts an explicit `agent_registry` argument so test code can stage the registry first.
- **`on_complete` hook ordering & failure**: hooks run in declaration order, each awaited. Exceptions logged but not raised. Document this contract.
- **Scheduler termination edge case**: a flow where every entry node fails on first dispatch must still terminate cleanly. Test: `test_all_entry_nodes_fail_terminates`.
- **Dev Loop Flow stays broken**: out of scope. PR description must list it as a known-broken follow-up so reviewers do not flag it as a regression.
- **Legacy `parrot/bots/flow/storage/`**: parallel storage tree exists at the legacy path (not under `core/`). The new executor must use `parrot/bots/flows/core/storage/` exclusively. Do not touch the legacy storage; it becomes unreachable once `fsm.py` is deleted.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncio` (stdlib) | n/a | Event-driven scheduler (`Queue`, `create_task`) |
| `pydantic` (existing) | `>=2.0` | Frozen `Node` subclasses, `PrivateAttr`, model validators |
| `celpy` (existing, via `cel_evaluator.py`) | unchanged | CEL predicate evaluation |
| (no new external dependencies) | | acceptance criterion guards this |

---

## 8. Open Questions

> Convention: `[x]` = resolved (carry-forward from brainstorm or this spec session); `[ ]` = open.

- [x] D1 — Where does the new executor live? — *Resolved in brainstorm*: `parrot/bots/flows/flow.py`; legacy `parrot/bots/flow/fsm.py` deleted at end of spec.
- [x] D2 — `NodeSpec` / `NodeRunState` split hardness? — *Resolved in brainstorm + B-lite*: "hard split" achieved by re-materializing fresh Node instances per `run_flow()` call (not by extracting FSM into a separate class). Brainstorm's `NodeSpec` abstraction collapses into existing `FlowDefinition`/`NodeDefinition` + the modified `core.node.AgentNode`.
- [x] D3 — Event-driven scheduler mechanism? — *Resolved in brainstorm*: `asyncio.Queue` of completion events, single scheduler consumer.
- [x] D4 — One node registry or two? — *Resolved in brainstorm*: single `@register_node(name)` decorator registering a `Node` subclass.
- [x] D5 — `from_definition()` agent resolver? — *Resolved in brainstorm*: `AgentRegistry` only (`parrot/registry/registry.py:228`). No `BotManager`.
- [x] D6 — Backward compat scope? — *Resolved in brainstorm*: none for the AgentsFlow API. Dev Loop migration and example migration are explicit follow-up specs. Legacy tests deleted; new integration tests cover linear / branching / fan-in / CEL / retry / decision-node / on_complete hook firing.
- [x] D7 — `DecisionFlowNode` integration? — *Resolved in brainstorm*: polymorphic via `@register_node("decision") class DecisionNode(Node)` wrapper. CEL predicates read `result.final_decision`.
- [x] D8 — HITL pause/resume preparation? — *Resolved in brainstorm*: scheduler is queue-based and does not hold tasks in `asyncio.gather`.
- [x] D9 — `FlowResult.output` semantics? — *Resolved in brainstorm*: dict of leaf-node outputs; scalar when exactly one leaf exists.
- [x] D10 — Cycle detection placement? — *Resolved in brainstorm*: `FlowDefinition.model_validator(mode="after")`.
- [x] D11 — `SynthesisMixin` strategy? — *Resolved in brainstorm*: drop from new executor. Replace with `run_flow(on_complete=[...])` hooks AND a `SynthesisNode` DAG node. `synthesize_results` + `SYNTHESIS_PROMPT` shared utils. Future spec removes `SynthesisMixin` from `AgentCrew`.
- [x] OQ-1 — Synthesis util location? — *Resolved in brainstorm*: `parrot/bots/flows/core/storage/synthesis.py` (existing file).
- [x] OQ-2 — `NodeSpec.execute` signature? — *Resolved in brainstorm*: accept `**kwargs` for forward-compat. (Method now lives on `Node` / `AgentNode` directly.)
- [x] OQ-3 — Pre/post-action hooks: declarative or mutable? — *Resolved this spec session*: keep the existing imperative `add_pre_action` / `add_post_action` API. Underlying lists are `PrivateAttr(default_factory=list)` so `frozen=True` does not block `.append()`. No API change for existing callers.
- [x] OQ-4 — Integration test breadth? — *Resolved in brainstorm*: include 7th test for `on_complete` hook firing (covered in §4).
- [x] OQ-5 — Agent resolution timing? — *Resolved in brainstorm*: eager at `from_definition()` time.
- [x] OQ-6 — Spec-class naming convention? — *Resolved this spec session*: no `…Spec` suffix. With B-lite, the registered class IS the modified `core.node.AgentNode` (and `StartNode`, `EndNode`, plus new `DecisionNode`/`InteractiveDecisionNode`/`SynthesisNode` in flow.py). No name collision because there's no parallel class.
- [x] OQ-8 — AgentCrew migration depth? — *Resolved this spec session*: B-lite. `parrot/bots/flows/crew/nodes.py:CrewAgentNode` + `parrot/bots/flows/crew/crew.py:223` (instantiation) updated. `.fsm` access sites in crew.py UNCHANGED.
- [x] OQ-9 — `parrot/bots/orchestration/` migration? — *Resolved this spec session*: untouched. Entire package on separate deletion track (legacy pre-FEAT-143).
- [ ] OQ-7 — `AgentRegistry.get_agent` method name verification — `parrot/registry/registry.py:228` defines the class; the exact getter method name (`get_agent`, `get`, `lookup`, …) is to be confirmed at impl time. — *Owner: implementer*.
- [ ] OQ-10 — `CrewAgentNode._build_prompt` semantic parity — the legacy `_format_prompt(input_data)` consumes a structured dict; the new `_build_prompt(ctx, deps)` derives `input_data` first then formats. Confirm exact equivalence in a regression test against an existing AgentCrew flow. — *Owner: implementer (Module 3 + test)*.

---

## Worktree Strategy

- **Default isolation**: `per-spec`. All tasks run sequentially in one worktree at `.claude/worktrees/feat-156-agentsflow-refactor-spec3/`.
- **Cross-feature dependencies**: depends on FEAT-134 (`flow-primitives`) and FEAT-143 (`agent-crew-primitives-migration`), both merged on `dev`. Confirmed.
- **Rationale**: the dependency chain inside this spec — `core.node` reshape → `FlowContext.resolve_agent` → AgentCrew migration → `NODE_REGISTRY` → new Node subclasses → scheduler → `from_definition()` → cycle validator → `synthesize_results` util → legacy deletion → tests — is short and tight. Splitting into multiple worktrees would create merge churn for no parallelism gain. The PR is one cohesive change touching `core/node.py`, `core/context.py`, `core/storage/synthesis.py`, `flow.py` (new), `definition.py`, `crew/nodes.py`, `crew/crew.py`, `loader.py`, and tests.
- **Worktree creation** (after task decomposition):
  ```bash
  git worktree add -b feat-156-agentsflow-refactor-spec3 \
    .claude/worktrees/feat-156-agentsflow-refactor-spec3 HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Jesus + Claude | Initial draft from brainstorm. |
| 0.2 | 2026-05-11 | Jesus + Claude | Reconciliation with `core.node.AgentNode` reuse: switched from two-class materialization (NodeSpec + AgentNode) to B-lite — promote `core.node.{Node, AgentNode, StartNode, EndNode}` to frozen Pydantic; FSM stays as field; AgentCrew migrated in `parrot/bots/flows/crew/` only; `parrot/bots/orchestration/` out of scope. Closed OQ-3, OQ-6; added OQ-8, OQ-9, OQ-10. |
