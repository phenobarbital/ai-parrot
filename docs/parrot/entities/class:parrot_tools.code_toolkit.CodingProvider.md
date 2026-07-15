---
type: Wiki Entity
title: CodingProvider
id: class:parrot_tools.code_toolkit.CodingProvider
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Provider protocol implemented by coding backends.
---

# CodingProvider

Defined in [`parrot_tools.code_toolkit`](../summaries/mod:parrot_tools.code_toolkit.md).

```python
class CodingProvider(Protocol)
```

Provider protocol implemented by coding backends.

## Methods

- `async def run_task(self, task: CodingTask, model: str | None=None) -> CodingTaskResult` — Run a coding task and return a structured result.
