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
from parrot.knowledge.pageindex.okf.concept_id import (
    derive_concept_id,
    dedup_concept_ids,
    assign_concept_ids,
)
from parrot.knowledge.pageindex.okf.frontmatter import (
    ConceptFrontmatter,
    project_frontmatter,
    parse_frontmatter,
)
from parrot.knowledge.pageindex.okf.graph import (
    KnowledgeGraph,
    build_graph,
    parse_markdown_links,
)
from parrot.knowledge.pageindex.okf.projection import (
    flatten_concept_id_for_filename,
    project_sidecar,
    project_sidecars,
    generate_index_md,
    ProjectionReport,
)

__all__ = [
    "ConceptType",
    "RelationType",
    "RelatesTo",
    "SourceProvenance",
    "derive_concept_id",
    "dedup_concept_ids",
    "assign_concept_ids",
    "ConceptFrontmatter",
    "project_frontmatter",
    "parse_frontmatter",
    "KnowledgeGraph",
    "build_graph",
    "parse_markdown_links",
    "flatten_concept_id_for_filename",
    "project_sidecar",
    "project_sidecars",
    "generate_index_md",
    "ProjectionReport",
]
