"""Pydantic v2 row models for the Concept Catalog tables.

These models represent the Postgres rows for ontology_concept,
ontology_concept_isa, and the CascadeAlert notification type emitted
when a Concept is deprecated. They are used by the service, worker,
seed, reconcile, and HTTP modules.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ConceptRow(BaseModel):
    """Represents a row in the ontology_concept Postgres table.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant owning this concept.
        slug: Tenant-local slug identifier (e.g. "sales_commissions").
        label: Human-readable display label.
        synonyms: List of synonym strings for this concept.
        description: Optional prose description.
        domain: Optional domain tag (e.g. "finance").
        state: Current state in the five-state machine.
        asserted_by: Who asserted this concept (user email or system).
        reviewed_by: Who reviewed the transition (optional).
        reviewed_at: When the review happened (optional).
        rationale: Curator's rationale for the proposal or decision.
        effective_from: When this concept became effective.
        effective_to: When this concept expires (optional).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    slug: str
    label: str
    synonyms: list[str] = Field(default_factory=list)
    description: str | None = None
    domain: str | None = None
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rationale: str | None = None
    effective_from: datetime
    effective_to: datetime | None = None


class IsaEdgeRow(BaseModel):
    """Represents a row in the ontology_concept_isa Postgres table.

    Captures a directional is_a (sub-class) relationship between a tenant
    concept (child) and a parent concept that may live in the framework
    layer or in the tenant's own catalog.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant owning this edge.
        child_id: FK to ontology_concept.id (the sub-concept).
        parent_tier: Whether the parent lives in the framework or tenant layer.
        parent_ref: Framework concept name or tenant ontology_concept.id (as str).
        state: Current state in the five-state machine.
        asserted_by: Who asserted this edge.
        reviewed_by: Reviewer (optional).
        rationale: Curator's rationale (optional).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    child_id: UUID
    parent_tier: Literal["framework", "tenant"]
    parent_ref: str
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    rationale: str | None = None


class CascadeAlert(BaseModel):
    """Notification emitted to the operational service when a Concept is deprecated.

    The cascade-on-deprecate flow emits exactly one CascadeAlert per
    deprecation operation, listing all operational topic_authority edge IDs
    that reference the deprecated concept.

    Attributes:
        tenant_id: Tenant owning the deprecated concept.
        concept_id: UUID of the deprecated concept.
        concept_slug: Slug of the deprecated concept.
        affected_edge_ids: List of operational topic_authority.id values
            that reference this concept.
        notified_at: Timestamp when this alert was emitted.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    concept_id: UUID
    concept_slug: str
    affected_edge_ids: list[UUID] = Field(default_factory=list)
    notified_at: datetime
