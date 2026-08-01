"""Checkpoint data models for AgentsFlow state checkpointing (FEAT-399).

Defines the Pydantic v2 models that make up a `FlowCheckpoint` — the unit
stored by every `CheckpointStore`, assembled by `FlowCheckpointer`, and
loaded by `AgentsFlow.resume()`.

These models are pure data: no I/O, no logging. Serialization to
ormsgpack lives in `serializer.py` (TASK-2047).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.bots.flows.flow.definition import FlowDefinition


class MemoryRefs(BaseModel):
    """References to conversational memory — never the memory content itself.

    Checkpoints reference memory by id so `resume()` can re-attach the
    live memory backend instead of duplicating conversation history.
    """
    session_id: str | None = Field(
        default=None,
        description="Conversation/session id to re-attach on resume",
    )
    chatbot_id: str | None = Field(
        default=None,
        description="Chatbot/bot id owning the memory",
    )
    user_id: str | None = Field(
        default=None,
        description="User id associated with the flow run",
    )


class NodeStateSnapshot(BaseModel):
    """Per-node FSM state at checkpoint time."""
    node_id: str = Field(..., description="Node identifier")
    fsm_state: str = Field(
        ...,
        description="AgentTaskMachine state name (e.g. running/completed/failed)",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="Timestamp the node reached a terminal state, if any",
    )


class ContextSnapshot(BaseModel):
    """Serialized snapshot of a `FlowContext` at checkpoint time.

    `agent_registry`, `synthesis_client`, and `trace_context` are
    intentionally excluded — they are not serializable and are
    re-bound/re-seeded by `AgentsFlow.resume()`.
    """
    initial_task: str = Field(..., description="Original task/prompt for the flow")
    results: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted per-node results, serialized via FlowStateSerializer",
    )
    responses: dict[str, Any] | None = Field(
        default=None,
        description="Raw per-node responses; only populated when "
        "checkpoint_include_responses=True",
    )
    completed_tasks: list[str] = Field(
        default_factory=list,
        description="Node ids that have completed",
    )
    completion_order: list[str] = Field(
        default_factory=list,
        description="Node ids in the order they completed",
    )
    shared_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Flow-level shared data dictionary",
    )
    errors: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="node_id -> {type, message, repr}; FlowContext.errors holds "
        "live Exception instances which are never serialized directly",
    )


class FlowCheckpoint(BaseModel):
    """A single point-in-time checkpoint of an AgentsFlow run.

    Embeds the full `FlowDefinition` graph snapshot (not a path or hash)
    so a checkpoint is self-contained and can rebuild the flow via
    `AgentsFlow.from_definition()` on resume.
    """
    flow_id: str = Field(..., description="Unique identifier of the flow run")
    flow_name: str = Field(..., description="Flow name")
    checkpoint_id: int = Field(..., description="Monotonic checkpoint id per flow_id")
    parent_checkpoint_id: int | None = Field(
        default=None,
        description="Previous checkpoint id in the time-travel chain, if any",
    )
    created_at: datetime = Field(..., description="Checkpoint creation timestamp")
    status: Literal["running", "suspended", "completed", "failed"] = Field(
        ..., description="Run status at checkpoint time"
    )
    definition: FlowDefinition = Field(
        ..., description="Embedded graph snapshot (full FlowDefinition)"
    )
    context: ContextSnapshot = Field(
        ..., description="Serialized FlowContext snapshot"
    )
    node_states: list[NodeStateSnapshot] = Field(
        default_factory=list, description="Per-node FSM states at checkpoint time"
    )
    memory_refs: MemoryRefs = Field(
        default_factory=MemoryRefs,
        description="References to conversational memory (not the content)",
    )
    lossy: bool = Field(
        default=False,
        description="True if any value degraded to a tagged repr during serialization",
    )
