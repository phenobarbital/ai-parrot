---
type: Wiki Entity
title: DispatchOutputValidationError
id: class:parrot.flows.dev_loop.dispatcher.DispatchOutputValidationError
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Raised when the final ResultMessage payload fails to validate.
---

# DispatchOutputValidationError

Defined in [`parrot.flows.dev_loop.dispatcher`](../summaries/mod:parrot.flows.dev_loop.dispatcher.md).

```python
class DispatchOutputValidationError(Exception)
```

Raised when the final ResultMessage payload fails to validate.

Attributes:
    raw_payload: The concatenated assistant text that failed
        ``output_model.model_validate_json``. Surfaced so the
        audit log / failure handler can capture it verbatim.
