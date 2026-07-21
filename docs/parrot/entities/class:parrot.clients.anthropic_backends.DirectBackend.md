---
type: Wiki Entity
title: DirectBackend
id: class:parrot.clients.anthropic_backends.DirectBackend
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Backend strategy for the direct Anthropic API (``AsyncAnthropic``).
---

# DirectBackend

Defined in [`parrot.clients.anthropic_backends`](../summaries/mod:parrot.clients.anthropic_backends.md).

```python
class DirectBackend
```

Backend strategy for the direct Anthropic API (``AsyncAnthropic``).

This reproduces the current ``get_client()`` behaviour so that adding
``backend`` to ``AnthropicClient`` is a no-op when ``backend="direct"``.

Args:
    api_key: Anthropic API key.  Pass ``None`` to let the SDK read the
        ``ANTHROPIC_API_KEY`` environment variable.

## Methods

- `async def build_client(self) -> 'AsyncAnthropic'` — Build and return an ``AsyncAnthropic`` SDK client.
- `def translate_model(self, model: str) -> str` — Identity — direct API uses public model IDs unchanged.
