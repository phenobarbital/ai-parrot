"""Request/result contracts for the workflow-authoring subsystem.

Shapes mirror ``parrot.bots.factory.contracts`` (the agent factory): a
request carrying the natural-language ask, progress the caller can poll, and
a result that is honest about partial success. The difference is scope — the
factory produces one ``BotConfig``; this produces a whole workflow.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .blueprint import Engine, WorkflowBlueprint

__all__ = (
    "AuthoringProgress",
    "AuthoringStage",
    "AuthoringStatus",
    "CapabilityGap",
    "FlowAuthoringRequest",
    "FlowAuthoringResult",
)


class AuthoringStage(str, Enum):
    """Where a run is in the pipeline. Surfaced through job metadata."""

    SKELETON = "skeleton"
    NODES = "nodes"
    TRANSITIONS = "transitions"
    ASSEMBLE = "assemble"
    VALIDATE = "validate"
    REPAIR = "repair"
    COMPILE = "compile"
    PERSIST = "persist"
    DONE = "done"


class AuthoringStatus(str, Enum):
    """Terminal states.

    ``DEGRADED`` is the important one: a workflow that dropped a node it
    could not author, or substituted a capability it does not have, is not a
    success and must not be reported as one — but it is still worth handing
    back, with the gaps named.
    """

    SUCCESS = "success"
    DEGRADED = "degraded"
    FAILED = "failed"


class CapabilityGap(BaseModel):
    """Something the request needed and the platform does not have.

    The alternative to reporting these is letting a model invent a plausible
    tool name, which produces a workflow that validates against nothing and
    fails at run time. Naming the gap keeps the failure at authoring time,
    where a human can still act on it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["tool", "toolkit", "agent", "node_type", "capability"]
    requested: str = Field(..., description="What the workflow asked for")
    reason: str = Field(..., description="Why it could not be satisfied")
    suggestion: Optional[str] = Field(
        default=None, description="The closest available substitute, if any"
    )
    node_id: Optional[str] = Field(
        default=None, description="Node that needed it, when attributable"
    )


class AuthoringProgress(BaseModel):
    """A progress tick, written to the job record as the run advances."""

    model_config = ConfigDict(extra="forbid")

    stage: AuthoringStage
    nodes_total: int = 0
    nodes_done: int = 0
    message: str = ""


class FlowAuthoringRequest(BaseModel):
    """The user-facing input."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        ...,
        min_length=1,
        description="Natural-language description of the desired workflow",
    )
    engine: Literal["crew", "flow", "auto"] = Field(
        default="auto",
        description=(
            "'crew' defines agents inline; 'flow' wires agents already in the "
            "AgentRegistry; 'auto' picks based on whether the workflow needs "
            "agents that do not exist yet"
        ),
    )
    name: Optional[str] = Field(
        default=None, description="Workflow name; derived from the request when unset"
    )
    tenant: str = Field(default="global", description="Tenant for crew isolation")
    max_nodes: int = Field(
        default=12,
        ge=1,
        le=40,
        description="Upper bound on authored nodes — one LLM call each",
    )
    allowed_tools: Optional[List[str]] = Field(
        default=None,
        description=(
            "Allowlist restricting the tool catalog. The workflow can only "
            "reference what the catalog lists, so this bounds what it can do."
        ),
    )
    persist: bool = Field(
        default=False,
        description=(
            "Register the compiled workflow. Off by default: authoring "
            "returns a definition, and storing it is a separate decision."
        ),
    )
    hints: Dict[str, Any] = Field(
        default_factory=dict, description="Caller-supplied overrides"
    )


class FlowAuthoringResult(BaseModel):
    """Terminal output of an authoring run.

    ``crew_definition``/``flow_definition`` are plain dicts rather than the
    models: the result is persisted to a Redis-backed job record, so it must
    stay JSON round-trippable.
    """

    model_config = ConfigDict(extra="forbid")

    status: AuthoringStatus
    engine: Optional[Engine] = None
    blueprint: Optional[WorkflowBlueprint] = None
    crew_definition: Optional[Dict[str, Any]] = None
    flow_definition: Optional[Dict[str, Any]] = None
    capability_gaps: List[CapabilityGap] = Field(default_factory=list)
    validation_issues: List[str] = Field(
        default_factory=list,
        description="Human-readable rendering of surviving validation issues",
    )
    repair_rounds: int = Field(
        default=0, description="How many repair rounds the run needed"
    )
    dropped_nodes: List[str] = Field(
        default_factory=list,
        description="Nodes that could not be authored and were excluded",
    )
    persisted_as: Optional[str] = Field(
        default=None, description="Storage key when persist=True"
    )
    error: Optional[str] = None
