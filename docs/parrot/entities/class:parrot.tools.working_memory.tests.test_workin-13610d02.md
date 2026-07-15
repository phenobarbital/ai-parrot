---
type: Wiki Entity
title: TestPydanticValidation
id: class:parrot.tools.working_memory.tests.test_working_memory.TestPydanticValidation
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Ensures the DSL contract rejects malformed inputs.
---

# TestPydanticValidation

Defined in [`parrot.tools.working_memory.tests.test_working_memory`](../summaries/mod:parrot.tools.working_memory.tests.test_working_memory.md).

```python
class TestPydanticValidation
```

Ensures the DSL contract rejects malformed inputs.

## Methods

- `def test_valid_filter_spec(self)`
- `def test_valid_aggregate_spec(self)`
- `def test_valid_join_spec(self)`
- `def test_invalid_op_rejected(self)`
- `def test_invalid_join_how_rejected(self)`
- `def test_invalid_agg_func_rejected(self)`
- `def test_compute_input_model(self)` — Validates the full ComputeAndStoreInput wrapper.
- `def test_merge_input_model(self)`
- `def test_summarize_input_model(self)`
