"""Pydantic v2 models for Intent Router and Capability Registry.

Defines all enums and data models for the FEAT-070 intent routing feature:
routing types, capability entries, routing decisions, routing traces, and
intent router configuration.

FEAT-111 addition: ``TraceEntry`` gains an optional ``store_rankings`` field
(list of ``StoreScore``) so the existing ``RoutingTrace`` machinery can carry
store-level detail when the ``StoreRouter`` is active.  The field defaults to
``None`` so all existing code that builds ``TraceEntry`` objects is unaffected.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    # Forward reference only — avoids a runtime circular import between
    # parrot.registry.capabilities.models and parrot.registry.routing.
    from parrot.registry.routing.models import StoreScore as _StoreScore


class ResourceType(str, Enum):
    """Type of resource registered in the capability index."""

    DATASET = "dataset"
    TOOL = "tool"
    GRAPH_NODE = "graph_node"
    PAGEINDEX = "pageindex"
    VECTOR_COLLECTION = "vector_collection"


class RoutingType(str, Enum):
    """Strategy the intent router can select."""

    GRAPH_PAGEINDEX = "graph_pageindex"
    DATASET = "dataset"
    VECTOR_SEARCH = "vector_search"
    TOOL_CALL = "tool_call"
    FREE_LLM = "free_llm"
    MULTI_HOP = "multi_hop"
    FALLBACK = "fallback"
    HITL = "hitl"


class CapabilityEntry(BaseModel):
    """A registered capability in the semantic index.

    Args:
        name: Unique name of the capability.
        description: Human-readable description used for embedding.
        resource_type: The type of resource this entry represents.
        embedding: Pre-computed embedding vector (None until build_index() is called).
        metadata: Arbitrary metadata dict for routing-specific information.
        not_for: Query patterns this capability should NOT match.
    """

    name: str = Field(..., description="Unique name of the capability")
    description: str = Field(
        ..., description="Human-readable description (used for embedding)"
    )
    resource_type: ResourceType
    embedding: Optional[list[float]] = Field(
        default=None, description="Pre-computed embedding vector"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)
    not_for: list[str] = Field(
        default_factory=list,
        description="Query patterns this capability should NOT match",
    )

    model_config = {"arbitrary_types_allowed": True}


class RouterCandidate(BaseModel):
    """A scored match from capability search.

    Args:
        entry: The matched capability entry.
        score: Cosine similarity score in [0.0, 1.0].
        resource_type: The resource type of the matched entry.
    """

    entry: CapabilityEntry
    score: float = Field(..., ge=0.0, le=1.0)
    resource_type: ResourceType


class RoutingDecision(BaseModel):
    """The router's selected strategy and candidates.

    Args:
        routing_type: Primary routing strategy selected.
        candidates: Top-K registry candidates that influenced the decision.
        cascades: Ordered list of fallback strategies if primary fails.
        confidence: Confidence score in [0.0, 1.0].
        reasoning: LLM explanation for the routing choice.
    """

    routing_type: RoutingType
    candidates: list[RouterCandidate] = Field(default_factory=list)
    cascades: list[RoutingType] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = Field("", description="LLM explanation for routing choice")


class TraceEntry(BaseModel):
    """One step in the routing trace.

    Args:
        routing_type: Strategy attempted in this step.
        produced_context: True if this step contributed to the final context.
        context_snippet: Brief excerpt of the produced context (if any).
        error: Error message if this step failed.
        elapsed_ms: Time taken for this step in milliseconds.
        store_rankings: Optional store-level routing detail populated by
            ``StoreRouter`` (FEAT-111).  ``None`` when the store router is not
            active — backward compatible with all existing callers.
    """

    routing_type: RoutingType
    produced_context: bool = False
    context_snippet: Optional[str] = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0
    # FEAT-111: additive optional field — defaults to None so existing code is unaffected.
    store_rankings: Optional[list] = Field(
        default=None,
        description="Store-level routing detail (list[StoreScore]) from StoreRouter. None when router is inactive.",
    )


class RoutingTrace(BaseModel):
    """Full trace of a routing session.

    Args:
        mode: Routing mode — "normal" (cascade) or "exhaustive" (all strategies).
        entries: Ordered list of trace entries for each strategy attempted.
        elapsed_ms: Total elapsed time for the full routing session.
    """

    mode: Literal["normal", "exhaustive"] = "normal"
    entries: list[TraceEntry] = Field(default_factory=list)
    elapsed_ms: float = 0.0


class IntentRouterConfig(BaseModel):
    """Configuration for the IntentRouter.

    Args:
        confidence_threshold: Minimum confidence to accept a route (0.0–1.0).
        hitl_threshold: Below this confidence, ask the human for clarification.
        strategy_timeout_s: Per-strategy timeout in seconds (must be > 0).
        exhaustive_mode: When True, run all strategies and concatenate results.
        max_cascades: Maximum number of cascade fallback steps before FALLBACK.
        custom_keywords: Extra keyword→strategy mappings merged on top of the
            built-in ``_KEYWORD_STRATEGY_MAP``.  Keys are lowercase keyword
            phrases; values are ``RoutingType`` values (as strings or enum
            members).  Example::

                custom_keywords={
                    "pricing": "graph_pageindex",
                    "stock level": "dataset",
                }
    """

    confidence_threshold: float = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description="Min confidence to accept a route",
    )
    hitl_threshold: float = Field(
        0.3,
        ge=0.0,
        le=1.0,
        description="Below this confidence, ask the human",
    )
    strategy_timeout_s: float = Field(
        30.0,
        gt=0.0,
        description="Per-strategy timeout in seconds",
    )
    exhaustive_mode: bool = Field(
        False,
        description="Run all strategies and concatenate results",
    )
    max_cascades: int = Field(
        3,
        ge=1,
        le=10,
        description="Max cascade steps before fallback",
    )
    custom_keywords: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Extra keyword→RoutingType mappings merged on top of the "
            "built-in keyword map.  Keys are lowercase phrases; values "
            "are RoutingType enum values (e.g. 'graph_pageindex')."
        ),
    )
