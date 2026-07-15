---
type: Concept
title: calculate_std()
id: func:parrot_tools.calculator.operations.statistics.calculate_std
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Calculate standard deviation.
---

# calculate_std

```python
def calculate_std(values: List[float], sample: bool=True, **kwargs) -> float
```

Calculate standard deviation.

Args:
    values: List of numerical values
    sample: If True, use sample std (n-1), else population std (n)
