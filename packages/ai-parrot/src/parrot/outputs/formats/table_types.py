"""FEAT-218: Deterministic dtype→vocabulary map + canonical value serialization.

Provides two pure functions that the ``StructuredTableRenderer`` uses to build
the deterministic half of the structured-table schema:

- :func:`base_column_types` — maps ``DatasetManager.categorize_columns`` output
  onto the FEAT-218 storage vocabulary.
- :func:`canonical_records` — serializes DataFrame rows to plain dicts with
  type-safe, JSON-boundary-safe values (ISO-8601 UTC datetimes, big-ints-as-strings,
  NaN/None → None).

Neither function performs I/O or LLM calls; both are fully deterministic and
independently unit-testable.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from parrot.tools.dataset_manager.tool import DatasetManager


# ── Storage vocabulary ────────────────────────────────────────────────────────

#: Map from ``DatasetManager.categorize_columns`` category → FEAT-218 storage type.
_CATEGORY_TO_TYPE: dict[str, str] = {
    "integer": "integer",
    "float": "number",
    "datetime": "datetime",
    "boolean": "boolean",
    "categorical": "string",
    "categorical_text": "string",
    "text": "string",
}


# ── Public API ────────────────────────────────────────────────────────────────


def base_column_types(df: pd.DataFrame) -> dict[str, str]:
    """Map DataFrame column dtypes to the FEAT-218 storage vocabulary.

    Calls :meth:`DatasetManager.categorize_columns` (read-only) and maps its
    coarse categories to the compact storage vocabulary used by
    :class:`~parrot.models.outputs.TableColumn`:

    - ``integer`` → ``"integer"``
    - ``float`` → ``"number"``
    - ``datetime`` → ``"datetime"``
    - ``boolean`` → ``"boolean"``
    - ``categorical`` / ``categorical_text`` / ``text`` → ``"string"``
    - anything else → ``"any"``

    Args:
        df: Source DataFrame.  The function is read-only — it never mutates
            the DataFrame or its columns.

    Returns:
        A ``{column_name: storage_type}`` dict with one entry per column.
    """
    raw: dict[str, str] = DatasetManager.categorize_columns(df)
    return {
        col: _CATEGORY_TO_TYPE.get(category, "any")
        for col, category in raw.items()
    }


def canonical_records(
    df: pd.DataFrame,
    row_limit: int = 1000,
) -> tuple[list[dict], int, bool]:
    """Serialize DataFrame rows to canonical, JSON-boundary-safe dicts.

    Applies ``row_limit`` truncation and serializes cell values so that the
    resulting list can be safely round-tripped through JSON without precision
    loss or type ambiguity:

    - **datetime / Timestamp** → ISO-8601 UTC string (``"2026-01-01T00:00:00Z"``).
    - **integer > 2^53** → ``str`` (avoids IEEE-754 precision loss in JSON).
    - **NaN / pd.NaT / None** → Python ``None`` (serializes as JSON ``null``).
    - **All other scalar types** → passed through as-is (int, float, bool, str).

    Args:
        df: Source DataFrame.  The function is read-only.
        row_limit: Maximum number of rows to include in the output list.
            Defaults to 1000.

    Returns:
        A three-tuple ``(rows, total_rows, truncated)`` where:

        - ``rows`` is a ``list[dict]`` of at most ``row_limit`` records.
        - ``total_rows`` is the original row count of ``df`` (before capping).
        - ``truncated`` is ``True`` when ``len(df) > row_limit``.
    """
    total_rows: int = len(df)
    truncated: bool = total_rows > row_limit

    sliced = df.iloc[:row_limit] if truncated else df
    rows: list[dict] = [
        {col: _canonical_value(val) for col, val in record.items()}
        for record in sliced.to_dict(orient="records")
    ]
    return rows, total_rows, truncated


# ── Internal helpers ──────────────────────────────────────────────────────────


def _canonical_value(value: Any) -> Any:
    """Serialize a single cell value to its canonical, JSON-safe form.

    Args:
        value: A raw cell value extracted from a pandas DataFrame row.

    Returns:
        The canonical representation:
        - ISO-8601 UTC string for datetime-like values.
        - ``str`` for Python ``int`` values beyond 2^53.
        - ``None`` for NaN, NaT, or missing values.
        - The original value for all other scalars.
    """
    # None / pd.NaT / numpy.nan → JSON null
    if value is None or value is pd.NaT:
        return None

    # pandas / numpy datetime types → ISO-8601 UTC string
    if isinstance(value, (pd.Timestamp,)):
        if pd.isna(value):
            return None
        # Normalize to UTC; emit Z suffix for maximum compatibility
        try:
            if value.tzinfo is None:
                # Treat as UTC when no timezone info present
                return value.strftime("%Y-%m-%dT%H:%M:%SZ")
            return value.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:  # noqa: BLE001
            return str(value)

    # Python datetime → ISO-8601
    try:
        from datetime import datetime as _dt
        if isinstance(value, _dt):
            if value.tzinfo is None:
                return value.strftime("%Y-%m-%dT%H:%M:%SZ")
            import datetime as _dtmod
            utc = value.astimezone(_dtmod.timezone.utc)
            return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:  # noqa: BLE001
        pass

    # NaN float → None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except (TypeError, ValueError):
        pass

    # Large integers → str to prevent IEEE-754 precision loss
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > 2 ** 53:
            return str(value)

    # numpy integer/bool scalar → Python native
    try:
        import numpy as np  # noqa: F401
        if isinstance(value, np.integer):
            iv = int(value)
            if abs(iv) > 2 ** 53:
                return str(iv)
            return iv
        if isinstance(value, np.floating):
            fv = float(value)
            return None if math.isnan(fv) else fv
        if isinstance(value, np.bool_):
            return bool(value)
    except ImportError:
        pass

    return value
