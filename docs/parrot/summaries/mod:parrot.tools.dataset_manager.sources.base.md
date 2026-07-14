---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.base
id: mod:parrot.tools.dataset_manager.sources.base
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: DataSource abstract base class.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.base.DataSource
  rel: defines
---

# `parrot.tools.dataset_manager.sources.base`

DataSource abstract base class.

A DataSource is a reference to data. It knows how to:
- prefetch_schema(): retrieve column names and types cheaply (no rows)
- fetch(**params): execute and return a pd.DataFrame
- describe(): produce a human-readable string for the LLM
- cache_key: a stable, unique string for Redis keying

Key rule: prefetch_schema must be cheap — a single metadata query, no data rows.
fetch is the expensive call, only triggered on demand.

Cache key ownership: The cache_key is owned by DataSource, not by the agent name.
Two different agents registering the same source (e.g. same QuerySlugSource slug)
will share the same Redis cache entry.

## Classes

- **`DataSource(ABC)`** — Abstract base for all data sources.
