---
type: Concept
title: warn_if_no_coverage()
id: func:parrot.tools.dataset_manager.filtering.store.warn_if_no_coverage
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Log a warning when no registered dataset covers the column(s).
---

# warn_if_no_coverage

```python
def warn_if_no_coverage(definition_name: str, columns: List[str], compatible: List[str], log: Optional[logging.Logger]=None) -> None
```

Log a warning when no registered dataset covers the column(s).

This is a non-fatal advisory — datasets may be added later, or their
schemas may not yet be prefetched.

Args:
    definition_name: The FilterDefinition name (for the log message).
    columns: The target column(s).
    compatible: Datasets found to be compatible (may be empty).
    log: Logger instance to use; falls back to the module logger.
