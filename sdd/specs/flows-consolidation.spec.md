# Feature Specification: Flows Consolidation — Migrate Orchestration to `parrot/bots/flows/`

**Feature ID**: FEAT-143
**Date**: 2026-05-04
**Author**: Jesus
**Status**: draft
**Target version**: next
**Depends on**: FEAT-134 (flow-primitives, merged to dev)

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot/bots/orchestration/` exists as a separate package from `parrot/bots/flows/`
even though it is the primary consumer of the flow primitives defined in
`parrot/bots/flows/core/` (FEAT-134). This split causes:

- **Confusing import geography**: `AgentCrew` lives in `orchestration/` but
  imports its core abstractions from `flows/core/`. New developers cannot
  predict where a class lives.
- **Incomplete primitives migration**: `AgentCrew` still uses the old result
  models (`CrewResult`, `AgentExecutionInfo`, `build_agent_metadata` from
  `parrot.models.crew`) instead of the canonical `FlowResult`,
  `NodeExecutionInfo`, `build_node_metadata` from `flows.core.result`.
- **Mode inconsistency**: `run_sequential()` and `run_loop()` use
  `AgentContext` (from `parrot.tools.agent`) for execution tracking while
  `run_flow()` correctly uses `FlowContext` (from `flows.core.context`).
  This means two of four execution modes bypass the shared context primitive.
- **Monolithic crew.py**: At 3589 lines, `crew.py` bundles the
  `_CrewAgentNode` dataclass alongside the `AgentCrew` orchestrator,
  preventing reuse of the node type in other flow engines.
- **Stale `bots/flow/` module**: The old singular `bots/flow/` coexists with
  the new `bots/flows/` — `ResultRetrievalTool` is still imported from the
  old location.

### Goals

- **Consolidate under `parrot/bots/flows/`**: Move `AgentCrew` to
  `flows/crew/` sub-package, `OrchestratorAgent` / `A2AOrchestratorAgent` to
  `flows/agents/`, and `ResultRetrievalTool` to `flows/tools.py`.
- **Complete the result model migration**: Replace all `CrewResult` /
  `AgentExecutionInfo` / `build_agent_metadata` usage inside `AgentCrew` with
  `FlowResult` / `NodeExecutionInfo` / `build_node_metadata`.
- **Unify execution context**: Refactor `run_sequential()` and `run_loop()`
  to use `FlowContext` instead of `AgentContext`.
- **Extract `CrewAgentNode`**: Move `_CrewAgentNode` from `crew.py` to its own
  `flows/crew/nodes.py` module, rename to `CrewAgentNode`.
- **Delete `orchestration/`**: The old package is removed entirely — no
  backward-compat re-exports.

### Non-Goals (explicitly out of scope)

- Fixing downstream consumers (handlers, manager, examples, tests) — those
  break intentionally and will be fixed in a separate refactoring pass.
- Refactor of `AgentsFlow` (the `bots/flow/` engine) — that is Spec 3
  territory.
- New execution modes, node types, or user-facing features.
- Changes to `parrot.models.crew` itself — the old models stay for any
  remaining consumers; they are simply no longer used inside `AgentCrew`.
- Migrating `AgentContext` out of `parrot.tools.agent` — it stays; we just
  stop using it inside `AgentCrew`.
- Performance optimizations or new test infrastructure.

---

## 2. Architectural Design

### Overview

This is a structural refactoring that reorganises the `parrot.bots` package
tree. The new layout under `parrot/bots/flows/` becomes:

```
parrot/bots/flows/
├── __init__.py              (existing — re-exports core primitives)
├── core/                    (existing — FEAT-134 primitives)
│   ├── __init__.py
│   ├── types.py
│   ├── fsm.py
│   ├── node.py
│   ├── context.py
│   ├── result.py
│   ├── transition.py
│   └── storage/
├── crew/                    (NEW — AgentCrew sub-package)
│   ├── __init__.py          (exports AgentCrew, CrewAgentNode)
│   ├── crew.py              (AgentCrew class, moved from orchestration/)
│   └── nodes.py             (CrewAgentNode, extracted from crew.py)
├── agents/                  (NEW — orchestrator agents)
│   ├── __init__.py          (exports OrchestratorAgent, A2AOrchestratorAgent, etc.)
│   ├── orchestrator.py      (OrchestratorAgent, moved from orchestration/agent.py)
│   ├── a2a_orchestrator.py  (A2AOrchestratorAgent, moved from orchestration/)
│   └── hr.py                (HRAgentFactory, RAGHRAgent, etc., moved from orchestration/)
└── tools.py                 (NEW — ResultRetrievalTool, moved from bots/flow/tools.py)
```

After the move, `parrot/bots/orchestration/` is **deleted entirely**.

### Component Diagram

```
parrot.bots.flows.core (FEAT-134 — untouched)
    ├── types, fsm, node, context, result, transition, storage
    │
    ├──→ parrot.bots.flows.crew (NEW)
    │      ├── nodes.py: CrewAgentNode(_CoreAgentNode)
    │      └── crew.py: AgentCrew(PersistenceMixin, SynthesisMixin)
    │            uses: FlowResult, NodeExecutionInfo, build_node_metadata
    │            uses: FlowContext (all 4 modes)
    │            uses: AgentTaskMachine, ExecutionMemory
    │
    ├──→ parrot.bots.flows.agents (NEW)
    │      ├── orchestrator.py: OrchestratorAgent(BasicAgent)
    │      ├── a2a_orchestrator.py: A2AOrchestratorAgent(OrchestratorAgent, A2AClientMixin)
    │      └── hr.py: HRAgentFactory, RAGHRAgent, EmployeeDataAgent
    │
    └──→ parrot.bots.flows.tools (NEW)
           └── ResultRetrievalTool(AbstractTool)

parrot.bots.orchestration/ → DELETED
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `flows.core.node.AgentNode` | extended by | `CrewAgentNode` subclasses it |
| `flows.core.context.FlowContext` | used by | All 4 AgentCrew execution modes |
| `flows.core.result.FlowResult` | returned by | Replaces `CrewResult` in AgentCrew |
| `flows.core.result.NodeExecutionInfo` | used by | Replaces `AgentExecutionInfo` in AgentCrew |
| `flows.core.result.build_node_metadata` | called by | Replaces `build_agent_metadata` in AgentCrew |
| `flows.core.storage.*` | inherited by | `AgentCrew(PersistenceMixin, SynthesisMixin)` |
| `flows.core.fsm.AgentTaskMachine` | composed by | Each `CrewAgentNode` contains one |
| `parrot.tools.agent.AgentTool` | used by | AgentCrew wraps agents as tools |
| `parrot.tools.agent.AgentContext` | **no longer used** | Replaced by `FlowContext` |
| `parrot.models.crew.AgentResult` | still used | For `ExecutionMemory.add_result()` — NOT changed |
| `parrot.models.crew.CrewResult` | **no longer used** | Replaced by `FlowResult` |

### Data Models

No new data models. The migration switches from old models to existing
`flows.core.result` models:

| Old (removed from AgentCrew) | New (already exists in flows.core) |
|---|---|
| `CrewResult` | `FlowResult` |
| `AgentExecutionInfo` | `NodeExecutionInfo` |
| `build_agent_metadata()` | `build_node_metadata()` |

`AgentResult` (used for `ExecutionMemory`) is **not changed** — it stays in
`parrot.models.crew` and is still used inside `AgentCrew` for memory storage.

### New Public Interfaces

No new classes or methods. The public API of `AgentCrew` remains identical.
Only the return type changes from `CrewResult` to `FlowResult`, which is
structurally compatible (all `CrewResult` properties exist as aliases on
`FlowResult`).

---

## 3. Module Breakdown

### Module 1: Extract `CrewAgentNode` to `flows/crew/nodes.py`

- **Path**: `parrot/bots/flows/crew/nodes.py`
- **Responsibility**: Crew-specific node type that subclasses core `AgentNode`.
  Contains `CrewAgentNode` (renamed from `_CrewAgentNode`) with
  `_format_prompt()` and `execute_in_context()`.
- **Depends on**: `flows.core.node.AgentNode`, `flows.core.context.FlowContext`

### Module 2: Move `ResultRetrievalTool` to `flows/tools.py`

- **Path**: `parrot/bots/flows/tools.py`
- **Responsibility**: `ResultRetrievalTool` moved from `bots/flow/tools.py`.
  Imports `ExecutionMemory` from `flows.core.storage` instead of old
  `bots/flow/storage`.
- **Depends on**: `flows.core.storage.memory.ExecutionMemory`

### Module 3: Move `AgentCrew` to `flows/crew/crew.py` + result model migration

- **Path**: `parrot/bots/flows/crew/crew.py`
- **Responsibility**: The full `AgentCrew` class. During this move:
  1. Replace all `CrewResult` → `FlowResult`
  2. Replace all `AgentExecutionInfo` → `NodeExecutionInfo`
  3. Replace all `build_agent_metadata()` → `build_node_metadata()`
  4. Import `CrewAgentNode` from `.nodes` instead of defining inline
  5. Import `ResultRetrievalTool` from `..tools` instead of `bots.flow.tools`
  6. Update relative imports to new location (`..core.`, `...agent`, etc.)
- **Depends on**: Module 1, Module 2

### Module 4: Refactor sequential/loop modes to use `FlowContext`

- **Path**: `parrot/bots/flows/crew/crew.py` (same file as Module 3)
- **Responsibility**: Replace `AgentContext` usage in `run_sequential()` and
  `run_loop()` with `FlowContext`. This means:
  1. Replace `AgentContext(...)` construction with `FlowContext(initial_task=...)`
  2. Use `context.mark_completed()` / `context.mark_failed()` for tracking
  3. Use `context.get_input_for_node()` for prompt assembly
  4. Adapt `_build_context_summary()` to read from `FlowContext.results`
     instead of `AgentContext.agent_results`
  5. Remove `AgentContext` import (only used by `_execute_agent()` — see
     Module 5 for that method's refactoring)
- **Depends on**: Module 3

### Module 5: Create `flows/crew/__init__.py` and `flows/agents/` package

- **Path**: `parrot/bots/flows/crew/__init__.py`,
  `parrot/bots/flows/agents/__init__.py`,
  `parrot/bots/flows/agents/orchestrator.py`,
  `parrot/bots/flows/agents/a2a_orchestrator.py`,
  `parrot/bots/flows/agents/hr.py`
- **Responsibility**:
  1. Create `crew/__init__.py` exporting `AgentCrew`, `CrewAgentNode`
  2. Move `orchestration/agent.py` → `flows/agents/orchestrator.py`
     (update relative imports)
  3. Move `orchestration/a2a_orchestrator.py` → `flows/agents/a2a_orchestrator.py`
     (update relative imports)
  4. Move `orchestration/hr.py` → `flows/agents/hr.py`
     (update relative imports)
  5. Create `agents/__init__.py` exporting public classes
- **Depends on**: Module 3

### Module 6: Delete `orchestration/` and update `flows/__init__.py`

- **Path**: `parrot/bots/orchestration/` (DELETE), `parrot/bots/flows/__init__.py`
- **Responsibility**:
  1. Delete `parrot/bots/orchestration/` entirely (all files including `__init__.py`, `verify.py`)
  2. Update `parrot/bots/flows/__init__.py` to also export `AgentCrew`,
     `CrewAgentNode`, and the agent classes from the new sub-packages
- **Depends on**: Module 5

---

## 4. Test Specification

### Unit Tests

Since downstream consumers are left intentionally broken, the scope of
testing for this spec is limited to verifying that the moved modules are
importable and structurally correct.

| Test | Module | Description |
|---|---|---|
| `test_crew_node_import` | Module 1 | `from parrot.bots.flows.crew.nodes import CrewAgentNode` works |
| `test_crew_node_inherits_core` | Module 1 | `CrewAgentNode` is a subclass of `flows.core.node.AgentNode` |
| `test_result_retrieval_tool_import` | Module 2 | `from parrot.bots.flows.tools import ResultRetrievalTool` works |
| `test_agent_crew_import` | Module 3 | `from parrot.bots.flows.crew import AgentCrew` works |
| `test_agent_crew_returns_flow_result` | Module 3 | `AgentCrew.run_sequential()` returns `FlowResult` (mock agents) |
| `test_flow_context_in_sequential` | Module 4 | `run_sequential` creates and populates `FlowContext` |
| `test_flow_context_in_loop` | Module 4 | `run_loop` creates and populates `FlowContext` |
| `test_orchestrator_agent_import` | Module 5 | `from parrot.bots.flows.agents import OrchestratorAgent` works |
| `test_a2a_orchestrator_import` | Module 5 | `from parrot.bots.flows.agents import A2AOrchestratorAgent` works |
| `test_orchestration_deleted` | Module 6 | `import parrot.bots.orchestration` raises `ImportError` |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_agent():
    """Minimal AgentLike mock for unit tests."""
    agent = AsyncMock()
    agent.name = "test_agent"
    agent.is_configured = True
    agent.ask = AsyncMock(return_value=Mock(content="result", output="result"))
    agent.tool_manager = Mock()
    agent.tool_manager.list_tools = Mock(return_value=[])
    agent.tool_manager.get_tool = Mock(return_value=None)
    agent.add_event_listener = Mock()
    return agent
```

---

## 5. Acceptance Criteria

- [ ] `parrot/bots/flows/crew/nodes.py` contains `CrewAgentNode` (public name,
  subclass of `flows.core.node.AgentNode`)
- [ ] `parrot/bots/flows/crew/crew.py` contains `AgentCrew` with all 4
  execution modes functional
- [ ] `parrot/bots/flows/tools.py` contains `ResultRetrievalTool`
- [ ] `parrot/bots/flows/agents/` contains `OrchestratorAgent`,
  `A2AOrchestratorAgent`, `HRAgentFactory`, `RAGHRAgent`, `EmployeeDataAgent`
- [ ] `AgentCrew` returns `FlowResult` (not `CrewResult`) from all execution
  modes: `run_sequential`, `run_parallel`, `run_flow`, `run_loop`
- [ ] `AgentCrew` uses `build_node_metadata()` (not `build_agent_metadata()`)
  for all execution metadata construction
- [ ] `run_sequential()` and `run_loop()` use `FlowContext` (not
  `AgentContext`) for execution state tracking
- [ ] `run_sequential()` and `run_loop()` call `context.mark_completed()` /
  `context.mark_failed()` for each agent execution
- [ ] No import of `AgentContext` exists in `flows/crew/crew.py`
- [ ] `parrot/bots/orchestration/` directory does not exist
- [ ] `from parrot.bots.flows.crew import AgentCrew` resolves successfully
- [ ] `from parrot.bots.flows.agents import OrchestratorAgent` resolves
  successfully
- [ ] All existing properties and methods of `AgentCrew` are preserved
  (same public API surface)

---

## 6. Codebase Contract

### Verified Imports

```python
# flows.core primitives (verified: parrot/bots/flows/core/__init__.py:1-79)
from parrot.bots.flows.core import (
    AgentLike, AgentRef, DependencyResults, PromptBuilder,
    ActionCallback, FlowStatus,
    AgentTaskMachine, TransitionCondition,
    Node, AgentNode, StartNode, EndNode,
    FlowResult, NodeExecutionInfo, build_node_metadata, determine_run_status,
    FlowContext,
    FlowTransition,
    ExecutionMemory, VectorStoreMixin, PersistenceMixin, SynthesisMixin,
)

# Old models still used for ExecutionMemory (verified: parrot/models/crew.py:386-446)
from parrot.models.crew import AgentResult

# Agent/Bot base classes (verified: parrot/bots/__init__.py:1-18)
from parrot.bots.agent import BasicAgent
from parrot.bots.abstract import AbstractBot

# Client infrastructure (verified: parrot/clients/__init__.py)
from parrot.clients import AbstractClient
from parrot.clients.factory import SUPPORTED_CLIENTS
from parrot.clients.google import GoogleGenAIClient

# Tool infrastructure (verified: parrot/tools/agent.py:1-30)
from parrot.tools.manager import ToolManager
from parrot.tools.agent import AgentTool, AgentContext
from parrot.tools.abstract import AbstractTool

# Response models (verified: parrot/models/responses.py)
from parrot.models.responses import AIMessage, AgentResponse

# Status enum (verified: parrot/models/status.py:1-9)
from parrot.models.status import AgentStatus

# Storage synthesis prompt (verified: parrot/bots/flows/core/storage/synthesis.py)
from parrot.bots.flows.core.storage.synthesis import SYNTHESIS_PROMPT
```

### Existing Class Signatures

```python
# parrot/bots/flows/core/node.py:143-242
@dataclass
class AgentNode(Node):
    agent: AgentLike
    node_id: str
    dependencies: Set[str] = field(default_factory=set)
    successors: Set[str] = field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = field(default=None)
    def __post_init__(self) -> None: ...
    @property
    def name(self) -> str: ...
    async def execute(self, prompt: str, *, timeout: Optional[float] = None, **ctx) -> Dict[str, Any]: ...

# parrot/bots/flows/core/context.py:26-183
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
    def can_execute(self, _node_id: str, dependencies: Set[str]) -> bool: ...
    def mark_completed(self, node_id: str, result=None, response=None, metadata=None) -> None: ...
    def mark_failed(self, node_id: str, error: Exception, metadata=None) -> None: ...
    def get_input_for_node(self, node_id: str, dependencies: Set[str]) -> Dict[str, Any]: ...
    # Backward-compat aliases:
    @property
    def agent_metadata(self) -> Dict[str, NodeExecutionInfo]: ...
    def get_input_for_agent(self, agent_name: str, dependencies: Set[str]) -> Dict[str, Any]: ...

# parrot/bots/flows/core/result.py:59-135
@dataclass
class NodeExecutionInfo:
    node_id: str
    node_name: str
    provider: Optional[str] = None
    model: Optional[str] = None
    execution_time: float = 0.0
    tool_calls: List[Dict[str, Any]]
    status: Literal["completed", "failed", "pending", "running"] = "pending"
    error: Optional[str] = None
    client: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    @property
    def agent_id(self) -> str: ...     # alias for node_id
    @property
    def agent_name(self) -> str: ...   # alias for node_name
    def to_dict(self) -> Dict[str, Any]: ...

# parrot/bots/flows/core/result.py:142-360
@dataclass
class FlowResult:
    output: Any
    responses: Dict[str, Any]
    summary: str = ""
    nodes: List[NodeExecutionInfo]         # was "agents" in CrewResult
    execution_log: List[Dict[str, Any]]
    total_time: float = 0.0
    status: FlowStatus = FlowStatus.COMPLETED
    errors: Dict[str, str]
    metadata: Dict[str, Any]
    @property
    def agents(self) -> List[NodeExecutionInfo]: ...  # backward compat alias
    @property
    def content(self) -> Optional[Any]: ...
    @property
    def success(self) -> bool: ...
    @property
    def agent_results(self) -> Dict[str, Any]: ...
    def to_dict(self) -> Dict[str, Any]: ...
    def __getitem__(self, item: str) -> Any: ...

# parrot/bots/flows/core/result.py:397-486
def build_node_metadata(
    node_id: str,
    agent: Optional[Any],
    response: Optional[Any],
    output: Optional[Any],
    execution_time: float,
    status: str,
    error: Optional[str] = None,
) -> NodeExecutionInfo: ...

# parrot/bots/flows/core/result.py:32-51
def determine_run_status(success_count: int, failure_count: int) -> Literal["completed", "partial", "failed"]: ...

# parrot/tools/agent.py:21-29
@dataclass
class AgentContext:
    user_id: str
    session_id: str
    original_query: str
    conversation_history: List[ConversationTurn]
    shared_data: Dict[str, Any]
    agent_results: Dict[str, Any]
    metadata: Dict[str, Any]

# parrot/bots/flow/tools.py:1-79
class ResultRetrievalTool(AbstractTool):
    name = "execution_context_tool"
    def __init__(self, memory: ExecutionMemory, *args, **kwargs): ...
    def get_schema(self) -> Dict[str, Any]: ...
    async def _execute(self, action: str, agent_id=None, query=None) -> str: ...
```

### Key Mapping: CrewResult → FlowResult Field Names

| `CrewResult` field | `FlowResult` field | Notes |
|---|---|---|
| `agents: List[AgentExecutionInfo]` | `nodes: List[NodeExecutionInfo]` | `.agents` exists as alias |
| `status: Literal[str]` | `status: FlowStatus` | Enum values match string literals |
| All other fields | Same name | `output`, `responses`, `summary`, `execution_log`, `total_time`, `errors`, `metadata` |

### Key Mapping: build_agent_metadata → build_node_metadata

Both functions have **identical signatures** and semantics. The only difference
is the return type (`AgentExecutionInfo` vs `NodeExecutionInfo`).

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `CrewAgentNode` | `flows.core.AgentNode` | dataclass inheritance | `core/node.py:143` |
| `AgentCrew.run_flow()` | `FlowContext` | already uses it | `crew.py:2209` |
| `AgentCrew.run_sequential()` | `FlowContext` | **will replace** `AgentContext` | `crew.py:1126` |
| `AgentCrew.run_loop()` | `FlowContext` | **will replace** `AgentContext` | `crew.py:1487` |
| `AgentCrew.run_parallel()` | `FlowContext` | **will replace** `AgentContext` | `crew.py:1878` |
| `AgentCrew` return type | `FlowResult` | **replaces** `CrewResult` | throughout `crew.py` |
| `ResultRetrievalTool` | `ExecutionMemory` | constructor injection | `flow/tools.py:13` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.bots.flows.crew`~~ — does not exist yet (Module 1-3 creates it)
- ~~`parrot.bots.flows.agents`~~ — does not exist yet (Module 5 creates it)
- ~~`parrot.bots.flows.tools`~~ — does not exist yet as a module (Module 2 creates it)
- ~~`FlowContext.agent_results`~~ — does NOT exist; use `FlowContext.results` (which maps `node_id → result`)
- ~~`FlowContext.original_query`~~ — does NOT exist; use `FlowContext.initial_task`
- ~~`FlowResult.agents` (as a constructor field)~~ — `agents` is a property alias; the constructor field is `nodes`
- ~~`CrewAgentNode` (as a public name)~~ — does not exist yet; currently `_CrewAgentNode` (private)
- ~~`parrot.bots.orchestration.tools`~~ — referenced in one example but does NOT exist; the tool is in `bots/flow/tools.py`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Relative imports within `flows/`**: Use `from ..core.context import FlowContext`,
  `from ..core.result import FlowResult`, etc.
- **FlowResult constructor uses `nodes=` not `agents=`**: When replacing
  `CrewResult(agents=agents_info, ...)` write `FlowResult(nodes=agents_info, ...)`.
- **FlowResult.status uses `FlowStatus` enum**: Replace string literals like
  `status='completed'` with `FlowStatus.COMPLETED`. Or use
  `determine_run_status()` which returns string literals (both work — FlowResult
  accepts either via `__setattr__`).
- **FlowContext.results vs AgentContext.agent_results**: `FlowContext` stores
  results in `self.results[node_id]` via `mark_completed()`. To get a dict of
  all results, read `context.results` directly.
- **`_execute_agent()` still needs `AgentContext`**: The `_execute_agent()` method
  passes `context.shared_data` to agents. For the FlowContext migration, either:
  (a) add a `shared_data` attribute to the FlowContext instance ad-hoc (as
  `run_flow` already does with `context.execution_memory`), or
  (b) pass `**kwargs` directly to `agent.ask()` without wrapping in AgentContext.
  Option (b) is cleaner. `_execute_agent()` should be refactored to accept kwargs
  directly instead of an `AgentContext`.

### Migration Strategy for `run_sequential()` / `run_loop()`

Currently these modes use `AgentContext` for:
1. `crew_context.agent_results[agent_id] = result` → becomes `context.mark_completed(agent_id, result, response, metadata)`
2. `crew_context.shared_data` → attach to FlowContext instance or pass via kwargs
3. `self._build_context_summary(crew_context)` reads `crew_context.agent_results` → refactor to read `context.results`

The `run_parallel()` mode also uses `AgentContext` in the same pattern and should
be migrated identically.

### Handling `_execute_agent()` Without `AgentContext`

`_execute_agent()` (line 855) currently takes an `AgentContext` and unpacks
`context.shared_data` into the agent call. After migration, either:
- Change its signature to accept `**kwargs` directly, or
- Accept a `FlowContext` and read from it.

The simplest approach: change signature to `_execute_agent(self, agent, query,
session_id, user_id, index, **kwargs)` and pass kwargs through. The `AgentContext`
wrapping was only used for `shared_data` passthrough.

### Known Risks / Gotchas

- **`FlowResult.status` is a `FlowStatus` enum, not a plain string**: Code that
  does `result.status == 'completed'` still works because `FlowStatus` inherits
  from `str`, but code that does `result.status` as a dict key or serialisation
  target should use `.value`.
- **`context.agent_metadata` is an alias**: The primary field is
  `context.node_metadata`. Use the primary name in new code.
- **`run_flow()` already sets ad-hoc attributes on FlowContext**:
  `context.execution_memory`, `context.user_id`, `context.session_id` are set
  dynamically (line 2211-2213). This works because `FlowContext` is a dataclass
  and Python allows setting arbitrary attributes. The same pattern should be
  used for sequential/loop/parallel modes.
- **`AgentResult` stays in `parrot.models.crew`**: This is intentional.
  `AgentResult` is used by `ExecutionMemory.add_result()` and changing it is
  out of scope.
- **Consumers will break**: Handlers, manager, examples, and tests that import
  from `parrot.bots.orchestration` will fail. This is by design — a subsequent
  pass will fix all consumers.
- **`verify.py` in orchestration/** is a standalone verification script, not
  a test — it can be deleted without impact.

### External Dependencies

No new external dependencies.

---

## 8. Open Questions

- [ ] Should `_execute_agent()` be refactored to drop `AgentContext` entirely, or
  should we add `shared_data` as a field on `FlowContext`? — *Owner: Jesus*
- [ ] Should `AgentResult` (used for ExecutionMemory) eventually move to
  `flows.core` or stay in `models.crew`? — *Owner: Jesus* (deferred to future spec)
- [ ] Should the old `bots/flow/` package (singular) also be cleaned up in this
  spec, or kept for the AgentsFlow refactor (Spec 3)? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: per-spec (single worktree, sequential tasks)
- **Rationale**: All modules modify the same package tree and have sequential
  dependencies. Parallel execution would cause merge conflicts.
- **Cross-feature dependencies**: FEAT-134 (flow-primitives) must be merged
  first — already merged to dev.

```bash
git worktree add -b feat-143-flows-consolidation \
  .claude/worktrees/feat-143-flows-consolidation HEAD
```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-04 | Jesus | Initial draft |
