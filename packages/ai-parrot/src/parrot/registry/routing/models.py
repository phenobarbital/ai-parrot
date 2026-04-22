"""Pydantic v2 data models for the FEAT-111 store-level router.

These models mirror the shape of ``IntentRouterConfig`` and friends in
``parrot.registry.capabilities.models`` but are scoped to store selection.

Public API (re-exported from ``parrot.registry.routing``)::

    from parrot.registry.routing import (
        StoreFallbackPolicy,
        StoreRule,
        StoreRouterConfig,
        StoreScore,
        StoreRoutingDecision,
    )
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from parrot.tools.multistoresearch import StoreType  # source of truth for store identifiers


class StoreFallbackPolicy(str, Enum):
    """What the router does when no store scores above ``confidence_floor``.

    Attributes:
        FAN_OUT: Delegate to ``MultiStoreSearchTool._execute()`` for parallel
            fan-out across all configured stores + BM25 reranking.
        FIRST_AVAILABLE: Use the first configured store in insertion order.
        EMPTY: Return an empty result list without raising.
        RAISE: Raise ``NoSuitableStoreError``.
    """

    FAN_OUT = "fan_out"
    FIRST_AVAILABLE = "first_available"
    EMPTY = "empty"
    RAISE = "raise"


class StoreRule(BaseModel):
    """One heuristic rule that maps a query pattern to a preferred store.

    Args:
        pattern: Lowercase substring or regex (see ``regex`` flag).
        store: Target store type.
        weight: Confidence weight assigned when the rule fires (0–1).
        regex: When ``True``, ``pattern`` is compiled as a regular expression
            and matched via ``re.search``.  When ``False`` (default), a
            plain substring match is used.
    """

    pattern: str = Field(..., description="Lowercase substring or regex (see regex flag)")
    store: StoreType
    weight: float = Field(1.0, ge=0.0, le=1.0, description="Confidence weight (0–1)")
    regex: bool = False


class StoreRouterConfig(BaseModel):
    """Full configuration for ``StoreRouter``.

    Shape mirrors ``IntentRouterConfig`` from
    ``parrot.registry.capabilities.models``.

    Args:
        margin_threshold: If ``top-1_confidence - top-2_confidence <
            margin_threshold``, engage the LLM fallback path.
        confidence_floor: Drop stores whose final score falls below this
            value from the ``StoreRoutingDecision.rankings``.
        llm_timeout_s: Maximum seconds to wait for the LLM ranking call.
        top_n: How many top-ranked stores to query in ``StoreRouter.execute``.
        fallback_policy: What to do when ``rankings`` is empty after
            applying the confidence floor.
        cache_size: Maximum number of ``StoreRoutingDecision`` entries to
            keep in the in-memory LRU.  ``0`` disables caching.
        enable_ontology_signal: Whether to query ``OntologyPreAnnotator``
            for query pre-annotation signals.
        custom_rules: Per-agent ``StoreRule`` list merged *on top of* the
            built-in default rules.  Follows the same precedence semantics as
            ``IntentRouterConfig.custom_keywords``.
    """

    margin_threshold: float = Field(
        0.15,
        ge=0.0,
        le=1.0,
        description="If top-1 - top-2 < margin, engage LLM fallback",
    )
    confidence_floor: float = Field(
        0.2,
        ge=0.0,
        le=1.0,
        description="Drop stores scoring below this from the decision",
    )
    llm_timeout_s: float = Field(
        1.0,
        gt=0.0,
        description="Maximum seconds to wait for the LLM ranking call",
    )
    top_n: int = Field(
        1,
        ge=1,
        description="How many top-ranked stores to query in execute()",
    )
    fallback_policy: StoreFallbackPolicy = StoreFallbackPolicy.FAN_OUT
    cache_size: int = Field(
        256,
        ge=0,
        description="LRU cache size; 0 disables caching",
    )
    enable_ontology_signal: bool = True
    custom_rules: list[StoreRule] = Field(
        default_factory=list,
        description="Per-agent YAML overrides merged on top of defaults",
    )


class StoreScore(BaseModel):
    """One ranked store entry within a ``StoreRoutingDecision``.

    Args:
        store: The store type.
        confidence: Routing confidence in ``[0.0, 1.0]``.
        reason: Human-readable explanation for the score.
    """

    store: StoreType
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = ""


class StoreRoutingDecision(BaseModel):
    """Complete output of ``StoreRouter.route()``.

    Args:
        rankings: Stores ranked by descending confidence.  May be empty when
            ``fallback_used`` is ``True``.
        fallback_used: ``True`` when no store cleared ``confidence_floor`` and
            the ``StoreFallbackPolicy`` was engaged.
        cache_hit: ``True`` when the decision was served from the LRU cache.
        ontology_annotations: Raw annotations produced by
            ``OntologyPreAnnotator.annotate()`` (if enabled).
        path: Decision path.  Conventional values:
            ``"cache"`` | ``"fast"`` | ``"llm"`` | ``"fallback"``.
        elapsed_ms: Wall-clock time from entering ``route()`` to returning the
            decision, in milliseconds.
    """

    rankings: list[StoreScore] = Field(default_factory=list)
    fallback_used: bool = False
    cache_hit: bool = False
    ontology_annotations: Optional[dict] = None
    path: str = Field(..., description='fast | llm | cache | fallback')
    elapsed_ms: float = 0.0
