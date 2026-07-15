---
type: Wiki Summary
title: parrot_tools.calculator.operations.statistics
id: mod:parrot_tools.calculator.operations.statistics
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Statistical operations.
relates_to:
- concept: func:parrot_tools.calculator.operations.statistics.calculate_correlation
  rel: defines
- concept: func:parrot_tools.calculator.operations.statistics.calculate_mean
  rel: defines
- concept: func:parrot_tools.calculator.operations.statistics.calculate_median
  rel: defines
- concept: func:parrot_tools.calculator.operations.statistics.calculate_std
  rel: defines
- concept: mod:parrot_tools.calculator.operations
  rel: references
---

# `parrot_tools.calculator.operations.statistics`

Statistical operations.

## Functions

- `def calculate_mean(values: List[float], **kwargs) -> float` — Calculate the arithmetic mean of a list of values.
- `def calculate_std(values: List[float], sample: bool=True, **kwargs) -> float` — Calculate standard deviation.
- `def calculate_median(values: List[float], **kwargs) -> float` — Calculate median value.
- `def calculate_correlation(values: List[float], **kwargs) -> float` — Calculate Pearson correlation coefficient.
