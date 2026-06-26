"""parrot.knowledge.wiki — LLM Wiki: Persistent Knowledge Base (FEAT-260).

Implements Karpathy's 3-layer LLM Wiki architecture on top of
AI-Parrot's existing PageIndex and GraphIndex modules:

- **Raw Sources** — :class:`SourceCollectionManager` tracks ingested
  documents with SHA-1 hash + mtime staleness detection.
- **Wiki Pages** — LLM-generated Markdown pages stored in PageIndex trees
  and synchronised to GraphIndex as ``WIKI_PAGE`` nodes.
- **Schema** — OKF ontology extensions (wiki ConceptType values,
  SUMMARIZES / CONTRADICTS relation types).

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
    )
"""

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
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
]
