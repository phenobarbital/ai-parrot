---
type: Concept
title: coalesce()
id: func:parrot_tools.interfaces.workday.parsers.job_posting_parsers.coalesce
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the first non-None value from the arguments.
---

# coalesce

```python
def coalesce(*args)
```

Return the first non-None value from the arguments.
Unlike `or`, this properly handles falsy values like 0 and False.
