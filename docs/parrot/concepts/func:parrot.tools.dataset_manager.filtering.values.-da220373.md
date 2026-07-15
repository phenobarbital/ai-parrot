---
type: Concept
title: infer_values_from_datasets()
id: func:parrot.tools.dataset_manager.filtering.values.infer_values_from_datasets
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Collect distinct values for *column* from in-memory datasets.
---

# infer_values_from_datasets

```python
def infer_values_from_datasets(column: str, datasets: Dict[str, Any], restrict_to_dataset: Optional[str]=None) -> List[Any]
```

Collect distinct values for *column* from in-memory datasets.

Only datasets that are already materialized (``entry._df is not None``)
and have *column* in their DataFrame are queried — this avoids triggering
I/O.

Args:
    column: The column name to collect distinct values from.
    datasets: Mapping of dataset-name → DatasetEntry.
    restrict_to_dataset: When provided, only the named dataset is queried.

Returns:
    Sorted, de-duplicated list of values.  Empty list if no dataset has
    the column in its loaded DataFrame.
