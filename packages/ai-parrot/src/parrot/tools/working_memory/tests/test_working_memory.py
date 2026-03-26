"""
Tests for WorkingMemoryToolkit.

Validates:
  - Pydantic input validation
  - Async method execution
  - Full workflow: store → compute → merge → summarize → import
  - Error handling with catalog persistence
  - DSL validation rejects malformed specs
  - Integration: real AbstractToolkit inheritance and package imports
"""
import pytest
import pandas as pd
import numpy as np

from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.models import (
    OperationSpecInput,
    OperationType,
    AggFunc,
    JoinHow,
    FilterSpec,
    JoinOnSpec,
    ComputeAndStoreInput,
    StoreInput,
    MergeStoredInput,
    SummarizeStoredInput,
    ImportFromToolInput,
)


# ─────────────────────────────────────────────
# Pydantic Validation Tests
# ─────────────────────────────────────────────

class TestPydanticValidation:
    """Ensures the DSL contract rejects malformed inputs."""

    def test_valid_filter_spec(self):
        spec = OperationSpecInput(
            op=OperationType.FILTER,
            source="census",
            store_as="filtered",
            filters=[FilterSpec(column="STATE", op="==", value="CA")],
        )
        assert spec.op == OperationType.FILTER
        assert len(spec.filters) == 1
        assert spec.filters[0].column == "STATE"

    def test_valid_aggregate_spec(self):
        spec = OperationSpecInput(
            op=OperationType.AGGREGATE,
            source="census",
            store_as="agg",
            group_by=["STATE"],
            agg_rules={"POPULATION": AggFunc.SUM, "MEDIAN_EARNINGS_2023_25plus_yrs": AggFunc.MEAN},
        )
        assert spec.agg_rules["POPULATION"] == AggFunc.SUM

    def test_valid_join_spec(self):
        spec = OperationSpecInput(
            op=OperationType.JOIN,
            source="census",
            store_as="joined",
            right_source="sales",
            join_on=JoinOnSpec(left="COUNTY_FIPS", right="FIPS_CODE"),
            join_how=JoinHow.LEFT,
        )
        assert spec.join_on.left == "COUNTY_FIPS"
        assert spec.join_how == JoinHow.LEFT

    def test_invalid_op_rejected(self):
        with pytest.raises(ValueError):
            OperationSpecInput(
                op="invalid_operation",
                source="census",
                store_as="nope",
            )

    def test_invalid_join_how_rejected(self):
        with pytest.raises(ValueError):
            OperationSpecInput(
                op=OperationType.JOIN,
                source="a",
                store_as="b",
                join_how="cartesian",  # not in JoinHow
            )

    def test_invalid_agg_func_rejected(self):
        with pytest.raises(ValueError):
            OperationSpecInput(
                op=OperationType.AGGREGATE,
                source="a",
                store_as="b",
                agg_rules={"col": "nonexistent_func"},
            )

    def test_compute_input_model(self):
        """Validates the full ComputeAndStoreInput wrapper."""
        inp = ComputeAndStoreInput(
            spec=OperationSpecInput(
                op=OperationType.CORRELATE,
                source="joined",
                store_as="corr",
                columns=["A", "B"],
                method="spearman",
            ),
            description="Test correlation",
            turn_id="turn_1",
        )
        assert inp.spec.method == "spearman"
        assert inp.turn_id == "turn_1"

    def test_merge_input_model(self):
        inp = MergeStoredInput(
            keys=["a", "b", "c"],
            store_as="merged",
            merge_on="STATE",
            merge_how="left",
        )
        assert len(inp.keys) == 3

    def test_summarize_input_model(self):
        inp = SummarizeStoredInput(
            keys=["x", "y"],
            store_as="summary",
            agg_rules={"col1": "sum", "col2": "mean"},
            group_by=["STATE"],
        )
        assert inp.agg_rules["col1"] == "sum"


# ─────────────────────────────────────────────
# Async Tool Method Tests
# ─────────────────────────────────────────────

class TestAsyncMethods:
    """Tests the async tool methods that AbstractToolkit will discover."""

    @pytest.mark.asyncio
    async def test_list_stored(self, toolkit):
        result = await toolkit.list_stored()
        assert result["count"] == 2
        keys = [e["key"] for e in result["entries"]]
        assert "census_raw" in keys

    @pytest.mark.asyncio
    async def test_get_stored(self, toolkit):
        result = await toolkit.get_stored("census_raw")
        assert result["shape"]["rows"] == 500
        assert "MEDIAN_EARNINGS_2023_25plus_yrs" in result["columns"]

    @pytest.mark.asyncio
    async def test_drop_stored(self, toolkit):
        result = await toolkit.drop_stored("census_raw")
        assert result["status"] == "dropped"
        listing = await toolkit.list_stored()
        assert listing["count"] == 1

    @pytest.mark.asyncio
    async def test_compute_filter(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "filter",
            "source": "census_raw",
            "filters": [{"column": "STATE", "op": "==", "value": "CA"}],
            "store_as": "census_ca",
        })
        assert result["status"] == "computed_and_stored"
        entry = toolkit._catalog.get("census_ca")
        assert (entry.df["STATE"] == "CA").all()

    @pytest.mark.asyncio
    async def test_compute_aggregate(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "aggregate",
            "source": "census_raw",
            "group_by": ["STATE"],
            "agg_rules": {"POPULATION": "sum", "MEDIAN_EARNINGS_2023_25plus_yrs": "mean"},
            "store_as": "by_state",
        })
        assert result["status"] == "computed_and_stored"
        df = toolkit._catalog.get("by_state").df
        assert len(df) == 5

    @pytest.mark.asyncio
    async def test_compute_join(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "join",
            "source": "census_raw",
            "right_source": "sales_raw",
            "join_on": {"left": "COUNTY_FIPS", "right": "FIPS_CODE"},
            "join_how": "inner",
            "store_as": "joined",
        })
        assert result["status"] == "computed_and_stored"
        df = toolkit._catalog.get("joined").df
        assert "TOTAL_SALES" in df.columns

    @pytest.mark.asyncio
    async def test_compute_correlate(self, toolkit):
        await toolkit.compute_and_store({
            "op": "join",
            "source": "census_raw",
            "right_source": "sales_raw",
            "join_on": {"left": "COUNTY_FIPS", "right": "FIPS_CODE"},
            "join_how": "inner",
            "store_as": "for_corr",
        })
        result = await toolkit.compute_and_store({
            "op": "correlate",
            "source": "for_corr",
            "columns": ["MEDIAN_EARNINGS_2023_25plus_yrs", "TOTAL_SALES", "POPULATION"],
            "method": "pearson",
            "store_as": "corr_matrix",
        })
        assert result["status"] == "computed_and_stored"
        df = toolkit._catalog.get("corr_matrix").df
        assert len(df) == 3

    @pytest.mark.asyncio
    async def test_compute_group_correlate(self, toolkit):
        await toolkit.compute_and_store({
            "op": "join",
            "source": "census_raw",
            "right_source": "sales_raw",
            "join_on": {"left": "COUNTY_FIPS", "right": "FIPS_CODE"},
            "join_how": "inner",
            "store_as": "for_gcorr",
        })
        result = await toolkit.compute_and_store({
            "op": "group_correlate",
            "source": "for_gcorr",
            "group_by": ["STATE"],
            "columns": ["MEDIAN_EARNINGS_2023_25plus_yrs", "TOTAL_SALES"],
            "store_as": "corr_by_state",
        })
        assert result["status"] == "computed_and_stored"
        df = toolkit._catalog.get("corr_by_state").df
        assert len(df) == 5

    @pytest.mark.asyncio
    async def test_compute_rank(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "rank",
            "source": "census_raw",
            "rank_column": "MEDIAN_EARNINGS_2023_25plus_yrs",
            "rank_ascending": False,
            "store_as": "ranked",
        })
        assert result["status"] == "computed_and_stored"
        df = toolkit._catalog.get("ranked").df
        assert "_rank" in df.columns

    @pytest.mark.asyncio
    async def test_compute_select(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "select",
            "source": "census_raw",
            "select_columns": ["STATE", "POPULATION"],
            "store_as": "slim",
        })
        df = toolkit._catalog.get("slim").df
        assert list(df.columns) == ["STATE", "POPULATION"]

    @pytest.mark.asyncio
    async def test_compute_describe(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "describe",
            "source": "census_raw",
            "columns": ["POPULATION", "POVERTY_RATE"],
            "store_as": "stats",
        })
        df = toolkit._catalog.get("stats").df
        assert "stat" in df.columns


# ─────────────────────────────────────────────
# Error Handling
# ─────────────────────────────────────────────

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_missing_source_stores_error(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "filter",
            "source": "nonexistent",
            "filters": [],
            "store_as": "should_fail",
        })
        assert result["status"] == "error"
        assert "not found" in result["error"]
        entry = toolkit._catalog.get("should_fail")
        assert entry.error is not None

    @pytest.mark.asyncio
    async def test_bad_column_stores_error(self, toolkit):
        result = await toolkit.compute_and_store({
            "op": "filter",
            "source": "census_raw",
            "filters": [{"column": "NOPE", "op": "==", "value": "x"}],
            "store_as": "col_err",
        })
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_error_visible_in_listing(self, toolkit):
        await toolkit.compute_and_store({
            "op": "correlate",
            "source": "census_raw",
            "columns": ["FAKE_A", "FAKE_B"],
            "store_as": "bad_corr",
        })
        listing = await toolkit.list_stored()
        bad = [e for e in listing["entries"] if e["key"] == "bad_corr"]
        assert len(bad) == 1
        assert "error" in bad[0]


# ─────────────────────────────────────────────
# Merge & Summarize
# ─────────────────────────────────────────────

class TestMergeAndSummarize:
    @pytest.mark.asyncio
    async def test_merge_with_key(self, toolkit):
        await toolkit.compute_and_store({
            "op": "aggregate",
            "source": "census_raw",
            "group_by": ["STATE"],
            "agg_rules": {"POPULATION": "sum"},
            "store_as": "agg1",
        })
        await toolkit.compute_and_store({
            "op": "join",
            "source": "census_raw",
            "right_source": "sales_raw",
            "join_on": {"left": "COUNTY_FIPS", "right": "FIPS_CODE"},
            "join_how": "inner",
            "store_as": "_tmp_j",
        })
        await toolkit.compute_and_store({
            "op": "aggregate",
            "source": "_tmp_j",
            "group_by": ["STATE"],
            "agg_rules": {"TOTAL_SALES": "sum"},
            "store_as": "agg2",
        })
        result = await toolkit.merge_stored(
            keys=["agg1", "agg2"],
            store_as="merged",
            merge_on="STATE",
        )
        assert result["status"] == "merged"
        df = toolkit._catalog.get("merged").df
        assert "POPULATION" in df.columns
        assert "TOTAL_SALES" in df.columns

    @pytest.mark.asyncio
    async def test_merge_concat(self, toolkit):
        await toolkit.compute_and_store({
            "op": "filter",
            "source": "census_raw",
            "filters": [{"column": "STATE", "op": "==", "value": "CA"}],
            "store_as": "ca",
        })
        await toolkit.compute_and_store({
            "op": "filter",
            "source": "census_raw",
            "filters": [{"column": "STATE", "op": "==", "value": "TX"}],
            "store_as": "tx",
        })
        result = await toolkit.merge_stored(keys=["ca", "tx"], store_as="ca_tx")
        assert result["status"] == "merged"

    @pytest.mark.asyncio
    async def test_summarize(self, toolkit):
        await toolkit.compute_and_store({
            "op": "aggregate",
            "source": "census_raw",
            "group_by": ["STATE"],
            "agg_rules": {"POPULATION": "sum"},
            "store_as": "s1",
        })
        await toolkit.compute_and_store({
            "op": "join",
            "source": "census_raw",
            "right_source": "sales_raw",
            "join_on": {"left": "COUNTY_FIPS", "right": "FIPS_CODE"},
            "join_how": "inner",
            "store_as": "_tj",
        })
        await toolkit.compute_and_store({
            "op": "aggregate",
            "source": "_tj",
            "group_by": ["STATE"],
            "agg_rules": {"TOTAL_SALES": "sum"},
            "store_as": "s2",
        })
        result = await toolkit.summarize_stored(
            keys=["s1", "s2"],
            store_as="final",
            agg_rules={"POPULATION": "sum", "TOTAL_SALES": "sum"},
            merge_on="STATE",
        )
        assert result["status"] == "summarized"


# ─────────────────────────────────────────────
# Import from Tool Bridge
# ─────────────────────────────────────────────

class TestImportFromTool:
    @pytest.mark.asyncio
    async def test_import_success(self, census_df):
        tk = WorkingMemoryToolkit(
            tool_locals_registry={"PythonPandasTool": {"df_census": census_df}},
        )
        result = await tk.import_from_tool(
            tool_name="PythonPandasTool",
            variable_name="df_census",
            store_as="imported",
        )
        assert result["status"] == "imported"
        assert result["summary"]["shape"]["rows"] == 500

        # Verify deep copy
        census_df.drop(census_df.index, inplace=True)
        assert len(tk._catalog.get("imported").df) == 500

    @pytest.mark.asyncio
    async def test_import_not_dataframe(self):
        tk = WorkingMemoryToolkit(
            tool_locals_registry={"REPL": {"x": 42}},
        )
        result = await tk.import_from_tool("REPL", "x", "nope")
        assert result["status"] == "error"
        assert "not a DataFrame" in result["error"]

    @pytest.mark.asyncio
    async def test_import_missing_tool(self):
        tk = WorkingMemoryToolkit()
        result = await tk.import_from_tool("Ghost", "df", "nope")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_list_tool_dataframes(self, census_df, sales_df):
        tk = WorkingMemoryToolkit(
            tool_locals_registry={"PT": {"df1": census_df, "df2": sales_df, "x": 42}},
        )
        result = await tk.list_tool_dataframes()
        assert "PT" in result
        assert "df1" in result["PT"]
        assert "x" not in result["PT"]


# ─────────────────────────────────────────────
# Full End-to-End Workflow
# ─────────────────────────────────────────────

class TestFullWorkflow:
    @pytest.mark.asyncio
    async def test_census_sales_analysis(self, census_df, sales_df):
        """Simulates a complete agent session analyzing census vs sales."""
        tk = WorkingMemoryToolkit(
            session_id="analysis-001",
            max_rows=5,
            max_cols=15,
            tool_locals_registry={
                "PythonPandasTool": {"df_census": census_df, "df_sales": sales_df},
            },
        )

        # 1. Import from PandasTool
        r = await tk.import_from_tool("PythonPandasTool", "df_census", "census")
        assert r["status"] == "imported"
        r = await tk.import_from_tool("PythonPandasTool", "df_sales", "sales")
        assert r["status"] == "imported"

        # 2. Join
        r = await tk.compute_and_store({
            "op": "join",
            "source": "census",
            "right_source": "sales",
            "join_on": {"left": "COUNTY_FIPS", "right": "FIPS_CODE"},
            "join_how": "inner",
            "store_as": "census_sales",
        }, turn_id="t1")
        assert r["status"] == "computed_and_stored"

        # 3. Filter
        r = await tk.compute_and_store({
            "op": "filter",
            "source": "census_sales",
            "filters": [{"column": "POPULATION", "op": ">", "value": 100000}],
            "store_as": "large_counties",
        }, turn_id="t1")
        assert r["status"] == "computed_and_stored"

        # 4. Correlate
        r = await tk.compute_and_store({
            "op": "correlate",
            "source": "large_counties",
            "columns": ["MEDIAN_EARNINGS_2023_25plus_yrs", "TOTAL_SALES", "POPULATION"],
            "store_as": "corr_large",
        }, turn_id="t1")
        assert r["status"] == "computed_and_stored"

        # 5. Aggregate by state
        r = await tk.compute_and_store({
            "op": "aggregate",
            "source": "large_counties",
            "group_by": ["STATE"],
            "agg_rules": {
                "TOTAL_SALES": "sum",
                "POPULATION": "sum",
                "MEDIAN_EARNINGS_2023_25plus_yrs": "mean",
            },
            "store_as": "state_summary",
        }, turn_id="t2")
        assert r["status"] == "computed_and_stored"

        # 6. Group correlation
        r = await tk.compute_and_store({
            "op": "group_correlate",
            "source": "large_counties",
            "group_by": ["STATE"],
            "columns": ["MEDIAN_EARNINGS_2023_25plus_yrs", "TOTAL_SALES"],
            "store_as": "corr_by_state",
        }, turn_id="t2")
        assert r["status"] == "computed_and_stored"

        # Verify everything
        listing = await tk.list_stored()
        assert listing["count"] == 7

        # Summaries are compact
        for entry in listing["entries"]:
            if entry.get("preview"):
                assert len(entry["preview"]) <= 5

        # Agent can inspect correlation
        corr = await tk.get_stored("corr_large")
        assert "numeric_stats" in corr


# ─────────────────────────────────────────────
# Integration Tests
# ─────────────────────────────────────────────

class TestIntegration:
    def test_import_from_parrot_tools(self):
        """Verify the package-level import works."""
        from parrot.tools.working_memory import WorkingMemoryToolkit
        assert WorkingMemoryToolkit is not None

    def test_toolkit_inherits_abstract(self):
        """Verify WorkingMemoryToolkit inherits from the real AbstractToolkit."""
        from parrot.tools.working_memory import WorkingMemoryToolkit
        from parrot.tools.toolkit import AbstractToolkit
        assert issubclass(WorkingMemoryToolkit, AbstractToolkit)
