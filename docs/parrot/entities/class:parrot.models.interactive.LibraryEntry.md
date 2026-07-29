---
type: Wiki Entity
title: LibraryEntry
id: class:parrot.models.interactive.LibraryEntry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single vetted JavaScript library the LLM may use in an artifact.
---

# LibraryEntry

Defined in [`parrot.models.interactive`](../summaries/mod:parrot.models.interactive.md).

```python
class LibraryEntry(BaseModel)
```

A single vetted JavaScript library the LLM may use in an artifact.

The library's delivery is described by ``bundle`` (a CDN ``<script>`` with
SRI, or an inline source block). Some libraries also ship a stylesheet —
captured by the optional ``css_bundle`` (a ``JSBundle`` whose ``url`` points
at a ``.css`` file). Both bundles flow into the enhance allow-list and the
CSP ``script-src`` / ``style-src`` directives.

``usage_snippet`` and ``ts_types`` are *reference material* for the LLM: the
snippet shows idiomatic usage and ``ts_types`` documents the API shape. They
are never executed or compiled — the LLM emits plain JavaScript.

## Methods

- `def bundles(self) -> List[JSBundle]` — Return all bundles (script + optional stylesheet) for allow-listing.
- `def to_prompt_entry(self) -> str` — Render this library as a compact prompt block for the catalog index.
