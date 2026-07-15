---
type: Concept
title: ensure_observability_bootstrapped()
id: func:parrot.observability.bootstrap.ensure_observability_bootstrapped
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Activate env-driven observability exactly once. Safe to call repeatedly.
---

# ensure_observability_bootstrapped

```python
def ensure_observability_bootstrapped() -> None
```

Activate env-driven observability exactly once. Safe to call repeatedly.

No-op (after recording the decision) when ``OBSERVABILITY_ENABLED`` is not
truthy. Never raises: any failure is logged at DEBUG and swallowed so it can
never break bot/client construction.
