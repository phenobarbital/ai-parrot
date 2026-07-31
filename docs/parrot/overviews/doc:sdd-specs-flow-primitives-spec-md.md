---
type: Wiki Overview
title: 'Feature Specification: Flow Primitives — Shared Core for AgentCrew & AgentsFlow'
id: doc:sdd-specs-flow-primitives-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: AI-Parrot has two orchestration engines — **AgentCrew** (`parrot.bots.orchestration.crew`)
  and **AgentsFlow** (`parrot.bots.flow.fsm`) — that share ~80% of their conceptual
  model (a graph of agents with dependencies executed in topological order) but implement
  it with divergent c
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.flows
  rel: mentions
- concept: mod:parrot.handlers.crew
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
- concept: mod:parrot.models.status
  rel: mentions
- concept: mod:parrot.tools.agent
  rel: mentions
---

# Feature Specification: Flow Primitives — Shared Core for AgentCrew & AgentsFlow

**Feature ID**: FEAT-134
**Date**: 2026-04-29
**Author**: Jesus
**Status**: implemented
**Target version**: next minor

> **Note (FEAT-196, 2026-05-28)**: Code examples in this spec reference `parrot.bots.flow`
> (singular, deleted in FEAT-196). Use `parrot.bots.flows` (plural) for all new code.

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot has two orchestration engines — **AgentCrew** (`parrot.bots.orchestration.crew`) and **AgentsFlow** (`parrot.bots.flow.fsm`) — that share ~80% of their conceptual model (a graph of agents with dependencies executed in topological order) but implement it with divergent classes and contracts.

Both engines define their own node types (`AgentNode` vs `FlowNode`), duplicate identical type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`), depend on the same result models (`CrewResult`, `AgentExecutionInfo`), and inherit the same storage mixins (`PersistenceMixin`, `SynthesisMixin`). This produces:

1. **Code duplication** across two engines that are conceptually the same graph-of-agents model.
2. **Divergent behavior** that makes it hard to reason about which engine to use.
3. **Blocked refactor** of AgentsFlow into a true DAG engine (Spec 3) — doing that without shared primitives means reinventing abstractions AgentCrew already validated.

The dead `AgentTask` class in `crew.py` (never instantiated, never imported, never exported) is a symptom of this drift.

The AgentsFlow DAG engine refactor is queued. Consolidating primitives first pays the debt once instead of dragging it into Spec 3.

### Goals

- Distill all shared classes, enums, types, and protocols into a single `parrot.bots.flows.core` module.
- Provide `FlowResult` (replacing `CrewResult`) and `NodeExecutionInfo` (replacing `AgentExecutionInfo`) as the canonical result models for both engines.
- Separate `node_id` from `agent.name` in the node hierarchy to support multiple instances of the same agent.
- Define `AgentLike` Protocol to decouple primitives from concrete bot imports.
- Move storage mixins (`PersistenceMixin`, `SynthesisMixin`, `ExecutionMemory`) into the core module.
- Provide contract tests (pure unit tests, no LLM) validating FSM invariants, ready-set computation, transition semantics, and FlowResult serialization round-trips.
- Maintain full backward compatibility via re-exports from old import paths.

### Non-Goals (explicitly out of scope)

- Refactoring AgentCrew to consume the new primitives internally — that is Spec 2 (`agent-crew-primitives-migration`).
- Refactoring AgentsFlow into a DAG engine with scatter/gather/decision/loop/HITL nodes — that is Spec 3 (`agents-flow-dag-engine`).
- Backend checkpoint/Redis for persisting flow state — deferred to Spec 3.
- Changes to Handlers REST (`parrot.handlers.crew`).
- Changes to BotManager / AgentRegistry.
- Runtime fallback-on-failure or advanced error recovery patterns (rejected in brainstorm Option C scope — see `sdd/proposals/flow-primitives.brainstorm.md`).

---

## 2. Architectural Design

### Overview

Create `parrot/bots/flows/core/` as a flat package containing all shared orchestration primitives. Agent coupling is via an `AgentLike` Protocol (not concrete `BasicAgent`/`AbstractBot` imports). Both engines import from this core. The existing `Node` ABC from `parrot.bots.flow.node` is adopted in a leaner form, preserving action hooks for future use. `CrewResult` is replaced by `FlowResult`; `AgentExecutionInfo` becomes `NodeExecutionInfo`.

The module name `parrot.bots.flows.core` was chosen because:
- `core` communicates "foundational, stable, shared" — better semantics than `base`.
- `flows` (plural) is a neutral namespace that neither engine "owns."
- Staying inside `bots/` preserves the mental model that orchestration is a bot concern.
- Both AgentCrew (Spec 2) and AgentsFlow (Spec 3) will eventually migrate into `parrot.bots.flows/`.

### Component Diagram

```
parrot/bots/flows/
  __init__.py                     # re-exports from core
  core/
    __init__.py                   # public API surface
    types.py                      # AgentLike Protocol, AgentRef, PromptBuilder, DependencyResults
    node.py                       # Node ABC, AgentNode (concrete, with FSM), StartNode, EndNode
    fsm.py                        # AgentTaskMachine (states + transitions)
    context.py                    # FlowContext (workflow state tracking)
    transition.py                 # FlowTransition, TransitionCondition enum
    result.py                     # FlowResult, NodeExecutionInfo, FlowStatus, utilities
    storage/
      __init__.py                 # re-exports
      memory.py                   # ExecutionMemory (with VectorStoreMixin)
      mixin.py                    # VectorStoreMixin (FAISS)
      persistence.py              # PersistenceMixin (DocumentDB)
      synthesis.py                # SynthesisMixin (LLM-based result synthesis)

parrot/bots/orchestration/crew.py  →  imports from flows.core (Spec 2)
parrot/bots/flow/fsm.py           →  imports from flows.core (Spec 3)
parrot/models/crew.py             →  re-exports FlowResult as CrewResult, NodeExecutionInfo as AgentExecutionInfo
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot/bots/flow/node.py` | superseded | `Node` ABC moves to `flows/core/node.py`; old path re-exports |
| `parrot/bots/flow/nodes/` | superseded | `StartNode`, `EndNode` move to `flows/core/node.py`; old path re-exports |
| `parrot/bots/flow/fsm.py` | will depend on (Spec 3) | Will import `AgentTaskMachine`, `FlowTransition`, `TransitionCondition` from core |
| `parrot/bots/orchestration/crew.py` | will depend on (Spec 2) | Will import `FlowContext`, types from core |
| `parrot/models/crew.py` | modifies | `CrewResult` becomes alias for `FlowResult`; `AgentExecutionInfo` alias for `NodeExecutionInfo` |
| `parrot/bots/flow/storage/` | moves | Entire subpackage relocates to `flows/core/storage/`; old path re-exports |
| `examples/crew/*` | no change | Imports via existing paths still work via re-exports |
| `parrot/handlers/crew/` | no change | Imports via existing paths still work |
| Tests (`test_fsm.py`, `test_agent_crew_examples.py`, etc.) | no change | Existing import paths preserved via re-exports |

### Data Models

```python
# FlowResult (replaces CrewResult)
@dataclass
class FlowResult:
    output: Any
    responses: Dict[str, ResponseType] = field(default_factory=dict)
    summary: str = ""
    nodes: List[NodeExecutionInfo] = field(default_factory=list)
    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    total_time: float = 0.0
    status: FlowStatus = FlowStatus.COMPLETED
    errors: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Backward-compat aliases
    @property
    def agents(self) -> List[NodeExecutionInfo]: ...   # alias for nodes
    @property
    def agent_results(self) -> Dict[str, Any]: ...     # alias for node_results
    @property
    def content(self) -> Optional[Any]: ...            # alias for output
    @property
    def success(self) -> bool: ...                     # status == COMPLETED
    @property
    def node_results(self) -> Dict[str, Any]: ...
    @property
    def completed(self) -> List[str]: ...
    @property
    def failed(self) -> List[str]: ...
    def to_dict(self) -> Dict[str, Any]: ...


# NodeExecutionInfo (replaces AgentExecutionInfo)
@dataclass
class NodeExecutionInfo:
    node_id: str
    node_name: str
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_time: float = 0.0
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    status: Literal['completed', 'failed', 'pending', 'running'] = 'pending'
    error: Optional[str] = None
    client: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None

    # Backward-compat aliases
    @property
    def agent_id(self) -> str: ...    # alias for node_id
    @property
    def agent_name(self) -> str: ...  # alias for node_name
    def to_dict(self) -> Dict[str, Any]: ...


# FlowStatus enum
class FlowStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


```

### New Public Interfaces

```python
# AgentLike Protocol — decouples primitives from concrete bot classes
from typing import Protocol, runtime_checkable

@runtime_checkable
class AgentLike(Protocol):
    @property
    def name(self) -> str: ...
    async def invoke(self, prompt: str, **kwargs) -> Any: ...


# Type aliases
AgentRef = Union[str, AgentLike]
DependencyResults = Dict[str, str]
PromptBuilder = Callable[[Any, DependencyResults], Union[str, Awaitable[str]]]


# Node hierarchy
class Node(ABC):
    node_id: str
    logger: logging.Logger
    _pre_actions: List[ActionCallback]
    _post_actions: List[ActionCallback]

    @property
    @abstractmethod
    def name(self) -> str: ...

    def add_pre_action(self, action: ActionCallback) -> None: ...
    def add_post_action(self, action: ActionCallback) -> None: ...
    async def run_pre_actions(self, prompt: str = "", **ctx) -> None: ...
    async def run_post_actions(self, result: Any = None, **ctx) -> None: ...


class AgentNode(Node):
    agent: AgentLike
    node_id: str            # unique per graph instance
    dependencies: Set[str]
    successors: Set[str]
    fsm: AgentTaskMachine

    @property
    def name(self) -> str: ...  # returns agent.name

    async def execute(self, context: FlowContext, timeout: Optional[float] = None) -> Any: ...


class StartNode(Node):
    def __init__(self, name: str = "__start__", *, metadata: Optional[Dict] = None): ...

class EndNode(Node):
    def __init__(self, name: str = "__end__", *, metadata: Optional[Dict] = None): ...


# FlowContext
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any]
    responses: Dict[str, Any]
    node_metadata: Dict[str, NodeExecutionInfo]
    completion_order: List[str]
    errors: Dict[str, Exception]
    active_tasks: Set[str]
    completed_tasks: Set[str]

    def can_execute(self, node_id: str, dependencies: Set[str]) -> bool: ...
    def mark_completed(self, node_id: str, result: Any, response: Any,
                       metadata: Optional[NodeExecutionInfo]) -> None: ...
    def get_input_for_node(self, node_id: str, dependencies: Set[str]) -> Dict[str, Any]: ...

    # Backward-compat aliases
    @property
    def agent_metadata(self) -> Dict[str, NodeExecutionInfo]: ...
    def get_input_for_agent(self, agent_name: str, dependencies: Set[str]) -> Dict[str, Any]: ...
```

---

## 3. Module Breakdown

### Module 1: Types (`types.py`)
- **Path**: `parrot/bots/flows/core/types.py`
- **Responsibility**: `AgentLike` Protocol, `AgentRef`, `DependencyResults`, `PromptBuilder`, `ActionCallback` type alias, `FlowStatus` enum.
- **Depends on**: none (pure types, no parrot imports)

### Module 2: FSM (`fsm.py`)
- **Path**: `parrot/bots/flows/core/fsm.py`
- **Responsibility**: `AgentTaskMachine` (StateMachine subclass with states: idle, ready, running, completed, failed, blocked; transitions: schedule, start, succeed, fail, block, unblock, retry). `TransitionCondition` enum.
- **Depends on**: `python-statemachine`, Module 1 (types)

### Module 3: Node hierarchy (`node.py`)
- **Path**: `parrot/bots/flows/core/node.py`
- **Responsibility**: `Node` ABC with `node_id`, action hooks, and `name` abstract property. `AgentNode` concrete class wrapping `AgentLike` + `AgentTaskMachine` with `node_id` separate from `agent.name`. `StartNode` and `EndNode` virtual nodes.
- **Depends on**: Module 1 (types), Module 2 (fsm)

### Module 4: Result models (`result.py`)
- **Path**: `parrot/bots/flows/core/result.py`
- **Responsibility**: `FlowResult` (replacing `CrewResult`), `NodeExecutionInfo` (replacing `AgentExecutionInfo`), `build_node_metadata()`, `determine_run_status()`. All with backward-compatible aliases. `AgentResult` stays in `parrot/models/crew.py` (not moved to core — resolved in brainstorm D11).
- **Depends on**: Module 1 (types)

### Module 5: FlowContext (`context.py`)
- **Path**: `parrot/bots/flows/core/context.py`
- **Responsibility**: `FlowContext` dataclass tracking workflow execution state. Methods: `can_execute()`, `mark_completed()`, `get_input_for_node()`. Backward-compatible `get_input_for_agent()` alias and `agent_metadata` property alias.
- **Depends on**: Module 1 (types), Module 4 (result — for `NodeExecutionInfo`)

### Module 6: Transitions (`transition.py`)
- **Path**: `parrot/bots/flows/core/transition.py`
- **Responsibility**: `FlowTransition` dataclass with conditional edge logic: `source`, `targets`, `condition`, `predicate`, `instruction`, `prompt_builder`, `priority`. Methods: `should_activate()`, `build_prompt()`.
- **Depends on**: Module 1 (types), Module 2 (fsm — for `TransitionCondition`), Module 4 (result — for `NodeExecutionInfo`)

### Module 7: Storage (`storage/`)
- **Path**: `parrot/bots/flows/core/storage/`
- **Responsibility**: `ExecutionMemory` (FAISS-based semantic search over agent results), `PersistenceMixin` (DocumentDB persistence), `SynthesisMixin` (LLM-based result synthesis), `VectorStoreMixin`.
- **Depends on**: `parrot.models.crew.AgentResult` (stays in models — D11), Module 4 (result — for `NodeExecutionInfo`)

### Module 8: Package init + re-exports
- **Path**: `parrot/bots/flows/__init__.py`, `parrot/bots/flows/core/__init__.py`
- **Responsibility**: Public API surface. Re-export all primitives from a single import path. Set up backward-compat re-exports in `parrot/models/crew.py`, `parrot/bots/flow/node.py`, `parrot/bots/flow/nodes/__init__.py`, `parrot/bots/flow/storage/__init__.py`.
- **Depends on**: Modules 1-7

### Module 9: Contract tests
- **Path**: `tests/test_flow_primitives/`
- **Responsibility**: Pure unit tests (no LLM, no network) validating:
  - FSM state invariants and transition legality
  - Ready-set computation (`FlowContext.can_execute()`)
  - Transition activation semantics
  - `FlowResult` serialization round-trips (`to_dict()` → reconstruct)
  - `NodeExecutionInfo` backward-compat aliases
  - `FlowContext` backward-compat aliases
  - `AgentLike` Protocol conformance checks
  - `Node` hierarchy: `node_id` vs `name` separation
- **Depends on**: Modules 1-8

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_agent_like_protocol` | Module 1 | Verify `AgentLike` Protocol accepts conforming objects, rejects non-conforming |
| `test_flow_status_values` | Module 1 | `FlowStatus` enum has `completed`, `partial`, `failed` |
| `test_fsm_initial_state` | Module 2 | `AgentTaskMachine` starts in `idle` |
| `test_fsm_happy_path` | Module 2 | idle → ready → running → completed is valid |
| `test_fsm_retry_path` | Module 2 | idle → ready → running → failed → ready (retry) is valid |
| `test_fsm_blocked_path` | Module 2 | idle → blocked → ready (unblock) is valid |
| `test_fsm_invalid_transitions` | Module 2 | idle → running, completed → ready, etc. raise `TransitionNotAllowed` |
| `test_fsm_completed_is_final` | Module 2 | No transitions from `completed` |
| `test_fsm_failed_is_not_final` | Module 2 | `failed` allows `retry` transition |
| `test_node_id_vs_name` | Module 3 | `AgentNode.node_id` differs from `AgentNode.name` (agent.name) |
| `test_start_end_nodes` | Module 3 | `StartNode` and `EndNode` instantiate with defaults |
| `test_node_action_hooks` | Module 3 | Pre/post actions execute in order (sync and async) |
| `test_flow_result_to_dict` | Module 4 | Round-trip serialization preserves all fields |
| `test_flow_result_backward_compat` | Module 4 | `.agents` property returns same as `.nodes`; `.agent_results` returns same as `.node_results` |
| `test_node_execution_info_aliases` | Module 4 | `.agent_id` returns `.node_id`; `.agent_name` returns `.node_name` |
| `test_determine_run_status` | Module 4 | (N success, 0 fail) → completed; (N, M) → partial; (0, M) → failed |
| `test_flow_context_can_execute` | Module 5 | Returns True when all deps in completed_tasks, False otherwise |
| `test_flow_context_mark_completed` | Module 5 | Updates results, completion_order, node_metadata |
| `test_flow_context_get_input_for_node` | Module 5 | No deps → initial_task only; with deps → includes dependency results |
| `test_flow_context_agent_metadata_alias` | Module 5 | `.agent_metadata` returns same as `.node_metadata` |
| `test_transition_condition_enum` | Module 6 | All values: on_success, on_error, on_timeout, on_condition, always |
| `test_transition_should_activate` | Module 6 | ON_SUCCESS activates on no-error; ON_ERROR activates on error |
| `test_transition_predicate` | Module 6 | ON_CONDITION delegates to async predicate |

### Integration Tests

| Test | Description |
|---|---|
| `test_crew_result_import_compat` | `from parrot.models.crew import CrewResult` still works and is `FlowResult` |
| `test_agent_execution_info_import_compat` | `from parrot.models.crew import AgentExecutionInfo` still works and is `NodeExecutionInfo` |
| `test_flow_node_import_compat` | `from parrot.bots.flow import Node, StartNode, EndNode` still work |
| `test_storage_import_compat` | `from parrot.bots.flow.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin` still work |
| `test_fsm_import_compat` | `from parrot.bots.flow import AgentTaskMachine, TransitionCondition` still work |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_agent():
    """An object satisfying AgentLike Protocol."""
    class MockAgent:
        @property
        def name(self) -> str:
            return "test-agent"
        async def invoke(self, prompt: str, **kwargs) -> Any:
            return f"response to: {prompt}"
    return MockAgent()

@pytest.fixture
def agent_node(mock_agent):
    """AgentNode with a mock agent and fresh FSM."""
    return AgentNode(agent=mock_agent, node_id="node-1")

@pytest.fixture
def flow_context():
    """Empty FlowContext for testing."""
    return FlowContext(initial_task="test task")
```

---

## 5. Acceptance Criteria

- [ ] `parrot/bots/flows/core/` package exists with all 7 submodules (types, fsm, node, result, context, transition, storage)
- [ ] `AgentLike` Protocol defined with `name` property and `invoke()` method
- [ ] `AgentTaskMachine` passes all FSM invariant tests (happy path, retry, blocked, invalid transitions)
- [ ] `Node` ABC has `node_id: str` field separate from `name` abstract property
- [ ] `AgentNode` wraps `AgentLike` + `AgentTaskMachine` with distinct `node_id` and `agent.name`
- [ ] `FlowResult` preserves all `CrewResult` observable properties with backward-compat aliases (`.agents`, `.agent_results`, `.content`, `.success`)
- [ ] `NodeExecutionInfo` preserves all `AgentExecutionInfo` fields with backward-compat aliases (`.agent_id`, `.agent_name`)
- [ ] `FlowContext` renamed methods (`get_input_for_node`) with backward-compat aliases (`get_input_for_agent`, `agent_metadata`)
- [ ] `FlowTransition` and `TransitionCondition` extracted from `fsm.py` with identical semantics
- [ ] Storage mixins (`ExecutionMemory`, `PersistenceMixin`, `SynthesisMixin`) moved to `flows/core/storage/` and operational
- [ ] All backward-compat re-exports work: `from parrot.models.crew import CrewResult`, `from parrot.bots.flow import Node`, `from parrot.bots.flow.storage import ExecutionMemory`
- [ ] Dead `AgentTask` class removed from `parrot/bots/orchestration/crew.py`
- [ ] Zero breaking changes to AgentCrew's public API
- [ ] All contract tests pass: `pytest tests/test_flow_primitives/ -v`
- [ ] All existing tests still pass (no regressions)
- [ ] No new external dependencies beyond `python-statemachine` (already in use)

---

## 6. Codebase Contract

### Verified Imports

```python
# These imports have been confirmed to work (re-verified 2026-04-29):
from parrot.bots.orchestration.crew import AgentCrew, AgentNode, FlowContext  # __init__.py
from parrot.bots.flow import Node, StartNode, EndNode                         # __init__.py
from parrot.bots.flow import AgentsFlow, AgentTaskMachine, FlowNode, FlowTransition, TransitionCondition
from parrot.models.crew import CrewResult, AgentExecutionInfo, AgentResult, build_agent_metadata, determine_run_status
from parrot.bots.flow.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin
from parrot.tools.agent import AgentContext
from parrot.models.status import AgentStatus
from statemachine import State, StateMachine  # used in fsm.py:23, verify.py:18
```

### Existing Class Signatures

```python
# parrot/bots/flow/node.py:11
ActionCallback = Callable[..., Union[None, Awaitable[None]]]

# parrot/bots/flow/node.py:14
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

# parrot/bots/flow/fsm.py:51
class TransitionCondition(str, Enum):
    ON_SUCCESS = "on_success"    # line 52
    ON_ERROR = "on_error"        # line 53
    ON_TIMEOUT = "on_timeout"    # line 54
    ON_CONDITION = "on_condition" # line 55
    ALWAYS = "always"            # line 56

# parrot/bots/flow/fsm.py:60
class AgentTaskMachine(StateMachine):
    idle = State("idle", initial=True)         # line 61
    ready = State("ready")                     # line 62
    running = State("running")                 # line 63
    completed = State("completed", final=True) # line 64
    failed = State("failed")                   # line 65  (NOT final — allows retry)
    blocked = State("blocked")                 # line 66
    schedule = idle.to(ready)                  # line 68
    start = ready.to(running)                  # line 69
    succeed = running.to(completed)            # line 70
    fail = running.to(failed) | ready.to(failed) | idle.to(failed)  # line 71
    block = idle.to(blocked) | ready.to(blocked)                     # line 72
    unblock = blocked.to(ready)                # line 73
    retry = failed.to(ready)                   # line 74

# parrot/bots/flow/fsm.py:116
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
    async def should_activate(self, result, error=None) -> bool: ...  # line 141
    async def build_prompt(self, context, dependencies) -> str: ...   # line 160

# parrot/bots/flow/fsm.py:198
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

# parrot/bots/orchestration/crew.py:75
@dataclass
class FlowContext:
    initial_task: str
    results: Dict[str, Any]
    responses: Dict[str, Any]
    agent_metadata: Dict[str, AgentExecutionInfo]
    completion_order: List[str]
    errors: Dict[str, Exception]

…(truncated)…
