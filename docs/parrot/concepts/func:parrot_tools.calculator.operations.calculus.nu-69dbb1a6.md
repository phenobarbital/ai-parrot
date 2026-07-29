---
type: Concept
title: numerical_integral()
id: func:parrot_tools.calculator.operations.calculus.numerical_integral
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Calculate numerical integral using Simpson's rule.
---

# numerical_integral

```python
def numerical_integral(expression: str=None, a: float=None, b: float=None, n: int=1000, **kwargs) -> float
```

Calculate numerical integral using Simpson's rule.

Args:
    expression: Python expression as string
    a: Lower bound
    b: Upper bound
    n: Number of intervals (must be even)
