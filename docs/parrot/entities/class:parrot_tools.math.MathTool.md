---
type: Wiki Entity
title: MathTool
id: class:parrot_tools.math.MathTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A tool for performing basic arithmetic operations.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# MathTool

Defined in [`parrot_tools.math`](../summaries/mod:parrot_tools.math.md).

```python
class MathTool(AbstractTool)
```

A tool for performing basic arithmetic operations.

## Methods

- `def add(self, a: float, b: float) -> float` — Add two numbers.
- `def subtract(self, a: float, b: float) -> float` — Subtract two numbers.
- `def multiply(self, a: float, b: float) -> float` — Multiply two numbers.
- `def divide(self, a: float, b: float) -> float` — Divide two numbers.
- `def sqrt(self, a: float) -> float` — Calculate the square root of a number.
