---
type: Concept
title: resolve_class()
id: func:parrot.tools.discovery.resolve_class
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Resolve a dotted path string to an actual class.
---

# resolve_class

```python
def resolve_class(dotted_path: str) -> Type
```

Resolve a dotted path string to an actual class.

Args:
    dotted_path: e.g., "parrot_tools.jira.toolkit.JiraToolkit"

Returns:
    The class object
