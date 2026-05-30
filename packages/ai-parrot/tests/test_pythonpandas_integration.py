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


class TestDriftSelfHeal:
    """Re-bind datasets materialized after a session clone is created.

    Reproduces the fetch_dataset → REPL race: the dataset tools and the sync
    callback can live on different DatasetManager instances, so a just-fetched
    DataFrame is occasionally absent from the next python_repl_pandas call and
    surfaces as a NameError.  ``_rebind_drifted_dataframes`` self-heals it.
    """

    def test_rebind_binds_drifted_dataset(self, sample_df):
        """A dataset materialized after clone creation re-binds on demand."""
        dm = DatasetManager()
        base = PythonPandasTool(dataframes={})
        base._dataset_manager = dm
        clone = base.create_session_clone(dataset_manager=dm)
        assert "financial_projection" not in clone.locals

        # Simulate fetch_dataset materializing a dataset on the shared DM
        # WITHOUT the clone's on_change callback firing (the race).
        dm.add_dataframe("financial_projection", sample_df)
        assert "financial_projection" not in clone.locals  # drift present

        clone._rebind_drifted_dataframes()

        assert "financial_projection" in clone.locals
        pd.testing.assert_frame_equal(
            clone.locals["financial_projection"], sample_df
        )

    def test_rebind_preserves_computed_locals(self, sample_df):
        """Re-binding must not clobber LLM-computed REPL variables."""
        dm = DatasetManager()
        tool = PythonPandasTool(dataframes={})
        tool._dataset_manager = dm
        tool.locals["fp_daily"] = sample_df.copy()  # computed earlier
        dm.add_dataframe("financial_projection", sample_df)

        tool._rebind_drifted_dataframes()

        assert "financial_projection" in tool.locals
        assert "fp_daily" in tool.locals  # preserved

    def test_rebind_noop_when_no_drift(self, sample_df):
        """With no drift, a scratch variable survives the rebind check."""
        dm = DatasetManager()
        dm.add_dataframe("ds", sample_df)
        tool = PythonPandasTool(dataframes={})
        tool._dataset_manager = dm
        tool.register_dataframes(
            dm.get_active_dataframes(), alias_map=dm._get_alias_map()
        )
        tool.locals["scratch"] = 42

        tool._rebind_drifted_dataframes()

        assert tool.locals.get("scratch") == 42

    def test_rebind_noop_without_manager(self, sample_df):
        """No DatasetManager attached → safe no-op."""
        tool = PythonPandasTool(dataframes={"a": sample_df})
        tool._dataset_manager = None
        tool._rebind_drifted_dataframes()  # must not raise


class TestExecScoping:
    """Regression tests for the exec() globals/locals scoping trap.

    When code is exec'd with distinct globals/locals dicts, free-variable
    lookups inside comprehensions, generator expressions and nested functions
    resolve as LOAD_GLOBAL (through `globals` only). Helper functions or
    variables defined earlier in the SAME snippet then raise NameError when
    referenced inside a comprehension. A single unified namespace fixes it.
    """

    @pytest.mark.asyncio
    async def test_helper_function_visible_inside_comprehension(self, sample_df):
        """A module-level helper must be callable from within a comprehension."""
        tool = PythonPandasTool(dataframes={"a": sample_df})
        code = (
            "def _double(x):\n"
            "    return x * 2\n"
            "vals = [_double(v) for v in [1, 2, 3]]\n"
            "print('RESULT', vals)\n"
        )
        out = await tool._execute(code)
        assert "NameError" not in out
        assert "ExecutionError" not in out
        assert "RESULT [2, 4, 6]" in out

    @pytest.mark.asyncio
    async def test_variable_visible_inside_generator_expression(self, sample_df):
        """A top-level variable must be visible inside a generator expression."""
        tool = PythonPandasTool(dataframes={"a": sample_df})
        code = (
            "factor = 10\n"
            "total = sum(v * factor for v in [1, 2, 3])\n"
            "print('TOTAL', total)\n"
        )
        out = await tool._execute(code)
        assert "NameError" not in out
        assert "TOTAL 60" in out

    @pytest.mark.asyncio
    async def test_helper_used_in_comprehension_over_dataframe(self, sample_df):
        """Mirrors the financial_projection compute.py failure pattern."""
        tool = PythonPandasTool(dataframes={"sales": sample_df})
        code = (
            "def _label(name):\n"
            "    return name.upper()\n"
            "labels = [_label(n) for n in sales['name']]\n"
            "print('LABELS', labels)\n"
        )
        out = await tool._execute(code)
        assert "NameError" not in out
        assert "LABELS ['ALICE', 'BOB', 'CHARLIE']" in out
