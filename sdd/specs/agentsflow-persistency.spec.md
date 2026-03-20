# Feature Specification: AgentsFlow Persistency

**Feature ID**: FEAT-009
**Date**: 2026-02-22
**Author**: Claude
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

> Enable AgentsFlow workflows to be persisted, loaded, and transferred as JSON definitions, making them portable, versionable, and compatible with visual workflow builders.

### Problem Statement

AgentsFlow (`parrot/bots/flow/fsm.py`) provides sophisticated DAG-based agent pipelines with FSM-controlled lifecycle management, conditional transitions, and pre/post hooks. However, flows are **defined exclusively in Python code**, creating significant limitations:

1. **No persistence** — Flows cannot be saved, versioned, or transferred between services
2. **Developer-only** — Non-technical stakeholders cannot view or modify workflow definitions
3. **No visual editing** — Incompatible with visual builders (SvelteFlow, ReactFlow)
4. **No runtime composition** — Flows must be compiled at startup, cannot be loaded dynamically
5. **Lambda predicates are not serializable** — Conditional transitions use Python lambdas that cannot be persisted

### Goals
- JSON schema for complete flow definitions (nodes, edges, actions, conditions)
- Load flows from files and Redis with parity to `AgentCrew` persistence patterns
- Materialize JSON definitions into runnable `AgentsFlow` instances
- Safe, serializable predicate system using CEL (Common Expression Language)
- SvelteFlow-compatible node/edge structure for visual builder integration
- Action registry for lifecycle hooks (log, notify, webhook, etc.)

### Non-Goals (explicitly out of scope)
- Visual flow builder UI (separate project; this spec provides the data layer)
- Runtime flow modification (hot-reload of running flows)
- Flow versioning/migration system (v1 only; migration deferred)
- Custom CEL functions beyond built-in operators

---

## 2. Architectural Design

### Overview

Introduce `FlowDefinition`, a JSON-first serialization format that fully describes an `AgentsFlow` workflow. A `FlowLoader` class handles persistence (file/Redis) and materialization (JSON → runnable flow). Conditional predicates use CEL (Common Expression Language) for safe, sandboxed evaluation.

### Component Diagram
```
┌─────────────────────────────────────────────────────────────────────┐
│                         FlowDefinition (JSON)                       │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────────┐   │
│  │   nodes[]   │   │   edges[]   │   │   metadata              │   │
│  │  NodeDef    │   │  EdgeDef    │   │  FlowMetadata           │   │
│  └─────────────┘   └─────────────┘   └─────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           FlowLoader                                │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐    │
│  │ load_from_*  │   │  save_to_*   │   │   to_agents_flow()   │    │
│  │  file/redis  │   │  file/redis  │   │                      │    │
│  └──────────────┘   └──────────────┘   └──────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
   ┌──────────────────┐  ┌─────────────┐  ┌─────────────────┐
   │ CELPredicate     │  │ ACTION_     │  │ AgentRegistry   │
   │ Evaluator        │  │ REGISTRY    │  │ (resolve refs)  │
   └──────────────────┘  └─────────────┘  └─────────────────┘
              │                 │                 │
              └─────────────────┼─────────────────┘
                                ▼
                    ┌─────────────────────┐
                    │     AgentsFlow      │
                    │   (runnable flow)   │
                    └─────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentsFlow` | extends | Add `EndNode` as first-class type |
| `FlowNode` | uses | Nodes materialized from `NodeDefinition` |
| `FlowTransition` | uses | Edges materialized from `EdgeDefinition` |
| `Node` | uses | Actions attach via `add_pre_action()` / `add_post_action()` |
| `AgentRegistry` | depends on | Resolve `agent_ref` names to agent instances |
| `StartNode` / `EndNode` | uses | Virtual nodes for flow boundaries |

### Data Models

```python
# parrot/bots/flow/definition.py

from pydantic import BaseModel, Field, model_validator
from typing import Any, Dict, List, Literal, Optional, Union
from datetime import datetime


# --- Action Definitions ---

class LogActionDef(BaseModel):
    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str  # Supports {node_name}, {result}, {prompt} placeholders


class NotifyActionDef(BaseModel):
    type: Literal["notify"] = "notify"
    channel: Literal["slack", "teams", "email", "log"] = "log"
    message: str
    target: Optional[str] = None


class WebhookActionDef(BaseModel):
    type: Literal["webhook"] = "webhook"
    url: str
    method: Literal["POST", "PUT"] = "POST"
    headers: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[str] = None


class MetricActionDef(BaseModel):
    type: Literal["metric"] = "metric"
    name: str
    tags: Dict[str, str] = Field(default_factory=dict)
    value: float = 1.0


class SetContextActionDef(BaseModel):
    type: Literal["set_context"] = "set_context"
    key: str
    value_from: str  # dot-notation path into result


class ValidateActionDef(BaseModel):
    type: Literal["validate"] = "validate"
    schema_: Dict[str, Any] = Field(alias="schema")
    on_failure: Literal["raise", "skip", "fallback"] = "raise"
    fallback_value: Any = None


class TransformActionDef(BaseModel):
    type: Literal["transform"] = "transform"
    expression: str  # Safe sandbox expression


ActionDefinition = Union[
    LogActionDef, NotifyActionDef, WebhookActionDef,
    MetricActionDef, SetContextActionDef, ValidateActionDef, TransformActionDef
]


# --- Node & Edge Definitions ---

class NodePosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class NodeDefinition(BaseModel):
    id: str
    type: Literal["start", "end", "agent", "decision", "interactive_decision", "human"]
    label: Optional[str] = None
    agent_ref: Optional[str] = None
    instruction: Optional[str] = None
    max_retries: int = 3
    config: Dict[str, Any] = Field(default_factory=dict)
    pre_actions: List[ActionDefinition] = Field(default_factory=list)
    post_actions: List[ActionDefinition] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    position: NodePosition = Field(default_factory=NodePosition)


class EdgeDefinition(BaseModel):
    id: Optional[str] = None
    from_: str = Field(alias="from")
    to: Union[str, List[str]]
    condition: Literal["always", "on_success", "on_error", "on_timeout", "on_condition"] = "on_success"
    predicate: Optional[str] = None  # CEL expression string
    instruction: Optional[str] = None
    priority: int = 0
    label: Optional[str] = None

    model_config = {"populate_by_name": True}


# --- Flow Definition (root) ---

class FlowMetadata(BaseModel):
    max_parallel_tasks: int = 10
    default_max_retries: int = 3
    execution_timeout: Optional[float] = None
    truncation_length: Optional[int] = None
    enable_execution_memory: bool = True
    embedding_model: Optional[str] = None
    vector_dimension: int = 384
    vector_index_type: str = "Flat"


class FlowDefinition(BaseModel):
    flow: str
    version: str = "1.0"
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: FlowMetadata = Field(default_factory=FlowMetadata)
    nodes: List[NodeDefinition]
    edges: List[EdgeDefinition]
```

### New Public Interfaces

- `load_from_file` and `save_to_file` by default will use the `AGENTS_DIR/flows/` directory. This directory can be configured in the `parrot.conf` file.
- `load_from_redis` and `save_to_redis` will use the `REDIS_URL` configuration.

```python
# parrot/bots/flow/loader.py

class FlowLoader:
    """Load, save, and materialize FlowDefinition instances."""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FlowDefinition: ...

    @classmethod
    def from_json(cls, json_str: str) -> FlowDefinition: ...

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> FlowDefinition: ...

    @classmethod
    def save_to_file(
        cls,
        definition: FlowDefinition,
        path: Union[str, Path],
        *,
        indent: int = 2,
        update_timestamp: bool = True,
    ) -> None: ...

    @classmethod
    async def load_from_redis(
        cls,
        redis: aioredis.Redis,
        flow_name: str,
    ) -> FlowDefinition: ...

    @classmethod
    async def save_to_redis(
        cls,
        redis: aioredis.Redis,
        definition: FlowDefinition,
        *,
        ttl: Optional[int] = None,
        update_timestamp: bool = True,
    ) -> None: ...

    @classmethod
    async def list_flows_in_redis(cls, redis: aioredis.Redis) -> List[str]: ...

    @classmethod
    async def delete_from_redis(cls, redis: aioredis.Redis, flow_name: str) -> None: ...

    @classmethod
    def to_agents_flow(
        cls,
        definition: FlowDefinition,
        agent_registry: Optional[AgentRegistry] = None,
        extra_agents: Optional[Dict[str, Any]] = None,
    ) -> AgentsFlow: ...


# parrot/bots/flow/cel_evaluator.py

class CELPredicateEvaluator:
    """Evaluates CEL expression strings as flow transition predicates."""

    def __init__(self, expression: str): ...

    def __call__(
        self,
        result: Any,
        error: Optional[Exception] = None,
        **ctx: Any
    ) -> bool: ...


# parrot/bots/flow/svelteflow.py

def to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]: ...

def from_svelteflow(sf_data: Dict[str, Any], flow_name: str) -> FlowDefinition: ...
```

---

## 3. Module Breakdown

### Module 1: Definition Models
- **Path**: `parrot/bots/flow/definition.py`
- **Responsibility**: Pydantic models for `FlowDefinition`, `NodeDefinition`, `EdgeDefinition`, and all action types. Validates structure and relationships.
- **Depends on**: `pydantic`

### Module 2: Action Registry
- **Path**: `parrot/bots/flow/actions.py`
- **Responsibility**: `ACTION_REGISTRY` dict mapping type strings to action classes. Implements `BaseAction` ABC and all built-in actions (log, notify, webhook, metric, set_context, validate, transform).
- **Depends on**: Module 1 (action definitions)

### Module 3: CEL Evaluator
- **Path**: `parrot/bots/flow/cel_evaluator.py`
- **Responsibility**: Wrap `cel-python` to compile and evaluate CEL predicate strings. Coerce Python objects to CEL-compatible types. Provide clear error messages for invalid expressions.
- **Depends on**: `cel-python`

### Module 4: Flow Loader
- **Path**: `parrot/bots/flow/loader.py`
- **Responsibility**: File I/O, Redis I/O, and `to_agents_flow()` materialization. Resolves agent references, compiles CEL predicates, attaches actions to nodes.
- **Depends on**: Module 1, Module 2, Module 3, `AgentsFlow`, `AgentRegistry`

### Module 5: SvelteFlow Adapter
- **Path**: `parrot/bots/flow/svelteflow.py`
- **Responsibility**: Bidirectional conversion between `FlowDefinition` and SvelteFlow's node/edge format.
- **Depends on**: Module 1

### Module 6: EndNode Implementation
- **Path**: `parrot/bots/flow/nodes/__init__.py` (extend existing)
- **Responsibility**: Add `EndNode` as first-class node type alongside `StartNode`. Terminal node with no outgoing transitions.
- **Depends on**: `Node` base class

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_flow_definition_validation` | Module 1 | Validates node/edge structure, required fields |
| `test_node_agent_ref_required` | Module 1 | Agent nodes require `agent_ref` |
| `test_edge_predicate_required_on_condition` | Module 1 | `on_condition` edges require `predicate` |
| `test_action_registry_lookup` | Module 2 | All action types resolve correctly |
| `test_log_action_formatting` | Module 2 | Template variables expand correctly |
| `test_cel_simple_equality` | Module 3 | `result.decision == "pizza"` |
| `test_cel_boolean_logic` | Module 3 | `result.confidence > 0.8 && result.approved` |
| `test_cel_list_membership` | Module 3 | `result.category in ["A", "B"]` |
| `test_cel_invalid_expression` | Module 3 | Raises `ValueError` with message |
| `test_loader_from_file` | Module 4 | Loads valid JSON, returns `FlowDefinition` |
| `test_loader_save_to_file` | Module 4 | Serializes with timestamps |
| `test_loader_to_agents_flow` | Module 4 | Produces runnable `AgentsFlow` |
| `test_svelteflow_roundtrip` | Module 5 | `from_svelteflow(to_svelteflow(def))` equals original |

### Integration Tests
| Test | Description |
|---|---|
| `test_load_run_flow` | Load JSON → materialize → `run_flow()` → verify result |
| `test_redis_persistence_roundtrip` | Save to Redis → load from Redis → compare |
| `test_decision_node_cel_routing` | Decision node with CEL predicates routes correctly |
| `test_actions_execute_in_order` | Pre/post actions fire at correct lifecycle points |

### Test Data / Fixtures
```python
@pytest.fixture
def food_order_flow_json() -> str:
    """Complete food ordering flow as JSON string."""
    return Path("tests/fixtures/food_order_flow.json").read_text()

@pytest.fixture
def simple_flow_definition() -> FlowDefinition:
    """Minimal flow: start → agent → end."""
    return FlowDefinition(
        flow="SimpleFlow",
        nodes=[
            NodeDefinition(id="__start__", type="start"),
            NodeDefinition(id="worker", type="agent", agent_ref="echo_agent"),
            NodeDefinition(id="__end__", type="end"),
        ],
        edges=[
            EdgeDefinition(from_="__start__", to="worker", condition="always"),
            EdgeDefinition(from_="worker", to="__end__", condition="on_success"),
        ],
    )

@pytest.fixture
def mock_redis():
    """Async Redis mock for persistence tests."""
    return fakeredis.aioredis.FakeRedis()
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `FlowDefinition` validates all node types (start, end, agent, decision, interactive_decision, human)
- [ ] `FlowLoader.load_from_file()` loads valid JSON and raises clear errors on invalid
- [ ] `FlowLoader.save_to_file()` persists with `updated_at` timestamp
- [ ] `FlowLoader.load_from_redis()` / `save_to_redis()` work with async Redis client
- [ ] `FlowLoader.to_agents_flow()` produces a runnable flow that executes correctly
- [ ] CEL predicates evaluate: equality, comparisons, boolean logic, `in` operator
- [ ] Invalid CEL expressions raise `ValueError` at load time (not runtime)
- [ ] All 7 action types (log, notify, webhook, metric, set_context, validate, transform) work
- [ ] `to_svelteflow()` / `from_svelteflow()` roundtrip without data loss
- [ ] All unit tests pass (`pytest tests/test_flow_definition.py -v`)
- [ ] All integration tests pass (`pytest tests/test_flow_loader_integration.py -v`)
- [ ] No breaking changes to existing `AgentsFlow` Python API

---

## 6. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `AgentCrew` Redis key pattern: `parrot:flow:{flow_name}`
- Use `model_dump_json(by_alias=True)` for JSON serialization (handles `from_` → `from`)
- Action classes inherit from `BaseAction(ABC)` with `async def __call__()`
- CEL evaluator compiles once at load time; evaluation is fast at runtime

### Known Risks / Gotchas
- **CEL syntax differs from Python** — `in` operator and string escaping work differently. Mitigate with examples in docs and clear error messages.
- **Agent resolution order** — `extra_agents` takes priority over `agent_registry` to allow overrides. Document this clearly.
- **File path resolution** — `load_from_file()` with string path resolves relative to `AGENTS_DIR/flows/` (from `parrot.conf`).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `cel-python` | `>=0.4` | Safe CEL predicate evaluation |
| `pydantic` | `>=2.0` | Already in project |
| `aioredis` | `>=2.0` | Already in project |

---

## 7. Open Questions

> Questions that must be resolved before or during implementation.

- [ ] **EndNode first-class type** — Confirm `EndNode` should be explicit in FSM (like `StartNode`) rather than implicit (node with no edges). *Owner: Core team*: `EndNode` need to be a first-class citizen in the FSM exactly like `StartNode`.
- [ ] **Fan-in semantics** — Should edges support explicit fan-in (all sources must complete), or remain implicit via dependencies? *Owner: Core team*: fan-in need to be explicit in the FSM.
- [ ] **Action extensibility** — Should `ACTION_REGISTRY` allow runtime registration of custom actions from outside `parrot`? *Owner: Core team*: yes, allow runtime registration.
- [ ] **CEL context access** — Should predicates have access to full `ctx` (shared context), or only `result`? Current design allows `ctx` read-only. *Owner: Core team*: I think that the CEL evaluator should allow access to `ctx` (full shared context) in predicates, but only for reading. 

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-02-22 | Claude | Initial draft from brainstorm |
