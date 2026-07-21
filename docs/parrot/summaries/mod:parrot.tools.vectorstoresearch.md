---
type: Wiki Summary
title: parrot.tools.vectorstoresearch
id: mod:parrot.tools.vectorstoresearch
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: VectorStoreSearchTool - A tool for performing similarity search on vector
  stores.
relates_to:
- concept: class:parrot.tools.vectorstoresearch.VectorSearchArgs
  rel: defines
- concept: class:parrot.tools.vectorstoresearch.VectorStoreSearchTool
  rel: defines
- concept: mod:parrot.models.stores
  rel: references
- concept: mod:parrot.stores
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.tools.vectorstoresearch`

VectorStoreSearchTool - A tool for performing similarity search on vector stores.

This tool accepts a StoreConfig to configure the vector store and performs
similarity searches based on user queries.

## Classes

- **`VectorSearchArgs(AbstractToolArgsSchema)`** — Arguments schema for VectorStoreSearchTool.
- **`VectorStoreSearchTool(AbstractTool)`** — A tool for performing similarity search on vector stores.
