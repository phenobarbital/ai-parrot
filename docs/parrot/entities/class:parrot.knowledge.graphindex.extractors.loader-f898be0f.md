---
type: Wiki Entity
title: LoaderExtractor
id: class:parrot.knowledge.graphindex.extractors.loader.LoaderExtractor
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract document structure from ai-parrot-loaders output.
---

# LoaderExtractor

Defined in [`parrot.knowledge.graphindex.extractors.loader`](../summaries/mod:parrot.knowledge.graphindex.extractors.loader.md).

```python
class LoaderExtractor
```

Extract document structure from ai-parrot-loaders output.

Routes hierarchical content (PDF, Markdown, DOCX, ebook) through
:class:`PageIndexToolkit` (when supplied) so per-node markdown is
persisted and addressable via
``UniversalNode.content_ref``. Flat content (transcripts, plain text)
becomes a single ``Document`` node.

Args:
    llm_adapter: Optional ``PageIndexLLMAdapter`` for section summaries.
        If ``None``, falls back to the first ``summary_length`` characters.
    toolkit: Optional :class:`PageIndexToolkit`. When provided,
        hierarchical content is persisted as a PageIndex tree (lean
        ToC JSON + per-node markdown sidecars) and section
        UniversalNodes carry a ``content_ref`` that points at it.
        When omitted, the extractor falls back to a transient
        in-memory ``md_to_tree`` walk and emits ``content_ref=None``.
    summary_length: Number of characters for the fallback summary.

## Methods

- `async def extract(self, loader: object, source: str) -> tuple[list[UniversalNode], list[UniversalEdge]]` — Run loader, detect content type, and extract nodes/edges.
