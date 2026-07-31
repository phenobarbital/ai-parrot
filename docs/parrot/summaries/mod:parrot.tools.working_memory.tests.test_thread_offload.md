---
type: Wiki Summary
title: parrot.tools.working_memory.tests.test_thread_offload
id: mod:parrot.tools.working_memory.tests.test_thread_offload
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tests for the CPU-bound thread-offload optimisation in WorkingMemoryToolkit.
relates_to:
- concept: class:parrot.tools.working_memory.tests.test_thread_offload.TestGating
  rel: defines
- concept: class:parrot.tools.working_memory.tests.test_thread_offload.TestOffloadRouting
  rel: defines
- concept: func:parrot.tools.working_memory.tests.test_thread_offload.spy
  rel: defines
- concept: mod:parrot.tools.working_memory
  rel: references
- concept: mod:parrot.tools.working_memory.internals
  rel: references
---

# `parrot.tools.working_memory.tests.test_thread_offload`

Tests for the CPU-bound thread-offload optimisation in WorkingMemoryToolkit.

Large DataFrame copy/summary work (``copy(deep=True)``, ``describe``,
``memory_usage(deep=True)``) is offloaded to a worker thread via
``asyncio.to_thread`` so it does not block the event loop, while small frames
stay inline to avoid the thread-dispatch overhead.

Covers:
- ``_is_large_df`` / ``_has_large_entry`` cell-count gating.
- store / get_stored / import_from_tool / compute_and_store / merge_stored /
  summarize_stored / list_stored / search_stored route large frames through
  ``asyncio.to_thread`` but produce identical results to the inline path.
- Small frames never hit ``asyncio.to_thread``.

## Classes

- **`TestGating`**
- **`TestOffloadRouting`**

## Functions

- `def spy(monkeypatch) -> _ToThreadSpy` — Patch ``asyncio.to_thread`` as seen by the toolkit module with a spy.
