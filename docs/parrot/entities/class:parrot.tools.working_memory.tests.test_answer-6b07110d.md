---
type: Wiki Entity
title: TestRecallByTurnId
id: class:parrot.tools.working_memory.tests.test_answer_memory_bridge.TestRecallByTurnId
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: recall_interaction() with exact turn_id lookup.
---

# TestRecallByTurnId

Defined in [`parrot.tools.working_memory.tests.test_answer_memory_bridge`](../summaries/mod:parrot.tools.working_memory.tests.test_answer_m-4c0e1fe7.md).

```python
class TestRecallByTurnId
```

recall_interaction() with exact turn_id lookup.

## Methods

- `async def test_recall_existing(self, toolkit_with_memory, answer_memory)`
- `async def test_recall_not_found(self, toolkit_with_memory)`
- `async def test_recall_no_memory(self)`
- `async def test_recall_and_import(self, toolkit_with_memory, answer_memory)`
- `async def test_recall_without_import_as(self, toolkit_with_memory, answer_memory)`
