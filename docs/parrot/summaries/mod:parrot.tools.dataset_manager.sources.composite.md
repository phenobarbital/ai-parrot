---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.composite
id: mod:parrot.tools.dataset_manager.sources.composite
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CompositeDataSource — virtual dataset that JOINs two or more existing datasets.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.composite.CompositeDataSource
  rel: defines
- concept: class:parrot.tools.dataset_manager.sources.composite.JoinSpec
  rel: defines
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
- concept: mod:parrot.tools.dataset_manager.tool
  rel: references
---

# `parrot.tools.dataset_manager.sources.composite`

CompositeDataSource — virtual dataset that JOINs two or more existing datasets.

Implements the ``DataSource`` ABC.  Components are materialized independently
(respecting their own caching strategy), per-component filters are applied
before the JOIN, and sequential ``pd.merge()`` calls produce the result.

Key design decisions (from spec):
- ``has_builtin_cache = True``: DatasetManager skips its Redis layer for the
  composite result.  Components are cached individually by their own sources.
- Filter propagation: a filter key is applied only to components that contain
  that column (column-existence check per component).
- ``pd.errors.MergeError`` is captured and re-raised as ``ValueError`` with
  a descriptive message.
- Circular import avoided via ``TYPE_CHECKING`` for DatasetManager reference.

## Classes

- **`JoinSpec(BaseModel)`** — Specification for joining two datasets.
- **`CompositeDataSource(DataSource)`** — Virtual DataSource that JOINs existing datasets on demand.
