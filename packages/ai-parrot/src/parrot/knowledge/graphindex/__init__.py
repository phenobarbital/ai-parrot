"""GraphIndex — Structured Knowledge Graph Indexing for AI-Parrot.

This package provides a unified knowledge graph that spans code, documents,
and skills within a single tenant. It is organized as a 6-stage pipeline:

1. Extract  — Code, Loader, and SKILL.md extractors emit UniversalNode/UniversalEdge
2. Embed    — Batch embedding via EmbeddingModel → FAISS (hot) + pgvector (persistent)
3. Assemble — rustworkx PyDiGraph built in-process from node/edge streams
4. Resolve  — Level 1 cosine-similarity cross-domain edge inference
5. Persist  — OntologyGraphStore → ArangoDB + embeddings → pgvector
6. Analyze  — Centrality, surprising connections, GRAPH_REPORT.md generation

The agent-facing toolkit lives in ``parrot_tools.graphindex.toolkit``.
"""

from parrot.knowledge.graphindex.schema import (
    Provenance,
    NodeKind,
    EdgeKind,
    UniversalNode,
    UniversalEdge,
    SourceConfig,
    BuildResult,
    IngestResult,
)
from parrot.knowledge.graphindex.signals import (
    SignalRelevance,
    SignalRelevanceConfig,
    compute_pairwise_signals,
    relevance_neighborhood,
    signal_relevance,
)
from parrot.knowledge.graphindex.communities import (
    Community,
    CommunitiesResult,
    cohesion_for_community,
    detect_communities,
)
from parrot.knowledge.graphindex.loader import GraphIndexLoader
from parrot.knowledge.graphindex.projection import (
    project_graph_sidecars,
    project_node_sidecar,
    project_report_frontmatter,
    node_to_frontmatter_dict,
    GraphProjectionReport,
)

__all__ = [
    "Provenance",
    "NodeKind",
    "EdgeKind",
    "UniversalNode",
    "UniversalEdge",
    "SourceConfig",
    "BuildResult",
    "IngestResult",
    "SignalRelevance",
    "SignalRelevanceConfig",
    "compute_pairwise_signals",
    "relevance_neighborhood",
    "signal_relevance",
    "Community",
    "CommunitiesResult",
    "cohesion_for_community",
    "detect_communities",
    "GraphIndexLoader",
    "project_graph_sidecars",
    "project_node_sidecar",
    "project_report_frontmatter",
    "node_to_frontmatter_dict",
    "GraphProjectionReport",
]
