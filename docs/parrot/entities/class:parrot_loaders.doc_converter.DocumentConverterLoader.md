---
type: Wiki Entity
title: DocumentConverterLoader
id: class:parrot_loaders.doc_converter.DocumentConverterLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load PDF, DOCX, and PPTX files using Docling and return Document objects.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# DocumentConverterLoader

Defined in [`parrot_loaders.doc_converter`](../summaries/mod:parrot_loaders.doc_converter.md).

```python
class DocumentConverterLoader(AbstractLoader)
```

Load PDF, DOCX, and PPTX files using Docling and return Document objects.

Converts documents to markdown internally, then builds ``Document`` objects
using the same helpers as :class:`AbstractLoader`.

Supports local paths and URLs — Docling handles both natively.
