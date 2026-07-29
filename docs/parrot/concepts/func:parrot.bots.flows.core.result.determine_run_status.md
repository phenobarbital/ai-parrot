---
type: Concept
title: determine_run_status()
id: func:parrot.bots.flows.core.result.determine_run_status
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Compute the overall status for a crew/flow execution.
---

# determine_run_status

```python
def determine_run_status(success_count: int, failure_count: int) -> Literal['completed', 'partial', 'failed']
```

Compute the overall status for a crew/flow execution.

Args:
    success_count: Number of nodes that completed successfully.
    failure_count: Number of nodes that failed.

Returns:
    - ``"completed"`` if no failures (including the ``(0, 0)`` case where
      no nodes ran — callers that consider an empty run an error should
      check ``success_count > 0`` themselves).
    - ``"failed"`` if no successes (all nodes failed).
    - ``"partial"`` if there are both successes and failures.
