---
type: Concept
title: generate_envelope()
id: func:parrot.outputs.a2ui.producer.generate_envelope
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Produce a catalog-valid display ``CreateSurface`` via a bounded retry loop.
---

# generate_envelope

```python
async def generate_envelope(client: 'AbstractClient', prompt: str, *, catalog: Any=None, max_attempts: int=DEFAULT_MAX_ATTEMPTS, model: str='', system_prompt: Optional[str]=None) -> ProducerResult
```

Produce a catalog-valid display ``CreateSurface`` via a bounded retry loop.

Args:
    client: An ``AbstractClient`` exposing ``async ask(...)`` (passed in — not imported).
    prompt: The display-UI request.
    catalog: Reserved for a future per-catalog override; the global catalog is used.
    max_attempts: Total ``ask()`` attempts (default from SPK-3: 3).
    model: Model id forwarded to ``client.ask``.
    system_prompt: Optional base system prompt; the catalog instructions are appended.

Returns:
    A :class:`ProducerResult` — either a validated envelope or a plain-text degradation.
