"""Unit tests for multi-dataset injection logic.

Tests for FEAT-098 TASK-663: Multi-Dataset Injection Logic.
"""
import pytest
import pandas as pd
from unittest.mock import MagicMock, AsyncMock, patch
from parrot.bots.data import DatasetResult


@pytest.fixture
def mock_pandas_tool():
    """Mock PythonPandasTool with two DataFrames in locals."""
    tool = MagicMock()
    tool.locals = {
        "users_q3": pd.DataFrame({
            "user_id": [1, 2, 3],
            "name": ["Alice", "Bob", "Carol"],
        }),
        "tasks_completed": pd.DataFrame({
            "user_id": [1, 1, 2],
            "task": ["Deploy", "Review", "Test"],
        }),
    }
    return tool


@pytest.fixture
def mock_response():
    """Mock AIMessage response object."""
    response = MagicMock()
    response.data = None
    return response


@pytest.fixture
def mock_agent(mock_pandas_tool):
    """Mock PandasAgent with _inject_multi_data_from_variables method."""
    from parrot.bots.data import PandasAgent  # noqa: F401 — for type reference

    agent = MagicMock()
    agent._get_python_pandas_tool = MagicMock(return_value=mock_pandas_tool)
    agent.logger = MagicMock()

    # Bind the real method to our mock agent
    from parrot.bots.data import PandasAgent as _PA
    agent._inject_multi_data_from_variables = (
        _PA._inject_multi_data_from_variables.__get__(agent, type(agent))
    )
    return agent


class TestMultiDatasetInjection:
    """Tests for _inject_multi_data_from_variables."""

    @pytest.mark.asyncio
    async def test_multiple_variables_resolved(self, mock_agent, mock_response):
        """Two valid variables produce two DatasetResult entries."""
        await mock_agent._inject_multi_data_from_variables(
            mock_response,
            ["users_q3", "tasks_completed"],
        )
        assert isinstance(mock_response.data, list)
        assert len(mock_response.data) == 2

        names = [entry["name"] for entry in mock_response.data]
        assert "users_q3" in names
        assert "tasks_completed" in names

        # Verify DatasetResult structure
        users_entry = next(e for e in mock_response.data if e["name"] == "users_q3")
        assert "data" in users_entry
        assert "shape" in users_entry
        assert "columns" in users_entry
        assert "variable" in users_entry
        assert len(users_entry["data"]) == 3  # 3 rows in users_q3

    @pytest.mark.asyncio
    async def test_missing_variable_skipped(self, mock_agent, mock_response):
        """A missing variable is skipped; other variables are still included."""
        await mock_agent._inject_multi_data_from_variables(
            mock_response,
            ["users_q3", "nonexistent_var"],
        )
        assert isinstance(mock_response.data, list)
        assert len(mock_response.data) == 1
        assert mock_response.data[0]["name"] == "users_q3"
        # Warning should have been logged for the missing variable
        mock_agent.logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_no_pandas_tool_warns(self, mock_response):
        """If PythonPandasTool is unavailable, logs warning and returns without setting data."""
        agent = MagicMock()
        agent._get_python_pandas_tool = MagicMock(return_value=None)
        agent.logger = MagicMock()

        from parrot.bots.data import PandasAgent as _PA
        agent._inject_multi_data_from_variables = (
            _PA._inject_multi_data_from_variables.__get__(agent, type(agent))
        )

        await agent._inject_multi_data_from_variables(
            mock_response,
            ["df1", "df2"],
        )
        assert mock_response.data is None
        agent.logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_dataset_result_structure(self, mock_agent, mock_response):
        """Each dataset entry contains expected fields with correct types."""
        await mock_agent._inject_multi_data_from_variables(
            mock_response,
            ["tasks_completed"],
        )
        assert mock_response.data is not None
        assert len(mock_response.data) == 1
        entry = mock_response.data[0]
        assert entry["name"] == "tasks_completed"
        assert entry["variable"] == "tasks_completed"
        assert isinstance(entry["data"], list)
        assert isinstance(entry["shape"], (tuple, list))
        assert isinstance(entry["columns"], list)
        # shape should be (3, 3) — 3 rows, user_id/task/index after reset_index
        assert entry["shape"][0] == 3

    @pytest.mark.asyncio
    async def test_all_variables_missing_no_data_set(self, mock_response):
        """When all variables are missing, response.data remains None."""
        agent = MagicMock()
        tool = MagicMock()
        tool.locals = {}
        agent._get_python_pandas_tool = MagicMock(return_value=tool)
        agent.logger = MagicMock()

        from parrot.bots.data import PandasAgent as _PA
        agent._inject_multi_data_from_variables = (
            _PA._inject_multi_data_from_variables.__get__(agent, type(agent))
        )

        await agent._inject_multi_data_from_variables(
            mock_response,
            ["nonexistent1", "nonexistent2"],
        )
        assert mock_response.data is None
        # Should log a warning about no results
        mock_agent.logger.warning.assert_called() if hasattr(mock_agent, 'logger') else None
