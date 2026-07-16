---
type: Wiki Entity
title: OutputRetryResult
id: class:parrot.outputs.formatter.OutputRetryResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Result from an output retry attempt.
---

# OutputRetryResult

Defined in [`parrot.outputs.formatter`](../summaries/mod:parrot.outputs.formatter.md).

```python
class OutputRetryResult
```

Result from an output retry attempt.

Attributes:
    success: Whether the retry produced valid output
    content: The formatted content (original or fixed)
    wrapped_content: Optional wrapped version (e.g., HTML)
    retry_count: Number of retry attempts made
    original_error: The original error that triggered retry
    final_error: The final error if all retries failed (None if success)
