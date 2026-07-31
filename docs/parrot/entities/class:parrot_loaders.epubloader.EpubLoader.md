---
type: Wiki Entity
title: EpubLoader
id: class:parrot_loaders.epubloader.EpubLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: EPUB loader that extracts clean Markdown (or plain text) from chapters/sections.
relates_to:
- concept: class:parrot.loaders.abstract.AbstractLoader
  rel: extends
---

# EpubLoader

Defined in [`parrot_loaders.epubloader`](../summaries/mod:parrot_loaders.epubloader.md).

```python
class EpubLoader(AbstractLoader)
```

EPUB loader that extracts clean Markdown (or plain text) from chapters/sections.

Features:
- Per-chapter documents with titles from TOC/HTML
- Optional full-book document (merged)
- Clean Markdown conversion (lists, headers, links)
- Skips non-document items (css, images, fonts)
- Configurable minimum content length
