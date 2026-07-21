---
type: Wiki Entity
title: PDFMarkdownLoader
id: class:parrot_loaders.pdfmark.PDFMarkdownLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Loader for PDF files converted content to markdown.
relates_to:
- concept: class:parrot_loaders.basepdf.BasePDF
  rel: extends
---

# PDFMarkdownLoader

Defined in [`parrot_loaders.pdfmark`](../summaries/mod:parrot_loaders.pdfmark.md).

```python
class PDFMarkdownLoader(BasePDF)
```

Loader for PDF files converted content to markdown.

This loader supports multiple backends for PDF to markdown conversion:
1. MarkItDown (Microsoft's universal document converter)
2. pymupdf4llm (PyMuPDF's markdown converter)
3. Fallback manual conversion using PyMuPDF

## Methods

- `def get_supported_backends(self) -> List[str]` — Get list of available conversion backends.
