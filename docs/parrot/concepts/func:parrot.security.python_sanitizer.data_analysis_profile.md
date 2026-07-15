---
type: Concept
title: data_analysis_profile()
id: func:parrot.security.python_sanitizer.data_analysis_profile
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return the data-analysis execution policy.
---

# data_analysis_profile

```python
def data_analysis_profile() -> PythonExecutionPolicy
```

Return the data-analysis execution policy.

Widens the allowlist for pandas/numpy compute on already-materialised
DataFrames injected via REPL locals.  File / network IO remains denied.

Returns:
    ``PythonExecutionPolicy`` with a broader but still restricted import
    allowlist.
