---
type: Wiki Summary
title: parrot.tools.dataset_manager.filtering.values
id: mod:parrot.tools.dataset_manager.filtering.values
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Value catalog helpers for FEAT-225 Module 5.
relates_to:
- concept: func:parrot.tools.dataset_manager.filtering.values.apply_cardinality_cap
  rel: defines
- concept: func:parrot.tools.dataset_manager.filtering.values.infer_values_from_datasets
  rel: defines
---

# `parrot.tools.dataset_manager.filtering.values`

Value catalog helpers for FEAT-225 Module 5.

Provides utilities for collecting distinct column values from a set of
DatasetEntry objects — used by DatasetManager.get_filter_values to populate
frontend combo selectors.

Functions:
    infer_values_from_datasets: Union distinct values across in-memory datasets.
    apply_cardinality_cap: Truncate to a maximum number of values with logging.

## Functions

- `def infer_values_from_datasets(column: str, datasets: Dict[str, Any], restrict_to_dataset: Optional[str]=None) -> List[Any]` — Collect distinct values for *column* from in-memory datasets.
- `def apply_cardinality_cap(values: List[Any], cap: int=DEFAULT_CARDINALITY_CAP, filter_name: str='', log: Optional[logging.Logger]=None) -> List[Any]` — Truncate *values* to at most *cap* items, logging a warning if truncated.
