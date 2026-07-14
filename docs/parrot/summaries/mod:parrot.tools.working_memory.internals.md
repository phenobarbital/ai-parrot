---
type: Wiki Summary
title: parrot.tools.working_memory.internals
id: mod:parrot.tools.working_memory.internals
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Internal engine classes for WorkingMemoryToolkit.
relates_to:
- concept: class:parrot.tools.working_memory.internals.CatalogEntry
  rel: defines
- concept: class:parrot.tools.working_memory.internals.GenericEntry
  rel: defines
- concept: class:parrot.tools.working_memory.internals.OperationExecutor
  rel: defines
- concept: class:parrot.tools.working_memory.internals.ShapeLimit
  rel: defines
- concept: class:parrot.tools.working_memory.internals.WorkingMemoryCatalog
  rel: defines
- concept: mod:parrot.tools.working_memory.models
  rel: references
---

# `parrot.tools.working_memory.internals`

Internal engine classes for WorkingMemoryToolkit.

Contains catalog storage, operation execution, and shape limiting components.
These are internal implementation details — consumers should use WorkingMemoryToolkit
from the package directly.

## Classes

- **`GenericEntry`** — Catalog entry for non-DataFrame data.
- **`CatalogEntry`** — Metadata and data container for a stored DataFrame in the catalog.
- **`OperationExecutor`** — Executes OperationSpecInput against DataFrames from the catalog.
- **`ShapeLimit`** — Maximum shape constraint for summaries returned to the LLM.
- **`WorkingMemoryCatalog`** — In-memory catalog of DataFrames and generic entries.
