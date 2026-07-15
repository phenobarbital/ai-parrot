---
type: Concept
title: parse_compensation_data()
id: func:parrot_tools.interfaces.workday.parsers.worker_parsers.parse_compensation_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse the compensation details of the worker.
---

# parse_compensation_data

```python
def parse_compensation_data(worker_data: Dict[str, Any]) -> Dict[str, Any]
```

Parse the compensation details of the worker.

Extracts:
  - wage (float)
  - compensation_effective_date (str)
  - compensation_guidelines (package / grade / profile IDs)
  - salary_and_hourly (list of elements)
  - compensation_summary (nested summary)
  - reason_references (mapping of reason type → ID)
