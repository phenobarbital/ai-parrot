---
type: Concept
title: frame_ancestors_from_env()
id: func:parrot.handlers.csp.frame_ancestors_from_env
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Read ``INFOGRAPHIC_FRAME_ANCESTORS`` and normalise to space-separated.
---

# frame_ancestors_from_env

```python
def frame_ancestors_from_env(env_var: str='INFOGRAPHIC_FRAME_ANCESTORS', default: str="'self'") -> str
```

Read ``INFOGRAPHIC_FRAME_ANCESTORS`` and normalise to space-separated.

Args:
    env_var: Environment variable name.
    default: Value to use when the env var is unset or empty.

Returns:
    Space-separated ``frame-ancestors`` value, e.g.
    ``"https://a.example https://b.example"``.
