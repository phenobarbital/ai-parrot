---
type: Wiki Entity
title: TestDetectEntryType
id: class:parrot.tools.working_memory.tests.test_generic_entries.TestDetectEntryType
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Auto-detection heuristic for Python objects.
---

# TestDetectEntryType

Defined in [`parrot.tools.working_memory.tests.test_generic_entries`](../summaries/mod:parrot.tools.working_memory.tests.test_generic_entries.md).

```python
class TestDetectEntryType
```

Auto-detection heuristic for Python objects.

## Methods

- `def test_str_is_text(self)`
- `def test_bytes_is_binary(self)`
- `def test_dict_is_json(self)`
- `def test_list_is_json(self)`
- `def test_message_duck_type(self)`
- `def test_dataframe(self)`
- `def test_fallback_int(self)`
- `def test_fallback_none(self)`
