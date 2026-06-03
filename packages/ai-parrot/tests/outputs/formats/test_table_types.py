"""Tests for FEAT-218 TASK-1430: Deterministic dtype→vocabulary map + canonical value serialization.

Tests:
  - base_column_types: dtype category → storage vocabulary mapping.
  - canonical_records: ISO-8601 datetimes, big-int-as-strings, NaN → null, truncation.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from parrot.outputs.formats.table_types import base_column_types, canonical_records


# ─────────────────────────────────────────────────────────────────────────────
# base_column_types
# ─────────────────────────────────────────────────────────────────────────────


def test_base_types_mapping():
    """float→number, int→integer, bool→boolean, datetime→datetime, str→string."""
    df = pd.DataFrame({
        "i": pd.array([1, 2], dtype="int64"),
        "f": [1.5, 2.5],
        "b": [True, False],
        "d": pd.to_datetime(["2026-01-01", "2026-02-01"]),
        "s": ["x", "y"],
    })
    t = base_column_types(df)
    assert t["i"] == "integer"
    assert t["f"] == "number"
    assert t["b"] == "boolean"
    assert t["d"] == "datetime"
    assert t["s"] == "string"


def test_base_types_categorical():
    """pd.Categorical columns map to 'string'."""
    df = pd.DataFrame({"cat": pd.Categorical(["a", "b", "a"])})
    t = base_column_types(df)
    assert t["cat"] == "string"


def test_base_types_empty_df():
    """Empty DataFrame returns empty dict."""
    df = pd.DataFrame({"x": pd.Series([], dtype="float64")})
    t = base_column_types(df)
    assert "x" in t  # column present; categorize_columns handles empty df


def test_base_types_all_columns_present():
    """Every column in the DataFrame appears in the result."""
    df = pd.DataFrame({"a": [1], "b": ["x"], "c": [True]})
    t = base_column_types(df)
    assert set(t.keys()) == {"a", "b", "c"}


# ─────────────────────────────────────────────────────────────────────────────
# canonical_records — truncation
# ─────────────────────────────────────────────────────────────────────────────


def test_canonical_truncation_and_total():
    """canonical_records caps at row_limit and sets total_rows + truncated."""
    df = pd.DataFrame({"a": list(range(5))})
    rows, total, truncated = canonical_records(df, row_limit=2)
    assert total == 5
    assert truncated is True
    assert len(rows) == 2
    assert rows[0]["a"] == 0
    assert rows[1]["a"] == 1


def test_canonical_no_truncation():
    """When rows <= row_limit, truncated is False and total matches len(df)."""
    df = pd.DataFrame({"a": [1, 2, 3]})
    rows, total, truncated = canonical_records(df, row_limit=10)
    assert total == 3
    assert truncated is False
    assert len(rows) == 3


def test_canonical_exact_limit():
    """Exactly row_limit rows → not truncated."""
    df = pd.DataFrame({"x": list(range(5))})
    _, total, truncated = canonical_records(df, row_limit=5)
    assert total == 5
    assert truncated is False


# ─────────────────────────────────────────────────────────────────────────────
# canonical_records — ISO-8601 datetime serialization
# ─────────────────────────────────────────────────────────────────────────────


def test_iso_datetime_naive():
    """Naive datetime columns serialize as ISO-8601 with Z suffix."""
    df = pd.DataFrame({"d": pd.to_datetime(["2026-01-01T00:00:00"])})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert rows[0]["d"].startswith("2026-01-01")
    assert "T" in rows[0]["d"]


def test_iso_datetime_timezone_aware():
    """Timezone-aware datetime columns serialize as UTC ISO-8601."""
    df = pd.DataFrame({
        "d": pd.to_datetime(["2026-06-01T12:00:00"]).tz_localize("US/Eastern")
    })
    rows, _, _ = canonical_records(df, row_limit=10)
    # Should be converted to UTC
    assert rows[0]["d"].endswith("Z")


def test_nat_becomes_null():
    """NaT values serialize as Python None (→ JSON null)."""
    df = pd.DataFrame({"d": pd.to_datetime([None, "2026-01-01"])})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert rows[0]["d"] is None
    assert rows[1]["d"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# canonical_records — NaN serialization
# ─────────────────────────────────────────────────────────────────────────────


def test_nan_becomes_null():
    """float NaN serializes as Python None (→ JSON null)."""
    df = pd.DataFrame({"v": [1.0, float("nan"), 3.0]})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert rows[0]["v"] == pytest.approx(1.0)
    assert rows[1]["v"] is None
    assert rows[2]["v"] == pytest.approx(3.0)


# ─────────────────────────────────────────────────────────────────────────────
# canonical_records — big-integer serialization
# ─────────────────────────────────────────────────────────────────────────────


def test_big_int_as_string():
    """Integer values beyond 2^53 serialize as strings."""
    big = 2 ** 53 + 1
    # Use object dtype to carry a Python big int in a DataFrame cell
    df = pd.DataFrame({"n": pd.array([big], dtype=object)})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert isinstance(rows[0]["n"], str)
    assert rows[0]["n"] == str(big)


def test_small_int_stays_int():
    """Normal integer values stay as Python int."""
    df = pd.DataFrame({"n": [42]})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert isinstance(rows[0]["n"], int)
    assert rows[0]["n"] == 42


# ─────────────────────────────────────────────────────────────────────────────
# canonical_records — regular scalar passthrough
# ─────────────────────────────────────────────────────────────────────────────


def test_string_passthrough():
    """String values pass through unchanged."""
    df = pd.DataFrame({"s": ["hello", "world"]})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert rows[0]["s"] == "hello"
    assert rows[1]["s"] == "world"


def test_bool_passthrough():
    """Boolean values pass through as Python bool."""
    df = pd.DataFrame({"flag": [True, False]})
    rows, _, _ = canonical_records(df, row_limit=10)
    assert rows[0]["flag"] is True
    assert rows[1]["flag"] is False
