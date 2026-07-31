---
type: Wiki Overview
title: 'Brainstorm: Flow Primitives — Shared Core for AgentCrew & AgentsFlow'
id: doc:sdd-proposals-flow-primitives-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'AI-Parrot has two orchestration engines that share ~80% of their conceptual
  model but implement it with divergent classes and contracts:'
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
- concept: mod:parrot.models.status
  rel: mentions
- concept: mod:parrot.tools.agent
  rel: mentions
---

# Brainstorm: Flow Primitives — Shared Core for AgentCrew & AgentsFlow

**Date**: 2026-04-29
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot has two orchestration engines that share ~80% of their conceptual model but implement it with divergent classes and contracts:

- **AgentCrew** (`parrot.bots.orchestration.crew`) — stable, with internal and external users. Supports sequential, parallel, flow, and loop modes. Uses a plain `AgentNode` (no FSM, boolean-based state) and `FlowContext` for shared workflow state.
- **AgentsFlow** (`parrot.bots.flow.fsm`) — richer conceptually (FSM per node via `AgentTaskMachine`, conditional transitions with predicates, retry support), but with minimal adoption.

Both engines define their own `AgentNode`/`FlowNode`, duplicate type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`), depend on identical result models (`CrewResult`, `AgentExecutionInfo`), and inherit the same storage mixins (`PersistenceMixin`, `SynthesisMixin`). This duplication produces:

1. **Code duplication** across two engines that are conceptually the same graph-of-agents model.
2. **Divergent behavior** that makes it hard to reason about which engine to use.
3. **Blocked refactor** of AgentsFlow into a true DAG engine (Spec 3) — doing that without shared primitives means reinventing abstractions AgentCrew already validated.

The dead `AgentTask` class in crew.py (never instantiated, never imported) is a symptom of this drift.

**Who is affected:**
- Framework developers maintaining two parallel implementations.
- Future consumers of AgentsFlow who would inherit the divergence debt.

**Why now:** The AgentsFlow DAG engine refactor is queued. Consolidating primitives first pays the debt once instead of dragging it into Spec 3.

## Constraints & Requirements

- Zero breaking changes to AgentCrew's public API (`run_sequential`, `run_parallel`, `run_flow`, `run_loop`, `task_flow`).
- Existing imports (`from parrot.bots.orchestration.crew import AgentNode, FlowContext`) must continue working via re-export.
- No new external dependencies — `python-statemachine` is already in use.
- `FlowResult` (renamed from `CrewResult`) must preserve all observable properties: `output`, `content`, `status`, `agents`, `errors`, `metadata`, `success`, `agent_results`, `completed`, `failed`, `to_dict()`.
- `node_id` must be separated from `agent.name` to support multiple instances of the same agent.
- Agent references in primitives use a Protocol (`AgentLike`), not concrete imports of `BasicAgent`/`AbstractBot`.
- Storage mixins (`PersistenceMixin`, `SynthesisMixin`, `ExecutionMemory`) move into the new core module.

---

## Options Explored

### Option A: Single `parrot.bots.flows.base` Module with Protocol-Based Contracts

Create `parrot/bots/flows/core/` as a flat package containing all shared primitives. Agent coupling is via an `AgentLike` Protocol. Both engines import from this core. `CrewResult` is replaced by `FlowResult` in the core module; `AgentExecutionInfo` becomes `NodeExecutionInfo`. The existing `Node` ABC is adopted in a leaner form (keeping action hooks but as optional mixin). `AgentCrew` and `AgentsFlow` eventually migrate into `parrot.bots.flows/` (Spec 2 and Spec 3 respectively).

**Module layout:**
```
parrot/bots/flows/
  core/
    __init__.py          # public API surface
    types.py             # AgentRef, AgentLike Protocol, PromptBuilder, DependencyResults
    node.py              # Node ABC, AgentNode (with FSM), StartNode, EndNode
    fsm.py               # AgentTaskMachine (states + transitions)
    context.py           # FlowContext (workflow state tracking)
    transition.py        # FlowTransition, TransitionCondition enum
    result.py            # FlowResult (ex CrewResult), NodeExecutionInfo (ex AgentExecutionInfo), FlowStatus
    storage/             # ExecutionMemory, PersistenceMixin, SynthesisMixin (moved from flow/storage)
```

Pros:
- Clean namespace that doesn't tie to either `orchestration` or `flow`.
- `core` communicates "foundational, stable, shared" — better semantics than `base`.
- Protocol-based agent reference eliminates import cycles.
- Single source of truth for all shared abstractions.
- `node_id` vs `agent.name` separation built in from day one.
- Natural home for both AgentCrew (Spec 2) and AgentsFlow (Spec 3) to migrate into.
- Storage mixins co-located with the primitives they serve.

Cons:
- New top-level package (`flows`) to create and maintain.
- Re-export shims needed in old locations until Spec 2/3 complete migration.
- Leaning the `Node` ABC means deciding which action hook features to keep now vs. defer.

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `python-statemachine` | FSM for `AgentTaskMachine` | Already in use, v2.x |

Existing Code to Reuse:
- `parrot/bots/flow/node.py` — `Node` ABC with action hooks (adopt and lean)
- `parrot/bots/flow/fsm.py` — `AgentTaskMachine`, `TransitionCondition`, `FlowTransition` (extract)
- `parrot/bots/flow/nodes/start.py`, `end.py` — `StartNode`, `EndNode` (move)
- `parrot/bots/orchestration/crew.py` — `FlowContext`, `AgentNode` pattern, type aliases (extract)
- `parrot/models/crew.py` — `CrewResult`, `AgentExecutionInfo`, `AgentResult`, utility functions (fork into `FlowResult`, `NodeExecutionInfo`)
- `parrot/bots/flow/storage/` — `ExecutionMemory`, `PersistenceMixin`, `SynthesisMixin` (move)

---

### Option B: Extend Existing `parrot.bots.flow` with a `core` Subpackage

Instead of creating a new `flows` namespace, add `parrot/bots/flow/core/` alongside the existing `flow/` modules. Both AgentCrew and AgentsFlow import from `parrot.bots.flow.core`. `CrewResult` stays in `parrot.models.crew` but gets aliased.

Pros:
- No new top-level namespace — fits into existing `flow/` hierarchy.
- Smaller diff — less directory restructuring.

Cons:
- Semantically couples "base primitives" to the `flow` namespace, which is currently the AgentsFlow engine — confusing for AgentCrew consumers.
- `parrot.bots.flow.core` implies `flow` is the primary engine, not a neutral shared base.
- Future migration path is muddier — AgentCrew importing from `flow.core` feels backwards.
- Doesn't address the eventual goal of unifying both engines under one namespace.

Effort: Low-Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `python-statemachine` | FSM for `AgentTaskMachine` | Already in use |

Existing Code to Reuse:
- Same as Option A, but without directory moves.

---

### Option C: Abstract Base Package at `parrot.orchestration.base`

Create a top-level `parrot/orchestration/` namespace (outside of `bots/`) for all orchestration primitives. This separates the execution model from the bot hierarchy entirely.

Pros:
- Cleanest conceptual separation — orchestration is not a "bot" concern.
- No ambiguity about which engine "owns" the primitives.
- Could eventually host other orchestration patterns (pipelines, workflows beyond agents).

Cons:
- Largest structural change — new top-level package in `parrot/`.
- Breaks the existing mental model where all agent-related code lives under `bots/`.
- `AgentCrew` and `AgentsFlow` would need to import from outside their parent package, creating a wider dependency surface.
- Over-engineers the namespace for the current scope (only two consumers).

Effort: High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| `python-statemachine` | FSM for `AgentTaskMachine` | Already in use |

Existing Code to Reuse:
- Same set of files, but relocated further from their consumers.

---

## Recommendation

**Option A** is recommended because:

- It creates a neutral namespace (`parrot.bots.flows.core`) that neither engine "owns," eliminating the semantic confusion of Option B where AgentCrew would import from `flow.core`.
- The `flows/` namespace naturally becomes the future home for both engines (AgentCrew as `flows/crew.py`, AgentsFlow as `flows/engine.py` or similar), providing a clear migration path for Specs 2 and 3.
- The effort is medium (not high like Option C) because it stays within `bots/` — consistent with the existing mental model that orchestration is a bot concern.
- Protocol-based agent references solve import cycles cleanly without over-abstracting.
- Co-locating storage mixins with the core primitives makes the dependency graph tighter and more discoverable.

The main tradeoff is the re-export shims in old locations, but these are explicitly temporary (removed in Spec 2/3) and protect existing consumers.

---

## Feature Description

### User-Facing Behavior

For consumers of `AgentCrew` — **nothing changes**. All public APIs, imports, and output structures continue to work identically. The `CrewResult` name remains available as an alias for `FlowResult`. `AgentExecutionInfo` remains available as an alias for `NodeExecutionInfo`.

For new code and framework developers, canonical imports shift to:
```python
from parrot.bots.flows.core import (
    Node, AgentNode, StartNode, EndNode,
    AgentTaskMachine,
    FlowContext,
    FlowTransition, TransitionCondition,
    FlowResult, NodeExecutionInfo, FlowStatus,
    AgentLike, AgentRef, PromptBuilder, DependencyResults,
)
```

### Internal Behavior

**Node hierarchy:**
- `Node` (ABC) — lean base with `node_id: str`, `name` property, optional pre/post action hooks.
- `AgentNode` — wraps an `AgentLike` agent with an `AgentTaskMachine` FSM. Has `node_id` (unique per graph instance) separate from `agent.name` (the agent's identity). Contains `dependencies: Set[str]`, `successors: Set[str]`, execution state (`result`, `error`, `execution_time`).
- `StartNode` / `EndNode` — virtual entry/exit points (no agent, no FSM).

**FSM lifecycle (`AgentTaskMachine`):**
`idle` -> `ready` -> `running` -> `completed` (final) or `failed` (non-final, allows retry). Additional transitions: `block` (idle/ready -> blocked), `unblock` (blocked -> ready), `retry` (failed -> ready).

**FlowContext:**
Tracks workflow execution state: `initial_task`, `results` dict, `responses` dict, `agent_metadata` (now `Dict[str, NodeExecutionInfo]`), `completion_order`, `errors`, `active_tasks`, `completed_tasks`. Methods: `can_execute()`, `mark_completed()`, `get_input_for_node()` (renamed from `get_input_for_agent`).

**FlowTransition:**
Conditional edges between nodes: `source: str`, `targets: Set[str]`, `condition: TransitionCondition`, optional `predicate`, `instruction`, `prompt_builder`, `priority`.

**FlowResult** (replaces `CrewResult`):
All fields preserved with more generic naming:
- `output`, `responses`, `summary`, `nodes` (was `agents`), `execution_log`, `total_time`, `status`, `errors`, `metadata`.
- Properties: `content`, `success`, `node_results` (was `agent_results`), `completed`, `failed`.
- Backward-compatible aliases: `agents` -> `nodes`, `agent_results` -> `node_results`.

**NodeExecutionInfo** (replaces `AgentExecutionInfo`):
- `node_id`, `node_name` (was `agent_id`, `agent_name`), plus `provider`, `model`, `execution_time`, `tool_calls`, `status`, `error`, `client`, `usage`.
- Backward-compatible aliases: `agent_id` -> `node_id`, `agent_name` -> `node_name`.

**Storage module:**
`ExecutionMemory`, `PersistenceMixin`, `SynthesisMixin` move unchanged from `parrot/bots/flow/storage/` into `parrot/bots/flows/base/storage/`.

### Edge Cases & Error Handling

- **Duplicate node_id**: `Node` subclasses validate uniqueness at graph registration time (in the engine, not in the primitive). The primitive exposes `node_id` as a required field.
- **FSM invalid transitions**: `AgentTaskMachine` (from `python-statemachine`) raises `TransitionNotAllowed` for invalid state changes. Consumers catch and handle.
- **FlowContext missing dependencies**: `can_execute()` returns `False` if any dependency is not in `completed_tasks`. `get_input_for_node()` silently omits missing results (existing behavior preserved).
- **FlowResult backward compatibility**: `CrewResult` alias and `agents`/`agent_results` property aliases ensure zero breakage. Deprecation warnings are NOT emitted in Spec 1 — that's a Spec 2 concern.

---

## Capabilities

### New Capabilities
- `flow-primitives`: Shared core module (`parrot.bots.flows.core`) containing `Node` ABC, `AgentNode`, `StartNode`, `EndNode`, `AgentTaskMachine`, `FlowContext`, `FlowTransition`, `TransitionCondition`, `FlowResult`, `NodeExecutionInfo`, `AgentLike` Protocol, type aliases, and storage mixins. Includes contract test suite (pure unit tests, no LLM) validating FSM invariants, ready-set computation, transition semantics, and FlowResult serialization round-trips.

### Modified Capabilities
- `parrot.models.crew`: `CrewResult` and `AgentExecutionInfo` get re-export aliases pointing to `FlowResult` and `NodeExecutionInfo` from the new base module. The actual classes move. `AgentResult`, `build_agent_metadata`, `determine_run_status` remain here (they are result-building utilities, not flow primitives).

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flows/core/` (NEW) | new module | All shared primitives live here |
| `parrot/bots/flow/node.py` | superseded | `Node` ABC moves to base; old path re-exports |
| `parrot/bots/flow/nodes/` | superseded | `StartNode`, `EndNode` move to base; old path re-exports |
| `parrot/bots/flow/fsm.py` | depends on | Imports `AgentTaskMachine`, `FlowTransition`, `TransitionCondition` from base |
| `parrot/bots/orchestration/crew.py` | depends on | Imports `FlowContext`, `AgentNode` types from base (Spec 2 migration) |
| `parrot/models/crew.py` | modifies | `CrewResult` -> alias for `FlowResult`; `AgentExecutionInfo` -> alias for `NodeExecutionInfo` |
| `parrot/bots/flow/storage/` | moves | Entire storage subpackage relocates to core; old path re-exports |
| `examples/crew/*` | no change | Imports via `parrot.bots.orchestration.crew` still work |
| `parrot/handlers/crew/` | no change | Imports via existing paths still work |
| Tests (`test_fsm.py`, `test_agent_crew_examples.py`, etc.) | no change | Existing import paths preserved via re-exports |

---

## Code Context

### User-Provided Code

_No code snippets provided during brainstorming._

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/bots/flow/node.py:11
ActionCallback = Callable[..., Union[None, Awaitable[None]]]

# From parrot/bots/flow/node.py:14
class Node(ABC):
    logger: logging.Logger                     # line 41
    _pre_actions: List[ActionCallback]         # line 42
    _post_actions: List[ActionCallback]        # line 43
    def _init_node(self, name: str) -> None: ...          # line 48
    @property @abstractmethod
    def name(self) -> str: ...                             # line 59
    def add_pre_action(self, action: ActionCallback): ...  # line 66
    def add_post_action(self, action: ActionCallback): ... # line 70
    async def run_pre_actions(self, prompt: str = "", **ctx): ...   # line 76
    async def run_post_actions(self, result: Any = None, **ctx): ... # line 92

# From parrot/bots/flow/fsm.py:50
class TransitionCondition(str, Enum):
    ON_SUCCESS = "on_success"
    ON_ERROR = "on_error"
    ON_TIMEOUT = "on_timeout"
    ON_CONDITION = "on_condition"
    ALWAYS = "always"

# From parrot/bots/flow/fsm.py:59
class AgentTaskMachine(StateMachine):
    idle = State("idle", initial=True)         # line 60
    ready = State("ready")                     # line 61
    running = State("running")                 # line 62
    completed = State("completed", final=True) # line 63
    failed = State("failed")                   # line 64  (NOT final — allows retry)
    blocked = State("blocked")                 # line 65
    # Transitions:
    schedule = idle.to(ready)
    start = ready.to(running)
    succeed = running.to(completed)
    fail = running.to(failed) | ready.to(failed) | idle.to(failed)
    block = idle.to(blocked) | ready.to(blocked)
    unblock = blocked.to(ready)
    retry = failed.to(ready)

# From parrot/bots/flow/fsm.py:115
@dataclass
class FlowTransition:
    source: str
    targets: Set[str]
    condition: TransitionCondition = TransitionCondition.ON_SUCCESS
    instruction: Optional[str] = None
    prompt_builder: Optional[PromptBuilder] = None
    predicate: Optional[Callable[[Any], Union[bool, Awaitable[bool]]]] = None
    priority: int = 0
    metadata: Optional[AgentExecutionInfo] = None
    async def should_activate(self, result: Any, error: Optional[Exception] = None) -> bool: ...
    async def build_prompt(self, context: AgentContext, dependencies: DependencyResults) -> str: ...

# From parrot/bots/flow/fsm.py:197
@dataclass
class FlowNode(Node):
    agent: Union[BasicAgent, AbstractBot]
    fsm: AgentTaskMachine
    dependencies: Set[str]
    outgoing_transitions: List[FlowTransition]
    retry_count: int = 0
    max_retries: int = 3
    @property
    def name(self) -> str: ...       # returns agent.name
    @property
    def is_terminal(self) -> bool: ...
    @property
    def can_retry(self) -> bool: ...
    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> Any: ...

# From parrot/bots/orchestration/crew.py:75
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any]
    responses: Dict[str, Any]
    agent_metadata: Dict[str, AgentExecutionInfo]
    completion_order: List[str]
    errors: Dict[str, Exception]
    active_tasks: Set[str]
    completed_tasks: Set[str]
    def can_execute(self, agent_name: str, dependencies: Set[str]) -> bool: ...   # line 105
    def mark_completed(self, agent_name, result, response, metadata) -> None: ... # line 109
    def get_input_for_agent(self, agent_name: str, dependencies: Set[str]) -> Dict[str, Any]: ... # line 124

# From parrot/bots/orchestration/crew.py:144
class AgentNode:
    agent: Union[BasicAgent, AbstractBot]
    dependencies: Set[str]
    successors: Set[str]
    def _format_prompt(self, input_data: Dict[str, Any]) -> str: ...           # line 162
    async def execute(self, context: FlowContext, timeout: Optional[float]) -> Any: ... # line 189

# From parrot/models/crew.py:20
@dataclass
class AgentExecutionInfo:
    agent_id: str
    agent_name: str
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_time: float = 0.0
    tool_calls: List[Dict[str, Any]]
    status: Literal['completed', 'failed', 'pending', 'running'] = 'pending'
    error: Optional[str] = None
    client: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    def to_dict(self) -> Dict[str, Any]: ...

# From parrot/models/crew.py:61
@dataclass
class CrewResult:
    output: Any
    responses: Dict[str, ResponseType]
    summary: str = ""
    agents: List[AgentExecutionInfo]
    execution_log: List[Dict[str, Any]]
    total_time: float = 0.0
    status: Literal['completed', 'partial', 'failed'] = 'completed'
    errors: Dict[str, str]
    metadata: Dict[str, Any]
    # Properties: content, final_result, success, agent_results, completed, failed, total_execution_time
    def to_dict(self) -> Dict[str, Any]: ...
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.orchestration.crew import AgentCrew, AgentNode, FlowContext  # __init__.py
from parrot.bots.flow import Node, StartNode, EndNode                         # __init__.py
from parrot.bots.flow import AgentsFlow, AgentTaskMachine, FlowNode, FlowTransition, TransitionCondition
from parrot.models.crew import CrewResult, AgentExecutionInfo, AgentResult, build_agent_metadata, determine_run_status
from parrot.bots.flow.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin
from parrot.tools.agent import AgentContext
from parrot.models.status import AgentStatus
from statemachine import State, StateMachine  # used in fsm.py:23, verify.py:18
```

#### Key Attributes & Constants
- `AgentRef = Union[str, BasicAgent, AbstractBot]` (crew.py:56, fsm.py:44) — duplicated in both
- `DependencyResults = Dict[str, str]` (crew.py:57, fsm.py:45) — duplicated in both
- `PromptBuilder = Callable[[AgentContext, DependencyResults], Union[str, Awaitable[str]]]` (crew.py:58, fsm.py:46) — duplicated in both

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.bots.flows`~~ — this namespace does not exist yet; it will be created by this feature
- ~~`parrot.bots.flows.core`~~ — does not exist yet
- ~~`FlowResult`~~ — does not exist yet; will be created from `CrewResult`
- ~~`NodeExecutionInfo`~~ — does not exist yet; will be created from `AgentExecutionInfo`
- ~~`AgentLike` Protocol~~ — does not exist yet; will be created
- ~~`parrot.bots.orchestration.crew.AgentTask`~~ — exists as dead code (line 61) but is never used, never imported, never exported; safe to delete
- ~~`AgentNode` base class~~ — the current `AgentNode` in crew.py has no base class (not a `Node` subclass)
- ~~`FlowNode.node_id`~~ — `FlowNode` uses `agent.name` as identity; there is no separate `node_id` field

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The primitives form a dependency chain: types -> Node ABC -> FSM -> context -> transition -> result. However, `result.py` (FlowResult/NodeExecutionInfo) and `types.py` (Protocol/aliases) can be developed independently of the node hierarchy. Storage migration is also independent. Estimate: 2-3 parallel tracks possible.
- **Cross-feature independence**: This feature creates a new package (`parrot.bots.flows.core`) and only adds re-export shims to existing modules. No conflicts with in-flight specs unless someone is simultaneously modifying `parrot/bots/flow/fsm.py` or `parrot/models/crew.py`.
- **Recommended isolation**: `per-spec` — tasks are tightly coupled (each builds on the previous layer of the type hierarchy) and the total scope is medium. A single worktree with sequential task execution is simpler and avoids merge conflicts between primitive layers.
- **Rationale**: The dependency chain between types, nodes, FSM, context, and transitions means most tasks need to see the output of previous tasks. The independent tracks (result models, storage migration) are small enough that the overhead of separate worktrees isn't justified.

---

## Open Questions

- [x] D1 — Module naming — *Owner: Jesus*: `parrot.bots.flows.core` — "core" has better semantics than "base"; future migration of both engines into `parrot.bots.flows/`
- [x] D2 — Fate of `AgentTask` — *Owner: Jesus*: Delete it (confirmed dead code, never used)
- [x] D3 — `node_id` vs `agent.name` — *Owner: Jesus*: Resolve in this spec; separate `node_id` from `agent.name`
- [x] D4 — Node hierarchy — *Owner: Jesus*: Adopt existing `Node` ABC (lean version preserving action hooks for future use)
- [x] D5 — Protocol vs concrete dependency — *Owner: Jesus*: Use `AgentLike` Protocol for cleaner decoupling
- [x] D6 — Prompt building — *Owner: Jesus*: Keep `PromptBuilder` type alias as a shared Protocol in base; each engine keeps its own prompt-building logic (crew's `_format_prompt`, flow's `FlowTransition.build_prompt`)
- [x] D7 — `FlowContext.get_input_for_agent` — *Owner: Jesus*: Stays as a primitive (renamed `get_input_for_node`); both engines need to build agent input from dependencies
- [x] D8 — Re-export strategy — *Owner: Jesus*: Option A (re-export from old locations for backward compat); no deprecation warnings in Spec 1
- [x] D9 — Observable invariants — *Owner: Jesus*: Enumerated explicitly; migration testing deferred to Spec 2
- [ ] D10 — `FlowResult` field rename for `agents` — *Owner: Jesus*: Should the primary field be `nodes: List[NodeExecutionInfo]` with `agents` as a backward-compat property, or keep `agents` as primary? Recommendation: `nodes` as primary, `agents` as alias property.

…(truncated)…
