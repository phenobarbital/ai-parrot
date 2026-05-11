---
type: feature
base_branch: dev
---

# Feature Specification: AgentsFlow Refactor — DAG Engine on flows.core

**Feature ID**: FEAT-156
**Date**: 2026-05-11
**Author**: Jesus
**Status**: draft
**Target version**: next minor
**Depends on**: FEAT-134 (`flow-primitives`, merged), FEAT-143 (`agent-crew-primitives-migration`, merged)
**Source**: `sdd/proposals/agentsflow-refactor-spec3.brainstorm.md` (Option C, 15 resolved questions)

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
- Hard split between **frozen** `NodeSpec` (static definition) and per-run `NodeRunState` (FSM, result, error, attempts) so the same flow instance can be executed concurrently.
- Single `@register_node(name)` decorator that wraps a `NodeSpec` subclass embedding both `validate()` and `async execute(ctx, deps, **kwargs)` — one registration point, no separate executor map.
- `from_definition(definition: FlowDefinition)` materializer with **eager** agent resolution via `AgentRegistry` (`parrot/registry/registry.py:228`).
- Replace `SynthesisMixin` inheritance with `run_flow(on_complete=[...])` hooks plus a new declarative `SynthesisNode`. Both call the shared `synthesize_results` util backed by `SYNTHESIS_PROMPT` (`parrot/bots/flows/core/storage/synthesis.py:23`).
- Cycle detection moved from runtime (`_would_create_cycle` at fsm.py:1252) to a `FlowDefinition.model_validator` (`parrot/bots/flow/definition.py:338` adds cycle check).
- `FlowResult.output` semantics: dict of leaf-node outputs, collapsed to a scalar when exactly one leaf exists.
- Foundation for future specs (HITL pause/resume, scatter/gather, loops, swarm) — scheduler design must allow a node to yield its task slot without blocking the executor.

### Non-Goals (explicitly out of scope)

- **Dev Loop Flow migration** (`parrot/flows/dev_loop/flow.py`). Deferred to a follow-up spec.
- **Example migration** (`examples/crew/pizza_sushi_flow.py`, `interactive_pizza_sushi_flow.py`, `consensus_synthesis_flow.py`, `simple.py`). Deferred.
- **Relocation of supporting modules** (`decision_node.py`, `interactive_node.py`, `definition.py`, `svelteflow.py`, `actions.py`, `cel_evaluator.py`) from `parrot/bots/flow/` to `parrot/bots/flows/`. Follow-up cleanup spec.
- **Removing `SynthesisMixin` from `AgentCrew`.** Only removed from the new `AgentsFlow`; `AgentCrew` parity is a future spec.
- **HITL pause/resume implementation.** This spec only ensures the scheduler does not preclude it. Implementation in a future HITL spec.
- **`ScatterNode`, `GatherNode`, `LoopNode`.** Future scatter/gather and iteration specs.
- **Multi-agent / swarm patterns.** Future swarm spec.
- **Redis-backed flow state persistence.** Future persistence spec.
- **Migration of legacy `AgentsFlow` API consumers** — Option A and Option B were rejected in brainstorm (`sdd/proposals/agentsflow-refactor-spec3.brainstorm.md`).
- **Backward compatibility for the `AgentsFlow` public API.** None required.

---

## 2. Architectural Design

### Overview

A new executor module at `parrot/bots/flows/flow.py` exporting `AgentsFlow(PersistenceMixin)`. It consumes primitives from `parrot.bots.flows.core` exclusively. The legacy `parrot/bots/flow/fsm.py` is **deleted** at the end of the spec.

**Three-layer separation:**

1. **Declarative layer** (existing, preserved in `parrot/bots/flow/`):
   `FlowDefinition` (+ `NodeDefinition`, `EdgeDefinition`, `FlowMetadata`), action definitions, the SvelteFlow adapter, the CEL evaluator. This is what visual editors, JSON files, and programmatic builders produce.

2. **Spec layer** (new, in `parrot/bots/flows/flow.py`):
   Frozen Pydantic `NodeSpec` subclasses registered via `@register_node(name)`. Each spec embeds its own `validate()` and `async execute(ctx, deps, **kwargs)`. The user-provided pattern (carried verbatim from brainstorm Code Context) is canonical:

   ```python
   # Source: brainstorm Code Context (user-provided)
   @register_node("agent")
   class AgentNodeSpec(NodeSpec):
       agent_ref: str
       instruction: Optional[str] = None

       def validate(self) -> None:
           if not self.agent_ref:
               raise ValueError("agent_ref required")

       async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any:
           agent = ctx.resolve_agent(self.agent_ref)
           return await agent.invoke(...)
   ```

   Note on naming: the existing `parrot/bots/flows/core/node.py:144` already defines an `AgentNode` class (executable node primitive from FEAT-134). To avoid a class-name collision, the registered Pydantic spec uses the `…Spec` suffix (`AgentNodeSpec`, `DecisionNodeSpec`, `InteractiveDecisionNodeSpec`, `StartNodeSpec`, `EndNodeSpec`, `SynthesisNodeSpec`). The existing `core.node.AgentNode` family is unchanged.

3. **Runtime layer** (new, in `parrot/bots/flows/flow.py`):
   `NodeRunState` (per-execution: `AgentTaskMachine` FSM, result, error, attempts, timestamps). One `NodeRunState` per node per `run_flow()` call. `NodeSpec` instances are reused across runs.

**Event-driven scheduler:**

`AgentsFlow.run_flow(ctx, on_complete=[...])`:
1. Build the static dependency graph; create a fresh `NodeRunState` for every spec.
2. Enqueue nodes with zero dependencies into the ready set.
3. For each ready node: spawn an `asyncio.Task` that runs pre-actions, calls `spec.execute(ctx, deps, **kwargs)`, runs post-actions, and pushes `CompletionEvent(node_id, result | error)` onto `completion_queue: asyncio.Queue`.
4. The scheduler coroutine `await completion_queue.get()`s. For each event:
   - Update the node's `NodeRunState` (status, result/error, timings).
   - Evaluate outgoing transitions via `CELPredicateEvaluator` (`parrot/bots/flow/cel_evaluator.py`).
   - For each newly-satisfied downstream node, spawn its task.
   - Update incremental counters `ready_count`, `active_count`, `completed_count`, `failed_count`. The previous `_get_ready_agents` / `_is_workflow_complete` / `_has_active_agents` full scans are eliminated.
5. Loop terminates when `active_count == 0` and `completion_queue.empty()`.
6. Fire `on_complete` hooks in declaration order (each is awaited; exceptions are caught and logged but do not fail the flow).
7. Aggregate `FlowResult` (`parrot/bots/flows/core/result.py:273`):
   - `output`: scalar from the single leaf node, or `dict[node_id → output]` when multiple leaves exist.
   - `nodes`: list of `NodeExecutionInfo`.
   - `responses`: `dict[node_id → response]`.
   - `errors`: `dict[node_id → error_str]` for failed nodes.
   - `status`: derived via `determine_run_status(success_count, failure_count)` (`parrot/bots/flows/core/result.py:162`).

### Component Diagram

```
                    parrot/bots/flows/flow.py  (NEW)
                    ────────────────────────────────
                    │ AgentsFlow(PersistenceMixin)  │
                    │   ├─ NODE_REGISTRY            │
                    │   ├─ @register_node decorator │
                    │   ├─ NodeSpec (ABC)           │
                    │   ├─ NodeRunState (dataclass) │
                    │   ├─ Scheduler (asyncio.Queue)│
                    │   ├─ from_definition()        │
                    │   └─ run_flow(on_complete=[]) │
                    └────────────────────────────────┘
                            │ consumes
                            ▼
        parrot/bots/flows/core/    (EXISTING, FEAT-134)
        ─────────────────────────────────────────────
        │ fsm.py        — AgentTaskMachine,         │
        │                 TransitionCondition       │
        │ types.py      — AgentRef, FlowStatus,     │
        │                 DependencyResults,        │
        │                 PromptBuilder, AgentLike  │
        │ transition.py — FlowTransition            │
        │ node.py       — Node, AgentNode,          │
        │                 StartNode, EndNode        │
        │ result.py     — FlowResult, NodeResult,   │
        │                 NodeExecutionInfo,        │
        │                 build_node_metadata,      │
        │                 determine_run_status      │
        │ context.py    — FlowContext               │
        │ storage/      — ExecutionMemory,          │
        │                 PersistenceMixin,         │
        │                 SynthesisMixin,           │
        │                 SYNTHESIS_PROMPT,         │
        │                 synthesize_results (new)  │
        └─────────────────────────────────────────────┘
                            │ uses
                            ▼
        parrot/bots/flow/  (LEGACY — preserved this spec)
        ─────────────────────────────────────────────
        │ definition.py    — FlowDefinition + new   │
        │                    cycle-detection        │
        │                    model_validator        │
        │ decision_node.py — DecisionResult,        │
        │                    DecisionMode,          │
        │                    DecisionFlowNode       │
        │ interactive_node.py                       │
        │ actions.py       — ACTION_REGISTRY        │
        │ cel_evaluator.py — CELPredicateEvaluator  │
        │ svelteflow.py    — bidirectional adapter  │
        │ fsm.py           — DELETED at spec end    │
        └─────────────────────────────────────────────┘
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
| `parrot.bots.flows.core.node` | uses | `Node` ABC consumed; existing `AgentNode`/`StartNode`/`EndNode` preserved |
| `parrot.bots.flows.core.result` | uses | `FlowResult`, `NodeResult`, `NodeExecutionInfo`, `build_node_metadata`, `determine_run_status` |
| `parrot.bots.flows.core.context` | uses + extends | `FlowContext` gains `resolve_agent(agent_ref)` helper backed by `AgentRegistry` |
| `parrot.bots.flows.core.storage` | uses | `PersistenceMixin` kept; `SynthesisMixin` NOT inherited |
| `parrot.bots.flows.core.storage.synthesis` | uses + extends | `SYNTHESIS_PROMPT` consumed; new `synthesize_results(ctx, result)` util added in the same module |
| `parrot.bots.flow.definition` | uses + modifies | New `@model_validator` for cycle detection added to `FlowDefinition` |
| `parrot.bots.flow.actions` | uses | `ACTION_REGISTRY`, `register_action` for pre/post-action hooks |
| `parrot.bots.flow.cel_evaluator` | uses | `CELPredicateEvaluator` for transition predicates |
| `parrot.bots.flow.decision_node` | uses + adapts | `DecisionFlowNode` + `DecisionResult` wrapped by `@register_node("decision") class DecisionNodeSpec` |
| `parrot.bots.flow.interactive_node` | uses + adapts | `InteractiveDecisionNode` wrapped by `@register_node("interactive_decision") class InteractiveDecisionNodeSpec` |
| `parrot.bots.flow.svelteflow` | uses | Round-trip target for visual editor; no changes |
| `parrot.registry.registry` | uses | `AgentRegistry` for eager agent resolution at `from_definition()` time |
| `parrot.bots.flow.fsm` | **deletes** | Entire file removed at end of spec |
| `parrot.bots.flow.loader.py` | **modifies** | Update its `from .fsm import AgentsFlow, TransitionCondition` to point at the new module |
| `parrot.flows.dev_loop.flow` | independent (deferred) | Out of scope; broken at the end of this spec; documented as follow-up |
| `parrot.manager.manager.BotManager` | independent | `get_bot` not used by the new executor (resolver is `AgentRegistry`) |

### Data Models

```python
# parrot/bots/flows/flow.py — sketch only; signatures finalized at implementation time.

class NodeSpec(BaseModel):
    """Frozen, declarative definition of a flow node. Subclassed per node type."""
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)
    name: str
    dependencies: list[str] = Field(default_factory=list)
    transitions: list[FlowTransition] = Field(default_factory=list)
    max_retries: int = 0

    def validate(self) -> None: ...           # type-specific invariants
    async def execute(self, ctx: FlowContext, deps: DependencyResults, **kwargs) -> Any: ...


@dataclass
class NodeRunState:
    """Per-execution mutable state. One instance per node per run_flow() call."""
    spec_name: str
    fsm: AgentTaskMachine
    status: FlowStatus = FlowStatus.PENDING
    result: Any = None
    error: str | None = None
    attempts: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class CompletionEvent:
    node_id: str
    result: Any = None
    error: BaseException | None = None


NODE_REGISTRY: dict[str, type[NodeSpec]] = {}

def register_node(name: str) -> Callable[[type[NodeSpec]], type[NodeSpec]]:
    """Decorator. Registers a NodeSpec subclass under `name` in NODE_REGISTRY."""
    ...


# Built-in spec subclasses registered by this spec:
#   @register_node("agent")               → AgentNodeSpec
#   @register_node("decision")            → DecisionNodeSpec
#   @register_node("interactive_decision")→ InteractiveDecisionNodeSpec
#   @register_node("start")               → StartNodeSpec
#   @register_node("end")                 → EndNodeSpec
#   @register_node("synthesis")           → SynthesisNodeSpec
```

### New Public Interfaces

```python
# parrot/bots/flows/flow.py
class AgentsFlow(PersistenceMixin):
    def __init__(self, name: str, *, agent_registry: AgentRegistry | None = None, **kwargs): ...

    def add_node(self, spec: NodeSpec) -> None: ...

    @classmethod
    def from_definition(
        cls,
        definition: FlowDefinition,
        *,
        agent_registry: AgentRegistry | None = None,
    ) -> "AgentsFlow":
        """Materialize an executable flow from a FlowDefinition.

        Eagerly resolves every NodeDefinition.agent_ref against AgentRegistry.
        Raises AgentNotFoundError on the first unresolved ref.
        """

    async def run_flow(
        self,
        ctx: FlowContext | None = None,
        *,
        on_complete: list[Callable[[FlowContext, FlowResult], Awaitable[None]]] = (),
    ) -> FlowResult: ...

# parrot/bots/flows/core/storage/synthesis.py — new util alongside existing SYNTHESIS_PROMPT
async def synthesize_results(ctx: FlowContext, result: FlowResult) -> str:
    """Shared util used both by the on_complete hook and by SynthesisNodeSpec.

    Builds an LLM prompt from SYNTHESIS_PROMPT, calls ctx's synthesis client,
    returns the summary string. Sets it on result.summary if available.
    """

# parrot/bots/flow/definition.py — new model_validator
class FlowDefinition(BaseModel):
    ...
    @model_validator(mode="after")
    def _validate_acyclic(self) -> "FlowDefinition":
        """Detect cycles in the (nodes, edges) graph. Raises ValueError on cycle."""
```

---

## 3. Module Breakdown

### Module 1: NodeSpec & NodeRunState (data layer)
- **Path**: `parrot/bots/flows/flow.py` (top of file)
- **Responsibility**: Define `NodeSpec` ABC (frozen Pydantic), `NodeRunState` dataclass, `CompletionEvent` dataclass.
- **Depends on**: `parrot.bots.flows.core.fsm.AgentTaskMachine`, `core.transition.FlowTransition`, `core.types.FlowStatus`.

### Module 2: NODE_REGISTRY & `@register_node` decorator
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**: Implement `NODE_REGISTRY` dict and `@register_node(name)` decorator that validates a class is a `NodeSpec` subclass and registers it. Raise on duplicate registration.
- **Depends on**: Module 1.

### Module 3: Built-in NodeSpec subclasses
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**: Define `AgentNodeSpec`, `StartNodeSpec`, `EndNodeSpec`, `DecisionNodeSpec` (wraps `DecisionFlowNode`), `InteractiveDecisionNodeSpec` (wraps `InteractiveDecisionNode`), `SynthesisNodeSpec`.
- **Depends on**: Module 1 + Module 2; `parrot.bots.flow.decision_node.DecisionFlowNode`, `parrot.bots.flow.interactive_node.InteractiveDecisionNode`, `parrot.bots.flows.core.storage.synthesis.synthesize_results` (Module 6).

### Module 4: Event-driven Scheduler
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**: Implement `AgentsFlow.run_flow`: build run-state graph, manage `completion_queue: asyncio.Queue`, spawn per-node tasks, drain events, evaluate transitions via `CELPredicateEvaluator`, maintain incremental counters, terminate on quiescence, fire `on_complete` hooks, aggregate `FlowResult` (scalar vs dict output rule).
- **Depends on**: Modules 1–3; `parrot.bots.flow.cel_evaluator.CELPredicateEvaluator`; `parrot.bots.flows.core.result.{FlowResult, NodeResult, NodeExecutionInfo, build_node_metadata, determine_run_status}`.

### Module 5: `from_definition()` materializer with eager agent resolution
- **Path**: `parrot/bots/flows/flow.py`
- **Responsibility**: `AgentsFlow.from_definition(definition, agent_registry=None)`: walk `FlowDefinition.nodes`, look up registered spec class via `NODE_REGISTRY[node_def.node_type]`, instantiate spec with field mapping, **eagerly** call `agent_registry.get_agent(agent_ref)` for every node with a non-empty `agent_ref` (raising `AgentNotFoundError` on the first miss), build edges, return the executable `AgentsFlow`.
- **Depends on**: Modules 1–3; `parrot.bots.flow.definition.FlowDefinition`; `parrot.registry.registry.AgentRegistry`.

### Module 6: Synthesis util & `SynthesisNodeSpec`
- **Path**: `parrot/bots/flows/core/storage/synthesis.py` (extend existing file — adds `synthesize_results` alongside existing `SYNTHESIS_PROMPT` and `SynthesisMixin`)
- **Responsibility**: Add `async def synthesize_results(ctx: FlowContext, result: FlowResult) -> str` reusing `SYNTHESIS_PROMPT`. `SynthesisNodeSpec` (in Module 3) calls this same util.
- **Depends on**: existing `SYNTHESIS_PROMPT` (synthesis.py:23); `parrot.bots.flows.core.context.FlowContext`; `parrot.bots.flows.core.result.FlowResult`.

### Module 7: `FlowContext.resolve_agent` helper
- **Path**: `parrot/bots/flows/core/context.py` (extend existing class at line 26)
- **Responsibility**: Add `resolve_agent(self, agent_ref: AgentRef) -> AgentLike` that delegates to `AgentRegistry` (passed in via context init, or read from a module-level default). Provides the single access point used inside `NodeSpec.execute`.
- **Depends on**: `parrot.registry.registry.AgentRegistry`.

### Module 8: Cycle detection in `FlowDefinition`
- **Path**: `parrot/bots/flow/definition.py`
- **Responsibility**: Add `@model_validator(mode="after")` to `FlowDefinition` that builds an adjacency list from `self.edges` and runs DFS / Kahn's algorithm to detect cycles. Raises `ValueError("Cycle detected: <node_ids>")`.
- **Depends on**: existing `FlowDefinition` at definition.py:288 (placed alongside the existing `validate_node_ids` at line 338).

### Module 9: Legacy file deletion
- **Path**: `parrot/bots/flow/fsm.py`
- **Responsibility**: Delete the file entirely. Update `parrot/bots/flow/loader.py` (which imports `from .fsm import AgentsFlow, TransitionCondition`) to import from the new location (`from parrot.bots.flows.flow import AgentsFlow` and `from parrot.bots.flows.core.fsm import TransitionCondition`). Delete the broken legacy tests (`test_fsm.py`, `test_agentsflow_branch.py`, `test_flow_integration.py`, `test_decision_node.py` — verify list at implementation time).
- **Depends on**: Modules 1–7 stable.

### Module 10: Integration test suite
- **Path**: `packages/ai-parrot/tests/bots/flows/test_agents_flow.py` (new) or `tests/bots/flows/test_agents_flow.py` (matching the repo convention found in §6).
- **Responsibility**: 7 integration tests against the new `AgentsFlow` API — see §4 Integration Tests.
- **Depends on**: Modules 1–8.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_nodespec_frozen` | 1 | A `NodeSpec` instance rejects attribute assignment after construction. |
| `test_node_run_state_fresh_per_run` | 1 | Two consecutive `run_flow()` calls on the same `AgentsFlow` produce distinct `NodeRunState` objects. |
| `test_register_node_decorator_registers` | 2 | `@register_node("foo")` adds the class to `NODE_REGISTRY["foo"]`. |
| `test_register_node_rejects_duplicate` | 2 | Re-registering `"foo"` raises `ValueError`. |
| `test_register_node_rejects_non_nodespec` | 2 | Decorating a non-`NodeSpec` class raises `TypeError`. |
| `test_agent_nodespec_validate` | 3 | `AgentNodeSpec(agent_ref="")` fails `.validate()`. |
| `test_decision_nodespec_wraps_decisionflownode` | 3 | `DecisionNodeSpec` exposes a `DecisionResult`-shaped output via `execute()`. |
| `test_synthesis_nodespec_calls_util` | 3 | `SynthesisNodeSpec.execute` calls `synthesize_results` and returns its string. |
| `test_completion_event_dispatch` | 4 | Putting an event on the queue updates the run state and triggers downstream scheduling. |
| `test_incremental_counters` | 4 | `active_count`/`completed_count` move incrementally; no full-graph scan is performed (assert via spy on a counter method). |
| `test_output_scalar_single_leaf` | 4 | A linear DAG returns `FlowResult.output` as a scalar. |
| `test_output_dict_multiple_leaves` | 4 | A branching DAG with two leaves returns `FlowResult.output` as `dict[node_id → value]`. |
| `test_on_complete_hook_runs` | 4 | A hook in `on_complete=[...]` is awaited exactly once after the flow terminates. |
| `test_from_definition_eager_resolve_ok` | 5 | All `agent_ref`s resolvable → returns an executable `AgentsFlow`. |
| `test_from_definition_eager_resolve_missing` | 5 | One unresolvable `agent_ref` → raises `AgentNotFoundError` at construction (before `run_flow`). |
| `test_flowdefinition_rejects_cycle` | 8 | `FlowDefinition` with `A → B → A` raises `ValueError` at model validation. |
| `test_flowdefinition_accepts_dag` | 8 | A valid acyclic graph constructs without error. |

### Integration Tests

(One file, e.g. `tests/bots/flows/test_agents_flow.py`. Match the convention in `tests/bots/flows/core/` if such a directory exists; otherwise mirror `tests/bots/flows/`.)

| Test | Description |
|---|---|
| `test_linear_flow` | 3-node A→B→C with mocked agents; assert sequential execution, final `output` is scalar. |
| `test_branching_fan_out` | A→{B, C}; assert B and C start as soon as A completes (not after a slow sibling); both run concurrently. |
| `test_branching_fan_in` | {A, B}→C; assert C starts only after both A and B complete; `DependencyResults` contains both. |
| `test_conditional_routing_cel` | A→B with a CEL predicate `result.value > 10`; assert routing fires correctly on pass and short-circuits on fail. |
| `test_retry_on_failure` | A node with `max_retries=2` that fails once then succeeds; assert one retry, final status success. |
| `test_decision_node_routing` | DecisionNodeSpec returns `DecisionResult.final_decision = "approve"`; CEL predicate `result.final_decision == "approve"` routes to the approval branch. |
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

- [ ] **New module exists**: `parrot/bots/flows/flow.py` exports `AgentsFlow`, `NodeSpec`, `NodeRunState`, `NODE_REGISTRY`, `register_node`, and the six built-in `…Spec` classes.
- [ ] **Legacy file deleted**: `parrot/bots/flow/fsm.py` no longer exists. `parrot/bots/flow/loader.py` updated to import from the new location.
- [ ] **No duplication**: `AgentTaskMachine`, `TransitionCondition`, `AgentRef`, `DependencyResults`, `PromptBuilder`, `FlowTransition` are imported from `parrot.bots.flows.core.*` only — `grep` confirms no local redefinition in `parrot/bots/flows/flow.py`.
- [ ] **Inheritance**: `AgentsFlow` inherits from `PersistenceMixin` only (NOT `SynthesisMixin`).
- [ ] **Scheduler is event-driven**: no `await asyncio.sleep(...)` in `run_flow`'s main loop; no `asyncio.gather` over the batch; per-node `asyncio.create_task` + single `asyncio.Queue` consumer.
- [ ] **No full-graph scans**: `_get_ready_agents` / `_is_workflow_complete` / `_has_active_agents` equivalents are NOT re-introduced; readiness is event-driven and counters are incremental.
- [ ] **Hard spec/state split**: `NodeSpec` is frozen Pydantic; `NodeRunState` is a separate dataclass; running the same `AgentsFlow` instance twice concurrently produces independent results (test).
- [ ] **`@register_node` decorator**: single decorator registers a `NodeSpec` subclass with embedded `validate()` + `async execute(ctx, deps, **kwargs)`; duplicate registration raises; non-`NodeSpec` registration raises.
- [ ] **`from_definition()` works and is eager**: `AgentsFlow.from_definition(flow_def)` materializes an executable flow; an unresolved `agent_ref` raises `AgentNotFoundError` at `from_definition` time, not at `run_flow` time.
- [ ] **`FlowResult.output` semantics**: scalar when exactly one leaf; dict when multiple leaves.
- [ ] **`on_complete` hooks**: `run_flow(on_complete=[…])` accepts and awaits each hook after termination; hook exceptions are caught and logged, do not fail the flow.
- [ ] **`SynthesisMixin` replaced**: `synthesize_results(ctx, result)` util added in `parrot/bots/flows/core/storage/synthesis.py`; `SynthesisNodeSpec` calls the same util; old `SynthesisMixin` is no longer inherited by `AgentsFlow` (kept for `AgentCrew`).
- [ ] **Cycle detection**: `FlowDefinition` rejects cyclic graphs at model validation (new `@model_validator(mode="after")` in `parrot/bots/flow/definition.py`); the runtime cycle check in `_would_create_cycle` is gone with `fsm.py`.
- [ ] **Decision nodes**: `DecisionFlowNode` and `InteractiveDecisionNode` consumed via `@register_node("decision")` / `@register_node("interactive_decision")` spec subclasses; their `DecisionResult` output flows through CEL predicates unchanged.
- [ ] **All 17 unit tests pass.**
- [ ] **All 7 integration tests pass.**
- [ ] **No new external dependencies introduced** (verified by `git diff pyproject.toml`).
- [ ] **Documentation**: a docstring at the top of `parrot/bots/flows/flow.py` summarizes the architecture; the brainstorm doc is linked.
- [ ] **Out-of-scope migrations documented**: `parrot/flows/dev_loop/flow.py` and `examples/crew/*flow*.py` are explicitly listed as known-broken in the spec follow-up section / PR description.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** Every reference below was verified
> via `grep` / `read` against the working tree on 2026-05-11.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist.
>
> **Filesystem note**: this is a monorepo. Python import paths
> `parrot.X.Y` resolve to filesystem paths
> `packages/ai-parrot/src/parrot/X/Y.py`. Below, paths shown without
> the `packages/ai-parrot/src/` prefix are Python-package-relative
> for readability; full filesystem paths are used when line numbers
> matter.

### Verified Imports (use these verbatim)

```python
# From parrot/bots/flows/flow.py the new executor will use:
from parrot.bots.flows.core.fsm import AgentTaskMachine, TransitionCondition
# (parrot/bots/flows/core/fsm.py:17, :40 — verified)

from parrot.bots.flows.core.types import (
    AgentRef, DependencyResults, PromptBuilder, FlowStatus, ActionCallback, AgentLike,
)
# (parrot/bots/flows/core/types.py:27, :30, :38, :55, :100, :103 — verified)

from parrot.bots.flows.core.transition import FlowTransition
# (parrot/bots/flows/core/transition.py:28 — verified)

from parrot.bots.flows.core.node import Node, AgentNode, StartNode, EndNode
# (parrot/bots/flows/core/node.py:34, :144, :250, :305 — verified)
# NOTE: AgentNode already exists. New registered spec is AgentNodeSpec to avoid collision.

from parrot.bots.flows.core.result import (
    FlowResult, NodeResult, NodeExecutionInfo,
    build_node_metadata, determine_run_status,
)
# (parrot/bots/flows/core/result.py:39, :162, :190, :273, :527 — verified)

from parrot.bots.flows.core.context import FlowContext
# (parrot/bots/flows/core/context.py:26 — verified)

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
# (parrot/bots/flow/cel_evaluator.py — class exists; line number verified separately)

from parrot.bots.flow.decision_node import (
    DecisionMode, DecisionResult, DecisionFlowNode, DecisionNodeConfig,
)
# (parrot/bots/flow/decision_node.py:26, :114, :238, :192 — verified)
# NOTE: the class is DecisionFlowNode, NOT "DecisionNode".

from parrot.bots.flow.interactive_node import InteractiveDecisionNode
# (parrot/bots/flow/interactive_node.py — verified)

from parrot.bots.flow.svelteflow import to_svelteflow
# (parrot/bots/flow/svelteflow.py — verified)

from parrot.registry.registry import AgentRegistry
# (parrot/registry/registry.py:228 — verified)
```

### Existing Class Signatures

```python
# parrot/bots/flow/fsm.py — TO DELETE at end of spec
class TransitionCondition(str, Enum):                    # line 52  (duplicate)
class AgentTaskMachine(StateMachine):                    # line 61  (duplicate)
class FlowTransition:                                    # line 117 (duplicate)
class FlowNode(Node):                                    # line 199 (replaced by NodeSpec+NodeRunState)
class AgentsFlow(PersistenceMixin, SynthesisMixin):      # line 278 (replaced; new inherits PersistenceMixin only)

# parrot/bots/flows/core/fsm.py — source of truth
class TransitionCondition(str, Enum):                    # line 17
class AgentTaskMachine(StateMachine):                    # line 40

# parrot/bots/flows/core/transition.py
class FlowTransition:                                    # line 28

# parrot/bots/flows/core/node.py
class Node(ABC):                                         # line 34
class AgentNode(Node):                                   # line 144 — DO NOT RENAME; new code uses AgentNodeSpec
class StartNode(Node):                                   # line 250
class EndNode(Node):                                     # line 305

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
class SynthesisMixin:                                    # line 34 — kept for AgentCrew, NOT inherited by new AgentsFlow

# parrot/bots/flows/core/storage/__init__.py
# re-exports: ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin

# parrot/bots/flows/crew/crew.py  — reference pattern, DO NOT MODIFY
class AgentCrew(PersistenceMixin, SynthesisMixin):       # line 87
# Its imports under `from ..core...` are the canonical pattern for the new AgentsFlow.

# parrot/bots/flows/crew/nodes.py — reference pattern
# class CrewAgentNode — informs how DAG-node wrappers are shaped

# parrot/bots/flow/definition.py
class NodePosition(BaseModel):                           # line 118
class NodeDefinition(BaseModel):                         # line 124
#   agent_ref: Optional[str]                             # field present
class EdgeDefinition(BaseModel):                         # line 187
class FlowMetadata(BaseModel):                           # line 246
class FlowDefinition(BaseModel):                         # line 288
#   @model_validator(mode="after")                       # line 338 — existing: references only
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
class DecisionFlowNode(Node):                            # line 238 — the class name is DecisionFlowNode

# parrot/bots/flow/node.py — legacy Node ABC (NOT the same as core.node.Node)
class Node(ABC):
    _pre_actions: List[ActionCallback]
    _post_actions: List[ActionCallback]
    @property
    @abstractmethod
    def name(self) -> str: ...
    def add_pre_action(self, action: ActionCallback) -> None
    def add_post_action(self, action: ActionCallback) -> None
    async def run_pre_actions(self, prompt: str = "", **ctx) -> None
    # The new NodeSpec layer reuses the action-hook semantics, not the class.

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
| `AgentsFlow.run_flow` | `AgentTaskMachine` | per-node FSM instance on `NodeRunState` | `parrot/bots/flows/core/fsm.py:40` |
| `AgentsFlow.run_flow` | `CELPredicateEvaluator.evaluate` | transition predicate eval | `parrot/bots/flow/cel_evaluator.py` |
| `AgentsFlow.from_definition` | `AgentRegistry.get_agent` | eager resolution per `agent_ref` | `parrot/registry/registry.py:228` (method name to confirm at impl time) |
| `AgentNodeSpec.execute` | `FlowContext.resolve_agent` | call resolver in run path | `parrot/bots/flows/core/context.py:26` (extended in Module 7) |
| `DecisionNodeSpec.execute` | `DecisionFlowNode` | delegated call | `parrot/bots/flow/decision_node.py:238` |
| `SynthesisNodeSpec.execute` | `synthesize_results` | shared util | `parrot/bots/flows/core/storage/synthesis.py` (added in Module 6) |
| `run_flow` aggregation | `build_node_metadata`, `determine_run_status` | result assembly | `parrot/bots/flows/core/result.py:527`, `:162` |
| `FlowDefinition` cycle validator | `EdgeDefinition.source`/`target` | DFS over adjacency list | `parrot/bots/flow/definition.py:187, :288` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.bots.flow.decision_node.DecisionNode`~~ — the class is `DecisionFlowNode`. There is no `DecisionNode`.
- ~~`AgentsFlow.from_definition()` (current)~~ — does not exist on the legacy `AgentsFlow`. Added in this spec.
- ~~`AgentCrew.from_definition()`~~ — does not exist either. Out of scope.
- ~~`BotManager.get_agent()`~~ — the method is `BotManager.get_bot()` (`parrot/manager/manager.py:601`). The new executor does NOT use `BotManager`.
- ~~`FlowDefinition` cycle validator (current)~~ — `validate_node_ids` at definition.py:338 only checks reference integrity, NOT acyclicity. Added in this spec.
- ~~`SynthesisMixin` on the new `AgentsFlow`~~ — explicitly dropped. Still inherited by `AgentCrew` (`parrot/bots/flows/crew/crew.py:87`) and unchanged there.
- ~~`parrot.models.crew.AgentResult`~~ — present in legacy import list at `fsm.py:33`. Audit could not confirm; the new module does not import it.
- ~~`parrot.models.crew.build_agent_metadata`~~ — superseded by `parrot.bots.flows.core.result.build_node_metadata` (result.py:527). The new module uses the latter.
- ~~`parrot.bots.flows.crew.py`~~ — it is a package: `parrot/bots/flows/crew/crew.py`.
- ~~`parrot.bots.flows.synthesis`~~ — does not exist. Synthesis util lives at `parrot/bots/flows/core/storage/synthesis.py` alongside `SYNTHESIS_PROMPT` and `SynthesisMixin`.
- ~~`DecisionResult.reasoning`, `DecisionResult.raw_response`~~ — not real fields. Use the verified fields listed above (`final_decision`, `confidence`, `votes`, …).
- ~~A class literally named `AgentNode` registered via `@register_node("agent")`~~ — would collide with the existing `parrot/bots/flows/core/node.py:144`. Use `AgentNodeSpec` (and `…Spec` for all registered classes).
- ~~Generic `AgentsFlow.add_node()` on the legacy file~~ — legacy has `add_agent`, `add_start_node`, `add_end_node` separately. The new executor introduces a polymorphic `add_node(spec: NodeSpec)`.
- ~~Any `asyncio.gather` in the new scheduler~~ — the scheduler uses `asyncio.create_task` + `asyncio.Queue`. `asyncio.gather` is explicitly forbidden by acceptance criterion.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Imports from `flows.core`** — mirror `AgentCrew`'s relative-import style:
  ```python
  from .core.fsm import AgentTaskMachine
  from .core.storage import PersistenceMixin
  ```
  (Same package depth as `parrot/bots/flows/crew/crew.py` — confirmed by reading its top-of-file imports.)
- **Pydantic for `NodeSpec`** — `model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)` to enforce immutability.
- **`asyncio.Queue` over polling** — the queue is a `Queue[CompletionEvent]`; no timeouts; the scheduler awaits `queue.get()` directly. Termination via incremental counters, not by sentinel.
- **Per-node `asyncio.create_task`** — store the task on `NodeRunState` for cancellation; do NOT call `asyncio.gather` on the task set.
- **Exception isolation** — task wrappers catch all exceptions, attach them to `CompletionEvent.error`, push to queue. Node exceptions never escape the executor.
- **Logging** — `self.logger = logging.getLogger(__name__)` at module top (consistent with `AgentCrew`).
- **CEL evaluator reuse** — instantiate `CELPredicateEvaluator` once per `AgentsFlow` (or per `run_flow`); pass results dict from `FlowContext` for predicate evaluation.

### Known Risks / Gotchas

- **`AgentNode` name collision**: `parrot/bots/flows/core/node.py:144` already defines an `AgentNode`. The registered Pydantic spec is named `AgentNodeSpec` to avoid it. Same convention for all node-type specs: `…Spec` suffix.
- **`DecisionFlowNode` vs hypothetical `DecisionNode`**: the legacy class is `DecisionFlowNode` at `decision_node.py:238`. Any code that says `DecisionNode` is wrong — fail PRs that reintroduce that name.
- **Cycle detection placement**: putting the cycle validator on `FlowDefinition` means programmatic builders (today's tests) need to call `FlowDefinition.model_validate(...)` (not just instantiate the model class with bypassed validators) to trigger the check. Document this in the new public interface.
- **Eager agent resolution + dynamic registries**: callers that register agents AFTER constructing `FlowDefinition` will get `AgentNotFoundError`. Mitigation: `from_definition()` accepts an explicit `agent_registry` argument so test code can stage the registry first.
- **`on_complete` hook ordering & failure**: hooks run in declaration order, each awaited. Exceptions logged but not raised. Document this contract.
- **Scheduler termination edge case**: a flow where every entry node fails on first dispatch must still terminate cleanly. Test: `test_all_entry_nodes_fail_terminates`.
- **Backward compat for `parrot/bots/flow/loader.py`**: it imports `from .fsm import AgentsFlow, TransitionCondition`. Update its imports as part of Module 9; do not leave a re-export shim in the deleted file.
- **Dev Loop Flow stays broken**: out of scope. PR description must list it as a known-broken follow-up so reviewers do not flag it as a regression.
- **`parrot/bots/flow/storage/` (legacy) vs `parrot/bots/flows/core/storage/` (new)**: both exist in the tree. The new executor must use the new path exclusively. Do not touch the legacy storage; it is consumed only by the deleted `fsm.py` and will become unreachable.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `asyncio` (stdlib) | n/a | Event-driven scheduler (`Queue`, `create_task`) |
| `pydantic` (existing) | `>=2.0` | Frozen `NodeSpec` subclasses, model validators |
| `celpy` (existing, via `cel_evaluator.py`) | unchanged | CEL predicate evaluation |
| (no new external dependencies) | | acceptance criterion guards this |

---

## 8. Open Questions

> Convention: `[x]` = resolved (carry-forward from brainstorm); `[ ]` = open.

- [x] D1 — Where does the new executor live? — *Resolved in brainstorm*: `parrot/bots/flows/flow.py`; legacy `parrot/bots/flow/fsm.py` deleted at end of spec.
- [x] D2 — `NodeSpec` / `NodeRunState` split hardness? — *Resolved in brainstorm*: hard split — `NodeSpec` frozen, `NodeRunState` per-run.
- [x] D3 — Event-driven scheduler mechanism? — *Resolved in brainstorm*: `asyncio.Queue` of completion events, single scheduler consumer.
- [x] D4 — One node registry or two? — *Resolved in brainstorm*: single `@register_node(name)` decorator wraps a `NodeSpec` subclass embedding `validate()` + `async execute(ctx, deps, **kwargs)`.
- [x] D5 — `from_definition()` agent resolver? — *Resolved in brainstorm*: `AgentRegistry` only (`parrot/registry/registry.py:228`). No `BotManager`. `FlowContext.resolve_agent` is the access point.
- [x] D6 — Backward compat scope? — *Resolved in brainstorm*: none for the AgentsFlow API. Dev Loop migration and example migration are explicit follow-up specs. Legacy tests deleted; new integration tests cover linear / branching / fan-in / CEL / retry / decision-node / on_complete hook firing.
- [x] D7 — `DecisionFlowNode` integration? — *Resolved in brainstorm*: polymorphic via `@register_node("decision") class DecisionNodeSpec(NodeSpec)`. CEL predicates read `result.final_decision`.
- [x] D8 — HITL pause/resume preparation? — *Resolved in brainstorm*: scheduler is queue-based and does not hold tasks in `asyncio.gather` — a future HITL spec plugs in external completion events without scheduler changes.
- [x] D9 — `FlowResult.output` semantics? — *Resolved in brainstorm*: dict of leaf-node outputs; scalar when exactly one leaf exists.
- [x] D10 — Cycle detection placement? — *Resolved in brainstorm*: `FlowDefinition.model_validator(mode="after")` — fails fast on JSON load, programmatic build, and SvelteFlow round-trip.
- [x] D11 — `SynthesisMixin` strategy? — *Resolved in brainstorm*: drop from new executor. Replace with `run_flow(on_complete=[...])` hooks AND a `SynthesisNodeSpec` DAG node. `synthesize_results` + `SYNTHESIS_PROMPT` are shared utils in `parrot/bots/flows/core/storage/synthesis.py`. Future spec removes `SynthesisMixin` from `AgentCrew`.
- [x] OQ-1 — Synthesis util location? — *Resolved in brainstorm*: `parrot/bots/flows/core/storage/synthesis.py` (the existing file where `SYNTHESIS_PROMPT` and `SynthesisMixin` already live).
- [x] OQ-2 — `NodeSpec.execute` signature? — *Resolved in brainstorm*: accept `**kwargs` for forward-compat from this spec onward.
- [x] OQ-4 — Integration test breadth? — *Resolved in brainstorm*: include a 7th test for `on_complete` hook firing (covered above in §4).
- [x] OQ-5 — Agent resolution timing? — *Resolved in brainstorm*: eager — `from_definition()` validates the resolved agent set at construction; raises `AgentNotFoundError` on the first miss. A flow with typos in `agent_ref` cannot reach `run_flow`.
- [ ] OQ-3 — Pre/post-action hooks on `NodeSpec`: keep `add_pre_action` / `add_post_action` mutable-list semantics (consistent with the legacy `Node` ABC at `parrot/bots/flow/node.py`), or declare actions as a frozen Pydantic field on the spec at construction? — *Owner: spec author / implementer*. Tentative: declarative, to match the frozen-spec invariant. To be decided in TASK design.
- [ ] OQ-6 — Final naming for the registered spec classes: `…Spec` suffix (proposed) vs. `…NodeSpec` vs. plain names (would collide with `core.node.AgentNode`). Tentative: `AgentNodeSpec`, `DecisionNodeSpec`, etc. — *Owner: implementer*.
- [ ] OQ-7 — Does `AgentRegistry.get_agent` exist with that signature, or is it `.get(...)`/`.lookup(...)`? Verify method name when implementing Module 5; do not assume. — *Owner: implementer (verify at `parrot/registry/registry.py:228`)*.

---

## Worktree Strategy

- **Default isolation**: `per-spec`. All tasks run sequentially in one worktree at `.claude/worktrees/feat-156-agentsflow-refactor-spec3/`.
- **Cross-feature dependencies**: depends on FEAT-134 (`flow-primitives`) and FEAT-143 (`agent-crew-primitives-migration`), both merged on `dev`. Confirmed.
- **Rationale**: the dependency chain inside this spec — primitives consumption → `NodeSpec`/`NodeRunState` split → `NODE_REGISTRY` → built-in spec classes → scheduler → `from_definition()` → cycle validator → `synthesize_results` util → legacy deletion → tests — is short and tight. Splitting into multiple worktrees would create merge churn for no parallelism gain. The PR is one cohesive new module plus targeted modifications to `definition.py`, `loader.py`, and `core/storage/synthesis.py`.
- **Worktree creation** (after task decomposition):
  ```bash
  git worktree add -b feat-156-agentsflow-refactor-spec3 \
    .claude/worktrees/feat-156-agentsflow-refactor-spec3 HEAD
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Jesus + Claude | Initial draft from brainstorm; 15 resolved + 3 open (OQ-3, OQ-6, OQ-7). |
