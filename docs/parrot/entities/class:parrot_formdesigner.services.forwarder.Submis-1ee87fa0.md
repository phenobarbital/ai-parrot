---
type: Wiki Entity
title: SubmissionForwarder
id: class:parrot_formdesigner.services.forwarder.SubmissionForwarder
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Forward form submission data to configured SubmitAction endpoints.
---

# SubmissionForwarder

Defined in [`parrot_formdesigner.services.forwarder`](../summaries/mod:parrot_formdesigner.services.forwarder.md).

```python
class SubmissionForwarder
```

Forward form submission data to configured SubmitAction endpoints.

Uses ``aiohttp.ClientSession`` for all HTTP requests. Auth headers are
resolved via ``submit_action.auth.resolve()`` if auth is configured.

Attributes:
    DEFAULT_TIMEOUT: Default request timeout in seconds (30).
    timeout: Configured timeout for this forwarder instance.

Args:
    timeout: Request timeout in seconds. Defaults to ``DEFAULT_TIMEOUT``.

## Methods

- `async def forward(self, data: dict[str, Any], submit_action: SubmitAction) -> ForwardResult` — Forward submission data to the endpoint configured in ``submit_action``.
