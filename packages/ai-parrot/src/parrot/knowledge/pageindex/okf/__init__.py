"""OKF Knowledge Layer subpackage for PageIndex.

This subpackage implements the OKF-compatible knowledge layer over PageIndex
(FEAT-238). It provides:

- ``ontology``: Controlled type/relation vocabulary (ConceptType, RelationType)
  and Pydantic data models (RelatesTo, SourceProvenance).
- ``concept_id``: Deterministic slug generation and dedup (assign_concept_ids).
- ``frontmatter``: ConceptFrontmatter model and byte-deterministic projection.
- ``graph``: In-memory knowledge graph (KnowledgeGraph).
- ``projection``: Sidecar and index.md generation.
- ``migrate``: okf-migrate command for retrofitting existing trees.
- ``tools``: Named read tools for type-scoped retrieval and traversal.
"""

from parrot.knowledge.pageindex.okf.ontology import (
    ConceptType,
    RelationType,
    RelatesTo,
    SourceProvenance,
)

__all__ = [
    "ConceptType",
    "RelationType",
    "RelatesTo",
    "SourceProvenance",
]
