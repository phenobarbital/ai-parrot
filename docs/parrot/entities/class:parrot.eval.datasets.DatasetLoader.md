---
type: Wiki Entity
title: DatasetLoader
id: class:parrot.eval.datasets.DatasetLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract loader that reads a benchmark file into an ``EvalDataset``.
---

# DatasetLoader

Defined in [`parrot.eval.datasets`](../summaries/mod:parrot.eval.datasets.md).

```python
class DatasetLoader(ABC)
```

Abstract loader that reads a benchmark file into an ``EvalDataset``.

The real ``AbstractLoader`` (``parrot.loaders``) is not reused because
it returns ``List[Document]`` — a contract that does not fit eval tasks
(spec §1 Non-Goals).

## Methods

- `async def load(self, source: str) -> EvalDataset` — Load *source* into an ``EvalDataset``.
