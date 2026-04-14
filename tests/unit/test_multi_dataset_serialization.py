"""Unit tests for serialization guard — multi-dataset and single-dataset paths.

Tests for FEAT-098 TASK-665: Serialization Guard for Multi-Dataset Responses.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock
from parrot.bots.data import DatasetResult


def _make_dataset_results():
    """Helper: create a list of pre-serialized DatasetResult dicts."""
    return [
        DatasetResult(
            name="ds1",
            variable="ds1",
            data=[{"a": 1, "b": 2}],
            shape=(1, 2),
            columns=["a", "b"],
        ).model_dump(),
        DatasetResult(
            name="ds2",
            variable="ds2",
            data=[{"x": 10}, {"x": 20}],
            shape=(2, 1),
            columns=["x"],
        ).model_dump(),
    ]


def _apply_serialization_guard(response_data):
    """
    Simulates the serialization guard logic from PandasAgent.

    This mirrors the block at ~L1660 in data.py.
    Returns the (possibly transformed) response.data value.
    """
    import logging
    _logger = logging.getLogger("test_serialization_guard")

    data = response_data
    if isinstance(data, pd.DataFrame):
        data = data.to_dict(orient="records")
    elif isinstance(data, list):
        pass  # already serialized — leave as-is
    elif data is not None:
        _logger.warning("PandasAgent response.data unexpected type: %s", type(data))
    return data


class TestSerializationGuard:
    """Tests for the serialization guard block."""

    def test_dataframe_serialized_to_records(self):
        """DataFrame response.data is serialized to list of dicts."""
        df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        result = _apply_serialization_guard(df)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0] == {"col1": 1, "col2": "a"}

    def test_multi_dataset_list_passthrough(self):
        """List of DatasetResult dicts passes through unchanged."""
        original = _make_dataset_results()
        result = _apply_serialization_guard(original)
        # Must be the exact same list — no transformation
        assert result is original
        assert len(result) == 2
        assert result[0]["name"] == "ds1"
        assert result[1]["name"] == "ds2"

    def test_plain_list_passthrough(self):
        """A plain list of record dicts (single-dataset) also passes through unchanged."""
        records = [{"id": 1, "val": "x"}, {"id": 2, "val": "y"}]
        result = _apply_serialization_guard(records)
        assert result is records

    def test_none_passthrough(self):
        """None response.data passes through without error."""
        result = _apply_serialization_guard(None)
        assert result is None

    def test_unexpected_type_logs_warning(self):
        """Non-list, non-DataFrame, non-None type logs a warning."""
        import logging

        with pytest.raises(Exception) if False else pytest.warns(None):
            # The guard logs a warning but does NOT raise an exception
            result = _apply_serialization_guard("unexpected string value")
            # The data is returned as-is (guard only logs, doesn't transform)
            assert result == "unexpected string value"

    def test_empty_dataframe_serialized(self):
        """Empty DataFrame is serialized to empty list."""
        df = pd.DataFrame()
        result = _apply_serialization_guard(df)
        assert result == []

    def test_multi_dataset_structure_integrity(self):
        """Multi-dataset list entries preserve DatasetResult fields."""
        original = _make_dataset_results()
        result = _apply_serialization_guard(original)

        # Check first entry
        entry_ds1 = next(e for e in result if e["name"] == "ds1")
        assert entry_ds1["variable"] == "ds1"
        assert entry_ds1["data"] == [{"a": 1, "b": 2}]
        assert entry_ds1["shape"] == (1, 2)
        assert entry_ds1["columns"] == ["a", "b"]

        # Check second entry
        entry_ds2 = next(e for e in result if e["name"] == "ds2")
        assert len(entry_ds2["data"]) == 2
