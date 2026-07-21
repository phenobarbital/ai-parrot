---
type: Wiki Summary
title: parrot.tools.dataset_manager.filtering.contracts
id: mod:parrot.tools.dataset_manager.filtering.contracts
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pure Pydantic contracts for common-field filtering (FEAT-225 Module 1).
relates_to:
- concept: class:parrot.tools.dataset_manager.filtering.contracts.FilterCondition
  rel: defines
- concept: class:parrot.tools.dataset_manager.filtering.contracts.FilterDefinition
  rel: defines
- concept: class:parrot.tools.dataset_manager.filtering.contracts.FilterResult
  rel: defines
- concept: class:parrot.tools.dataset_manager.filtering.contracts.ValuesSource
  rel: defines
---

# `parrot.tools.dataset_manager.filtering.contracts`

Pure Pydantic contracts for common-field filtering (FEAT-225 Module 1).

These are I/O-free data models. They carry no driver, DSN, or SQL
information — the FilterCompiler and DatasetManager methods consume them.

Classes:
    ValuesSource: Specifies where to obtain distinct values for a filter.
    FilterDefinition: Declarative filter definition stored on a DatasetManager.
    FilterCondition: A single applied condition within a filter request.
    FilterResult: Per-run outcome recording applied/skipped datasets.

Note: ``from __future__ import annotations`` is intentionally omitted here to
ensure Pydantic v2 can resolve Literal annotations at class definition time
without requiring a manual ``model_rebuild()`` call.

## Classes

- **`ValuesSource(BaseModel)`** — Specifies where to obtain the distinct values for a frontend combo.
- **`FilterDefinition(BaseModel)`** — A declarative common-field filter definition stored on a DatasetManager.
- **`FilterCondition(BaseModel)`** — A single applied condition within a filter request.
- **`FilterResult(BaseModel)`** — Records the per-run outcome of ``DatasetManager.apply_filters``.
