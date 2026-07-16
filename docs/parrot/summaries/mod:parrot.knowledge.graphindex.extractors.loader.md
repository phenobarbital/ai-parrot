---
type: Wiki Summary
title: parrot.knowledge.graphindex.extractors.loader
id: mod:parrot.knowledge.graphindex.extractors.loader
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Loader-based extractor for GraphIndex.
relates_to:
- concept: class:parrot.knowledge.graphindex.extractors.loader.LoaderExtractor
  rel: defines
- concept: mod:parrot.knowledge.graphindex.schema
  rel: references
- concept: mod:parrot.knowledge.pageindex
  rel: references
- concept: mod:parrot.knowledge.pageindex.toolkit
  rel: references
---

# `parrot.knowledge.graphindex.extractors.loader`

Loader-based extractor for GraphIndex.

Bridges ai-parrot's loader ecosystem and PageIndex hierarchical indexing
system to produce ``UniversalNode`` / ``UniversalEdge`` instances from
documents (PDF, Markdown, DOCX, audio/video transcripts, web pages, etc.).

Hierarchical content routes through :class:`PageIndexToolkit` (when one
is supplied) so the document body is persisted as per-node markdown
sidecars in a :class:`NodeContentStore` and ``UniversalNode.content_ref``
points at it via the ``pageindex://<tree_name>/<node_id>`` scheme. The
toolkit's tree name is also exposed as ``domain_tags['pageindex_tree_id']``
on the document root so the ontology's
``search_documents_scoped`` routing has something concrete to dispatch on.

When no toolkit is supplied, the extractor degrades gracefully: it
builds a transient in-memory tree via ``md_to_tree`` and emits
``content_ref=None``. This path stays so callers without a PageIndex
storage directory (legacy code, ad-hoc graph builds) keep working.

Flat content (transcripts, plain text) always produces a single
``Document`` node — there's no hierarchy to persist.

## Classes

- **`LoaderExtractor`** — Extract document structure from ai-parrot-loaders output.
