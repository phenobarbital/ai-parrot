"""
FlowDefinition — Pydantic models for AgentsFlow JSON serialization.

This module defines the complete schema for persisting and loading AgentsFlow
workflows as JSON. The schema supports:
- Node definitions (start, end, agent, decision, interactive_decision, human)
- Edge definitions with conditional transitions
- Pre/post lifecycle actions
- SvelteFlow-compatible position data

Example:
    >>> from parrot.bots.flow.definition import FlowDefinition
    >>> definition = FlowDefinition.model_validate(json_data)
    >>> json_str = definition.model_dump_json(by_alias=True)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Action Definition Models
# ---------------------------------------------------------------------------

class LogActionDef(BaseModel):
    """Log a message with template variables.

    Template variables: {node_name}, {result}, {prompt}
    """
    type: Literal["log"] = "log"
    level: Literal["debug", "info", "warning", "error"] = "info"
    message: str = Field(..., description="Message template with {node_name}, {result}, {prompt}")


class NotifyActionDef(BaseModel):
    """Send a notification to a channel."""
    type: Literal["notify"] = "notify"
    channel: Literal["slack", "teams", "email", "log"] = "log"
    message: str = Field(..., description="Notification message")
    target: Optional[str] = Field(
        default=None,
        description="Target channel/address (optional, falls back to configured default)"
    )


class WebhookActionDef(BaseModel):
    """Make an HTTP webhook call."""
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
    type: Literal["metric"] = "metric"
    name: str = Field(..., description="Metric name (e.g., 'flow.node.completed')")
    tags: Dict[str, str] = Field(default_factory=dict)
    value: float = 1.0


class SetContextActionDef(BaseModel):
    """Extract a value from result and set in shared context."""
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

    model_config = {"populate_by_name": True}


class TransformActionDef(BaseModel):
    """Transform result using a safe expression."""
    type: Literal["transform"] = "transform"
    expression: str = Field(
        ...,
        description="Safe expression to transform result (e.g., 'result.lower()')"
    )


# Discriminated union of all action types
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
# Node Definition Models
# ---------------------------------------------------------------------------

class NodePosition(BaseModel):
    """UI position hint for visual flow builders (SvelteFlow compatible)."""
    x: float = 0.0
    y: float = 0.0


class NodeDefinition(BaseModel):
    """Definition of a node in the flow.

    Node types:
    - start: Entry point, no agent_ref required
    - end: Terminal point, no agent_ref required
    - agent: Wraps a registered agent, requires agent_ref
    - decision: Multi-agent voting/consensus
    - interactive_decision: Human-in-the-loop choice
    - human: Full HITL escalation
    """
    id: str = Field(..., description="Unique node identifier")
    type: Literal[
        "start", "end", "agent", "decision", "interactive_decision", "human"
    ] = Field(..., description="Node type")
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
    max_retries: int = Field(default=3, ge=0)
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

    model_config = {"populate_by_name": True}

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
