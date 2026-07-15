---
type: Wiki Summary
title: parrot.tools.working_memory.tests.test_working_memory
id: mod:parrot.tools.working_memory.tests.test_working_memory
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Tests for WorkingMemoryToolkit.
relates_to:
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestAsyncMethods
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestErrorHandling
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestFullWorkflow
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestImportFromTool
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestIntegration
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestMergeAndSummarize
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_working_memory.TestPydanticValidation
  rel: defines
- concept: mod:parrot.tools.toolkit
  rel: references
- concept: mod:parrot.tools.working_memory
  rel: references
- concept: mod:parrot.tools.working_memory.models
  rel: references
---

# `parrot.tools.working_memory.tests.test_working_memory`

Tests for WorkingMemoryToolkit.

Validates:
  - Pydantic input validation
  - Async method execution
  - Full workflow: store → compute → merge → summarize → import
  - Error handling with catalog persistence
  - DSL validation rejects malformed specs
  - Integration: real AbstractToolkit inheritance and package imports

## Classes

- **`TestPydanticValidation`** — Ensures the DSL contract rejects malformed inputs.
- **`TestAsyncMethods`** — Tests the async tool methods that AbstractToolkit will discover.
- **`TestErrorHandling`**
- **`TestMergeAndSummarize`**
- **`TestImportFromTool`**
- **`TestFullWorkflow`**
- **`TestIntegration`**
