---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.query_slug
id: mod:parrot.tools.dataset_manager.sources.query_slug
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: QuerySlugSource and MultiQuerySlugSource implementations.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.query_slug.MultiQuerySlugSource
  rel: defines
- concept: class:parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
---

# `parrot.tools.dataset_manager.sources.query_slug`

QuerySlugSource and MultiQuerySlugSource implementations.

Wraps the QuerySource (QS) and MultiQS patterns as proper DataSource
implementations, replacing the inline _call_qs() / _call_multiquery()
logic that previously lived in DatasetManager.

## Classes

- **`QuerySlugSource(DataSource)`** — DataSource backed by a single QuerySource slug.
- **`MultiQuerySlugSource(DataSource)`** — DataSource backed by multiple QuerySource slugs whose results are merged.
