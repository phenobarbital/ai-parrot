---
type: Concept
title: parse_worker_status()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_worker_status
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse worker status details (active, hire/termination dates, eligibility),
---

# parse_worker_status

```python
def parse_worker_status(worker_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse worker status details (active, hire/termination dates, eligibility),
asegurando no romper si algún _Reference es None.
