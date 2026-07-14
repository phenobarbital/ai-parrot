---
type: Concept
title: parse_retry_after()
id: func:parrot.mcp.client.parse_retry_after
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Normalize a server-provided retry hint into seconds-from-now.
---

# parse_retry_after

```python
def parse_retry_after(value: Any, *, now: Optional[float]=None) -> Optional[float]
```

Normalize a server-provided retry hint into seconds-from-now.

Servers are inconsistent about how they express ``retryAfter``. This
accepts the three common forms and always returns a non-negative delay in
seconds (or ``None`` when the value is missing/uninterpretable):

  * plain delay in seconds (HTTP ``Retry-After`` style): ``5``, ``2.5``
  * absolute epoch **seconds**: ``1782259200``
  * absolute epoch **milliseconds**: ``1782259200009`` (e.g. Fireflies)

Args:
    value: The raw ``retryAfter`` value from the error payload.
    now: Override for the current epoch seconds (testing hook).

Returns:
    Seconds to wait before retrying, clamped to ``>= 0``, or ``None``.
