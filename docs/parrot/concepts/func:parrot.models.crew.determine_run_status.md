---
type: Concept
title: determine_run_status()
id: func:parrot.models.crew.determine_run_status
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Compute the overall status for a crew execution.
---

# determine_run_status

```python
def determine_run_status(success_count: int, failure_count: int) -> Literal['completed', 'partial', 'failed']
```

Compute the overall status for a crew execution.
