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

__all__ = [
    "Provenance",
    "NodeKind",
    "EdgeKind",
    "UniversalNode",
    "UniversalEdge",
    "SourceConfig",
    "BuildResult",
    "IngestResult",
]
