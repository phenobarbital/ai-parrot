---
type: Wiki Summary
title: parrot.knowledge.wiki
id: mod:parrot.knowledge.wiki
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'parrot.knowledge.wiki — LLM Wiki: Persistent Knowledge Base (FEAT-260).'
relates_to:
- concept: mod:parrot.knowledge.wiki.bookkeeper
  rel: references
- concept: mod:parrot.knowledge.wiki.context
  rel: references
- concept: mod:parrot.knowledge.wiki.file_store
  rel: references
- concept: mod:parrot.knowledge.wiki.ingest
  rel: references
- concept: mod:parrot.knowledge.wiki.models
  rel: references
- concept: mod:parrot.knowledge.wiki.search
  rel: references
- concept: mod:parrot.knowledge.wiki.sources
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
- concept: mod:parrot.knowledge.wiki.toolkit
  rel: references
---

# `parrot.knowledge.wiki`

parrot.knowledge.wiki — LLM Wiki: Persistent Knowledge Base (FEAT-260).

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
