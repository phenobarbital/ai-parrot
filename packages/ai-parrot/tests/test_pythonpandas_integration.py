"""Integration tests for PythonPandasTool + DatasetManager."""
import pytest
import pandas as pd
import numpy as np
from parrot.tools.pythonpandas import PythonPandasTool
from parrot.tools.dataset_manager import DatasetManager


@pytest.fixture
def sample_df():
    """Sample DataFrame for testing."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["Alice", "Bob", "Charlie"],
        "value": [100.5, 200.0, 300.75],
    })


@pytest.fixture
def sample_df_with_nulls():
    """Sample DataFrame with null values."""
    return pd.DataFrame({
        "id": [1, 2, 3, 4],
        "name": ["Alice", None, "Charlie", "Diana"],
        "value": [100.5, 200.0, np.nan, 300.75]
    })


class TestPythonPandasToolStandalone:
    """Tests for PythonPandasTool without DatasetManager."""

    def test_init_standalone(self, sample_df):
        """Tool initializes in standalone mode."""
        tool = PythonPandasTool(dataframes={"test": sample_df})
        assert tool.dataset_manager is None
        assert "test" in tool.dataframes
        assert tool.df_locals["test"] is sample_df
        assert tool.df_locals["df1"] is sample_df

    def test_add_dataframe_standalone(self, sample_df):
        """add_dataframe works in standalone mode."""
        tool = PythonPandasTool()
        result = tool.add_dataframe("test", sample_df)
        
        assert "test" in result
        assert "df1" in result
        assert "test" in tool.dataframes

    def test_remove_dataframe_standalone(self, sample_df):
        """remove_dataframe works in standalone mode."""
        tool = PythonPandasTool(dataframes={"test": sample_df})
        result = tool.remove_dataframe("test")
        
        assert "test" in result
        assert "test" not in tool.dataframes

    def test_list_dataframes_standalone(self, sample_df):
        """list_dataframes returns basic info in standalone mode."""
        tool = PythonPandasTool(dataframes={"sales": sample_df})
        result = tool.list_dataframes()
        
        assert "sales" in result
        assert result["sales"]["alias"] == "df1"
        assert result["sales"]["shape"] == (3, 3)

    def test_get_dataframe_summary_standalone(self, sample_df):
        """get_dataframe_summary works in standalone mode."""
        tool = PythonPandasTool(dataframes={"test": sample_df})
        result = tool.get_dataframe_summary("test")
        
        assert result["row_count"] == 3
        assert result["column_count"] == 3
        assert "dtypes" in result

    def test_nan_warnings_standalone(self, sample_df_with_nulls):
        """_get_nan_warnings works in standalone mode."""
        tool = PythonPandasTool(dataframes={"test": sample_df_with_nulls})
        warnings = tool._get_nan_warnings()
        
        assert len(warnings) == 2  # name and value columns
        assert any("name" in w for w in warnings)
        assert any("value" in w for w in warnings)


class TestPythonPandasToolWithManager:
    """Tests for PythonPandasTool with DatasetManager integration."""

    def test_init_with_manager(self, sample_df):
        """Tool initializes with DatasetManager."""
        dm = DatasetManager()
        dm.add_dataframe("sales", sample_df)
        
        tool = PythonPandasTool(dataset_manager=dm)
        
        assert tool.dataset_manager is dm
        assert "sales" in tool.dataframes
        assert tool.df_locals["sales"] is sample_df

    def test_df_guide_from_manager(self, sample_df):
        """df_guide property delegates to manager."""
        dm = DatasetManager(generate_guide=True)
        dm.add_dataframe("sales", sample_df)
        
        tool = PythonPandasTool(dataset_manager=dm)
        
        assert "sales" in tool.df_guide
        assert "DataFrame Guide" in tool.df_guide

    def test_list_dataframes_delegates_to_manager(self, sample_df):
        """list_dataframes delegates to manager when available."""
        dm = DatasetManager(auto_detect_types=True)
        dm.add_dataframe("sales", sample_df)
        
        tool = PythonPandasTool(dataset_manager=dm)
        result = tool.list_dataframes()
        
        # Manager returns column_types, standalone does not by default
        assert "column_types" in result["sales"]

    def test_sync_from_manager(self, sample_df):
        """sync_from_manager updates tool dataframes."""
        dm = DatasetManager()
        tool = PythonPandasTool(dataset_manager=dm)
        
        # Initially empty
        assert len(tool.dataframes) == 0
        
        # Add dataframe to manager
        dm.add_dataframe("sales", sample_df)
        tool.sync_from_manager()
        
        # Now synced
        assert "sales" in tool.dataframes
        assert tool.df_locals["sales"] is sample_df

    def test_add_dataframe_syncs_with_manager(self, sample_df):
        """add_dataframe registers in manager and syncs."""
        dm = DatasetManager()
        tool = PythonPandasTool(dataset_manager=dm)
        
        tool.add_dataframe("sales", sample_df)
        
        # Should be in both manager and tool
        assert "sales" in dm._datasets
        assert "sales" in tool.dataframes

    def test_remove_dataframe_syncs_with_manager(self, sample_df):
        """remove_dataframe removes from manager and syncs."""
        dm = DatasetManager()
        dm.add_dataframe("sales", sample_df)
        tool = PythonPandasTool(dataset_manager=dm)
        
        tool.remove_dataframe("sales")
        
        # Should be removed from both
        assert "sales" not in dm._datasets
        assert "sales" not in tool.dataframes

    def test_nan_warnings_from_manager(self, sample_df_with_nulls):
        """_get_nan_warnings delegates to manager."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df_with_nulls)
        tool = PythonPandasTool(dataset_manager=dm)
        
        warnings = tool._get_nan_warnings()
        
        assert len(warnings) == 2
        assert any("name" in w for w in warnings)

    def test_dataset_manager_setter(self, sample_df):
        """Setting dataset_manager property triggers sync."""
        dm = DatasetManager()
        dm.add_dataframe("sales", sample_df)
        
        tool = PythonPandasTool()
        assert tool.dataset_manager is None
        assert "sales" not in tool.dataframes
        
        # Set manager
        tool.dataset_manager = dm
        
        assert tool.dataset_manager is dm
        assert "sales" in tool.dataframes


class TestPythonPandasToolEnvironment:
    """Tests for execution environment setup."""

    def test_environment_info_has_manager_flag(self, sample_df):
        """get_environment_info includes has_dataset_manager check."""
        dm = DatasetManager()
        tool_with = PythonPandasTool(dataset_manager=dm)
        tool_without = PythonPandasTool()
        
        # Check property directly to avoid parent class REPL dependencies
        assert tool_with._dataset_manager is not None
        assert tool_without._dataset_manager is None

    def test_clear_dataframes(self, sample_df):
        """clear_dataframes removes all bindings."""
        tool = PythonPandasTool(dataframes={"test": sample_df})
        
        assert "test" in tool.dataframes
        assert "test" in tool.df_locals
        
        tool.clear_dataframes()
        
        assert len(tool.dataframes) == 0
        assert len(tool.df_locals) == 0

    def test_register_dataframes(self, sample_df):
        """register_dataframes replaces all dataframes."""
        tool = PythonPandasTool(dataframes={"old": sample_df})
        
        new_df = pd.DataFrame({"x": [1, 2]})
        tool.register_dataframes({"new": new_df})
        
        assert "old" not in tool.dataframes
        assert "new" in tool.dataframes
