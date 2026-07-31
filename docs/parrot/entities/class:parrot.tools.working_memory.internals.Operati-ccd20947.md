---
type: Wiki Entity
title: OperationExecutor
id: class:parrot.tools.working_memory.internals.OperationExecutor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Executes OperationSpecInput against DataFrames from the catalog.
---

# OperationExecutor

Defined in [`parrot.tools.working_memory.internals`](../summaries/mod:parrot.tools.working_memory.internals.md).

```python
class OperationExecutor
```

Executes OperationSpecInput against DataFrames from the catalog.

Purely deterministic — no LLM calls, no free-form code execution.
Each operation type is dispatched to a dedicated handler method.

## Methods

- `def execute(self, spec: OperationSpecInput, catalog: dict[str, CatalogEntry]) -> pd.DataFrame` — Dispatch the operation spec to the appropriate handler.
