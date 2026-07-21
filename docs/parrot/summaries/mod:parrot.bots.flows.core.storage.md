---
type: Wiki Summary
title: parrot.bots.flows.core.storage
id: mod:parrot.bots.flows.core.storage
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Flow Primitives — Storage Sub-package.
relates_to:
- concept: mod:parrot.bots.flows.core
  rel: references
---

# `parrot.bots.flows.core.storage`

Flow Primitives — Storage Sub-package.

Provides storage mixins and execution memory, migrated from
``parrot.bots.flow.storage`` into the shared core location.

Re-exports:
    ExecutionMemory — in-memory execution history with optional FAISS indexing.
    VectorStoreMixin — FAISS vector store mixin.
    PersistenceMixin — DocumentDB persistence mixin.
    SynthesisMixin — LLM-based result synthesis mixin.
    synthesize_results — top-level async util for LLM result synthesis (FEAT-163).
    CrewExecutionDocument — deterministic, LLM-free consolidated execution
        record (FEAT-306).
