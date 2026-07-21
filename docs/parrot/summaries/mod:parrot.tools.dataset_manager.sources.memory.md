---
type: Wiki Summary
title: parrot.tools.dataset_manager.sources.memory
id: mod:parrot.tools.dataset_manager.sources.memory
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: InMemorySource — wraps an already-loaded pd.DataFrame as a DataSource.
relates_to:
- concept: class:parrot.tools.dataset_manager.sources.memory.InMemorySource
  rel: defines
- concept: mod:parrot.tools.dataset_manager.sources.base
  rel: references
---

# `parrot.tools.dataset_manager.sources.memory`

InMemorySource — wraps an already-loaded pd.DataFrame as a DataSource.

No I/O is performed; schema is derived directly from df.dtypes and fetch
returns the wrapped DataFrame unchanged.

## Classes

- **`InMemorySource(DataSource)`** — Wraps an already-loaded pd.DataFrame as a DataSource.
