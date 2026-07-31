---
type: Wiki Entity
title: ExtractJsonLd
id: class:parrot_tools.scraping.models.ExtractJsonLd
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Extract structured data from JSON-LD blocks on the current page.
relates_to:
- concept: class:parrot_tools.scraping.models.BrowserAction
  rel: extends
---

# ExtractJsonLd

Defined in [`parrot_tools.scraping.models`](../summaries/mod:parrot_tools.scraping.models.md).

```python
class ExtractJsonLd(BrowserAction)
```

Extract structured data from JSON-LD blocks on the current page.

Iterates every ``<script type="application/ld+json">`` block, walks
the JSON graph (descending into ``@graph`` and arrays), and dispatches
typed nodes through the shared ``EXTRACTOR_REGISTRY`` from
``parrot.utils.jsonld_extractors``. Result is a flat list of dicts,
one per extracted ``JsonLdItem``, written to
``step_extracted[extract_name]``.

Two filtering modes:
- ``types=None`` (default): extract every registered ``@type``.
- ``types=["Product", "Recipe"]``: only those types.
