---
type: Wiki Overview
title: 'Feature Specification: AgentCrew Primitives Migration (Spec 2)'
id: doc:sdd-specs-agentcrew-primitives-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-134 just merged. The primitives are fresh, testable, and haven't accumulated
  downstream dependents. If a design flaw exists (e.g., FSM state transitions don't
  map to AgentCrew's `completed_tasks` pattern), now is the cheapest time to discover
  and fix it.
relates_to:
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
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# Feature Specification: AgentCrew Primitives Migration (Spec 2)

**Feature ID**: FEAT-137
**Date**: 2026-04-30
**Author**: Jesus
**Status**: draft
**Target version**: next
**Depends on**: FEAT-134 (flow-primitives, merged to dev)

---

## 1. Motivation & Business Requirements

### Problem Statement

`AgentCrew` (`parrot/bots/orchestration/crew.py`) and the new `flows.core` primitives (FEAT-134) define overlapping abstractions: both have `AgentNode`, `FlowContext`, type aliases (`AgentRef`, `DependencyResults`, `PromptBuilder`), and storage classes. This duplication means bug fixes and improvements must be applied twice, and the primitives remain unvalidated against a real consumer with real LLM calls.

FEAT-134 just merged. The primitives are fresh, testable, and haven't accumulated downstream dependents. If a design flaw exists (e.g., FSM state transitions don't map to AgentCrew's `completed_tasks` pattern), now is the cheapest time to discover and fix it.

### Goals

- **Eliminate duplication**: `crew.py` imports `AgentNode`, `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` from `parrot.bots.flows.core` instead of defining them locally.
- **Validate primitives under real load**: Exercise `AgentTaskMachine`, `FlowContext.can_execute()`, and the `node_id`-vs-`agent.name` separation against AgentCrew's four execution modes with real LLM calls.
- **Enrich core AgentNode**: Add `execute()` to core `AgentNode` with timeout handling, execution time tracking, and pre/post action hooks — making it reusable by both AgentCrew and the future AgentsFlow refactor (Spec 3).
- **Establish real-LLM test infrastructure**: Create `@pytest.mark.real_llm` marker and canonical regression tests using Gemini Flash (`temperature=0`).

### Non-Goals (explicitly out of scope)

- Refactor of AgentsFlow → Spec 3.
- New node types (Scatter/Gather/Decision/Loop/HITL) → Spec 3.
- Changes to the Handlers REST layer.
- Changes to `AgentCrew.add_agent()` signature (keeps `Union[BasicAgent, AbstractBot]` even though internal code uses `AgentLike`).
- Elimination of re-exports from FEAT-134 (those remain indefinitely for external users).
- Any new user-facing features or performance optimizations (except preventing regression).
- Runtime fallback-on-failure was rejected in brainstorm — see `proposals/agentcrew-primitives.brainstorm.md` Option C.

---

## 2. Architectural Design

### Overview

Migrate AgentCrew one execution mode at a time (per-mode sequential strategy), in order of complexity: `sequential` → `parallel` → `flow` → `loop`. Before mode migration, a prep task updates storage imports and sets up test infrastructure, and a core enhancement task adds `execute()` to `AgentNode`.

The migration is **invisible** to users: the public API, all observable behavior, and all historical import paths remain identical. Internally, `crew.py` stops defining local copies of types and node classes, importing everything from `parrot.bots.flows.core` instead. `_CrewAgentNode` becomes a subclass of core `AgentNode`, inheriting the new `execute()` method and overriding `_format_prompt()` to preserve crew-specific prompt formatting.

The `on_agent_complete` callback in `run_flow()` is wired to the FSM's `on_enter_completed` hook instead of the current ad-hoc call site, providing architecturally clean lifecycle event delivery.

### Component Diagram

```
parrot.bots.flows.core (FEAT-134, enhanced by this spec)
  ├── types.py           AgentLike, AgentRef, DependencyResults, PromptBuilder, FlowStatus
  ├── fsm.py             AgentTaskMachine, TransitionCondition
  ├── node.py            Node ABC, AgentNode (+execute()), StartNode, EndNode
  ├── context.py         FlowContext (with backward-compat aliases)
  ├── result.py          FlowResult, NodeExecutionInfo, determine_run_status
  ├── transition.py      FlowTransition
  └── storage/           ExecutionMemory, PersistenceMixin, SynthesisMixin, VectorStoreMixin

parrot.bots.orchestration.crew (this spec modifies)
  ├── _CrewAgentNode     NOW SUBCLASS of core AgentNode
  │   └── _format_prompt()  (private method, crew-specific prompt format)
  ├── AgentCrew          IMPORTS types/context/node from flows.core
  │   ├── run_sequential()   ← migrated in Task 2
  │   ├── run_parallel()     ← migrated in Task 3
  │   ├── run_flow()         ← migrated in Task 4 (callback via on_enter_completed)
  │   └── run_loop()         ← migrated in Task 5
  └── AgentNode = _CrewAgentNode  (backward-compat alias preserved)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.flows.core.node.AgentNode` | extends | Add `execute()` method; `_CrewAgentNode` becomes subclass |
| `parrot.bots.flows.core.context.FlowContext` | replaces local | crew.py's local `FlowContext` removed, imports from core |
| `parrot.bots.flows.core.types` | replaces local | Local `AgentRef`, `DependencyResults`, `PromptBuilder` removed |
| `parrot.bots.flows.core.fsm.AgentTaskMachine` | uses | FSM per node; `on_enter_completed` hook for callback wiring |
| `parrot.bots.flows.core.storage` | replaces old import path | Storage imports updated from `parrot.bots.flow.storage` to canonical `parrot.bots.flows.core.storage` |
| `parrot.models.crew` | depends on | `build_agent_metadata`, `CrewResult`, `AgentExecutionInfo` — unchanged |

### Data Models

No new data models introduced. Existing models unchanged:
- `CrewResult` (alias of `FlowResult`) — return type of all `run_*` methods.
- `AgentExecutionInfo` (alias of `NodeExecutionInfo`) — per-agent metadata.
- `FlowContext` — shared execution state with backward-compat aliases.

### New Public Interfaces

```python
# Added to parrot.bots.flows.core.node.AgentNode
class AgentNode(Node):
    async def execute(
        self,
        prompt: str,
        *,
        timeout: Optional[float] = None,
        **ctx: Any,
    ) -> Dict[str, Any]:
        """Execute the agent with pre/post hooks, timeout, and time tracking.

        Returns dict with keys: 'response', 'output', 'execution_time', 'prompt'.
        """
        ...
```

---

## 3. Module Breakdown

### Module 0: Prep — Test Audit & Infrastructure
- **Path**: `packages/ai-parrot/tests/conftest.py`, `pyproject.toml`, `crew.py` (imports only)
- **Responsibility**: Audit existing AgentCrew tests, identify invariant gaps. Set up `@pytest.mark.real_llm` marker with `PARROT_TEST_REAL_LLM=1` env var gating. Update storage imports in `crew.py` from `parrot.bots.flow.storage` to `parrot.bots.flows.core.storage`.
- **Depends on**: none

### Module 1: Core AgentNode Enhancement
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/core/node.py`, `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`
- **Responsibility**: Add `execute()` method to core `AgentNode` with timeout handling (`asyncio.wait_for`), execution time tracking, and pre/post action hook invocation. Make `_CrewAgentNode` a subclass of core `AgentNode` that overrides `_format_prompt()` as a private method. Verify `_CrewAgentNode.execute()` produces identical results to the current implementation.
- **Depends on**: Module 0

### Module 2: Migrate `run_sequential`
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`, `packages/ai-parrot/tests/`
- **Responsibility**: Swap local type aliases and `FlowContext` for `flows.core` imports within `run_sequential`. Wire FSM transitions (schedule → start → succeed/fail) at the correct points. Verify: execution order, output propagation, early-stop on failure, status calculation. Add regression tests (mock + real_llm).
- **Depends on**: Module 1

### Module 3: Migrate `run_parallel`
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`, `packages/ai-parrot/tests/`
- **Responsibility**: Same pattern as Module 2 for `run_parallel`. Verify: `asyncio.gather(return_exceptions=True)` semantics, concurrent FSM safety (each node has own FSM, shared `FlowContext.completed_tasks` mutation is atomic), status calculation (completed/partial/failed). Add regression tests.
- **Depends on**: Module 2

### Module 4: Migrate `run_flow`
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`, `packages/ai-parrot/tests/`
- **Responsibility**: Migrate DAG-based execution. Wire `on_agent_complete` callback to FSM `on_enter_completed` hook. Verify: dependency-based execution order, `task_flow` with `ON_SUCCESS`/`ON_ERROR`/`ON_CONDITION`/`ALWAYS` conditions, priority-based transition evaluation, cycle detection (warning, not exception), retry semantics. Add regression tests.
- **Depends on**: Module 3

### Module 5: Migrate `run_loop`
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`, `packages/ai-parrot/tests/`
- **Responsibility**: Migrate iterative execution. Verify: initial_task prompt, output-chaining between iterations (no context accumulation), LLM-evaluated stop condition, `max_iterations` cap, `result.metadata['iterations']` count. Add regression tests.
- **Depends on**: Module 4

### Module 6: Cleanup & Final Regression
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/crew.py`, `packages/ai-parrot/tests/`
- **Responsibility**: Remove dead local definitions (`FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` from crew.py). Verify re-exports work (`from parrot.bots.orchestration.crew import AgentNode, FlowContext`). Run full regression suite. Verify performance baseline (5-agent parallel flow no more than 10% regression).
- **Depends on**: Module 5

---

## 4. Test Specification

### Unit Tests (Mock-based, run always)

| Test | Module | Description |
|---|---|---|
| `test_agentnode_execute_returns_result_dict` | 1 | Core `AgentNode.execute()` returns dict with expected keys |
| `test_agentnode_execute_timeout_raises` | 1 | Timeout triggers `TimeoutError` + FSM transitions to `failed` |
| `test_agentnode_execute_pre_post_hooks` | 1 | Pre/post action hooks fire in correct order |
| `test_crewagentnode_format_prompt_byte_equality` | 1 | `_format_prompt` produces exact same bytes as before migration |
| `test_crewagentnode_subclass_of_agentnode` | 1 | `isinstance(_CrewAgentNode(), AgentNode)` is True |
| `test_sequential_execution_order` | 2 | Agents execute in add-order, output propagates N→N+1 |
| `test_sequential_early_stop_on_failure` | 2 | Agent K fails → K+1..N skip, status = partial |
| `test_parallel_gather_semantics` | 3 | All agents start concurrently, errors don't abort others |
| `test_parallel_status_calculation` | 3 | All OK → completed, mixed → partial, all fail → failed |
| `test_parallel_fsm_concurrent_safety` | 3 | Each node FSM transitions independently under gather |
| `test_flow_dependency_ordering` | 4 | Agent executes only when all deps completed |
| `test_flow_on_success_transition` | 4 | B runs only if A succeeded |
| `test_flow_on_error_transition` | 4 | C runs only if A failed |
| `test_flow_on_condition_predicate` | 4 | Predicate evaluated against real result |
| `test_flow_cycle_detection_warning` | 4 | Cycle → warning, not exception |
| `test_flow_callback_on_enter_completed` | 4 | `on_agent_complete` fires via FSM hook with correct args |
| `test_loop_iteration_chaining` | 5 | Iteration N prompt = output of N-1 |
| `test_loop_max_iterations_cap` | 5 | Stops at cap even if condition unmet |
| `test_backward_compat_imports` | 6 | `from parrot.bots.orchestration.crew import AgentNode, FlowContext` works |
| `test_crew_result_structure_unchanged` | 6 | `CrewResult` fields, aliases, and `to_dict()` format unchanged |

### Integration Tests (Real LLM, gated by `@pytest.mark.real_llm`)

| Test | Description |
|---|---|
| `test_real_sequential_3_agents` | 3-agent pipeline with Gemini Flash, verify output propagation |
| `test_real_sequential_middle_failure` | Middle agent fails, verify early-stop + partial status |
| `test_real_parallel_3_agents` | 3 agents in parallel, verify gather semantics with real timing |
| `test_real_parallel_one_failure` | One fails, verify partial status + others complete |
| `test_real_flow_dag` | A→B,C→D DAG, verify B/C run after A, D runs after B+C |
| `test_real_flow_conditional` | A→B (ON_SUCCESS), A→C (ON_ERROR), verify branching |
| `test_real_loop_condition_met` | Loop until output contains keyword, verify iteration count |
| `test_real_loop_max_cap` | Condition never met, verify max_iterations respected |

### Test Data / Fixtures

```python
@pytest.fixture
def stub_agent():
    """Deterministic agent returning configured responses."""
    # Uses existing DummyAgent pattern from test_agent_crew_examples.py

@pytest.fixture
def gemini_flash_agent():
    """Real Gemini Flash agent for @pytest.mark.real_llm tests."""
    # Requires PARROT_TEST_REAL_LLM=1 env var
    # Uses google-genai client with temperature=0
```

---

## 5. Acceptance Criteria

- [ ] `crew.py` no longer defines locally: `FlowContext`, `AgentRef`, `DependencyResults`, `PromptBuilder` — all imported from `parrot.bots.flows.core`
- [ ] `_CrewAgentNode` is a subclass of core `AgentNode`
- [ ] Core `AgentNode` has `execute()` method with timeout handling and time tracking
- [ ] `_format_prompt()` is a private method on `_CrewAgentNode` producing byte-identical output
- [ ] All existing tests in `test_agent_crew_examples.py` pass without modification
- [ ] `on_agent_complete` callback fires via FSM `on_enter_completed` hook
- [ ] `from parrot.bots.orchestration.crew import AgentNode, FlowContext` still works (re-exports)
- [ ] Storage imports use canonical path `parrot.bots.flows.core.storage`
- [ ] `@pytest.mark.real_llm` marker registered and gated by `PARROT_TEST_REAL_LLM=1`
- [ ] All mock-based unit tests pass (`pytest tests/ -v -m "not real_llm"`)
- [ ] All real_llm tests pass when enabled (`PARROT_TEST_REAL_LLM=1 pytest -m real_llm`)
- [ ] No new external dependencies added
- [ ] No changes to public API signatures
- [ ] 5-agent parallel flow does not regress >10% in wall-clock time
- [ ] Zero breaking changes to `CrewResult` structure and status semantics

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# Core primitives — all confirmed in flows/core/__init__.py
from parrot.bots.flows.core import (
    AgentLike, AgentRef, DependencyResults, PromptBuilder,
    ActionCallback, FlowStatus,
    AgentTaskMachine, TransitionCondition,
    Node, AgentNode, StartNode, EndNode,
    FlowResult, NodeExecutionInfo, build_node_metadata, determine_run_status,
    FlowContext, FlowTransition,
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)

# Crew result types — from parrot.models.crew
from parrot.models.crew import (
    CrewResult,                # line 43 in crew.py import
    AgentExecutionInfo,        # line 45 in crew.py import
    build_agent_metadata,      # line 46 in crew.py import — defined at parrot/models/crew.py:322
)

# Storage — canonical new path
from parrot.bots.flows.core.storage import (
    ExecutionMemory, PersistenceMixin, SynthesisMixin, VectorStoreMixin,
)

# Re-export shim at flows level — confirmed in parrot/bots/flows/__init__.py
from parrot.bots.flows import AgentNode, FlowContext
```

### Existing Class Signatures

```python
# parrot/bots/flows/core/node.py:34
class Node(ABC):
    node_id: str                                          # line 61
    logger: logging.Logger                                # line 62
    _pre_actions: list                                    # line 63
    _post_actions: list                                   # line 64
    def _init_node(self, node_id: str, name: str) -> None:  # line 66
    @property
    @abstractmethod
    def name(self) -> str:                                # line 80
    def add_pre_action(self, action: ActionCallback) -> None:  # line 87
    def add_post_action(self, action: ActionCallback) -> None: # line 95
    async def run_pre_actions(self, prompt: str = "", **ctx: Any) -> None:  # line 105
    async def run_post_actions(self, result: Any = None, **ctx: Any) -> None:  # line 121

# parrot/bots/flows/core/node.py:144
@dataclass
class AgentNode(Node):
    agent: AgentLike                                      # line 161
    node_id: str                                          # line 162
    dependencies: Set[str] = field(default_factory=set)   # line 163
    successors: Set[str] = field(default_factory=set)     # line 164
    fsm: Optional[AgentTaskMachine] = field(default=None) # line 165
    def __post_init__(self) -> None:                       # line 167
    @property
    def name(self) -> str:                                # line 173

# parrot/bots/orchestration/crew.py:130
class _CrewAgentNode:
    def __init__(self, agent: Union[BasicAgent, AbstractBot],
                 dependencies: Optional[Set[str]] = None):  # line 141
    def _format_prompt(self, input_data: Dict[str, Any]) -> str:  # line 146
    async def execute(self, context: FlowContext,
                      timeout: Optional[float] = None) -> Any:  # line 172

# parrot/bots/orchestration/crew.py:241
AgentNode = _CrewAgentNode  # backward-compat alias

# parrot/bots/orchestration/crew.py:244
class AgentCrew(PersistenceMixin, SynthesisMixin):
    async def run_sequential(self, query, ...) -> CrewResult:   # line 1123
    async def run_loop(self, initial_task, ...) -> CrewResult:  # line 1420
    async def run_parallel(self, tasks, ...) -> CrewResult:     # line 1846
    async def run_flow(self, initial_task, ...) -> CrewResult:  # line 2131
    def add_agent(self, agent: Union[BasicAgent, AbstractBot],
                  agent_id: str = None) -> None:                # line 412
    def task_flow(self, source_agent, target_agents):           # line 633

# parrot/bots/flows/core/context.py:26
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
    def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool:  # line 66
    def mark_completed(self, node_id, result=None, response=None,
                       metadata=None):                                      # line 80
    def mark_failed(self, node_id, error, metadata=None):                   # line 109
    def get_input_for_node(self, node_id, dependencies: Set[str]):          # line 132
    # Backward-compat aliases:
    @property
    def agent_metadata(self) -> Dict[str, NodeExecutionInfo]:               # line 169
    def get_input_for_agent(self, agent_name, dependencies):                # line 169+

# parrot/bots/flows/core/fsm.py:17
class TransitionCondition(str, Enum):
    ON_SUCCESS = "on_success"     # line 18
    ON_ERROR = "on_error"         # line 19
    ON_TIMEOUT = "on_timeout"     # line 20
    ON_CONDITION = "on_condition" # line 21
    ALWAYS = "always"             # line 22

# parrot/bots/flows/core/fsm.py:40
class AgentTaskMachine(StateMachine):
    # States: idle (initial), ready, running, completed (final), failed, blocked
    # Transitions: schedule, start, succeed, fail, block, unblock, retry
    # Hooks: on_enter_running(), on_enter_completed(), on_enter_failed()

# parrot/bots/flows/core/types.py:55
@runtime_checkable
class AgentLike(Protocol):
    @property
    def name(self) -> str:                             # line 63
    async def invoke(self, prompt: str, **kwargs) -> Any:  # line 73

# parrot/bots/flows/core/types.py:38
class FlowStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"

# parrot/bots/flows/core/types.py:100
AgentRef = Union[str, AgentLike]

# parrot/bots/flows/core/result.py:32
def determine_run_status(success_count: int, failure_count: int) -> Literal["completed", "partial", "failed"]:

# parrot/bots/flows/core/result.py:60
@dataclass
class NodeExecutionInfo:
    node_id: str
    node_name: str
    # ... agent_id, agent_name as backward-compat properties

# parrot/bots/flows/core/result.py:143
@dataclass
class FlowResult:
    # ... agents as backward-compat alias for nodes

# parrot/bots/flows/core/result.py:397
def build_node_metadata(...) -> NodeExecutionInfo:

# parrot/models/crew.py:322
def build_agent_metadata(
    agent_id: str, agent: Optional[Any], response: Optional[ResponseType],
    output: Optional[Any], execution_time: float, status: str,
    error: Optional[str] = None,
) -> AgentExecutionInfo:

# parrot/bots/flows/core/transition.py:28
@dataclass
class FlowTransition:
    source: str
    targets: Set[str]
    condition: TransitionCondition = TransitionCondition.ON_SUCCESS
    predicate: Optional[Callable] = None
    priority: int = 0
    async def should_activate(self, result, error) -> bool:

# parrot/bots/flow/fsm.py:198 (AgentsFlow's FlowNode — Spec 3 will refactor this)
@dataclass
class FlowNode(Node):
    agent: Union[BasicAgent, AbstractBot]           # line 210
    fsm: AgentTaskMachine                           # line 211
    execution_time: float = 0.0                     # line 217
    async def execute(self, prompt: str, ctx: Dict[str, Any]) -> Any:  # line 266
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_CrewAgentNode` (subclass) | `core.AgentNode` | inheritance | `flows/core/node.py:144` |
| `_CrewAgentNode._format_prompt()` | `FlowContext.get_input_for_agent()` | method call | `flows/core/context.py:169` |
| `AgentCrew.run_flow()` | `AgentTaskMachine.on_enter_completed` | FSM hook | `flows/core/fsm.py:40` |
| `AgentCrew` (all modes) | `FlowContext.mark_completed()` | method call | `flows/core/context.py:80` |
| `AgentCrew` (all modes) | `FlowContext.can_execute()` | method call | `flows/core/context.py:66` |
| `AgentCrew` (all modes) | `determine_run_status()` | function call | `flows/core/result.py:32` |
| `AgentCrew` (all modes) | `build_agent_metadata()` | function call | `parrot/models/crew.py:322` |

### Does NOT Exist (Anti-Hallucination)

- ~~`AgentNode.execute()`~~ — does NOT exist yet on core `AgentNode`; Module 1 will add it
- ~~`AgentLike.ask()`~~ — protocol defines `invoke()`, not `ask()`. Concrete agents use `ask()` but the protocol says `invoke()`. See Open Question D11
- ~~`FlowNode` in `flows.core`~~ — `FlowNode` exists only in old `parrot.bots.flow.fsm` (line 198), not in `flows.core`
- ~~`AgentNode.execution_time`~~ — does NOT exist on core `AgentNode`; only `FlowNode` has it (line 217)
- ~~`AgentNode.started_at` / `completed_at`~~ — do NOT exist on core `AgentNode`; only `FlowNode`
- ~~`Node.execute()`~~ — `Node` ABC has no `execute()` method; only action hooks
- ~~`@pytest.mark.real_llm`~~ — does NOT exist yet; Module 0 will create it
- ~~`FlowContext.mark_completed()` returning a value~~ — it returns `None`
- ~~`build_agent_metadata` in `flows.core`~~ — it lives in `parrot.models.crew`, not in `flows.core`. `flows.core` has `build_node_metadata` instead (result.py:397)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Async-first: all execution methods are `async def`.
- `_CrewAgentNode` inherits from core `AgentNode` via dataclass inheritance. Override `_format_prompt()` to preserve the crew-specific "Task + Context from previous agents" format.
- Core `AgentNode.execute()` calls `self.agent.ask()` (not `invoke()`) to match concrete agent implementations. The `AgentLike` protocol naming inconsistency is tracked for Spec 3 cleanup (D11).
- `execute()` returns a `Dict[str, Any]` with keys `'response'`, `'output'`, `'execution_time'`, `'prompt'` for backward compatibility. A structured `NodeExecutionResult` dataclass is deferred to Spec 3 (D12).

…(truncated)…
