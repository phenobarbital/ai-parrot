---
type: Wiki Summary
title: parrot.tools.dataset_manager.filtering.store
id: mod:parrot.tools.dataset_manager.filtering.store
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Pure validation helpers for the FilterDefinition instance store (FEAT-225
  Module 2).
relates_to:
- concept: func:parrot.tools.dataset_manager.filtering.store.columns_present_in_any
  rel: defines
- concept: func:parrot.tools.dataset_manager.filtering.store.warn_if_no_coverage
  rel: defines
---

# `parrot.tools.dataset_manager.filtering.store`

Pure validation helpers for the FilterDefinition instance store (FEAT-225 Module 2).

These functions are I/O-free and test-friendly.  DatasetManager.define_filters
delegates column-presence checks here so that the logic is independently testable.

Functions:
    columns_present_in_any:  Return the subset of dataset names that contain
        all required columns.
    check_columns_coverage:  Raise (or log) when no registered dataset exposes
        the target column(s).

## Functions

- `def columns_present_in_any(columns: List[str], datasets: Dict[str, Any]) -> List[str]` — Return names of datasets that contain ALL of the given columns.
- `def warn_if_no_coverage(definition_name: str, columns: List[str], compatible: List[str], log: Optional[logging.Logger]=None) -> None` — Log a warning when no registered dataset covers the column(s).
