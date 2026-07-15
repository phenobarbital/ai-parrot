---
type: Wiki Summary
title: parrot.tools.working_memory.models
id: mod:parrot.tools.working_memory.models
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Enums and Pydantic input models for WorkingMemoryToolkit DSL.
relates_to:
- concept: class:parrot.tools.working_memory.models.AggFunc
  rel: defines
- concept: class:parrot.tools.working_memory.models.ComputeAndStoreInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.DropStoredInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.EntryType
  rel: defines
- concept: class:parrot.tools.working_memory.models.FilterSpec
  rel: defines
- concept: class:parrot.tools.working_memory.models.GetResultInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.GetStoredInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.ImportFromToolInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.JoinHow
  rel: defines
- concept: class:parrot.tools.working_memory.models.JoinOnSpec
  rel: defines
- concept: class:parrot.tools.working_memory.models.ListStoredInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.ListToolDataFramesInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.MergeStoredInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.OperationSpecInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.OperationType
  rel: defines
- concept: class:parrot.tools.working_memory.models.RecallInteractionInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.SaveInteractionInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.SearchStoredInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.StoreInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.StoreResultInput
  rel: defines
- concept: class:parrot.tools.working_memory.models.SummarizeStoredInput
  rel: defines
---

# `parrot.tools.working_memory.models`

Enums and Pydantic input models for WorkingMemoryToolkit DSL.

## Classes

- **`EntryType(str, Enum)`** — Discriminator for catalog entry types.
- **`OperationType(str, Enum)`** — Allowed deterministic operations the agent can request.
- **`JoinHow(str, Enum)`** — Join type options for JOIN and MERGE operations.
- **`AggFunc(str, Enum)`** — Aggregation function options for AGGREGATE, PIVOT, WINDOW, and SUMMARIZE operations.
- **`FilterSpec(BaseModel)`** — A single filter condition.
- **`JoinOnSpec(BaseModel)`** — Join key specification.
- **`OperationSpecInput(BaseModel)`** — Declarative operation specification — the DSL contract.
- **`StoreInput(BaseModel)`** — Input for storing a DataFrame directly.
- **`DropStoredInput(BaseModel)`** — Input for removing a stored DataFrame.
- **`GetStoredInput(BaseModel)`** — Input for retrieving a summary of a stored DataFrame.
- **`ListStoredInput(BaseModel)`** — Input for listing all stored entries.
- **`ComputeAndStoreInput(BaseModel)`** — Input for executing a declarative operation and storing the result.
- **`MergeStoredInput(BaseModel)`** — Input for merging multiple stored DataFrames.
- **`SummarizeStoredInput(BaseModel)`** — Input for merging + aggregating stored DataFrames.
- **`ImportFromToolInput(BaseModel)`** — Input for importing a DataFrame from another tool's namespace.
- **`ListToolDataFramesInput(BaseModel)`** — Input for listing DataFrames available in other tools.
- **`StoreResultInput(BaseModel)`** — Input for storing a generic (non-DataFrame) result into working memory.
- **`GetResultInput(BaseModel)`** — Input for retrieving a stored generic result.
- **`SearchStoredInput(BaseModel)`** — Input for searching stored entries by key/description substring or type.
- **`SaveInteractionInput(BaseModel)`** — Input for saving a Q&A interaction to AnswerMemory.
- **`RecallInteractionInput(BaseModel)`** — Input for recalling a Q&A interaction from AnswerMemory.
