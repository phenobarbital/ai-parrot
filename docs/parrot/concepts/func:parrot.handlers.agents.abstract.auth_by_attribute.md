---
type: Concept
title: auth_by_attribute()
id: func:parrot.handlers.agents.abstract.auth_by_attribute
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Ensure the request is authenticated *and* the user belongs
---

# auth_by_attribute

```python
def auth_by_attribute(allowed: Sequence[str], attribute: str='job_code') -> Callable[[Callable[..., Awaitable]], Callable[..., Awaitable]]
```

Ensure the request is authenticated *and* the user belongs
to at least one of `allowed` Job Codes.
