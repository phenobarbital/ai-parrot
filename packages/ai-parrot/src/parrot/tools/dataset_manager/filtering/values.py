"""Value catalog helpers for FEAT-225 Module 5.

Provides utilities for collecting distinct column values from a set of
DatasetEntry objects — used by DatasetManager.get_filter_values to populate
frontend combo selectors.

Functions:
    infer_values_from_datasets: Union distinct values across in-memory datasets.
    apply_cardinality_cap: Truncate to a maximum number of values with logging.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# Default cardinality cap for inferred value catalogs.
DEFAULT_CARDINALITY_CAP: int = 1000


def infer_values_from_datasets(
    column: str,
    datasets: Dict[str, Any],  # DatasetEntry values
    restrict_to_dataset: Optional[str] = None,
) -> List[Any]:
    """Collect distinct values for *column* from in-memory datasets.

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
    """
    collected: set = set()

    for ds_name, entry in datasets.items():
        if restrict_to_dataset is not None and ds_name != restrict_to_dataset:
            continue

        df: Optional[pd.DataFrame] = getattr(entry, "_df", None)
        if df is None or column not in df.columns:
            continue

        vals = df[column].dropna().unique().tolist()
        collected.update(vals)

    # Sort for determinism; fall back to string comparison for mixed types.
    try:
        return sorted(collected)
    except TypeError:
        return sorted(collected, key=str)


def apply_cardinality_cap(
    values: List[Any],
    cap: int = DEFAULT_CARDINALITY_CAP,
    filter_name: str = "",
    log: Optional[logging.Logger] = None,
) -> List[Any]:
    """Truncate *values* to at most *cap* items, logging a warning if truncated.

    Args:
        values: The full value list.
        cap: Maximum number of values to return.
        filter_name: Used in the warning message for context.
        log: Logger to use; falls back to the module logger.

    Returns:
        The (possibly truncated) value list.
    """
    if len(values) <= cap:
        return values

    _log = log or logger
    _log.warning(
        "get_filter_values: filter '%s' has %d distinct values (cap %d). "
        "Truncating to first %d values. Increase the cardinality cap or declare "
        "an explicit values_source to expose all values.",
        filter_name,
        len(values),
        cap,
        cap,
    )
    return values[:cap]
