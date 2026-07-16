---
type: Wiki Overview
title: 'Feature Specification: Flows Consolidation — Migrate Orchestration to `parrot/bots/flows/`'
id: doc:sdd-specs-flows-consolidation-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: even though it is the primary consumer of the flow primitives defined in
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.result
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage.synthesis
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.nodes
  rel: mentions
- concept: mod:parrot.bots.flows.tools
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.clients.factory
  rel: mentions
- concept: mod:parrot.clients.google
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
- concept: mod:parrot.models.responses
  rel: mentions
- concept: mod:parrot.models.status
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
- concept: mod:parrot.tools.agent
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# Feature Specification: Flows Consolidation — Migrate Orchestration to `parrot/bots/flows/`

**Feature ID**: FEAT-143
**Date**: 2026-05-04
**Author**: Jesus
**Status**: approved
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
- **Leave `orchestration/` in place for review**: The moved files are
  superseded by their new locations in `flows/`, but `orchestration/` is
  NOT deleted — remaining code needs review before removal.
- **Introduce `NodeResult` in `flows.core`**: Move `AgentResult` from
  `parrot.models.crew` to `flows.core.result` as `NodeResult` with
  node-centric naming (`node_id`/`node_name` instead of
  `agent_id`/`agent_name`) and backward-compat property aliases. This
  unifies the storage model across AgentCrew and future AgentsFlow.
- **Add `shared_data` to `FlowContext`**: Drop `AgentContext` entirely from
  AgentCrew by adding a `shared_data: Dict[str, Any]` field to
  `FlowContext`.

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
- Cleaning up `bots/flow/` (singular) — that module is for the AgentsFlow
  refactor (Spec 3) and is left untouched.
- Cleaning up `bots/orchestration/` beyond deletion — remaining code that
  other packages depend on stays until consumers are migrated in a separate
  pass. **Update**: orchestration/ is NOT deleted in this spec; it is left
  in place for review of remaining code. Only the files that move to
  `flows/` stop being maintained in `orchestration/`.

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

After the move, `parrot/bots/orchestration/` is **left in place** for review
of remaining code — it is NOT deleted in this spec.

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

parrot.bots.orchestration/ → LEFT IN PLACE (review remaining code separately)
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
| `parrot.models.crew.AgentResult` | **replaced by** | `NodeResult` in `flows.core.result` — unified storage model |
| `parrot.models.crew.CrewResult` | **no longer used** | Replaced by `FlowResult` |

### Data Models

The migration switches from old models to `flows.core.result` models and
introduces one new model (`NodeResult`):

| Old (removed from AgentCrew) | New (in flows.core) |
|---|---|
| `CrewResult` | `FlowResult` (already exists) |
| `AgentExecutionInfo` | `NodeExecutionInfo` (already exists) |
| `build_agent_metadata()` | `build_node_metadata()` (already exists) |
| `AgentResult` | `NodeResult` (**new** — created in this spec) |

#### `NodeResult` (new — replaces `AgentResult`)

`NodeResult` is the unified per-node execution record used by
`ExecutionMemory` for storage and FAISS vectorization. It replaces
`AgentResult` with node-centric naming while preserving all fields and
the `to_text()` vectorization method.

```python
# parrot/bots/flows/core/result.py (new class)
@dataclass
class NodeResult:
    """Per-node execution record for storage and vectorization."""
    node_id: str
    node_name: str
    task: str
    result: Any
    ai_message: Optional[AIMessage] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_execution_id: Optional[str] = None
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Backward-compat aliases
    @property
    def agent_id(self) -> str: return self.node_id
    @property
    def agent_name(self) -> str: return self.node_name

    def to_text(self) -> str:
        """Rich text for FAISS vectorization (handles DataFrame, dict, list)."""
        ...
```

`ExecutionMemory`, `VectorStoreMixin`, and all crew code switch from
`AgentResult` to `NodeResult`. `AgentResult` stays in `parrot.models.crew`
for any remaining consumers.

#### `FlowContext` — new `shared_data` field

```python
# parrot/bots/flows/core/context.py (add field)
@dataclass
class FlowContext:
    ...
    shared_data: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary key-value data shared across all nodes (replaces AgentContext.shared_data)."""
```

This eliminates the need for `AgentContext` in all AgentCrew execution modes.

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

### Module 4: Add `shared_data` to `FlowContext` + introduce `NodeResult`

- **Path**: `parrot/bots/flows/core/context.py`, `parrot/bots/flows/core/result.py`,
  `parrot/bots/flows/core/storage/memory.py`, `parrot/bots/flows/core/storage/mixin.py`
- **Responsibility**:
  1. Add `shared_data: Dict[str, Any]` field to `FlowContext`
  2. Create `NodeResult` dataclass in `flows/core/result.py` (replacing
     `AgentResult` for all flow-internal usage)
  3. Update `ExecutionMemory` to use `NodeResult` instead of `AgentResult`
  4. Update `VectorStoreMixin` to use `NodeResult` instead of `AgentResult`
  5. Export `NodeResult` from `flows/core/__init__.py` and `flows/__init__.py`
- **Depends on**: None (modifies core primitives)

### Module 5: Refactor sequential/loop/parallel modes to use `FlowContext`

- **Path**: `parrot/bots/flows/crew/crew.py` (same file as Module 3)
- **Responsibility**: Replace `AgentContext` usage in `run_sequential()`,
  `run_loop()`, and `run_parallel()` with `FlowContext`. This means:
  1. Replace `AgentContext(...)` construction with
     `FlowContext(initial_task=..., shared_data={...})`
  2. Use `context.mark_completed()` / `context.mark_failed()` for tracking
  3. Use `context.get_input_for_node()` for prompt assembly
  4. Adapt `_build_context_summary()` to read from `FlowContext.results`
     instead of `AgentContext.agent_results`
  5. Refactor `_execute_agent()` to accept `**kwargs` directly instead of
     `AgentContext` — pass `context.shared_data` as kwargs
  6. Remove `AgentContext` import entirely from `flows/crew/crew.py`
  7. Replace all `AgentResult(...)` constructions with `NodeResult(...)`
- **Depends on**: Module 3, Module 4

### Module 6: Create `flows/crew/__init__.py` and `flows/agents/` package

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

### Module 7: Update `flows/__init__.py` exports

- **Path**: `parrot/bots/flows/__init__.py`
- **Responsibility**:
  1. Update `parrot/bots/flows/__init__.py` to also export `AgentCrew`,
     `CrewAgentNode`, `NodeResult`, and the agent classes from the new
     sub-packages
  2. `parrot/bots/orchestration/` is **NOT deleted** — it remains for
     review of remaining code and consumer migration in a separate pass
- **Depends on**: Module 6

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
| `test_node_result_import` | Module 4 | `from parrot.bots.flows.core.result import NodeResult` works |
| `test_node_result_compat_aliases` | Module 4 | `NodeResult.agent_id` / `NodeResult.agent_name` return node_id/node_name |
| `test_flow_context_shared_data` | Module 4 | `FlowContext(initial_task="x", shared_data={"k": "v"})` works |
| `test_execution_memory_uses_node_result` | Module 4 | `ExecutionMemory.add_result()` accepts `NodeResult` |
| `test_flow_context_in_sequential` | Module 5 | `run_sequential` creates and populates `FlowContext` |
| `test_flow_context_in_loop` | Module 5 | `run_loop` creates and populates `FlowContext` |
| `test_no_agent_context_import` | Module 5 | `AgentContext` not imported in `flows/crew/crew.py` |
| `test_orchestrator_agent_import` | Module 6 | `from parrot.bots.flows.agents import OrchestratorAgent` works |
| `test_a2a_orchestrator_import` | Module 6 | `from parrot.bots.flows.agents import A2AOrchestratorAgent` works |

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
- [ ] `run_sequential()`, `run_loop()`, and `run_parallel()` use
  `FlowContext` (not `AgentContext`) for execution state tracking
- [ ] `run_sequential()`, `run_loop()`, and `run_parallel()` call
  `context.mark_completed()` / `context.mark_failed()` for each agent
  execution
- [ ] No import of `AgentContext` exists in `flows/crew/crew.py`
- [ ] `FlowContext` has a `shared_data: Dict[str, Any]` field
- [ ] `NodeResult` exists in `flows.core.result` with `node_id`,
  `node_name`, `task`, `result`, `to_text()`, and backward-compat
  `agent_id`/`agent_name` property aliases
- [ ] `ExecutionMemory` and `VectorStoreMixin` use `NodeResult` instead
  of `AgentResult`
- [ ] All `AgentResult(...)` constructions in `AgentCrew` are replaced
  with `NodeResult(...)`
- [ ] `from parrot.bots.flows.crew import AgentCrew` resolves successfully
- [ ] `from parrot.bots.flows.agents import OrchestratorAgent` resolves
  successfully
- [ ] `from parrot.bots.flows.core.result import NodeResult` resolves
  successfully
- [ ] All existing properties and methods of `AgentCrew` are preserved
  (same public API surface)
- [ ] `parrot/bots/orchestration/` is left in place (NOT deleted) for
  review of remaining code

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

…(truncated)…
