---
type: Wiki Entity
title: TestStoreResult
id: class:parrot.tools.working_memory.tests.test_generic_entries.TestStoreResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: store_result() async tool method.
---

# TestStoreResult

Defined in [`parrot.tools.working_memory.tests.test_generic_entries`](../summaries/mod:parrot.tools.working_memory.tests.test_generic_entries.md).

```python
class TestStoreResult
```

store_result() async tool method.

## Methods

- `async def test_store_text(self)`
- `async def test_store_dict(self)`
- `async def test_store_list(self)`
- `async def test_store_bytes(self)`
- `async def test_store_message(self, sample_message)`
- `async def test_store_with_metadata(self)`
- `async def test_store_explicit_type(self)`
- `async def test_store_invalid_type_falls_back_to_auto(self)`
- `async def test_data_field_in_tool_schema(self)` — Regression: the LLM-facing schema must advertise `data` as required.
- `async def test_store_result_via_execute_carries_data(self)` — Regression: `data` must survive the execute() validation pipeline.
