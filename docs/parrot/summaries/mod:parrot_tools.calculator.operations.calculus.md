---
type: Wiki Summary
title: parrot_tools.calculator.operations.calculus
id: mod:parrot_tools.calculator.operations.calculus
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Calculus operations.
relates_to:
- concept: func:parrot_tools.calculator.operations.calculus.numerical_derivative
  rel: defines
- concept: func:parrot_tools.calculator.operations.calculus.numerical_integral
  rel: defines
- concept: mod:parrot_tools.calculator.operations
  rel: references
---

# `parrot_tools.calculator.operations.calculus`

Calculus operations.

## Functions

- `def numerical_derivative(expression: str=None, x: float=None, h: float=1e-05, **kwargs) -> float` — Calculate numerical derivative using central difference.
- `def numerical_integral(expression: str=None, a: float=None, b: float=None, n: int=1000, **kwargs) -> float` — Calculate numerical integral using Simpson's rule.
