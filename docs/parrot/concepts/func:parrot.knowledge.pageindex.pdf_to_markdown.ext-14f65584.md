---
type: Concept
title: extract_markdown_per_page()
id: func:parrot.knowledge.pageindex.pdf_to_markdown.extract_markdown_per_page
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Extract per-physical-page markdown from a PDF.
---

# extract_markdown_per_page

```python
def extract_markdown_per_page(pdf_path: str | Path) -> list[tuple[int, str]]
```

Extract per-physical-page markdown from a PDF.

Args:
    pdf_path: Path to the source PDF on disk.

Returns:
    ``[(physical_page_1based, markdown_text), ...]`` covering every
    physical page in the document. Empty pages are emitted as
    ``(page_num, "")`` so the returned list is dense and the index
    space matches :func:`get_page_tokens`.

Raises:
    FileNotFoundError: If ``pdf_path`` does not exist.
    ImportError: If ``pymupdf`` / ``pymupdf4llm`` are not installed.
    ValueError: If the page count emitted by ``pymupdf4llm`` does
        not match ``pymupdf.open(path).page_count``. Mis-alignment
        here would silently mis-slice every downstream node.
