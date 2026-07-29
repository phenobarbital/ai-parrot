---
type: Concept
title: apply_cardinality_cap()
id: func:parrot.tools.dataset_manager.filtering.values.apply_cardinality_cap
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Truncate *values* to at most *cap* items, logging a warning if truncated.
---

# apply_cardinality_cap

```python
def apply_cardinality_cap(values: List[Any], cap: int=DEFAULT_CARDINALITY_CAP, filter_name: str='', log: Optional[logging.Logger]=None) -> List[Any]
```

Truncate *values* to at most *cap* items, logging a warning if truncated.

Args:
    values: The full value list.
    cap: Maximum number of values to return.
    filter_name: Used in the warning message for context.
    log: Logger to use; falls back to the module logger.

Returns:
    The (possibly truncated) value list.
