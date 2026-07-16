---
type: Wiki Entity
title: HFDatasetLoader
id: class:parrot.eval.datasets.HFDatasetLoader
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Reserved stub for Hugging Face dataset ingest.
relates_to:
- concept: class:parrot.eval.datasets.DatasetLoader
  rel: extends
---

# HFDatasetLoader

Defined in [`parrot.eval.datasets`](../summaries/mod:parrot.eval.datasets.md).

```python
class HFDatasetLoader(DatasetLoader)
```

Reserved stub for Hugging Face dataset ingest.

Full HF ingest (SWE-bench, τ-bench) is out of scope for this feature
(spec §1 Non-Goals, §7 deps table).  Install ``datasets`` from HF and
implement a subclass when needed.

## Methods

- `async def load(self, source: str) -> EvalDataset` — Not implemented — raises ``NotImplementedError``.
