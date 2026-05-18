"""Pydantic contracts for the Agent Factory subsystem.

The factory orchestrates several specialist builder agents (RAG, tool-agent,
clone). Every specialist produces the same end-shape: a ``BotConfig`` ready to
be persisted as YAML and registered with the ``AgentRegistry``. The wrapper
types below carry orchestrator-level state (routing decisions, provisioning
side-effects, HITL outcomes) around that shared payload.

The ``AgentDefinition`` alias points at ``BotConfig`` deliberately — there is
exactly one source of truth for the registry schema and the factory consumes
it directly to avoid drift.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from parrot.registry.registry import BotConfig

AgentDefinition = BotConfig


class BuilderType(str, Enum):
    """Specialist builders the orchestrator can delegate to."""

    RAG = "rag"
    TOOL_AGENT = "tool_agent"
    CLONE = "clone"


class HITLCheckpoint(str, Enum):
    """Named human-in-the-loop checkpoints in the factory flow."""

    PRE_DELEGATION = "pre_delegation"
    PRE_FINALIZE = "pre_finalize"


class FactoryStatus(str, Enum):
    """Terminal states for a factory run."""

    SUCCESS = "success"
    CANCELLED_BY_USER = "cancelled_by_user"
    TIMEOUT = "timeout"
    FAILED = "failed"


class FactoryRequest(BaseModel):
    """User-facing input to the orchestrator.

    ``description`` is the natural-language ask. ``clone_from`` short-circuits
    the router toward the CloneBuilder. ``hints`` lets callers pin choices the
    LLM would otherwise infer (useful for the HTTP handler when the caller
    already knows the desired builder).
    """

    description: str = Field(..., min_length=1)
    clone_from: Optional[str] = Field(
        default=None,
        description="Name of an existing agent in the registry to clone from.",
    )
    hints: Dict[str, Any] = Field(default_factory=dict)


class RouterDecision(BaseModel):
    """First-stage output: which specialist the orchestrator wants to invoke.

    The LLM emits this via structured output. The orchestrator then surfaces
    it through ``HITLCheckpoint.PRE_DELEGATION`` for user confirmation before
    paying for the specialist's tokens.
    """

    builder: BuilderType
    reasoning: str = Field(
        ...,
        description="One-paragraph justification shown to the user at the "
        "pre-delegation checkpoint.",
    )
    detected_integrations: List[str] = Field(
        default_factory=list,
        description="External services the router detected in the request "
        "(e.g. 'linkedin', 'jira'). The specialist uses this to decide "
        "whether to register an OpenAPI toolkit on the fly.",
    )


class ProvisioningRecord(BaseModel):
    """Side-effect produced by a builder while drafting the definition.

    Builders may provision a vector store, register an OpenAPI toolkit, etc.
    These records let the orchestrator report what was done and, if the user
    cancels at pre-finalize, surface the items that may need cleanup.
    """

    kind: Literal["vector_store", "openapi_toolkit", "other"]
    name: str
    details: Dict[str, Any] = Field(default_factory=dict)


class BuilderOutput(BaseModel):
    """Specialist-to-orchestrator handoff payload.

    Every builder returns this shape regardless of internal flow.
    """

    builder: BuilderType
    definition: AgentDefinition
    provisioning: List[ProvisioningRecord] = Field(default_factory=list)
    notes: Optional[str] = Field(
        default=None,
        description="Free-form notes the builder wants surfaced at "
        "pre-finalize (e.g. assumptions, deferred work).",
    )

    model_config = {"arbitrary_types_allowed": True}


class FactoryResult(BaseModel):
    """Terminal output of an orchestrator run.

    ``definition`` and ``yaml_path`` are populated only when ``status`` is
    ``SUCCESS``. ``cancelled_at`` records which HITL checkpoint the user
    bailed at, so the handler/CLI can show a meaningful message.
    """

    status: FactoryStatus
    definition: Optional[AgentDefinition] = None
    yaml_path: Optional[str] = None
    provisioning: List[ProvisioningRecord] = Field(default_factory=list)
    cancelled_at: Optional[HITLCheckpoint] = None
    error: Optional[str] = None
    router_decision: Optional[RouterDecision] = None

    model_config = {"arbitrary_types_allowed": True}
