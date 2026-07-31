---
type: Wiki Entity
title: TestOffloadRouting
id: class:parrot.tools.working_memory.tests.test_thread_offload.TestOffloadRouting
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Class TestOffloadRouting in parrot.tools.working_memory.tests.test_thread_offload
---

# TestOffloadRouting

Defined in [`parrot.tools.working_memory.tests.test_thread_offload`](../summaries/mod:parrot.tools.working_memory.tests.test_thread_offload.md).

```python
class TestOffloadRouting
```

## Methods

- `async def test_store_large_frame_offloads(self, spy)`
- `async def test_store_small_frame_runs_inline(self, spy)`
- `async def test_offload_summary_matches_inline_summary(self)` — The offloaded summary must be byte-for-byte the same as the inline one.
- `async def test_get_stored_large_offloads(self, spy)`
- `async def test_import_from_tool_large_offloads_copy_and_summary(self, spy)`
- `async def test_compute_and_store_large_offloads(self, spy)`
- `async def test_merge_stored_large_offloads(self, spy)`
- `async def test_list_stored_offloads_when_any_entry_large(self, spy)`
- `async def test_list_stored_inline_when_all_small(self, spy)`
- `async def test_search_stored_large_offloads_and_matches(self, spy)`
