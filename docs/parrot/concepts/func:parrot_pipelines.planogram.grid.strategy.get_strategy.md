---
type: Concept
title: get_strategy()
id: func:parrot_pipelines.planogram.grid.strategy.get_strategy
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Instantiate and return the grid strategy for the given GridType.
---

# get_strategy

```python
def get_strategy(grid_type: GridType) -> AbstractGridStrategy
```

Instantiate and return the grid strategy for the given GridType.

Args:
    grid_type: The desired grid strategy type.

Returns:
    An instance of the corresponding AbstractGridStrategy subclass.

Raises:
    ValueError: If grid_type is not registered in the strategy registry.
