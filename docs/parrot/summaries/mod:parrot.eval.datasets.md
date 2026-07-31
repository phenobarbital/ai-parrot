---
type: Wiki Summary
title: parrot.eval.datasets
id: mod:parrot.eval.datasets
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dataset loaders for the Generic Agent Evaluation Harness.
relates_to:
- concept: class:parrot.eval.datasets.DatasetLoader
  rel: defines
- concept: class:parrot.eval.datasets.HFDatasetLoader
  rel: defines
- concept: class:parrot.eval.datasets.JSONLDatasetLoader
  rel: defines
- concept: class:parrot.eval.datasets.YAMLDatasetLoader
  rel: defines
- concept: mod:parrot.eval.models
  rel: references
---

# `parrot.eval.datasets`

Dataset loaders for the Generic Agent Evaluation Harness.

FEAT-217 — Module 8.

A distinct ``DatasetLoader`` ABC is used instead of ``AbstractLoader``
(which produces ``List[Document]`` — wrong contract for eval tasks; see
spec §1 Non-Goals).

Provided implementations:
- ``JSONLDatasetLoader`` — one JSON object per line → ``EvalTask``.
- ``YAMLDatasetLoader`` — YAML doc with ``name`` + ``tasks: [...]``.
- ``HFDatasetLoader`` — stub; raises ``NotImplementedError`` (HF ingest
  is out of scope for this feature).

## Classes

- **`DatasetLoader(ABC)`** — Abstract loader that reads a benchmark file into an ``EvalDataset``.
- **`JSONLDatasetLoader(DatasetLoader)`** — Load an ``EvalDataset`` from a JSONL file.
- **`YAMLDatasetLoader(DatasetLoader)`** — Load an ``EvalDataset`` from a YAML file.
- **`HFDatasetLoader(DatasetLoader)`** — Reserved stub for Hugging Face dataset ingest.
