---
type: Wiki Entity
title: JSONLDatasetLoader
id: class:parrot.eval.datasets.JSONLDatasetLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load an ``EvalDataset`` from a JSONL file.
relates_to:
- concept: class:parrot.eval.datasets.DatasetLoader
  rel: extends
---

# JSONLDatasetLoader

Defined in [`parrot.eval.datasets`](../summaries/mod:parrot.eval.datasets.md).

```python
class JSONLDatasetLoader(DatasetLoader)
```

Load an ``EvalDataset`` from a JSONL file.

Each non-empty line must be a JSON object that validates as an
``EvalTask``.  The dataset name defaults to the filename stem.

Malformed records raise ``pydantic.ValidationError`` immediately —
no silent skipping.

## Methods

- `async def load(self, source: str) -> EvalDataset` — Load *source* (a JSONL file path) into an ``EvalDataset``.
