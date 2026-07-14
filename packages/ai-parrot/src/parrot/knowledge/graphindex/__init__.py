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
    GraphProjectionReport,
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
    derive_community_label,
    detect_communities,
)
from parrot.knowledge.graphindex.export_html import (
    GraphExportPayload,
    build_export_payload,
    community_color,
    export_graph,
    write_graph_html,
    write_graph_json,
)
from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.projection import (
    project_graph_sidecars,
    project_node_sidecar,
    project_report_frontmatter,
    node_to_frontmatter_dict,
)
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader
from parrot.knowledge.graphindex.extractors.odoo_code import OdooCodeExtractor

__all__ = [
    "Provenance",
    "NodeKind",
    "EdgeKind",
    "UniversalNode",
    "UniversalEdge",
    "SourceConfig",
    "GraphProjectionReport",
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
    "derive_community_label",
    "detect_communities",
    "GraphExportPayload",
    "build_export_payload",
    "community_color",
    "export_graph",
    "write_graph_html",
    "write_graph_json",
    "GraphIndexLoader",
    "OdooCodeExtractor",
    "SQLitePersistence",
    "SQLiteGraphReader",
    "project_graph_sidecars",
    "project_node_sidecar",
    "project_report_frontmatter",
    "node_to_frontmatter_dict",
]

# ``GraphIndexLoader`` transitively pulls the full loaders/clients web-framework
# stack (aiohttp, navigator, embeddings). Import it lazily (PEP 562) so that
# ``import parrot.knowledge.graphindex`` — and the local-first CLI / pure graph
# modules — stay lightweight and usable without those heavyweight dependencies.
_LAZY_ATTRS = {"GraphIndexLoader": "parrot.knowledge.graphindex.loader"}


def __getattr__(name: str):
    """Resolve lazily-exported attributes on first access (PEP 562)."""
    module_path = _LAZY_ATTRS.get(name)
    if module_path is not None:
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
