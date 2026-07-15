---
type: Concept
title: numerical_derivative()
id: func:parrot_tools.calculator.operations.calculus.numerical_derivative
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Calculate numerical derivative using central difference.
---

# numerical_derivative

```python
def numerical_derivative(expression: str=None, x: float=None, h: float=1e-05, **kwargs) -> float
```

Calculate numerical derivative using central difference.

Args:
    expression: Python expression as string (e.g., "x**2 + 3*x")
    x: Point at which to evaluate derivative
    h: Step size for numerical differentiation
