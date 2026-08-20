"""
FlowDefinition — Pydantic models for AgentsFlow JSON serialization.

This module defines the complete schema for persisting and loading AgentsFlow
workflows as JSON. The schema supports:
- Node definitions, typed by any key registered in ``NODE_REGISTRY``
- Edge definitions with conditional transitions
- Pre/post lifecycle actions
- SvelteFlow-compatible position data

Every model here is closed (``extra="forbid"``). A definition is frequently
machine-generated, and a silently-ignored unknown key is the difference
between "this flow does what it says" and "this flow quietly dropped a step".

Example:
    >>> from parrot.bots.flows.flow.definition import FlowDefinition
    >>> definition = FlowDefinition.model_validate(json_data)
    >>> json_str = definition.model_dump_json(by_alias=True)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Annotated


# ---------------------------------------------------------------------------
# Action Definition Models
# ---------------------------------------------------------------------------

class LogActionDef(BaseModel):
    """Log a message with template variables.

    Template variables: {node_name}, {result}, {prompt}
    """
    model_config = ConfigDict(extra="forbid")

    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str = Field(..., description="Message template with {node_name}, {result}, {prompt}")


class NotifyActionDef(BaseModel):
    """Send a notification to a channel."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["notify"] = "notify"
    channel: Literal["slack", "teams", "email", "log"] = "log"
    message: str = Field(..., description="Notification message")
    target: Optional[str] = Field(
        default=None,
        description="Target channel/address (optional, falls back to configured default)"
    )


class WebhookActionDef(BaseModel):
    """Make an HTTP webhook call."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["webhook"] = "webhook"
    url: str = Field(..., description="Webhook URL")
    method: Literal["POST", "PUT"] = "POST"
    headers: Dict[str, str] = Field(default_factory=dict)
    body_template: Optional[str] = Field(
        default=None,
        description="JSON body template with {node_name}, {result} placeholders"
    )


class MetricActionDef(BaseModel):
    """Emit a metric."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["metric"] = "metric"
    name: str = Field(..., description="Metric name (e.g., 'flow.node.completed')")
    tags: Dict[str, str] = Field(default_factory=dict)
    value: float = 1.0


class SetContextActionDef(BaseModel):
    """Extract a value from result and set in shared context."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["set_context"] = "set_context"
    key: str = Field(..., description="Context key to set")
    value_from: str = Field(
        ...,
        description="Dot-notation path into result (e.g., 'result.final_decision')"
    )


class ValidateActionDef(BaseModel):
    """Validate result against a JSON schema."""
    type: Literal["validate"] = "validate"
    schema_: Dict[str, Any] = Field(
        ...,
        alias="schema",
        description="JSON Schema to validate against"
    )
    on_failure: Literal["raise", "skip", "fallback"] = "raise"
    fallback_value: Any = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TransformActionDef(BaseModel):
    """Transform result using a safe expression."""
    model_config = ConfigDict(extra="forbid")

    type: Literal["transform"] = "transform"
    expression: str = Field(
        ...,
        description="Safe expression to transform result (e.g., 'result.lower()')"
    )


# Discriminated union of all action types.
#
# The ``discriminator`` is what makes this a *tagged* union: without it
# Pydantic resolves members by smart-union left-to-right, and
# ``model_json_schema()`` emits an ``anyOf`` that tells a generating model
# nothing about which fields belong to which action. With it, the schema is a
# ``oneOf`` keyed on ``type``, and a wrong field is reported against the
# intended action instead of "no member matched".
ActionDefinition = Annotated[
    Union[
        LogActionDef,
        NotifyActionDef,
        WebhookActionDef,
        MetricActionDef,
        SetContextActionDef,
        ValidateActionDef,
        TransformActionDef,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Node Definition Models
# ---------------------------------------------------------------------------

class NodePosition(BaseModel):
    """UI position hint for visual flow builders (SvelteFlow compatible)."""

    model_config = ConfigDict(extra="forbid")

    x: float = 0.0
    y: float = 0.0


class NodeDefinition(BaseModel):
    """Definition of a node in the flow.

    The set of valid ``type`` values is exactly the ``NODE_REGISTRY`` keys —
    see :func:`parrot.bots.flows.flow.flow.register_node`. Do not maintain a
    second list here: the registry is populated by import side effects
    (``dev_loop.*``, ``"tool"``), so any hand-written enumeration drifts.

    Membership is deliberately *not* checked at parse time. Because
    registration is an import side effect, a definition is routinely loaded
    (from disk, Redis or an API payload) before the modules that register its
    types have been imported, and rejecting it then would be wrong. The check
    belongs where the types must actually exist: ``AgentsFlow.from_definition``
    at build time, and — for machine-generated documents — the authoring
    validator, which builds its type enum from the live registry.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Unique node identifier")
    type: str = Field(
        ...,
        description=(
            "Node type. Must be a key registered in ``NODE_REGISTRY`` via "
            "``@register_node`` — core types are 'start', 'end', 'agent', "
            "'decision', 'interactive_decision' and 'synthesis'; packages "
            "register more (e.g. 'tool', 'dev_loop.development'). Membership "
            "is enforced by ``AgentsFlow.from_definition`` at build time."
        ),
    )
    label: Optional[str] = Field(
        default=None,
        description="Human-readable label for UI"
    )
    agent_ref: Optional[str] = Field(
        default=None,
        description="Registered agent name (required for type='agent')"
    )
    instruction: Optional[str] = Field(
        default=None,
        description="Optional prompt override for this node"
    )
    max_retries: int = Field(
        default=0,
        ge=0,
        description=(
            "How many times a failed node is re-executed. Defaults to 0 — no "
            "retries. The field predates the machinery that reads it: until "
            "``Node.max_retries`` existed, nothing consumed this value and "
            "every definition-driven node ran exactly once regardless of what "
            "it said. Defaulting to 3 now that it IS read would hand three "
            "silent re-executions (extra LLM spend, repeated tool side "
            "effects) to every already-stored flow that never asked for them. "
            "Retries are opt-in: set it explicitly."
        ),
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific configuration (e.g., decision mode, question/options)"
    )
    pre_actions: List[ActionDefinition] = Field(
        default_factory=list,
        description="Actions to run before node execution"
    )
    post_actions: List[ActionDefinition] = Field(
        default_factory=list,
        description="Actions to run after node execution"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata forwarded to Node.metadata"
    )
    position: NodePosition = Field(
        default_factory=NodePosition,
        description="UI position hint (ignored at runtime)"
    )

    @model_validator(mode="after")
    def validate_agent_ref(self) -> "NodeDefinition":
        """Agent nodes require agent_ref."""
        if self.type == "agent" and not self.agent_ref:
            raise ValueError(
                f"Node '{self.id}' of type 'agent' requires 'agent_ref'."
            )
        return self


# ---------------------------------------------------------------------------
# Edge Definition Models
# ---------------------------------------------------------------------------

class EdgeDefinition(BaseModel):
    """Definition of an edge (transition) between nodes.

    Conditions:
    - always: Unconditional transition
    - on_success: Only if source completed successfully
    - on_error: Only if source failed
    - on_timeout: Only if source timed out
    - on_condition: Custom CEL predicate
    """
    id: Optional[str] = Field(
        default=None,
        description="Optional unique edge ID (for UI)"
    )
    from_: str = Field(
        ...,
        alias="from",
        description="Source node ID"
    )
    to: Union[str, List[str]] = Field(
        ...,
        description="Target node ID(s) - single string or array for fan-out"
    )
    condition: Literal[
        "always", "on_success", "on_error", "on_timeout", "on_condition"
    ] = "on_success"
    predicate: Optional[str] = Field(
        default=None,
        description="CEL expression string (required when condition='on_condition')"
    )
    instruction: Optional[str] = Field(
        default=None,
        description="Optional prompt override for target node(s)"
    )
    priority: int = Field(
        default=0,
        description="Higher priority transitions evaluated first"
    )
    label: Optional[str] = Field(
        default=None,
        description="Optional UI label"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def validate_predicate(self) -> "EdgeDefinition":
        """on_condition edges require predicate."""
        if self.condition == "on_condition" and not self.predicate:
            raise ValueError(
                f"Edge from '{self.from_}' requires 'predicate' when condition='on_condition'."
            )
        return self


# ---------------------------------------------------------------------------
# Flow Metadata
# ---------------------------------------------------------------------------

class FlowMetadata(BaseModel):
    """Flow-level configuration and defaults."""

    model_config = ConfigDict(extra="forbid")

    max_parallel_tasks: int = Field(
        default=10,
        ge=1,
        description="Maximum concurrent agent executions"
    )
    default_max_retries: int = Field(
        default=3,
        ge=0,
        description="Default retry count for failed agents"
    )
    execution_timeout: Optional[float] = Field(
        default=None,
        description="Maximum workflow execution time in seconds"
    )
    truncation_length: Optional[int] = Field(
        default=None,
        description="Maximum length for truncated output"
    )
    enable_execution_memory: bool = Field(
        default=True,
        description="Enable ExecutionMemory for result storage"
    )
    embedding_model: Optional[str] = Field(
        default=None,
        description="Optional embedding model for semantic search"
    )
    vector_dimension: int = Field(
        default=384,
        description="Dimension of embedding vectors"
    )
    vector_index_type: str = Field(
        default="Flat",
        description="FAISS index type: 'Flat', 'FlatIP', or 'HNSW'"
    )

    # ── State checkpointing (FEAT-399) ─────────────────────────────────────
    # All default to off/unset so existing definitions parse unchanged.
    checkpoint: bool = Field(
        default=False,
        description="Enable AgentsFlow state checkpointing for this flow"
    )
    checkpoint_retention: Optional[int] = Field(
        default=None,
        description="Ephemeral (Redis) checkpoint TTL in seconds; "
        "defaults to FLOW_CHECKPOINT_REDIS_TTL when unset"
    )
    checkpoint_history: Optional[int] = Field(
        default=None,
        description="Max retained checkpoints per flow; defaults to "
        "FLOW_CHECKPOINT_HISTORY when unset"
    )
    checkpoint_include_responses: bool = Field(
        default=False,
        description="Include raw per-node responses in checkpoints "
        "(heavy; results-only by default)"
    )
    durable: bool = Field(
        default=False,
        description="Write-through every checkpoint to the durable "
        "store in addition to the ephemeral one"
    )


# ---------------------------------------------------------------------------
# FlowDefinition (root model)
# ---------------------------------------------------------------------------

class FlowDefinition(BaseModel):
    """Complete definition of an AgentsFlow workflow.

    This is the root model for JSON serialization. It can be:
    - Loaded from file or Redis
    - Saved to file or Redis
    - Materialized into a runnable AgentsFlow instance

    Example:
        >>> definition = FlowDefinition(
        ...     flow="MyFlow",
        ...     nodes=[
        ...         NodeDefinition(id="start", type="start"),
        ...         NodeDefinition(id="worker", type="agent", agent_ref="my_agent"),
        ...     ],
        ...     edges=[
        ...         EdgeDefinition(**{"from": "start", "to": "worker", "condition": "always"})
        ...     ]
        ... )
    """
    model_config = ConfigDict(extra="forbid")

    flow: str = Field(..., description="Flow name (unique identifier)")
    version: str = Field(
        default="1.0",
        description="Schema version"
    )
    description: str = Field(
        default="",
        description="Human-readable description"
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="Creation timestamp"
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp"
    )
    metadata: FlowMetadata = Field(
        default_factory=FlowMetadata,
        description="Flow-level configuration"
    )
    nodes: List[NodeDefinition] = Field(
        ...,
        description="Node definitions"
    )
    edges: List[EdgeDefinition] = Field(
        default_factory=list,
        description="Edge definitions"
    )

    @model_validator(mode="after")
    def validate_node_ids(self) -> "FlowDefinition":
        """Validate all edge references point to existing node IDs."""
        node_ids = {n.id for n in self.nodes}

        for edge in self.edges:
            # Check source
            if edge.from_ not in node_ids:
                raise ValueError(
                    f"Edge references unknown node ID: '{edge.from_}'. "
                    f"Available nodes: {sorted(node_ids)}"
                )

            # Check targets (handle both string and list)
            targets = [edge.to] if isinstance(edge.to, str) else edge.to
            for target in targets:
                if target not in node_ids:
                    raise ValueError(
                        f"Edge references unknown node ID: '{target}'. "
                        f"Available nodes: {sorted(node_ids)}"
                    )

        return self

    @model_validator(mode="after")
    def _validate_acyclic(self) -> "FlowDefinition":
        """Reject FlowDefinition whose *unconditional* edges form a cycle.

        Runs Kahn's algorithm: repeatedly remove nodes with in-degree 0.
        If any node remains after the queue empties, it participates in a cycle.

        ``on_condition`` edges are exempt from this check (FEAT-377
        TASK-1910): a CEL-gated back-edge is a deliberate, bounded repair/
        retry loop (e.g. dev-loop's ``qa → development`` edge, gated by an
        attempt-count predicate) — the engine's explicit-edge executor
        (OR-join + skip-propagation) supports such cycles; only the
        ``from_definition`` AND-join materialization path benefits from
        acyclicity. A genuinely unconditional cycle (``always``/
        ``on_success``/``on_error``/``on_timeout``) still raises — those
        edges have no predicate to bound iteration.

        Placed AFTER ``validate_node_ids`` so dangling-reference errors surface
        first (cycle detection assumes referential integrity). Pydantic v2 runs
        ``mode="after"`` validators in declaration order.

        Raises:
            ValueError: If any cycle is detected, listing the node IDs involved.
        """
        in_degree: Dict[str, int] = defaultdict(int)
        adj: Dict[str, List[str]] = defaultdict(list)
        node_ids = {n.id for n in self.nodes}

        for n in self.nodes:
            in_degree.setdefault(n.id, 0)

        for edge in self.edges:
            if edge.condition == "on_condition":
                continue
            targets = [edge.to] if isinstance(edge.to, str) else edge.to
            for target in targets:
                # Reference integrity already validated above; guard defensively.
                if edge.from_ in node_ids and target in node_ids:
                    adj[edge.from_].append(target)
                    in_degree[target] += 1

        queue = [nid for nid in in_degree if in_degree[nid] == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for nxt in adj[node]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if visited < len(in_degree):
            cyclic = [nid for nid, deg in in_degree.items() if deg > 0]
            raise ValueError(
                f"Cycle detected in flow definition. "
                f"Nodes involved in cycle: {sorted(cyclic)}"
            )

        return self


# ---------------------------------------------------------------------------
# Convenience exports
# ---------------------------------------------------------------------------

__all__ = [
    # Action definitions
    "LogActionDef",
    "NotifyActionDef",
    "WebhookActionDef",
    "MetricActionDef",
    "SetContextActionDef",
    "ValidateActionDef",
    "TransformActionDef",
    "ActionDefinition",
    # Node/Edge definitions
    "NodePosition",
    "NodeDefinition",
    "EdgeDefinition",
    # Flow definition
    "FlowMetadata",
    "FlowDefinition",
]
