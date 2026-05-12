"""Concept Catalog sub-package for FEAT-159 Topic-Authority Ontology Curation.

Provides Pydantic models, service, worker, seed, reconcile, and HTTP modules
for managing per-tenant Concept entities and is_a taxonomy in Postgres.
"""
from datetime import datetime, timezone

from parrot.knowledge.ontology.schema import MergedOntology

from .models import CascadeAlert, ConceptRow, IsaEdgeRow

# N4 fix: single shared sentinel — prevents divergence between worker.py and
# reconcile.py which each previously defined their own copy with a different name.
# Worker and reconciler only need this to build a lightweight TenantContext for
# graph store calls; no ontology content is required.
_EMPTY_ONTOLOGY = MergedOntology(
    name="_concept_catalog",
    version="0",
    entities={},
    relations={},
    traversal_patterns={},
    layers=[],
    merge_timestamp=datetime(2000, 1, 1, tzinfo=timezone.utc),
)

__all__ = [
    "ConceptRow",
    "IsaEdgeRow",
    "CascadeAlert",
    "_EMPTY_ONTOLOGY",
]
