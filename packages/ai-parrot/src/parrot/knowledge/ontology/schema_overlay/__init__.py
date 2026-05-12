"""Schema Overlay sub-package for FEAT-159 Topic-Authority Ontology Curation.

Provides Pydantic models, validator, service, worker, and HTTP modules for
managing per-tenant schema overlays (entity types, relation types, traversal
patterns) in Postgres with a mandatory dry-run gate before approval.
"""
from .models import DryRunReport, SchemaOverlayRow

__all__ = [
    "SchemaOverlayRow",
    "DryRunReport",
]
