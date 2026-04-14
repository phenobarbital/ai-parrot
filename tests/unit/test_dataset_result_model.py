"""Unit tests for DatasetResult model and PandasAgentResponse extension.

Tests for FEAT-098 TASK-662: DatasetResult Model & PandasAgentResponse Extension.
"""
import pytest
from parrot.bots.data import DatasetResult, PandasAgentResponse, PandasTable


class TestDatasetResult:
    """Tests for the DatasetResult model."""

    def test_instantiation(self):
        """DatasetResult initializes with required fields."""
        result = DatasetResult(
            name="users_q3",
            variable="users_q3",
            data=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            shape=(2, 2),
            columns=["id", "name"],
        )
        assert result.name == "users_q3"
        assert result.variable == "users_q3"
        assert result.shape == (2, 2)
        assert len(result.data) == 2
        assert result.columns == ["id", "name"]

    def test_serialization(self):
        """DatasetResult serializes to dict."""
        result = DatasetResult(
            name="test",
            variable="test_df",
            data=[{"a": 1}],
            shape=(1, 1),
            columns=["a"],
        )
        d = result.model_dump()
        assert isinstance(d, dict)
        assert d["name"] == "test"
        assert d["variable"] == "test_df"
        assert d["data"] == [{"a": 1}]
        assert d["shape"] == (1, 1)
        assert d["columns"] == ["a"]

    def test_empty_data_defaults(self):
        """DatasetResult can be created with default empty data and columns."""
        result = DatasetResult(
            name="empty",
            variable="empty_df",
            shape=(0, 0),
        )
        assert result.data == []
        assert result.columns == []

    def test_json_serialization(self):
        """DatasetResult serializes to JSON string."""
        result = DatasetResult(
            name="json_test",
            variable="df1",
            data=[{"x": 1, "y": 2}],
            shape=(1, 2),
            columns=["x", "y"],
        )
        json_str = result.model_dump_json()
        assert isinstance(json_str, str)
        assert "json_test" in json_str


class TestPandasAgentResponseExtension:
    """Tests for the PandasAgentResponse data_variables extension."""

    def test_backward_compat_no_data_variables(self):
        """PandasAgentResponse without data_variables still works."""
        resp = PandasAgentResponse(
            explanation="Test",
            data=PandasTable(columns=["a"], rows=[[1]]),
        )
        assert resp.data_variables is None
        assert resp.data_variable is None

    def test_data_variables_accepted(self):
        """PandasAgentResponse accepts data_variables list."""
        resp = PandasAgentResponse(
            explanation="Test",
            data_variables=["df1", "df2"],
        )
        assert resp.data_variables == ["df1", "df2"]

    def test_both_singular_and_plural(self):
        """Both data_variable and data_variables can coexist."""
        resp = PandasAgentResponse(
            explanation="Test",
            data_variable="df1",
            data_variables=["df1", "df2"],
        )
        assert resp.data_variable == "df1"
        assert resp.data_variables == ["df1", "df2"]

    def test_data_variables_empty_list(self):
        """data_variables accepts an empty list."""
        resp = PandasAgentResponse(
            explanation="Test",
            data_variables=[],
        )
        assert resp.data_variables == []

    def test_data_variables_single_entry(self):
        """data_variables with a single entry is valid."""
        resp = PandasAgentResponse(
            explanation="Test",
            data_variables=["single_df"],
        )
        assert resp.data_variables == ["single_df"]

    def test_existing_fields_unchanged(self):
        """Existing fields (explanation, data, data_variable, code) are unaffected."""
        resp = PandasAgentResponse(
            explanation="My explanation",
            data=PandasTable(columns=["col1", "col2"], rows=[[1, 2], [3, 4]]),
            data_variable="my_df",
            code="import pandas as pd",
            data_variables=["my_df", "other_df"],
        )
        assert resp.explanation == "My explanation"
        assert resp.data is not None
        assert resp.data.columns == ["col1", "col2"]
        assert resp.data_variable == "my_df"
        assert resp.code == "import pandas as pd"
        assert resp.data_variables == ["my_df", "other_df"]
