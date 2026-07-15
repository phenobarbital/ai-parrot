---
type: Wiki Entity
title: FilterResult
id: class:parrot.tools.dataset_manager.filtering.contracts.FilterResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Records the per-run outcome of ``DatasetManager.apply_filters``.
---

# FilterResult

Defined in [`parrot.tools.dataset_manager.filtering.contracts`](../summaries/mod:parrot.tools.dataset_manager.filtering.contracts.md).

```python
class FilterResult(BaseModel)
```

Records the per-run outcome of ``DatasetManager.apply_filters``.

Attributes:
    applied: Names of datasets that were successfully filtered.
    skipped: Names of datasets that were skipped entirely because they
        lack ALL target columns and the filter's ``required`` flag is False.
    partial_skips: Per-dataset mapping of filter names that were skipped
        for that dataset because the target column was absent (but the
        filter was not ``required``).  A dataset may appear in both
        ``applied`` (at least one filter matched) and ``partial_skips``
        (at least one other filter was skipped).
        Example::

            {
                "stores": ["temperature"],   # temperature col absent
            }
