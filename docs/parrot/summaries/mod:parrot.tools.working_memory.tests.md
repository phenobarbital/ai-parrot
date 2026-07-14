---
type: Wiki Summary
title: parrot.tools.working_memory.tests
id: mod:parrot.tools.working_memory.tests
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tests for WorkingMemoryToolkit v2 (AbstractToolkit-compatible).
relates_to:
- concept: class:parrot.tools.working_memory.tests.TestAsyncMethods
  rel: defines
- concept: class:parrot.tools.working_memory.tests.TestErrorHandling
  rel: defines
- concept: class:parrot.tools.working_memory.tests.TestFullWorkflow
  rel: defines
- concept: class:parrot.tools.working_memory.tests.TestImportFromTool
  rel: defines
- concept: class:parrot.tools.working_memory.tests.TestMergeAndSummarize
  rel: defines
- concept: class:parrot.tools.working_memory.tests.TestPydanticValidation
  rel: defines
- concept: mod:parrot.tools.working_memory.tool
  rel: references
---

# `parrot.tools.working_memory.tests`

Tests for WorkingMemoryToolkit v2 (AbstractToolkit-compatible).

Validates:
  - Pydantic input validation
  - Async method execution
  - Full workflow: store → compute → merge → summarize → import
  - Error handling with catalog persistence
  - DSL validation rejects malformed specs

## Classes

- **`TestPydanticValidation`** — Ensures the DSL contract rejects malformed inputs.
- **`TestAsyncMethods`** — Tests the async tool methods that AbstractToolkit will discover.
- **`TestErrorHandling`**
- **`TestMergeAndSummarize`**
- **`TestImportFromTool`**
- **`TestFullWorkflow`**

## Functions

- `def census_df()`
- `def sales_df()`
- `def toolkit(census_df, sales_df)`
