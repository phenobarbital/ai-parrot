---
type: Wiki Entity
title: PDFTablesLoader
id: class:parrot_loaders.pdftables.PDFTablesLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specialized loader for extracting tables from PDF files.
relates_to:
- concept: class:parrot_loaders.basepdf.BasePDF
  rel: extends
---

# PDFTablesLoader

Defined in [`parrot_loaders.pdftables`](../summaries/mod:parrot_loaders.pdftables.md).

```python
class PDFTablesLoader(BasePDF)
```

Specialized loader for extracting tables from PDF files.

This loader focuses on table extraction with multiple backends:
1. PyMuPDF (fitz) with configurable table detection settings
2. MarkItDown for universal table extraction (optional)

Supports output formats:
- JSON (via pandas DataFrame serialization)
- Markdown table format
- Raw table data (list of lists)

## Methods

- `def get_table_settings(self) -> Dict[str, Any]` — Get current table extraction settings.
- `def update_table_settings(self, **settings)` — Update table extraction settings.
- `def get_supported_backends(self) -> List[str]` — Get list of available backends.
