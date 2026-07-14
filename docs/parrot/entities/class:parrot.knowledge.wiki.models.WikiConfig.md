---
type: Wiki Entity
title: WikiConfig
id: class:parrot.knowledge.wiki.models.WikiConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Configuration for a single wiki instance.
---

# WikiConfig

Defined in [`parrot.knowledge.wiki.models`](../summaries/mod:parrot.knowledge.wiki.models.md).

```python
class WikiConfig(BaseModel)
```

Configuration for a single wiki instance.

Attributes:
    wiki_name: Unique identifier / human-readable name for the wiki.
    storage_dir: Root directory where all wiki data is persisted.
    source_dir: Optional dedicated directory for raw source documents.
        Defaults to ``{storage_dir}/sources`` when omitted.
    page_categories: Ordered list of page categories that this wiki
        supports.  Defaults to all seven WikiPageCategory values.
    search_weights: Relative weighting applied to each search backend
        during combined-search score merging.  Keys must be
        ``"pageindex"`` and ``"graphindex"``; values must sum to ~1.0.
    lightweight_model: Optional model identifier for the fast CoT
        (analysis) step of TwoStepIngester.  Falls back to ``model``
        when ``None``.
    model: Optional model identifier for the heavyweight generation
        step of TwoStepIngester.
    sync_graph: When ``True``, wiki writes also mirror pages into
        GraphIndex.  Off by default — the WikiStore plane is the
        wiki's retrieval backend.
    storage_backend: ``"sqlite"`` (default; single-file ``wiki.db``)
        or ``"memory"`` (in-memory indexes + OKF markdown bundle
        directory — no SQLite dependency).

## Methods

- `def validate_search_weights(cls, v: dict[str, float]) -> dict[str, float]` — Ensure each weight is in [0, 1] and the total is approximately 1.
