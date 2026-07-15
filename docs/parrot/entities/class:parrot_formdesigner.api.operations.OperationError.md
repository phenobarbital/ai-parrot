---
type: Wiki Entity
title: OperationError
id: class:parrot_formdesigner.api.operations.OperationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Per-op apply failure carried back to the HTTP layer.
---

# OperationError

Defined in [`parrot_formdesigner.api.operations`](../summaries/mod:parrot_formdesigner.api.operations.md).

```python
class OperationError(Exception)
```

Per-op apply failure carried back to the HTTP layer.

Attributes:
    index: 0-based index of the failing op within the envelope.
    op_name: Discriminator value (e.g., ``"add_field"``).
    message: Human-readable reason.
