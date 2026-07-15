---
type: Wiki Entity
title: InvokeResult
id: class:parrot.models.responses.InvokeResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Lightweight result from a stateless invoke() call.
---

# InvokeResult

Defined in [`parrot.models.responses`](../summaries/mod:parrot.models.responses.md).

```python
class InvokeResult(BaseModel)
```

Lightweight result from a stateless invoke() call.

Returned by ``AbstractClient.invoke()`` instead of the heavier
``AIMessage``. Carries only what is needed for structured extraction:
the parsed output, the type class, model name, token usage, and the
raw provider response for debugging.

Attributes:
    output: Parsed result — Pydantic model instance, dataclass, or raw str.
    output_type: The type class used for structured output (stores the class
        itself so callers can use ``isinstance`` checks).
    model: Model identifier used for this invocation.
    usage: Token usage statistics.
    raw_response: Provider's raw response object, kept for debugging.
