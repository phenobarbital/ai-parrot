---
type: Wiki Entity
title: YAMLDatasetLoader
id: class:parrot.eval.datasets.YAMLDatasetLoader
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Load an ``EvalDataset`` from a YAML file.
relates_to:
- concept: class:parrot.eval.datasets.DatasetLoader
  rel: extends
---

# YAMLDatasetLoader

Defined in [`parrot.eval.datasets`](../summaries/mod:parrot.eval.datasets.md).

```python
class YAMLDatasetLoader(DatasetLoader)
```

Load an ``EvalDataset`` from a YAML file.

Expected structure::

    name: my-dataset
    tasks:
      - task_id: t1
        inputs:
          query: "Do X"
        expected:
          goal_state: {}

The ``name`` field defaults to the filename stem if absent.
Each entry under ``tasks`` is validated as an ``EvalTask``.

## Methods

- `async def load(self, source: str) -> EvalDataset` — Load *source* (a YAML file path) into an ``EvalDataset``.
