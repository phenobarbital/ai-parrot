---
type: Wiki Summary
title: parrot.tools.dataset_manager.filtering.compiler
id: mod:parrot.tools.dataset_manager.filtering.compiler
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Filter Compiler for FEAT-225 Module 3.
relates_to:
- concept: class:parrot.tools.dataset_manager.filtering.compiler.FilterCompiler
  rel: defines
- concept: mod:parrot.tools.dataset_manager.filtering.contracts
  rel: references
---

# `parrot.tools.dataset_manager.filtering.compiler`

Filter Compiler for FEAT-225 Module 3.

Translates a :class:`FilterCondition` into either:

- A **SQL WHERE fragment** (for SQL-backed ``TableSource`` / ``QuerySlugSource``
  datasets), following the same predicate style used by
  ``TableSource._build_filter_clause``.
- A **pandas boolean mask** (for in-memory DataFrame datasets).

Both ``compile_where`` and ``compile_pandas`` are deterministic and I/O-free.
Execution — iterating datasets and deciding which path to take — is the
responsibility of :meth:`DatasetManager.apply_filters` (TASK-1467).

Note: ``from __future__ import annotations`` is intentionally omitted so that
Pydantic v2 resolves type hints at class-definition time without a manual
``model_rebuild()`` call.

Classes:
    FilterCompiler: Stateless compiler for FilterCondition → SQL / pandas.

## Classes

- **`FilterCompiler`** — Stateless compiler that translates FilterCondition to SQL or pandas.
