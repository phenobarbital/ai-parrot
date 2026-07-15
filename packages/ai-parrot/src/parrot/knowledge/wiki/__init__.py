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

Exports are resolved lazily (PEP 562) so lightweight consumers — the
``wikitoolkit`` CLI and the Claude Code integration hook — can import
the retrieval plane (``store``/``search``/``context``/``export``)
without pulling in the agent framework behind
:class:`LLMWikiToolkit`.
"""

# Map of exported name -> defining submodule (lazy import targets).
_EXPORT_MODULES: dict[str, str] = {
    # Toolkit (agent-facing)
    "LLMWikiToolkit": "parrot.knowledge.wiki.toolkit",
    # Configuration
    "WikiConfig": "parrot.knowledge.wiki.models",
    "WikiPageCategory": "parrot.knowledge.wiki.models",
    # Source tracking
    "SourceManifestEntry": "parrot.knowledge.wiki.models",
    "SourceCollectionManager": "parrot.knowledge.wiki.sources",
    # Search
    "WikiSearchResult": "parrot.knowledge.wiki.models",
    "WikiCombinedSearch": "parrot.knowledge.wiki.search",
    # Bookkeeping
    "WikiBookkeeper": "parrot.knowledge.wiki.bookkeeper",
    # Ingest
    "WikiIngestOrchestrator": "parrot.knowledge.wiki.ingest",
    "IngestReport": "parrot.knowledge.wiki.ingest",
    # Lint
    "WikiLintReport": "parrot.knowledge.wiki.models",
    # Retrieval plane (machine-first, pluggable backends)
    "BaseWikiStore": "parrot.knowledge.wiki.store",
    "WikiStore": "parrot.knowledge.wiki.store",
    "SQLiteWikiStore": "parrot.knowledge.wiki.store",
    "InMemoryWikiStore": "parrot.knowledge.wiki.file_store",
    "create_wiki_store": "parrot.knowledge.wiki.store",
    "WikiPageRecord": "parrot.knowledge.wiki.store",
    # Context packing
    "PackedContext": "parrot.knowledge.wiki.context",
    "pack_results": "parrot.knowledge.wiki.context",
}

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str):
    """Resolve a public export lazily on first attribute access.

    Args:
        name: Attribute requested on the package.

    Returns:
        The resolved object from its defining submodule.

    Raises:
        AttributeError: If ``name`` is not a public wiki export.
    """
    module_path = _EXPORT_MODULES.get(name)
    if module_path is None:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        )
    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    globals()[name] = value  # cache for subsequent lookups
    return value


def __dir__() -> list[str]:
    """Expose lazy exports to :func:`dir`."""
    return sorted(set(globals()) | set(__all__))
