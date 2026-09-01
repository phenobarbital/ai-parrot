"""Flex dashboard normalization layer (FEAT-491 TASK-2693, spec §3 Module 1).

Pure, deterministic input canonicalization shared by every Flex transformer
(:mod:`agents.flex_dashboard.transformers`, TASK-2694). The six Flex
datasets arrive dirty:

- ``Finance_results_bi`` currency columns are formatted strings
  (``"$137,456.85"``, negatives ``"-$44,621.24"``).
- Three date-grain conventions coexist: finance ``month`` (month-end date),
  hours ``month_start``/``month_end``, and the ``fm_*`` datasets'
  ``BOP Date``/``EOP Date`` (or lowercase ``bop_date``/``eop_date``).
- ``fm_rep_utilization`` ships a ``catagory`` typo column, and header
  casing differs from ``fm_regions_avg_employees_html``.

ALL canonicalization for these datasets lives here — transformers never
inline it (spec §7 Known Risks: "Dirty inputs ... ALL canonicalization goes
through Module 1 — never inline in transformers").

Every function here is a pure function over :class:`pandas.DataFrame`
objects: no I/O, no logging, no mutation of the input frame (always returns
a copy). Determinism matters — recipe replay (TASK-2697) depends on the
same input frame always producing the same output frame.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "canonicalize_columns",
    "month_period",
    "normalize_currency_columns",
    "parse_currency",
]

#: Matches the characters `parse_currency` strips before calling `float()`.
_CURRENCY_STRIP_RE = re.compile(r"[,$]")

#: Per-source candidate date columns consulted by `month_period`, in the
#: order finance/hours/fm datasets are documented in spec §2.
_MONTH_SOURCE_COLUMNS: dict[str, Sequence[str]] = {
    "finance": ("month",),
    "hours": ("month_start",),
    "fm": ("BOP Date", "bop_date"),
}

#: Per-source rename maps consulted by `canonicalize_columns`. Only keys
#: present in the input frame are ever renamed — declaring a header that
#: happens to be absent from a given frame is a no-op, not an error.
_COLUMN_RENAMES: dict[str, dict[str, str]] = {
    "msl": {},
    "finance": {},
    "hours": {},
    "employees": {
        "Flex Employees": "flex_employees",
        "Flex Type": "flex_type",
        "Years of Service": "years_of_service",
        "Months of Service": "months_of_service",
        "Days of Service": "days_of_service",
        "Days of Service Retention": "days_of_service_retention",
    },
    "region_utilization": {
        "BOP Date": "bop_date",
        "EOP Date": "eop_date",
        "FM Region": "region",
        "State Code": "state",
        "State": "state_name",
        "Category": "category",
        "Employees Worked": "employees_worked",
        "Average Active Employees": "average_active",
        "Flex Employees": "flex_employees",
        "Employee Utilization": "employee_utilization",
    },
    "rep_utilization": {
        "catagory": "category",
    },
}


def parse_currency(value: Any) -> float:
    """Parse a Flex currency string (or passthrough numeric) into a float.

    Handles the ``Finance_results_bi`` currency-string convention:
    ``"$137,456.85"`` -> ``137456.85``, negatives ``"-$44,621.24"`` ->
    ``-44621.24``, ``"$0.00"`` -> ``0.0``. Already-numeric values pass
    through unchanged (as ``float``); missing/unparseable values return
    ``float("nan")`` (NaN-safe).

    Args:
        value: A currency string, an already-numeric value (``int``/
            ``float``), or a missing value (``None``/``NaN``).

    Returns:
        The parsed float value, or ``float("nan")`` when *value* is
        missing or cannot be parsed.
    """
    if value is None:
        return float("nan")
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    try:
        if pd.isna(value):
            return float("nan")
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return float("nan")
    cleaned = _CURRENCY_STRIP_RE.sub("", text)
    try:
        return float(cleaned)
    except ValueError:
        return float("nan")


def normalize_currency_columns(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Apply :func:`parse_currency` to the given columns of *df*.

    Args:
        df: Input frame (never mutated).
        columns: Column names to parse. Columns absent from *df* are
            silently skipped.

    Returns:
        A copy of *df* with the requested columns converted to ``float``.
    """
    result = df.copy()
    for column in columns:
        if column in result.columns:
            result[column] = result[column].map(parse_currency)
    return result


def month_period(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Add a canonical ``month`` column (``"YYYY-MM"``) to *df*.

    Resolves one of the three Flex date-grain conventions documented in
    spec §3 Module 1:

    - ``source="finance"`` — the month-end ``month`` column
      (``Finance_results_bi``).
    - ``source="hours"`` — the ``month_start`` column
      (``flex_hours_query_pbi``).
    - ``source="fm"`` — ``BOP Date`` or ``bop_date``
      (``fm_regions_avg_employees_html`` / ``fm_rep_utilization``).

    Args:
        df: Input frame (never mutated).
        source: One of ``"finance"``, ``"hours"``, ``"fm"``.

    Returns:
        A copy of *df* with an added ``month`` column of ``"YYYY-MM"``
        strings.

    Raises:
        ValueError: If *source* is not a recognized convention.
        KeyError: If none of the source's candidate date columns are
            present in *df*.
    """
    try:
        candidates = _MONTH_SOURCE_COLUMNS[source]
    except KeyError as exc:
        raise ValueError(f"Unknown month source: {source!r}") from exc

    date_column = next((c for c in candidates if c in df.columns), None)
    if date_column is None:
        raise KeyError(f"No date column found for source={source!r}; expected one of {candidates}")

    result = df.copy()
    dates = pd.to_datetime(result[date_column])
    result["month"] = dates.dt.strftime("%Y-%m")
    return result


def canonicalize_columns(df: pd.DataFrame, *, source: str) -> pd.DataFrame:
    """Rename dataset-specific dirty headers to a canonical snake_case form.

    Covers the known Flex header variants (spec §3 Module 1): the
    ``catagory`` -> ``category`` typo in ``fm_rep_utilization``, and the
    Title/Space-Case headers of ``fm_regions_avg_employees_html`` and
    ``flex_empolyees_brian_bi``.

    Args:
        df: Input frame (never mutated).
        source: One of the six Flex aliases (spec §2): ``"msl"``,
            ``"finance"``, ``"hours"``, ``"employees"``,
            ``"region_utilization"``, ``"rep_utilization"``.

    Returns:
        A copy of *df* with recognized headers renamed. Headers not in the
        rename map for *source* are left unchanged.

    Raises:
        ValueError: If *source* is not one of the six known aliases.
    """
    try:
        rename_map = _COLUMN_RENAMES[source]
    except KeyError as exc:
        raise ValueError(f"Unknown canonicalization source: {source!r}") from exc

    applicable = {k: v for k, v in rename_map.items() if k in df.columns}
    return df.rename(columns=applicable)
