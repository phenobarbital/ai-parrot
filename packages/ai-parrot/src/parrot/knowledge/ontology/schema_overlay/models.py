"""Pydantic v2 row models for the Schema Overlay tables.

These models represent the Postgres rows for ontology_schema_overlay and
the DryRunReport structure returned by the schema overlay validator.
They are used by the service, validator, worker, and HTTP modules.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SchemaOverlayRow(BaseModel):
    """Represents a row in the ontology_schema_overlay Postgres table.

    Schema overlays extend the tenant's merged ontology with new entity types,
    relation types, or traversal patterns. A mandatory dry-run gate validates
    the overlay before it can be approved.

    Attributes:
        id: UUID primary key.
        tenant_id: Tenant owning this overlay.
        overlay_kind: Type of overlay — entity_type, relation_type, or traversal_pattern.
        name: Name of the entity/relation/pattern being introduced.
        definition: Serialized definition dict (EntityDef, RelationDef, or TraversalPattern).
        state: Current state in the five-state machine.
        asserted_by: Who asserted this overlay.
        reviewed_by: Reviewer (optional).
        rationale: Curator's rationale (optional).
        dry_run_report: Last dry-run outcome (success or failure + trace).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: str
    overlay_kind: Literal["entity_type", "relation_type", "traversal_pattern"]
    name: str
    definition: dict[str, Any]
    state: Literal["proposed", "pending_review", "approved", "rejected", "deprecated"]
    asserted_by: str
    reviewed_by: str | None = None
    rationale: str | None = None
    dry_run_report: dict[str, Any] | None = None


class DryRunReport(BaseModel):
    """Result of a schema overlay dry-run validation.

    The dry-run runs a sandboxed merge of the candidate overlay with the
    tenant's current YAML chain, validates AQL for traversal patterns, and
    checks for framework-override attempts.

    Attributes:
        ok: True if all checks passed, False if any check failed.
        checks: Per-check results with check_name, passed, and details.
        error: Top-level error message if the entire dry-run failed.
        duration_ms: Wall-clock duration of the dry-run in milliseconds.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    checks: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    duration_ms: int
