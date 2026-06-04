"""Pure validation helpers for the FilterDefinition instance store (FEAT-225 Module 2).

These functions are I/O-free and test-friendly.  DatasetManager.define_filters
delegates column-presence checks here so that the logic is independently testable.

Functions:
    columns_present_in_any:  Return the subset of dataset names that contain
        all required columns.
    check_columns_coverage:  Raise (or log) when no registered dataset exposes
        the target column(s).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def columns_present_in_any(
    columns: List[str],
    datasets: Dict[str, Any],  # DatasetEntry values (have ._column_types)
) -> List[str]:
    """Return names of datasets that contain ALL of the given columns.

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
    """
    compatible: List[str] = []
    for name, entry in datasets.items():
        col_types: Dict[str, str] = getattr(entry, "_column_types", {}) or {}
        if not col_types:
            # Schema not yet known; skip for now (no false negatives at define time).
            continue
        if all(col in col_types for col in columns):
            compatible.append(name)
    return compatible


def warn_if_no_coverage(
    definition_name: str,
    columns: List[str],
    compatible: List[str],
    log: Optional[logging.Logger] = None,
) -> None:
    """Log a warning when no registered dataset covers the column(s).

    This is a non-fatal advisory — datasets may be added later, or their
    schemas may not yet be prefetched.

    Args:
        definition_name: The FilterDefinition name (for the log message).
        columns: The target column(s).
        compatible: Datasets found to be compatible (may be empty).
        log: Logger instance to use; falls back to the module logger.
    """
    _log = log or logger
    if not compatible:
        _log.warning(
            "define_filters: no registered dataset with a known schema "
            "contains column(s) %r for filter '%s'. "
            "The filter will still be stored; it will silently skip all "
            "datasets at apply time.",
            columns,
            definition_name,
        )
