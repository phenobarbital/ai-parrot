"""parrot.knowledge.wiki — LLM Wiki: Persistent Knowledge Base (FEAT-260).

Implements Karpathy's 3-layer LLM Wiki architecture, optimised for
machine retrieval (tools and LLMs) rather than human-readable storage:

- **Raw Sources** — :class:`SourceCollectionManager` tracks ingested
  documents with SHA-1 hash + mtime staleness detection (persisted in
  the wiki's SQLite plane).
- **Wiki Pages** — structured by PageIndex at ingest time, then served
  from :class:`WikiStore` — a single-file SQLite retrieval plane
  (FTS5/BM25 + optional embedding cosine + typed edges) — with
  token-budgeted context packing (:func:`pack_results`) and
  progressive disclosure.
- **Schema** — open-string categories/relations in the machine plane;
  OKF ontology extensions retained at the export boundary.

Public API::

    from parrot.knowledge.wiki import (
        LLMWikiToolkit,
        WikiConfig,
        WikiPageCategory,
        SourceManifestEntry,
        WikiSearchResult,
        WikiLintReport,
        SourceCollectionManager,
        WikiBookkeeper,
        WikiCombinedSearch,
        WikiIngestOrchestrator,
        IngestReport,
        WikiStore,
        WikiPageRecord,
        PackedContext,
        pack_results,
    )
"""

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.context import PackedContext, pack_results
from parrot.knowledge.wiki.ingest import IngestReport, WikiIngestOrchestrator
from parrot.knowledge.wiki.models import (
    SourceManifestEntry,
    WikiConfig,
    WikiLintReport,
    WikiPageCategory,
    WikiSearchResult,
)
from parrot.knowledge.wiki.search import WikiCombinedSearch
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import WikiPageRecord, WikiStore
from parrot.knowledge.wiki.toolkit import LLMWikiToolkit

__all__ = [
    # Toolkit (agent-facing)
    "LLMWikiToolkit",
    # Configuration
    "WikiConfig",
    "WikiPageCategory",
    # Source tracking
    "SourceManifestEntry",
    "SourceCollectionManager",
    # Search
    "WikiSearchResult",
    "WikiCombinedSearch",
    # Bookkeeping
    "WikiBookkeeper",
    # Ingest
    "WikiIngestOrchestrator",
    "IngestReport",
    # Lint
    "WikiLintReport",
    # Retrieval plane (machine-first)
    "WikiStore",
    "WikiPageRecord",
    # Context packing
    "PackedContext",
    "pack_results",
]
