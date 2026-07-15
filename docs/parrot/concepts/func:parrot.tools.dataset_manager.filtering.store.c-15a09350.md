---
type: Concept
title: columns_present_in_any()
id: func:parrot.tools.dataset_manager.filtering.store.columns_present_in_any
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Return names of datasets that contain ALL of the given columns.
---

# columns_present_in_any

```python
def columns_present_in_any(columns: List[str], datasets: Dict[str, Any]) -> List[str]
```

Return names of datasets that contain ALL of the given columns.

A dataset is considered *potentially compatible* when:
- Its ``_column_types`` dict is non-empty (meaning the schema has been
  prefetched or materialised) AND every column in ``columns`` is a key.
- OR its ``_column_types`` is empty/unknown (not yet materialised) — in
  this case we cannot definitively exclude it; it is NOT included in the
  compatible set but also not treated as failing.

Args:
    columns: Column names the filter requires.
    datasets: Mapping of dataset-name → DatasetEntry.

Returns:
    List of dataset names whose known schema contains all columns.
