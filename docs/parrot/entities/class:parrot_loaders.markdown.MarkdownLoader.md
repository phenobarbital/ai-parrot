---
type: Wiki Entity
title: MarkdownLoader
id: class:parrot_loaders.markdown.MarkdownLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Universal Document Loader using MarkItDown library.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# MarkdownLoader

Defined in [`parrot_loaders.markdown`](../summaries/mod:parrot_loaders.markdown.md).

```python
class MarkdownLoader(AbstractLoader)
```

Universal Document Loader using MarkItDown library.

Converts various document formats to markdown and returns Document objects.
Supports:
- PDF files
- PowerPoint presentations (.pptx, .ppt)
- Word documents (.docx, .doc)
- Excel spreadsheets (.xlsx, .xls, .csv)
- HTML files
- Text-based formats (CSV, JSON, XML)
- Images with OCR (if enabled)
- Audio files (if enabled)

## Methods

- `def get_supported_formats(self) -> dict` — Get information about supported file formats.
- `def validate_file_support(self, path: Union[str, Path]) -> bool` — Check if a file is supported by MarkItDown.
- `async def convert_to_markdown(self, path: Union[str, Path]) -> str` — Convert a single file to markdown and return the content.
