---
type: Concept
title: auth_groups()
id: func:parrot.handlers.agents.abstract.auth_groups
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Ensure the request is authenticated *and* the user belongs
---

# auth_groups

```python
def auth_groups(allowed: Sequence[str]) -> Callable[[Callable[..., Awaitable]], Callable[..., Awaitable]]
```

Ensure the request is authenticated *and* the user belongs
to at least one of `allowed` groups.
