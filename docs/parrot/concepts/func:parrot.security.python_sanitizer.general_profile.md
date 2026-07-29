---
type: Concept
title: general_profile()
id: func:parrot.security.python_sanitizer.general_profile
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Return the general (tightest) execution policy.
---

# general_profile

```python
def general_profile() -> PythonExecutionPolicy
```

Return the general (tightest) execution policy.

Suitable for Jira/GitHub/tool-orchestration agents that consume data via
structured tools rather than raw REPL IO.

Returns:
    ``PythonExecutionPolicy`` with restricted import/builtin allowlists.
