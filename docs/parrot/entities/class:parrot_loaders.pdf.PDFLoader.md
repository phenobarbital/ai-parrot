---
type: Wiki Entity
title: PDFLoader
id: class:parrot_loaders.pdf.PDFLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Advanced PDF Loader using PyMuPDF (fitz).
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# PDFLoader

Defined in [`parrot_loaders.pdf`](../summaries/mod:parrot_loaders.pdf.md).

```python
class PDFLoader(AbstractLoader)
```

Advanced PDF Loader using PyMuPDF (fitz).
- Skips image-only pages.
- Combines title-only pages with next content page.
- Preserves tables as text for chatbot/RAG KB usage.
- Returns a Parrot Document per logical page.
- Supports chapter-based splitting for markdown output.

## Methods

- `def is_title_only(self, text: str, min_len: int=5, max_len: int=50) -> bool` — Check if text looks like a title (short, single line, large font).
- `def is_image_only(self, page: fitz.Page) -> bool` — Return True if the page only contains images (no visible text).
- `def is_table_like(self, text: str) -> bool` — Naive check: Table if lines have multiple columns (lots of |, tab, or spaces).
- `def extract_table(self, page: fitz.Page) -> Optional[str]` — Attempt to extract table structure, return as markdown if detected, else None.
- `def extract_chapters_from_markdown(self, md_text: str) -> List[dict]` — Extract chapters from markdown text based on headers.
- `def extract_pages_from_markdown(self, md_text: str) -> List[dict]` — Extract pages from markdown text based on page separators.
