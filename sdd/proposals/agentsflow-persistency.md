# AgentsFlow FlowDefinition — Technical Specification

**Project:** AI-Parrot  
**Component:** `parrot/bots/flow/`  
**Status:** Proposal  
**Version:** 1.0  

---

## 1. Motivation

AgentsFlow (`parrot/bots/flow/fsm.py`) allows building sophisticated DAG-based agent pipelines with FSM-controlled lifecycle management, conditional transitions, and pre/post lifecycle hooks. Currently, flows are defined exclusively in Python code, making them:

- Impossible to persist, version-control as data, or transfer between services.
- Difficult to share with non-developer stakeholders.
- Incompatible with visual builders (e.g. SvelteFlow UI).

This proposal defines `FlowDefinition`, a JSON-first serialization format and
companion loader/materializer for `AgentsFlow`, with parity to `AgentCrew`'s
Redis persistence model.

---

## 2. Scope

| Feature | Included |
|---|---|
| JSON schema for nodes + edges + actions | ✅ |
| Load from JSON file | ✅ |
| Load from / save to Redis | ✅ |
| Save to disk (JSON) | ✅ |
| Materialize as runnable `AgentsFlow` | ✅ |
| Predicate system (CEL-based) | ✅ |
| Action registry (fixed initial set) | ✅ |
| SvelteFlow-compatible node/edge shape | ✅ |

---

## 3. JSON Schema

### 3.1 Top-Level Structure

```json
{
  "flow": "FoodOrderFlow",
  "version": "1.0",
  "description": "Customer food ordering flow",
  "created_at": "2025-07-01T10:00:00Z",
  "updated_at": "2025-07-01T10:00:00Z",
  "metadata": {
    "max_parallel_tasks": 10,
    "default_max_retries": 3,
    "execution_timeout": 300,
    "truncation_length": null,
    "enable_execution_memory": true,
    "embedding_model": null,
    "vector_dimension": 384,
    "vector_index_type": "Flat"
  },
  "nodes": [ /* NodeDefinition[] */ ],
  "edges": [ /* EdgeDefinition[] */ ]
}
```

### 3.2 NodeDefinition

Every node has a required `node_id` (unique within the flow), a `type`, and
type-specific optional fields.

```json
{
  "node_id": "string (unique, used as agent name in the flow)",
  "type": "start | end | agent | decision | human | interactive_decision",
  "label": "optional human-readable label for UI",
  "agent_ref": "registered agent name (type=agent only)",
  "instruction": "optional prompt override for this node",
  "max_retries": 3,
  "config": { /* type-specific config object */ },
  "pre_actions": [ /* ActionDefinition[] */ ],
  "post_actions": [ /* ActionDefinition[] */ ],
  "metadata": { /* arbitrary key-value, forwarded to Node.metadata */ },
  "position": { "x": 100, "y": 200 }  /* SvelteFlow UI hint, ignored at runtime */
}
```

#### 3.2.1 Node Types

| `type` | Python class | Notes |
|---|---|---|
| `start` | `StartNode` | No `agent_ref`. Entry point. |
| `end` | Terminal `FlowNode` | No outgoing edges. Signals workflow completion. |
| `agent` | `FlowNode` wrapping `BasicAgent` | Requires `agent_ref`. |
| `decision` | `DecisionFlowNode` | Multi-agent voting/consensus. Requires `config.agents`. |
| `interactive_decision` | `InteractiveDecisionNode` | Human-in-the-loop choice. Requires `config.question` and `config.options`. |
| `human` | `HumanDecisionNode` | Full HITL escalation. Requires HITL manager. |

#### 3.2.2 Config Objects by Type

**`agent` node** — no config required; all settings at node level.

**`decision` node:**
```json
{
  "mode": "cio | ballot | consensus",
  "decision_type": "binary | approval | multi_choice | custom",
  "choices": ["option_a", "option_b"],
  "agents": ["agent_name_1", "agent_name_2"],
  "vote_weight": "equal | seniority | confidence | custom",
  "custom_weights": { "agent_name_1": 0.7, "agent_name_2": 0.3 },
  "quorum": 0.6
}
```

**`interactive_decision` node:**
```json
{
  "question": "What are you in the mood for?",
  "options": ["Pizza", "Sushi"],
  "timeout": 60
}
```

**`human` node:**
```json
{
  "hitl_manager_ref": "registered_hitl_manager_name",
  "interaction_type": "text | choice | approval",
  "target_humans": ["user_id_or_channel"],
  "timeout": 300
}
```

### 3.3 EdgeDefinition

An edge maps to a single `FlowTransition` call (`task_flow`, `on_success`,
`on_error`, `on_condition`).

```json
{
  "id": "optional unique edge id (for UI)",
  "from": "source_node_id",
  "to": "target_node_id | [target_node_id, target_node_id]",
  "condition": "always | on_success | on_error | on_timeout | on_condition",
  "predicate": "CEL expression string (required when condition=on_condition)",
  "instruction": "optional prompt override for the target node",
  "priority": 0,
  "label": "optional UI label"
}
```

`to` accepts either a single string or an array of strings for fan-out edges
(same source, multiple targets, same condition).

### 3.4 ActionDefinition

Actions are serialized descriptors resolved at load time against the `ACTION_REGISTRY`.

```json
{
  "type": "log | notify | webhook | metric | set_context | validate | transform",
  /* type-specific parameters follow */
}
```

---

## 4. Action Registry

### 4.1 Initial ACTION_REGISTRY

```python
# parrot/bots/flow/actions.py

ACTION_REGISTRY: Dict[str, Type[BaseAction]] = {
    "log":          LogAction,
    "notify":       NotifyAction,
    "webhook":      WebhookCallAction,
    "metric":       MetricAction,
    "set_context":  SetContextAction,
    "validate":     ValidateAction,
    "transform":    TransformAction,
}
```

### 4.2 Action Schemas

All actions inherit from `BaseAction`:

```python
class BaseAction(ABC):
    async def __call__(self, node_name: str, payload: Any, **ctx: Any) -> None:
        ...
```

#### `log`
```json
{
  "type": "log",
  "level": "info | debug | warning | error",
  "message": "Starting node {node_name}: {result}"
}
```
Template variables: `{node_name}`, `{result}`, `{prompt}`. Rendered via
`str.format_map()`.

#### `notify`
```json
{
  "type": "notify",
  "channel": "slack | teams | email | log",
  "message": "Node {node_name} completed",
  "target": "channel-name or address (optional, falls back to configured default)"
}
```

#### `webhook`
```json
{
  "type": "webhook",
  "url": "https://example.com/hook",
  "method": "POST | PUT",
  "headers": { "X-Token": "secret" },
  "body_template": "{ \"node\": \"{node_name}\", \"result\": \"{result}\" }"
}
```

#### `metric`
```json
{
  "type": "metric",
  "name": "flow.node.completed",
  "tags": { "flow": "{flow_name}", "node": "{node_name}" },
  "value": 1
}
```

#### `set_context`
```json
{
  "type": "set_context",
  "key": "last_decision",
  "value_from": "result.final_decision"
}
```
Extracts a value from the result using dot-notation and injects it into the
shared context for downstream nodes.

#### `validate`
```json
{
  "type": "validate",
  "schema": { "type": "object", "required": ["decision"] },
  "on_failure": "raise | skip | fallback",
  "fallback_value": null
}
```

#### `transform`
```json
{
  "type": "transform",
  "expression": "result.final_decision.lower()"
}
```
Evaluated in a safe sandbox. Updates `result` in the context.

---

## 5. Predicate System (CEL)

### 5.1 Why CEL

Lambda predicates cannot be serialized. Options considered:

| Option | Pro | Con |
|---|---|---|
| `eval()` raw Python | Trivial | Security risk, arbitrary code execution |
| JSONPath / JMESPath | Familiar, safe | Only path extraction, no logic |
| **CEL (Common Expression Language)** | **Safe, typed, fast, standard** | **Requires `cel-python` dependency** |
| Custom mini-language | Full control | Maintenance burden |

CEL is Google's expression language used in Firebase, Kubernetes admission
webhooks, and OPA. The `cel-python` library provides a pure-Python
interpreter with no external runtime.

```bash
pip install cel-python
```

Need to add `cel-python` to `pyproject.toml`.

### 5.2 CEL Execution Context

When a predicate is evaluated, the following variables are available:

| Variable | Type | Description |
|---|---|---|
| `result` | `map` or `string` | Output of the source node |
| `result.final_decision` | `string` | For `DecisionResult` outputs |
| `result.confidence` | `double` | Confidence score (0.0–1.0) |
| `ctx` | `map` | Shared flow context dict |
| `error` | `string` or `null` | Exception message if node failed |

### 5.3 CEL Predicate Examples

The Python lambda predicates translate directly to CEL:

| Python lambda | CEL string |
|---|---|
| `lambda r: r.final_decision == "pizza"` | `result.final_decision == "pizza"` |
| `lambda r: r.confidence > 0.8` | `result.confidence > 0.8` |
| `lambda r: "error" not in r` | `!("error" in result)` |
| `lambda r: r.final_decision in ["pizza", "calzone"]` | `result.final_decision in ["pizza", "calzone"]` |
| `lambda r: ctx.get("retries", 0) < 3` | `ctx.retries < 3` |

### 5.4 CEL Evaluator Helper

```python
# parrot/bots/flow/cel_evaluator.py

import cel
from typing import Any, Dict

class CELPredicateEvaluator:
    """Evaluates CEL expression strings as flow transition predicates."""

    def __init__(self, expression: str):
        self.expression = expression
        self._env = cel.Environment()
        self._prog = self._env.compile(expression)

    def __call__(self, result: Any, error: Exception | None = None, **ctx: Any) -> bool:
        activation = {
            "result": self._coerce(result),
            "error": str(error) if error else "",
            "ctx": ctx,
        }
        return bool(self._env.evaluate(self._prog, activation))

    @staticmethod
    def _coerce(value: Any) -> Any:
        """Coerce Python objects to CEL-compatible types."""
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, str):
            return value
        return value
```

### 5.5 Edge with CEL Predicate (Full Example)

**Python (current):**
```python
crew.task_flow(
    source=decision_node,
    targets=pizza_agent,
    condition=TransitionCondition.ON_CONDITION,
    predicate=lambda result: result.final_decision == "pizza",
    instruction="Provide a pizza recipe."
)
```

**JSON equivalent:**
```json
{
  "from": "food_decision",
  "to": "pizza_agent",
  "condition": "on_condition",
  "predicate": "result.final_decision == \"pizza\"",
  "instruction": "Provide a pizza recipe."
}
```

---

## 6. Complete JSON Example — Food Order Flow

```json
{
  "flow": "FoodOrderFlow",
  "version": "1.0",
  "description": "Interactive food ordering with pizza or sushi routing.",
  "metadata": {
    "max_parallel_tasks": 5,
    "default_max_retries": 2,
    "execution_timeout": 120
  },
  "nodes": [
    {
      "id": "__start__",
      "type": "start",
      "label": "Start",
      "position": { "x": 0, "y": 200 }
    },
    {
      "id": "food_decision",
      "type": "interactive_decision",
      "label": "What do you want?",
      "config": {
        "question": "What are you in the mood for?",
        "options": ["Pizza", "Sushi"],
        "timeout": 60
      },
      "pre_actions": [
        { "type": "log", "level": "info", "message": "User starting food selection" }
      ],
      "post_actions": [
        { "type": "log", "level": "info", "message": "User chose: {result}" }
      ],
      "position": { "x": 250, "y": 200 }
    },
    {
      "id": "pizza_agent",
      "type": "agent",
      "label": "Pizza Specialist",
      "agent_ref": "pizza_specialist_agent",
      "max_retries": 2,
      "pre_actions": [
        { "type": "log", "level": "debug", "message": "Entering pizza flow" }
      ],
      "post_actions": [],
      "position": { "x": 500, "y": 100 }
    },
    {
      "id": "sushi_agent",
      "type": "agent",
      "label": "Sushi Specialist",
      "agent_ref": "sushi_specialist_agent",
      "max_retries": 2,
      "pre_actions": [
        { "type": "log", "level": "debug", "message": "Entering sushi flow" }
      ],
      "post_actions": [],
      "position": { "x": 500, "y": 300 }
    },
    {
      "id": "order_node",
      "type": "agent",
      "label": "Order Processor",
      "agent_ref": "order_agent",
      "max_retries": 3,
      "pre_actions": [
        {
          "type": "notify",
          "channel": "teams",
          "message": "New order incoming from flow {node_name}"
        }
      ],
      "post_actions": [
        {
          "type": "webhook",
          "url": "https://orders.internal/created",
          "method": "POST"
        }
      ],
      "position": { "x": 750, "y": 200 }
    },
    {
      "id": "__end__",
      "type": "end",
      "label": "End",
      "position": { "x": 1000, "y": 200 }
    }
  ],
  "edges": [
    {
      "from": "__start__",
      "to": "food_decision",
      "condition": "always"
    },
    {
      "from": "food_decision",
      "to": "pizza_agent",
      "condition": "on_condition",
      "predicate": "result.final_decision == \"pizza\"",
      "instruction": "Provide a pizza recipe."
    },
    {
      "from": "food_decision",
      "to": "sushi_agent",
      "condition": "on_condition",
      "predicate": "result.final_decision == \"sushi\"",
      "instruction": "Tell me a sushi curiosity."
    },
    {
      "from": "pizza_agent",
      "to": "order_node",
      "condition": "on_success"
    },
    {
      "from": "sushi_agent",
      "to": "order_node",
      "condition": "on_success"
    },
    {
      "from": "order_node",
      "to": "__end__",
      "condition": "on_success"
    }
  ]
}
```

---

## 7. Pydantic Models (FlowDefinition)

```python
# parrot/bots/flow/definition.py

from __future__ import annotations
from typing import Any, Dict, List, Literal, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Action Models
# ---------------------------------------------------------------------------

class LogActionDef(BaseModel):
    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str


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
    expression: str


ActionDefinition = Union[
    LogActionDef,
    NotifyActionDef,
    WebhookActionDef,
    MetricActionDef,
    SetContextActionDef,
    ValidateActionDef,
    TransformActionDef,
]


# ---------------------------------------------------------------------------
# Node Models
# ---------------------------------------------------------------------------

class NodePosition(BaseModel):
    x: float = 0.0
    y: float = 0.0


class NodeDefinition(BaseModel):
    id: str
    type: Literal["start", "end", "agent", "decision", "interactive_decision", "human"]
    label: Optional[str] = None
    agent_ref: Optional[str] = None          # For type=agent
    instruction: Optional[str] = None
    max_retries: int = 3
    config: Dict[str, Any] = Field(default_factory=dict)
    pre_actions: List[ActionDefinition] = Field(default_factory=list)
    post_actions: List[ActionDefinition] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    position: NodePosition = Field(default_factory=NodePosition)

    @model_validator(mode="after")
    def validate_agent_ref(self) -> "NodeDefinition":
        if self.type == "agent" and not self.agent_ref:
            raise ValueError(f"Node '{self.id}' of type 'agent' requires 'agent_ref'.")
        return self


# ---------------------------------------------------------------------------
# Edge Models
# ---------------------------------------------------------------------------

class EdgeDefinition(BaseModel):
    id: Optional[str] = None
    from_: str = Field(alias="from")
    to: Union[str, List[str]]
    condition: Literal[
        "always", "on_success", "on_error", "on_timeout", "on_condition"
    ] = "on_success"
    predicate: Optional[str] = None          # CEL expression string
    instruction: Optional[str] = None
    priority: int = 0
    label: Optional[str] = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_predicate(self) -> "EdgeDefinition":
        if self.condition == "on_condition" and not self.predicate:
            raise ValueError(
                f"Edge from '{self.from_}' requires 'predicate' when condition=on_condition."
            )
        return self


# ---------------------------------------------------------------------------
# Flow Metadata
# ---------------------------------------------------------------------------

class FlowMetadata(BaseModel):
    max_parallel_tasks: int = 10
    default_max_retries: int = 3
    execution_timeout: Optional[float] = None
    truncation_length: Optional[int] = None
    enable_execution_memory: bool = True
    embedding_model: Optional[str] = None
    vector_dimension: int = 384
    vector_index_type: str = "Flat"


# ---------------------------------------------------------------------------
# FlowDefinition (root model)
# ---------------------------------------------------------------------------

class FlowDefinition(BaseModel):
    flow: str
    version: str = "1.0"
    description: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: FlowMetadata = Field(default_factory=FlowMetadata)
    nodes: List[NodeDefinition]
    edges: List[EdgeDefinition]

    @model_validator(mode="after")
    def validate_node_ids(self) -> "FlowDefinition":
        ids = {n.id for n in self.nodes}
        for edge in self.edges:
            targets = [edge.to] if isinstance(edge.to, str) else edge.to
            missing = {t for t in [edge.from_] + targets if t not in ids}
            if missing:
                raise ValueError(f"Edge references unknown node IDs: {missing}")
        return self
```

---

## 8. FlowLoader — Load, Save, Materialize

```python
# parrot/bots/flow/loader.py

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .definition import FlowDefinition, ActionDefinition
from .fsm import AgentsFlow, TransitionCondition
from .cel_evaluator import CELPredicateEvaluator
from .actions import ACTION_REGISTRY
from ..agent import BasicAgent
from ...agents.registry import AgentRegistry  # existing registry


REDIS_KEY_PREFIX = "parrot:flow:"


class FlowLoader:
    """
    Load, save, and materialize FlowDefinition instances.

    Mirrors the AgentCrew persistence model:
      - disk  : load_from_file / save_to_file
      - Redis : load_from_redis / save_to_redis
      - build : to_agents_flow
    """

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlowDefinition":
        return FlowDefinition.model_validate(data)

    @classmethod
    def from_json(cls, json_str: str) -> "FlowDefinition":
        return cls.from_dict(json.loads(json_str))

    # ------------------------------------------------------------------
    # Disk I/O
    # ------------------------------------------------------------------

    @classmethod
    def load_from_file(cls, path: Union[str, Path]) -> "FlowDefinition":
        """Load a FlowDefinition from a JSON file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Flow file not found: {path}")
        raw = path.read_text(encoding="utf-8")
        return cls.from_json(raw)

    @classmethod
    def save_to_file(
        cls,
        definition: "FlowDefinition",
        path: Union[str, Path],
        *,
        indent: int = 2,
        update_timestamp: bool = True,
    ) -> None:
        """Persist a FlowDefinition to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if update_timestamp:
            definition = definition.model_copy(
                update={"updated_at": datetime.now(timezone.utc)}
            )
        path.write_text(
            definition.model_dump_json(indent=indent, by_alias=True),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Redis I/O
    # ------------------------------------------------------------------

    @classmethod
    async def load_from_redis(
        cls,
        redis,          # aioredis.Redis or compatible async client
        flow_name: str,
    ) -> "FlowDefinition":
        """Load a FlowDefinition from Redis by flow name."""
        key = f"{REDIS_KEY_PREFIX}{flow_name}"
        raw = await redis.get(key)
        if raw is None:
            raise KeyError(f"Flow '{flow_name}' not found in Redis (key={key})")
        return cls.from_json(raw if isinstance(raw, str) else raw.decode())

    @classmethod
    async def save_to_redis(
        cls,
        redis,
        definition: "FlowDefinition",
        *,
        ttl: Optional[int] = None,
        update_timestamp: bool = True,
    ) -> None:
        """Persist a FlowDefinition to Redis.

        Args:
            redis: Async Redis client.
            definition: The flow to persist.
            ttl: Optional TTL in seconds. None = no expiry.
            update_timestamp: Update updated_at before saving.
        """
        if update_timestamp:
            definition = definition.model_copy(
                update={"updated_at": datetime.now(timezone.utc)}
            )
        key = f"{REDIS_KEY_PREFIX}{definition.flow}"
        payload = definition.model_dump_json(by_alias=True)
        if ttl:
            await redis.setex(key, ttl, payload)
        else:
            await redis.set(key, payload)

    @classmethod
    async def list_flows_in_redis(cls, redis) -> list[str]:
        """Return all flow names stored in Redis."""
        pattern = f"{REDIS_KEY_PREFIX}*"
        keys = await redis.keys(pattern)
        prefix_len = len(REDIS_KEY_PREFIX)
        return [k.decode()[prefix_len:] if isinstance(k, bytes) else k[prefix_len:] for k in keys]

    @classmethod
    async def delete_from_redis(cls, redis, flow_name: str) -> None:
        """Delete a persisted flow from Redis."""
        await redis.delete(f"{REDIS_KEY_PREFIX}{flow_name}")

    # ------------------------------------------------------------------
    # Materialization
    # ------------------------------------------------------------------

    @classmethod
    def to_agents_flow(
        cls,
        definition: "FlowDefinition",
        agent_registry: Optional[AgentRegistry] = None,
        extra_agents: Optional[Dict[str, Any]] = None,
    ) -> AgentsFlow:
        """
        Materialize a FlowDefinition into a runnable AgentsFlow.

        Args:
            definition: Parsed flow definition.
            agent_registry: Global AgentRegistry to resolve agent_ref names.
            extra_agents: Dict of name -> agent instance for agents not in registry.

        Returns:
            A fully configured AgentsFlow ready to call run_flow().
        """
        meta = definition.metadata

        # Build the AgentsFlow instance
        flow = AgentsFlow(
            name=definition.flow,
            max_parallel_tasks=meta.max_parallel_tasks,
            default_max_retries=meta.default_max_retries,
            execution_timeout=meta.execution_timeout,
            truncation_length=meta.truncation_length,
            enable_execution_memory=meta.enable_execution_memory,
            embedding_model=meta.embedding_model,
            vector_dimension=meta.vector_dimension,
            vector_index_type=meta.vector_index_type,
        )

        node_map: Dict[str, Any] = {}   # id -> FlowNode / agent

        # --- 1. Build nodes ---
        for node_def in definition.nodes:
            flow_node = cls._build_node(
                node_def,
                flow,
                agent_registry=agent_registry,
                extra_agents=extra_agents or {},
            )
            node_map[node_def.id] = flow_node

        # --- 2. Wire edges ---
        for edge_def in definition.edges:
            targets_raw = edge_def.to if isinstance(edge_def.to, list) else [edge_def.to]
            targets = [node_map[t] for t in targets_raw]

            condition = TransitionCondition(edge_def.condition)
            predicate = None

            if condition == TransitionCondition.ON_CONDITION:
                predicate = CELPredicateEvaluator(edge_def.predicate)

            flow.task_flow(
                source=node_map[edge_def.from_],
                targets=targets if len(targets) > 1 else targets[0],
                condition=condition,
                predicate=predicate,
                instruction=edge_def.instruction,
                priority=edge_def.priority,
            )

        return flow

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @classmethod
    def _build_node(
        cls,
        node_def,
        flow: AgentsFlow,
        agent_registry,
        extra_agents: Dict[str, Any],
    ):
        """Resolve and register a single node into the flow."""

        if node_def.type == "start":
            fn = flow.add_start_node(name=node_def.id, metadata=node_def.metadata)
            cls._attach_actions(fn, node_def)
            return fn

        if node_def.type == "end":
            # End nodes are regular agents with no outgoing transitions.
            # We register a pass-through agent or a dummy if none provided.
            agent = cls._resolve_agent(node_def, agent_registry, extra_agents)
            if agent is None:
                from .nodes.passthrough import PassthroughAgent
                agent = PassthroughAgent(name=node_def.id)
            fn = flow.add_agent(agent, agent_id=node_def.id,
                                max_retries=node_def.max_retries)
            cls._attach_actions(fn, node_def)
            return fn

        if node_def.type == "agent":
            agent = cls._resolve_agent(node_def, agent_registry, extra_agents)
            fn = flow.add_agent(agent, agent_id=node_def.id,
                                max_retries=node_def.max_retries)
            if node_def.instruction:
                fn.instruction = node_def.instruction
            cls._attach_actions(fn, node_def)
            return fn

        if node_def.type == "interactive_decision":
            from .interactive_node import InteractiveDecisionNode
            cfg = node_def.config
            node = InteractiveDecisionNode(
                name=node_def.id,
                question=cfg.get("question", ""),
                options=cfg.get("options", []),
                timeout=cfg.get("timeout", 60),
            )
            fn = flow.add_agent(node, agent_id=node_def.id)
            cls._attach_actions(fn, node_def)
            return fn

        if node_def.type == "decision":
            from .decision_node import DecisionFlowNode, DecisionConfig, DecisionMode, DecisionType
            cfg = node_def.config
            agents = {
                name: cls._resolve_agent_by_name(name, agent_registry, extra_agents)
                for name in cfg.get("agents", [])
            }
            node = DecisionFlowNode(
                name=node_def.id,
                agents=agents,
                config=DecisionConfig(
                    mode=DecisionMode(cfg.get("mode", "cio")),
                    decision_type=DecisionType(cfg.get("decision_type", "binary")),
                ),
            )
            fn = flow.add_agent(node, agent_id=node_def.id)
            cls._attach_actions(fn, node_def)
            return fn

        raise ValueError(f"Unknown node type: '{node_def.type}' on node '{node_def.id}'")

    @staticmethod
    def _resolve_agent(node_def, agent_registry, extra_agents):
        name = node_def.agent_ref
        if name in extra_agents:
            return extra_agents[name]
        if agent_registry and (agent := agent_registry.get(name)):
            return agent
        raise LookupError(
            f"Agent '{name}' not found in registry or extra_agents "
            f"(required by node '{node_def.id}')."
        )

    @staticmethod
    def _resolve_agent_by_name(name, agent_registry, extra_agents):
        if name in extra_agents:
            return extra_agents[name]
        if agent_registry and (agent := agent_registry.get(name)):
            return agent
        raise LookupError(f"Agent '{name}' not found.")

    @classmethod
    def _attach_actions(cls, flow_node, node_def) -> None:
        """Materialize and attach pre/post actions to a FlowNode."""
        for action_def in node_def.pre_actions:
            action = cls._build_action(action_def)
            flow_node.add_pre_action(action)
        for action_def in node_def.post_actions:
            action = cls._build_action(action_def)
            flow_node.add_post_action(action)

    @staticmethod
    def _build_action(action_def: ActionDefinition):
        action_type = action_def.type
        action_cls = ACTION_REGISTRY.get(action_type)
        if action_cls is None:
            raise ValueError(f"Unknown action type '{action_type}'. "
                             f"Registered: {list(ACTION_REGISTRY)}")
        return action_cls(action_def)
```

---

## 9. SvelteFlow UI Compatibility

The JSON schema is designed to map 1:1 to SvelteFlow's node/edge format:

| FlowDefinition field | SvelteFlow field |
|---|---|
| `node.id` | `node.id` |
| `node.label` | `node.data.label` |
| `node.type` | `node.type` (custom node component) |
| `node.position.x/y` | `node.position.x/y` |
| `edge.from` | `edge.source` |
| `edge.to` | `edge.target` |
| `edge.condition` | `edge.data.condition` |
| `edge.label` | `edge.label` |

A thin adapter converts between the two formats:

```python
def to_svelteflow(definition: FlowDefinition) -> Dict[str, Any]:
    nodes = [
        {
            "id": n.id,
            "type": n.type,
            "position": {"x": n.position.x, "y": n.position.y},
            "data": {
                "label": n.label or n.id,
                "agent_ref": n.agent_ref,
                "instruction": n.instruction,
                "config": n.config,
                "pre_actions": [a.model_dump() for a in n.pre_actions],
                "post_actions": [a.model_dump() for a in n.post_actions],
            },
        }
        for n in definition.nodes
    ]
    edges = [
        {
            "id": e.id or f"{e.from_}->{e.to}",
            "source": e.from_,
            "target": e.to if isinstance(e.to, str) else e.to[0],
            "label": e.label or e.condition,
            "data": {
                "condition": e.condition,
                "predicate": e.predicate,
                "instruction": e.instruction,
                "priority": e.priority,
            },
        }
        for e in definition.edges
    ]
    return {"nodes": nodes, "edges": edges}


def from_svelteflow(sf_data: Dict[str, Any], flow_name: str) -> FlowDefinition:
    nodes = [
        {
            "id": n["id"],
            "type": n["type"],
            "label": n["data"].get("label"),
            "agent_ref": n["data"].get("agent_ref"),
            "instruction": n["data"].get("instruction"),
            "config": n["data"].get("config", {}),
            "pre_actions": n["data"].get("pre_actions", []),
            "post_actions": n["data"].get("post_actions", []),
            "position": n.get("position", {"x": 0, "y": 0}),
        }
        for n in sf_data["nodes"]
    ]
    edges = [
        {
            "from": e["source"],
            "to": e["target"],
            "id": e.get("id"),
            "label": e.get("label"),
            "condition": e.get("data", {}).get("condition", "on_success"),
            "predicate": e.get("data", {}).get("predicate"),
            "instruction": e.get("data", {}).get("instruction"),
            "priority": e.get("data", {}).get("priority", 0),
        }
        for e in sf_data["edges"]
    ]
    return FlowDefinition.model_validate({
        "flow": flow_name,
        "nodes": nodes,
        "edges": edges,
    })
```

---

## 10. Usage Examples

### 10.1 Load from File and Run

- `load_from_file` can accept a PosixPath directory or an string, if is an string, then will be loaded from AGENTS_DIR.joinpath('flows'), where `AGENTS_DIR` is defined in `parrot.conf`.

```python
from parrot.bots.flow.loader import FlowLoader

definition = FlowLoader.load_from_file("flows/food_order.json")

flow = FlowLoader.to_agents_flow(
    definition,
    extra_agents={
        "pizza_specialist_agent": pizza_agent,
        "sushi_specialist_agent": sushi_agent,
        "order_agent": order_agent,
    }
)

result = await flow.run_flow("I want to order some food")
```

### 10.2 Save to Redis and Reload

- from `parrot.conf` we can import the REDIS_URL.

```python
import aioredis
from parrot.conf import REDIS_URL

redis = await aioredis.from_url(REDIS_URL)

# Save
await FlowLoader.save_to_redis(redis, definition)

# Later, in another process or service:
definition = await FlowLoader.load_from_redis(redis, "FoodOrderFlow")
flow = FlowLoader.to_agents_flow(definition, extra_agents=agents)
```

### 10.3 Build Programmatically and Export

```python
# Build the definition in Python (e.g. from UI input)
definition = FlowDefinition(
    flow="MyFlow",
    nodes=[...],
    edges=[...],
)

# Export to disk
FlowLoader.save_to_file(definition, "flows/my_flow.json")

# Export to Redis
await FlowLoader.save_to_redis(redis, definition)
```

---

## 11. File Layout

```
parrot/bots/flow/
├── definition.py          # Pydantic models: FlowDefinition, NodeDef, EdgeDef, ActionDef
├── loader.py              # FlowLoader: from_file, from_redis, save_*, to_agents_flow
├── cel_evaluator.py       # CELPredicateEvaluator
├── actions.py             # ACTION_REGISTRY + BaseAction + all ActionImpl classes
├── svelteflow.py          # to_svelteflow / from_svelteflow adapters
├── fsm.py                 # AgentsFlow (existing, unchanged)
├── node.py                # Node base class (existing, unchanged)
├── decision_node.py       # DecisionFlowNode (existing, unchanged)
├── interactive_node.py    # InteractiveDecisionNode (existing, unchanged)
└── nodes/
    └── passthrough.py     # PassthroughAgent (new, for end nodes)
```

---

## 12. Dependencies

| Package | Purpose | Already in project |
|---|---|---|
| `pydantic` | Schema models | ✅ |
| `aioredis` | Redis I/O | ✅ |
| `cel-python` | CEL predicate evaluation | ❌ Add to `pyproject.toml` |

```toml
# pyproject.toml
[project.dependencies]
cel-python = ">=0.4"
```

---

## 13. Implementation Phases

| Phase | Deliverable | Effort |
|---|---|---|
| 1 | `definition.py` — Pydantic models + validation | Small |
| 2 | `actions.py` — ACTION_REGISTRY + 7 action implementations | Medium |
| 3 | `cel_evaluator.py` — CEL predicate wrapper | Small |
| 4 | `loader.py` — file/Redis I/O + `to_agents_flow` | Medium |
| 5 | `svelteflow.py` — UI adapters | Small |
| 6 | Tests — unit + integration | Medium |
| 7 | SvelteFlow UI builder (separate repo/package) | Large |

---

## 14. Open Questions

1. **`end` node agent:** Should `EndNode` be a first-class type in `fsm.py` (like `StartNode`), or remain a convention (node with no outgoing edges)? A dedicated `EndNode` class makes the JSON explicit and the UI cleaner: `EndNode` need to be a first-class type like `StartNode` will be always the last node in the flow (with no outgoing edges).

2. **CEL sandbox depth:** Should the CEL evaluator allow access to `ctx` (full shared context) in predicates, or restrict to `result` only? Full `ctx` access is more powerful but harder to document and test. I think that the CEL evaluator should allow access to `ctx` (full shared context) in predicates, but only for reading.

3. **Fan-in edges:** Currently `to` can be an array for fan-out (one source, many targets). Should fan-in be explicit in the schema (many sources, one target, requires all to complete), or remain implicit via shared dependencies as in the current `AgentsFlow`? I think that fan-in should be explicit in the schema (many sources, one target, requires all to complete).

4. **Action extensibility:** Should `ACTION_REGISTRY` be pluggable at runtime (register custom actions from outside `parrot`), or remain a fixed internal set for v1? I think that `ACTION_REGISTRY` should be pluggable at runtime (register custom actions from outside `parrot`).

5. **Versioning:** When a `FlowDefinition` with `version: "1.0"` is loaded and the schema has evolved to `2.0`, what migration strategy applies? Suggest a `FlowMigrator` pattern similar to database migrations. I think that `FlowDefinition` should have a `version` field but we don't need to implement `FlowMigrator` for now.