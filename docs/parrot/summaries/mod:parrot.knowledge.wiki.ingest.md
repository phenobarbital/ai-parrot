---
type: Wiki Summary
title: parrot.knowledge.wiki.ingest
id: mod:parrot.knowledge.wiki.ingest
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Wiki ingest orchestrator for the LLM Wiki feature (FEAT-260).
relates_to:
- concept: class:parrot.knowledge.wiki.ingest.IngestReport
  rel: defines
- concept: class:parrot.knowledge.wiki.ingest.WikiIngestOrchestrator
  rel: defines
- concept: mod:parrot.knowledge.pageindex.utils
  rel: references
- concept: mod:parrot.knowledge.wiki.bookkeeper
  rel: references
- concept: mod:parrot.knowledge.wiki.models
  rel: references
- concept: mod:parrot.knowledge.wiki.sources
  rel: references
- concept: mod:parrot.knowledge.wiki.store
  rel: references
---

# `parrot.knowledge.wiki.ingest`

Wiki ingest orchestrator for the LLM Wiki feature (FEAT-260).

Implements the "Ingest" operation from Karpathy's 3-layer architecture.
Orchestrates the full pipeline for a single source document:

1. Check the source registry — skip if already ingested and not stale.
2. Load source content from the file path.
3. Process via ``PageIndexToolkit.insert_content()`` (which internally
   delegates to ``TwoStepIngester``).
4. Upsert the generated pages into the :class:`WikiStore` retrieval
   plane (bodies, categories, token counts) and record
   ``summarizes`` edges page → source.  ``replace_source_slice``
   guarantees re-ingest never accumulates duplicates.
5. Optionally (``sync_graph=True``) mirror a ``wiki_page`` node into
   GraphIndex.
6. Update the source registry (hash + mtime + pages generated).
7. Append to the operation log via ``WikiBookkeeper.log_operation()``.

All operations are async.  On partial failure the error is logged but
no corrupt state is left: the registry is only updated after all steps
succeed.

## Classes

- **`IngestReport(BaseModel)`** — Result of a single wiki ingest run.
- **`WikiIngestOrchestrator`** — Orchestrates the full source-to-wiki-page ingest pipeline.
