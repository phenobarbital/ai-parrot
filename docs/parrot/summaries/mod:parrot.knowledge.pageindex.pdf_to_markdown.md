---
type: Wiki Summary
title: parrot.knowledge.pageindex.pdf_to_markdown
id: mod:parrot.knowledge.pageindex.pdf_to_markdown
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: PDF → per-page markdown extraction for PageIndex.
relates_to:
- concept: func:parrot.knowledge.pageindex.pdf_to_markdown.build_node_markdown_map
  rel: defines
- concept: func:parrot.knowledge.pageindex.pdf_to_markdown.extract_markdown_per_page
  rel: defines
---

# `parrot.knowledge.pageindex.pdf_to_markdown`

PDF → per-page markdown extraction for PageIndex.

A thin, opinionated wrapper around
``pymupdf4llm.to_markdown(path, page_chunks=True)`` so the result lines
up with :func:`parrot.knowledge.pageindex.utils.get_page_tokens` (1-based, every
physical page represented). The output is consumed by
:func:`parrot.knowledge.pageindex.builder.build_page_index` to emit per-node
markdown via ``start_index``/``end_index`` slicing.

Choice of extractor: PageIndex already uses ``pymupdf4llm`` indirectly
via :class:`parrot_loaders.pdf.PDFLoader`. Calling it directly keeps the
page indexing aligned with ``get_page_tokens`` (no implicit reordering,
no page-filtering side effects).

## Functions

- `def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]` — Extract per-physical-page markdown from a PDF.
- `def build_node_markdown_map(structure: object, pages: list[tuple[int, str]]) -> dict[str, str]` — Walk a node tree and return ``{node_id: concatenated_markdown}``.
