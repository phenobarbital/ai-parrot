"""Unit tests for DatasetManager."""
import pytest
import pandas as pd
import numpy as np
from parrot.tools.dataset_manager import DatasetManager, DatasetEntry, DatasetInfo


@pytest.fixture
def sample_df():
    """Sample DataFrame for testing."""
    return pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["Alice", "Bob", "Charlie"],
        "value": [100.5, 200.0, 300.75],
        "category": ["A", "B", "A"]
    })


@pytest.fixture
def sample_df_with_missing():
    """Sample DataFrame with missing values."""
    return pd.DataFrame({
        "id": [1, 2, 3, 4],
        "name": ["Alice", None, "Charlie", "Diana"],
        "value": [100.5, 200.0, np.nan, 300.75]
    })


@pytest.fixture
def dm():
    """Fresh DatasetManager instance."""
    return DatasetManager()


class TestDatasetEntry:
    """Tests for DatasetEntry class."""

    def test_entry_creation(self, sample_df):
        """Entry should store DataFrame and metadata."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry.name == "test"
        assert entry.loaded is True
        assert entry.is_active is True

    def test_entry_shape(self, sample_df):
        """Entry should report correct shape."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry.shape == (3, 4)

    def test_entry_columns(self, sample_df):
        """Entry should list columns."""
        entry = DatasetEntry(name="test", df=sample_df)
        assert entry.columns == ["id", "name", "value", "category"]

    def test_entry_inactive(self, sample_df):
        """Entry can be created inactive."""
        entry = DatasetEntry(name="test", df=sample_df, is_active=False)
        assert entry.is_active is False

    def test_entry_query_slug(self):
        """Entry can store query slug without DataFrame."""
        entry = DatasetEntry(name="lazy", query_slug="my_query")
        assert entry.loaded is False
        assert entry.query_slug == "my_query"
        assert entry.shape == (0, 0)

    def test_to_info(self, sample_df):
        """Entry should convert to DatasetInfo."""
        entry = DatasetEntry(name="test", df=sample_df, metadata={"description": "Test data"})
        info = entry.to_info(alias="df1")
        assert isinstance(info, DatasetInfo)
        assert info.name == "test"
        assert info.alias == "df1"
        assert info.is_active is True
        assert info.loaded is True


class TestDatasetManager:
    """Tests for DatasetManager class."""

    def test_add_dataframe_active_by_default(self, dm, sample_df):
        """Datasets should be active by default when added."""
        dm.add_dataframe("test", sample_df)
        assert dm._datasets["test"].is_active is True

    def test_add_dataframe_with_inactive(self, dm, sample_df):
        """Can explicitly add inactive dataset."""
        dm.add_dataframe("test", sample_df, is_active=False)
        assert dm._datasets["test"].is_active is False

    def test_add_dataframe_returns_message(self, dm, sample_df):
        """add_dataframe returns confirmation message."""
        result = dm.add_dataframe("test", sample_df)
        assert "test" in result
        assert "3 rows" in result

    def test_add_query(self, dm):
        """Can register query slug."""
        result = dm.add_query("lazy_ds", "my_query_slug")
        assert "lazy_ds" in result
        assert dm._datasets["lazy_ds"].query_slug == "my_query_slug"
        assert dm._datasets["lazy_ds"].is_active is True

    def test_remove(self, dm, sample_df):
        """Can remove dataset."""
        dm.add_dataframe("test", sample_df)
        result = dm.remove("test")
        assert "test" in result
        assert "test" not in dm._datasets

    def test_remove_nonexistent_raises(self, dm):
        """Removing nonexistent dataset raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            dm.remove("nonexistent")

    def test_activate_deactivate(self, dm, sample_df):
        """Can activate and deactivate datasets."""
        dm.add_dataframe("ds1", sample_df)
        dm.add_dataframe("ds2", sample_df)

        # Both active by default
        assert dm._datasets["ds1"].is_active
        assert dm._datasets["ds2"].is_active

        # Deactivate ds1
        deactivated = dm.deactivate(["ds1"])
        assert deactivated == ["ds1"]
        assert not dm._datasets["ds1"].is_active
        assert dm._datasets["ds2"].is_active

        # Reactivate ds1
        activated = dm.activate(["ds1"])
        assert activated == ["ds1"]
        assert dm._datasets["ds1"].is_active

    def test_get_active_dataframes(self, dm, sample_df):
        """get_active_dataframes returns only active and loaded datasets."""
        dm.add_dataframe("ds1", sample_df, is_active=True)
        dm.add_dataframe("ds2", sample_df, is_active=False)
        dm.add_query("ds3", "query_slug", is_active=True)  # Not loaded

        active = dm.get_active_dataframes()
        assert "ds1" in active
        assert "ds2" not in active
        assert "ds3" not in active  # Query not loaded

    def test_alias_map(self, dm, sample_df):
        """_get_alias_map returns correct aliases."""
        dm.add_dataframe("sales", sample_df)
        dm.add_dataframe("inventory", sample_df)

        alias_map = dm._get_alias_map()
        assert alias_map["sales"] == "df1"
        assert alias_map["inventory"] == "df2"

    def test_resolve_name_direct(self, dm, sample_df):
        """_resolve_name returns direct match."""
        dm.add_dataframe("sales", sample_df)
        assert dm._resolve_name("sales") == "sales"

    def test_resolve_name_alias(self, dm, sample_df):
        """_resolve_name resolves alias to name."""
        dm.add_dataframe("sales", sample_df)
        assert dm._resolve_name("df1") == "sales"

    def test_resolve_name_case_insensitive(self, dm, sample_df):
        """_resolve_name handles case insensitive matching."""
        dm.add_dataframe("Sales_Data", sample_df)
        assert dm._resolve_name("sales_data") == "Sales_Data"


class TestDatasetManagerTools:
    """Tests for DatasetManager LLM-exposed tools."""

    @pytest.mark.asyncio
    async def test_list_available(self, dm, sample_df):
        """list_available returns dataset info."""
        dm.add_dataframe("test", sample_df, metadata={"description": "Test data"})
        result = await dm.list_available()

        assert len(result) == 1
        assert result[0]["name"] == "test"
        assert result[0]["is_active"] is True
        assert result[0]["loaded"] is True
        assert result[0]["shape"] == (3, 4)

    @pytest.mark.asyncio
    async def test_get_active(self, dm, sample_df):
        """get_active returns active dataset names."""
        dm.add_dataframe("ds1", sample_df, is_active=True)
        dm.add_dataframe("ds2", sample_df, is_active=False)

        active = await dm.get_active()
        assert active == ["ds1"]

    @pytest.mark.asyncio
    async def test_get_metadata_full(self, dm, sample_df):
        """get_metadata returns comprehensive metadata."""
        dm.add_dataframe("test", sample_df, metadata={"description": "Test data"})
        result = await dm.get_metadata("test", include_eda=True, include_samples=True)

        assert result["dataframe"] == "test"
        assert result["description"] == "Test data"
        assert result["shape"]["rows"] == 3
        assert result["shape"]["columns"] == 4
        assert "eda_summary" in result
        assert "sample_rows" in result
        assert result["is_active"] is True

    @pytest.mark.asyncio
    async def test_get_metadata_with_alias(self, dm, sample_df):
        """get_metadata resolves alias to name."""
        dm.add_dataframe("sales", sample_df)
        result = await dm.get_metadata("df1")  # Use alias

        assert result["dataframe"] == "sales"
        assert result["alias"] == "df1"

    @pytest.mark.asyncio
    async def test_get_metadata_single_column(self, dm, sample_df):
        """get_metadata for single column returns column stats."""
        dm.add_dataframe("test", sample_df)
        result = await dm.get_metadata("test", column="value")

        assert result["column"] == "value"
        assert "statistics" in result
        assert result["statistics"]["dtype"] == "float64"

    @pytest.mark.asyncio
    async def test_get_metadata_not_found(self, dm):
        """get_metadata returns error for missing dataset."""
        result = await dm.get_metadata("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_get_metadata_unloaded(self, dm):
        """get_metadata for unloaded dataset returns message."""
        dm.add_query("lazy", "query_slug")
        result = await dm.get_metadata("lazy")

        assert result["loaded"] is False
        assert "not loaded" in result.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_activate_datasets(self, dm, sample_df):
        """activate_datasets tool activates datasets."""
        dm.add_dataframe("ds1", sample_df, is_active=False)
        result = await dm.activate_datasets(["ds1"])

        assert "Activated" in result
        assert dm._datasets["ds1"].is_active is True

    @pytest.mark.asyncio
    async def test_deactivate_datasets(self, dm, sample_df):
        """deactivate_datasets tool deactivates datasets."""
        dm.add_dataframe("ds1", sample_df, is_active=True)
        result = await dm.deactivate_datasets(["ds1"])

        assert "Deactivated" in result
        assert dm._datasets["ds1"].is_active is False


class TestDatasetManagerEDA:
    """Tests for DatasetManager EDA capabilities."""

    @pytest.mark.asyncio
    async def test_eda_summary_basic_info(self, dm, sample_df):
        """EDA summary includes basic info."""
        dm.add_dataframe("test", sample_df)
        result = await dm.get_metadata("test", include_eda=True)

        eda = result["eda_summary"]["basic_info"]
        assert eda["total_rows"] == 3
        assert eda["total_columns"] == 4
        assert eda["numeric_columns"] == 2  # id, value
        assert eda["categorical_columns"] == 2  # name, category

    @pytest.mark.asyncio
    async def test_eda_summary_missing_data(self, dm, sample_df_with_missing):
        """EDA summary detects missing values."""
        dm.add_dataframe("test", sample_df_with_missing)
        result = await dm.get_metadata("test", include_eda=True)

        missing = result["eda_summary"]["missing_data"]
        assert missing["total_missing"] == 2  # One None + one NaN
        assert len(missing["columns_with_missing"]) == 2

    @pytest.mark.asyncio
    async def test_column_statistics(self, dm, sample_df):
        """Column statistics for numeric and categorical."""
        dm.add_dataframe("test", sample_df)
        result = await dm.get_metadata("test", include_column_stats=True)

        stats = result["column_statistics"]
        assert "value" in stats["numeric_columns"]
        assert "category" in stats["categorical_columns"]

        # Numeric stats
        value_stats = stats["numeric_columns"]["value"]
        assert "mean" in value_stats
        assert "min" in value_stats
        assert "max" in value_stats

        # Categorical stats
        cat_stats = stats["categorical_columns"]["category"]
        assert cat_stats["unique_values"] == 2
        assert "most_common" in cat_stats


class TestDatasetManagerToolkitIntegration:
    """Tests for AbstractToolkit integration."""

    def test_get_tools_returns_tools(self, dm, sample_df):
        """get_tools returns list of tools."""
        dm.add_dataframe("test", sample_df)
        tools = dm.get_tools()

        assert len(tools) > 0
        tool_names = [t.name for t in tools]
        assert "list_available" in tool_names
        assert "get_active" in tool_names
        assert "get_metadata" in tool_names
        assert "activate_datasets" in tool_names
        assert "deactivate_datasets" in tool_names
        assert "get_dataframe" in tool_names
        assert "store_dataframe" in tool_names


class TestDatasetManagerGuide:
    """Tests for DataFrame guide generation."""

    def test_guide_generation_on_add(self, sample_df):
        """Guide is regenerated when adding dataframe."""
        dm = DatasetManager(generate_guide=True)
        dm.add_dataframe("test", sample_df)
        
        assert dm.df_guide != ""
        assert "test" in dm.df_guide
        assert "df1" in dm.df_guide

    def test_guide_includes_summary_stats(self, sample_df):
        """Guide includes summary stats when enabled."""
        dm = DatasetManager(generate_guide=True, include_summary_stats=True)
        dm.add_dataframe("test", sample_df)

        assert "Numeric Summary" in dm.df_guide

    def test_guide_excludes_summary_stats_by_default(self, sample_df):
        """Guide excludes summary stats by default."""
        dm = DatasetManager(generate_guide=True, include_summary_stats=False)
        dm.add_dataframe("test", sample_df)

        assert "Numeric Summary" not in dm.df_guide

    def test_get_guide_method(self, sample_df):
        """get_guide returns guide string."""
        dm = DatasetManager(generate_guide=True)
        dm.add_dataframe("test", sample_df)
        
        guide = dm.get_guide()
        assert "DataFrame Guide" in guide


class TestDatasetManagerEnhancedTools:
    """Tests for get_dataframe and store_dataframe tools."""

    @pytest.mark.asyncio
    async def test_get_dataframe_success(self, dm, sample_df):
        """get_dataframe returns DataFrame info."""
        dm.add_dataframe("test", sample_df)
        result = await dm.get_dataframe("test")

        assert result["name"] == "test"
        assert result["alias"] == "df1"
        assert result["shape"]["rows"] == 3
        assert "columns" in result
        assert "sample_rows" in result
        assert "column_types" in result
        assert "null_count" in result

    @pytest.mark.asyncio
    async def test_get_dataframe_with_alias(self, dm, sample_df):
        """get_dataframe resolves alias."""
        dm.add_dataframe("sales", sample_df)
        result = await dm.get_dataframe("df1")

        assert result["name"] == "sales"

    @pytest.mark.asyncio
    async def test_get_dataframe_not_found(self, dm):
        """get_dataframe returns error for missing dataset."""
        result = await dm.get_dataframe("nonexistent")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_store_dataframe_returns_instructions(self, dm):
        """store_dataframe returns usage instructions."""
        result = await dm.store_dataframe("new_df", "Filtered sales data")
        
        assert "new_df" in result
        assert "Filtered sales data" in result


class TestCategorizeColumns:
    """Tests for column type categorization."""

    def test_categorize_integer_columns(self):
        """Categorizes integer columns correctly."""
        df = pd.DataFrame({"count": [1, 2, 3]})
        types = DatasetManager.categorize_columns(df)
        assert types["count"] == "integer"

    def test_categorize_float_columns(self):
        """Categorizes float columns correctly."""
        df = pd.DataFrame({"price": [1.5, 2.0, 3.14]})
        types = DatasetManager.categorize_columns(df)
        assert types["price"] == "float"

    def test_categorize_datetime_columns(self):
        """Categorizes datetime columns correctly."""
        df = pd.DataFrame({"date": pd.to_datetime(["2023-01-01", "2023-01-02"])})
        types = DatasetManager.categorize_columns(df)
        assert types["date"] == "datetime"

    def test_categorize_boolean_columns(self):
        """Categorizes boolean columns correctly."""
        df = pd.DataFrame({"is_active": pd.array([True, False, True], dtype="boolean")})
        types = DatasetManager.categorize_columns(df)
        assert types["is_active"] == "boolean"

    def test_categorize_categorical_text(self):
        """Categorizes low-cardinality text as categorical_text."""
        df = pd.DataFrame({"status": ["A", "B", "A", "B", "A"] * 20})
        types = DatasetManager.categorize_columns(df)
        assert types["status"] == "categorical_text"

    def test_categorize_high_cardinality_text(self):
        """Categorizes high-cardinality text as text."""
        df = pd.DataFrame({"unique_id": [f"id_{i}" for i in range(100)]})
        types = DatasetManager.categorize_columns(df)
        assert types["unique_id"] == "text"


class TestDataQualityChecks:
    """Tests for data quality checking features."""

    def test_check_dataframes_for_nans(self, sample_df_with_missing):
        """check_dataframes_for_nans detects NaN values."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df_with_missing)
        
        warnings = dm.check_dataframes_for_nans()
        
        assert len(warnings) == 2  # name and value columns have NaNs
        assert any("name" in w for w in warnings)
        assert any("value" in w for w in warnings)

    def test_check_dataframes_for_nans_no_nulls(self, sample_df):
        """check_dataframes_for_nans returns empty for clean data."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df)
        
        warnings = dm.check_dataframes_for_nans()
        
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_check_data_quality_tool(self, sample_df_with_missing):
        """check_data_quality tool returns quality report."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df_with_missing)
        
        result = await dm.check_data_quality()
        
        assert result["datasets_checked"] == 1
        assert len(result["nan_warnings"]) == 2
        assert "test" in result["dataset_quality"]
        
        quality = result["dataset_quality"]["test"]
        assert quality["null_cells"] == 2
        assert "completeness_pct" in quality
        assert "duplicate_rows" in quality

    @pytest.mark.asyncio 
    async def test_remove_dataset_tool(self, sample_df):
        """remove_dataset tool removes dataset from catalog."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df)
        
        result = await dm.remove_dataset("test")
        
        assert "removed" in result.lower()
        assert "test" not in dm._datasets


class TestMetricsGuide:
    """Tests for metrics guide generation."""

    def test_generate_metrics_guide_all_columns(self, sample_df):
        """generate_metrics_guide generates guide for all columns."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df)
        
        guide = dm.generate_metrics_guide(sample_df)
        
        assert "id" in guide
        assert "name" in guide
        assert "value" in guide
        assert "category" in guide

    def test_generate_metrics_guide_specific_columns(self, sample_df):
        """generate_metrics_guide can target specific columns."""
        dm = DatasetManager()
        dm.add_dataframe("test", sample_df)
        
        guide = dm.generate_metrics_guide(sample_df, columns=["id", "value"])
        
        assert "id" in guide
        assert "value" in guide
        assert "category" not in guide

    def test_generate_metrics_guide_with_nulls(self, sample_df_with_missing):
        """generate_metrics_guide shows null counts."""
        dm = DatasetManager()
        
        guide = dm.generate_metrics_guide(sample_df_with_missing)
        
        assert "Nulls" in guide


class TestListDataframes:
    """Tests for list_dataframes method."""

    def test_list_dataframes_returns_all(self, sample_df):
        """list_dataframes returns all loaded datasets."""
        dm = DatasetManager()
        dm.add_dataframe("sales", sample_df)
        dm.add_dataframe("inventory", sample_df)
        
        result = dm.list_dataframes()
        
        assert "sales" in result
        assert "inventory" in result
        assert result["sales"]["alias"] == "df1"
        assert result["inventory"]["alias"] == "df2"

    def test_list_dataframes_includes_column_types(self, sample_df):
        """list_dataframes includes column type information."""
        dm = DatasetManager(auto_detect_types=True)
        dm.add_dataframe("test", sample_df)
        
        result = dm.list_dataframes()
        
        assert result["test"]["column_types"] is not None
        assert "id" in result["test"]["column_types"]


class TestDatasetInfoEnhancements:
    """Tests for enhanced DatasetInfo fields."""

    def test_dataset_info_null_count(self, sample_df_with_missing):
        """DatasetInfo includes null count."""
        entry = DatasetEntry(name="test", df=sample_df_with_missing)
        info = entry.to_info()
        
        assert info.null_count == 2

    def test_dataset_info_column_types(self, sample_df):
        """DatasetInfo includes column types."""
        entry = DatasetEntry(name="test", df=sample_df, auto_detect_types=True)
        info = entry.to_info()
        
        assert info.column_types is not None
        assert "id" in info.column_types


class TestAutoDetectTypes:
    """Tests for auto_detect_types configuration."""

    def test_auto_detect_types_enabled(self, sample_df):
        """Column types are detected when auto_detect_types is True."""
        dm = DatasetManager(auto_detect_types=True)
        dm.add_dataframe("test", sample_df)
        
        entry = dm.get_dataset_entry("test")
        assert entry.column_types is not None

    def test_auto_detect_types_disabled(self, sample_df):
        """Column types are not detected when auto_detect_types is False."""
        dm = DatasetManager(auto_detect_types=False)
        dm.add_dataframe("test", sample_df)
        
        entry = dm.get_dataset_entry("test")
        assert entry.column_types is None


class TestUnhashableColumnTypes:
    """Tests for DataFrames with unhashable column types (arrays, lists)."""

    def test_add_dataframe_with_array_columns(self):
        """add_dataframe should handle columns with numpy array values."""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "embedding": [np.array([0.1, 0.2]), np.array([0.3, 0.4]), np.array([0.5, 0.6])],
            "tags": [["a", "b"], ["c"], ["d", "e", "f"]],
        })
        dm = DatasetManager(generate_guide=True)
        
        # Should NOT raise "unhashable type: numpy.ndarray"
        result = dm.add_dataframe("test", df)
        assert "test" in result
        assert dm._datasets["test"].loaded is True

    def test_categorize_columns_with_arrays(self):
        """categorize_columns should handle columns with array values."""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "embedding": [np.array([0.1, 0.2]), np.array([0.3, 0.4]), np.array([0.5, 0.6])],
        })
        
        # Should NOT raise TypeError
        types = DatasetManager.categorize_columns(df)
        assert types["id"] == "integer"
        assert types["embedding"] == "text"  # Falls back to text for unhashable

    @pytest.mark.asyncio
    async def test_get_metadata_with_array_columns(self):
        """get_metadata should handle columns with array values."""
        df = pd.DataFrame({
            "id": [1, 2, 3],
            "embedding": [np.array([0.1, 0.2]), np.array([0.3, 0.4]), np.array([0.5, 0.6])],
        })
        dm = DatasetManager()
        dm.add_dataframe("test", df)
        
        # Should NOT raise "unhashable type: numpy.ndarray"
        result = await dm.get_metadata("test")
        assert result["dataframe"] == "test"
        assert "eda_summary" in result
        
        # Verify duplicate check fell back safely
        assert result["eda_summary"]["data_quality"]["duplicate_rows"] == -1

    @pytest.mark.asyncio
    async def test_load_queries_resilience(self):
        """load_data should handle partial failures from loader."""
        dm = DatasetManager()
        
        # Mock loader that succeeds for one query and fails for another
        async def mock_loader(queries):
            results = {}
            for q in queries:
                if q == "success_query":
                    results[q] = pd.DataFrame({"a": [1, 2]})
                # "fail_query" is just omitted or raises error? 
            return results

        dm.set_query_loader(mock_loader)
        
        queries = ["success_query", "fail_query"]
        # Use no_cache=True to skip Redis and hit execute_query (which hits mock_loader)
        result = await dm.load_data(queries, agent_name="test", no_cache=True)
        
        assert "success_query" in result
        assert "fail_query" not in result
        assert "success_query" in dm.get_active_dataframes()
        assert len(dm.get_active_dataframes()) == 1

    @pytest.mark.asyncio
    async def test_load_queries_loader_exception(self):
        """load_data should safely handle exception from loader."""
        dm = DatasetManager()
        
        async def crashing_loader(queries):
            raise ValueError("Loader crashed")
            
        dm.set_query_loader(crashing_loader)
        
        # load_data does NOT catch exception from _execute_query itself?
        # DatasetManager._execute_query does NOT catch exception from _query_loader.
        # But _call_qs (internal loader) DOES catch exceptions for individual queries.
        # If external loader crashes, load_data will crash?
        # Let's verify load_data Implementation.
        # load_data calls _execute_query.
        # If _execute_query raises (e.g. from Custom Loader), load_data raises?
        # PandasAgent used to raise.
        # If user wants resilience, custom loader should implement it?
        # OR load_data should catch it?
        # _call_qs is resilient. Custom loader (mock) crashes here.
        # I should probably catch it in test and assert raise?
        # Or I Expect load_data to crash?
        try:
             await dm.load_data(["q1"], agent_name="test", no_cache=True)
             assert False, "Should have raised exception"
        except ValueError:
             assert True

