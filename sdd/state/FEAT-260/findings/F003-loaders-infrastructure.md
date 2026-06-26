---
id: F003
query_id: Q003
type: read
intent: Survey document loader infrastructure for source ingestion
executed_at: 2026-06-26T00:00:00Z
duration_ms: 1800
parent_id: null
depth: 0
---

# F003 — Loaders: 20+ Format Support via AbstractLoader

## Summary

The `parrot_loaders` package (ai-parrot-loaders) provides 20+ document loaders inheriting from `AbstractLoader`. Formats include PDF (3 variants), DOCX, HTML, Excel, CSV, TXT, PowerPoint, audio, video (local + YouTube + Vimeo), web scraping, ePub, images (with LLM understanding), and database queries. The `MarkdownLoader` uses MarkItDown for universal conversion. All loaders produce `List[Document]` with metadata (source, page, section, language, etc.) and support configurable text splitting (SemanticTextSplitter, MarkdownTextSplitter, TokenTextSplitter).

## Citations

- path: `packages/ai-parrot/src/parrot/loaders/abstract.py`
  symbol: `AbstractLoader`
  excerpt: |
    class AbstractLoader(ABC):
        extensions: List[str]
        def __init__(self, source, *, chunk_size=2048, chunk_overlap=200, ...)

- path: `packages/ai-parrot-loaders/src/parrot_loaders/markdown.py`
  symbol: `MarkdownLoader`

## Notes

The loaders provide the ingestion backbone for the "Raw Sources" layer. They already produce chunked Documents with metadata — perfect for feeding into PageIndex tree construction and GraphIndex entity extraction. The gap: no "source collection" manager that tracks which sources have been ingested, their state, and triggers re-ingestion when sources change.
