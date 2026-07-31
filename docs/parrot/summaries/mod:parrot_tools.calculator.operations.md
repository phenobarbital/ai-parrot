---
type: Wiki Summary
title: parrot_tools.calculator.operations
id: mod:parrot_tools.calculator.operations
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Calculator operations module.
relates_to:
- concept: func:parrot_tools.calculator.operations.operation
  rel: defines
---

# `parrot_tools.calculator.operations`

Calculator operations module.

Each operation should be a function that:
1. Has clear type hints
2. Includes a docstring
3. Is decorated with @operation (optional, for metadata)

## Functions

- `def operation(name: str=None, description: str=None)` — Decorator to mark a function as a calculator operation.
