---
type: Concept
title: operation()
id: func:parrot_tools.calculator.operations.operation
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Decorator to mark a function as a calculator operation.
---

# operation

```python
def operation(name: str=None, description: str=None)
```

Decorator to mark a function as a calculator operation.

Args:
    name: Operation name (defaults to function name)
    description: Operation description (defaults to docstring)
