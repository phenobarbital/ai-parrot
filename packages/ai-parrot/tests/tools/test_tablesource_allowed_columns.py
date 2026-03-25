"""Unit tests for FEAT-061 — TableSource allowed_columns feature.

Covers:
- Construction: parameter storage, property, invalid names, empty list
- Schema filtering: prefetch filters to allowed columns, strict/lenient handling
- describe(): mentions restriction
- cache_key: includes allowed_columns hash
- fetch() validation: SELECT *, disallowed columns, valid columns
- Post-fetch DataFrame filtering (defense-in-depth)
- Backward compatibility: allowed_columns=None preserves all existing behavior
- DatasetManager.add_table_source() passthrough
"""

import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.dataset_manager.sources.table import TableSource
from parrot.tools.dataset_manager.tool import DatasetManager


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def restricted_source() -> TableSource:
    """TableSource restricted to id, name, department."""
    ts = TableSource(
        table="public.employees",
        driver="pg",
        allowed_columns=["id", "name", "department"],
    )
    ts._schema = {"id": "integer", "name": "varchar", "department": "varchar"}
    return ts


@pytest.fixture
def unrestricted_source() -> TableSource:
    """TableSource without allowed_columns (baseline)."""
    ts = TableSource(table="public.employees", driver="pg")
    ts._schema = {
        "id": "integer",
        "name": "varchar",
        "department": "varchar",
        "salary": "numeric",
        "ssn": "varchar",
    }
    return ts


@pytest.fixture
def full_schema() -> dict:
    """Simulated full schema from INFORMATION_SCHEMA."""
    return {
        "id": "integer",
        "name": "varchar",
        "department": "varchar",
        "salary": "numeric",
        "ssn": "varchar",
        "password_hash": "varchar",
    }


# ─────────────────────────────────────────────────────────────────────────────
# TestAllowedColumnsConstruction
# ─────────────────────────────────────────────────────────────────────────────


class TestAllowedColumnsConstruction:
    def test_allowed_columns_stored(self):
        """allowed_columns list is stored on the instance."""
        ts = TableSource(
            table="public.t",
            driver="pg",
            allowed_columns=["id", "name"],
        )
        assert ts._allowed_columns == ["id", "name"]

    def test_allowed_columns_none_default(self):
        """Without allowed_columns, _allowed_columns defaults to None."""
        ts = TableSource(table="public.t", driver="pg")
        assert ts._allowed_columns is None

    def test_allowed_columns_property(self):
        """allowed_columns property returns the stored list."""
        ts = TableSource(
            table="public.t",
            driver="pg",
            allowed_columns=["a", "b", "c"],
        )
        assert ts.allowed_columns == ["a", "b", "c"]

    def test_allowed_columns_property_none(self):
        """allowed_columns property returns None when not set."""
        ts = TableSource(table="public.t", driver="pg")
        assert ts.allowed_columns is None

    def test_allowed_columns_validated_invalid_name(self):
        """Column names with unsafe characters raise ValueError."""
        with pytest.raises(ValueError, match="Unsafe SQL"):
            TableSource(
                table="public.t",
                driver="pg",
                allowed_columns=["valid_col", "bad; DROP TABLE"],
            )

    def test_allowed_columns_validated_injection_attempt(self):
        """SQL-injection style names are rejected."""
        with pytest.raises(ValueError, match="Unsafe SQL"):
            TableSource(
                table="public.t",
                driver="pg",
                allowed_columns=["1invalid"],
            )

    def test_allowed_columns_empty_list_rejected(self):
        """Empty allowed_columns list raises ValueError."""
        with pytest.raises(ValueError, match="must not be an empty list"):
            TableSource(table="public.t", driver="pg", allowed_columns=[])

    def test_allowed_columns_defensive_copy(self):
        """Modifying input list after construction does not affect stored list."""
        cols = ["id", "name"]
        ts = TableSource(table="public.t", driver="pg", allowed_columns=cols)
        cols.append("salary")
        assert ts.allowed_columns == ["id", "name"]


# ─────────────────────────────────────────────────────────────────────────────
# TestSchemaFiltering
# ─────────────────────────────────────────────────────────────────────────────


class TestSchemaFiltering:
    @pytest.mark.asyncio
    async def test_schema_filtered_to_allowed(self, full_schema: dict):
        """prefetch_schema() filters _schema to allowed columns only."""
        ts = TableSource(
            table="public.employees",
            driver="pg",
            allowed_columns=["id", "name"],
        )

        with patch.object(ts, "_run_query", new_callable=AsyncMock) as mock_rq:
            # Simulate INFORMATION_SCHEMA result
            mock_rq.return_value = pd.DataFrame(
                [
                    {"column_name": col, "data_type": dtype}
                    for col, dtype in full_schema.items()
                ]
            )
            await ts.prefetch_schema()

        assert set(ts._schema.keys()) == {"id", "name"}
        assert "salary" not in ts._schema
        assert "ssn" not in ts._schema
        assert "password_hash" not in ts._schema

    @pytest.mark.asyncio
    async def test_schema_missing_allowed_column_strict(self, full_schema: dict):
        """When allowed_columns has a column not in the table, strict=True raises."""
        ts = TableSource(
            table="public.employees",
            driver="pg",
            allowed_columns=["id", "nonexistent_column"],
            strict_schema=True,
        )

        with patch.object(ts, "_run_query", new_callable=AsyncMock) as mock_rq:
            mock_rq.return_value = pd.DataFrame(
                [
                    {"column_name": col, "data_type": dtype}
                    for col, dtype in full_schema.items()
                ]
            )
            with pytest.raises(ValueError, match="nonexistent_column"):
                await ts.prefetch_schema()

    @pytest.mark.asyncio
    async def test_schema_missing_allowed_column_lenient(self, full_schema: dict):
        """When allowed_columns has a missing column, strict=False logs warning only."""
        ts = TableSource(
            table="public.employees",
            driver="pg",
            allowed_columns=["id", "ghost_col"],
            strict_schema=False,
        )

        with patch.object(ts, "_run_query", new_callable=AsyncMock) as mock_rq:
            mock_rq.return_value = pd.DataFrame(
                [
                    {"column_name": col, "data_type": dtype}
                    for col, dtype in full_schema.items()
                ]
            )
            # Should not raise
            await ts.prefetch_schema()

        # Schema has 'id' but not 'ghost_col'
        assert "id" in ts._schema
        assert "ghost_col" not in ts._schema

    @pytest.mark.asyncio
    async def test_schema_unrestricted_unchanged(self, full_schema: dict):
        """Without allowed_columns, prefetch_schema returns full schema."""
        ts = TableSource(table="public.employees", driver="pg")

        with patch.object(ts, "_run_query", new_callable=AsyncMock) as mock_rq:
            mock_rq.return_value = pd.DataFrame(
                [
                    {"column_name": col, "data_type": dtype}
                    for col, dtype in full_schema.items()
                ]
            )
            await ts.prefetch_schema()

        assert set(ts._schema.keys()) == set(full_schema.keys())


# ─────────────────────────────────────────────────────────────────────────────
# TestDescribe
# ─────────────────────────────────────────────────────────────────────────────


class TestDescribe:
    def test_describe_mentions_restriction(self, restricted_source: TableSource):
        """describe() includes restriction info and allowed column list."""
        desc = restricted_source.describe()
        assert "restricted" in desc.lower() or "3 columns" in desc
        # Must list the allowed columns
        assert "id" in desc
        assert "name" in desc
        assert "department" in desc

    def test_describe_no_restriction_when_none(self, unrestricted_source: TableSource):
        """describe() does not mention restriction when allowed_columns=None."""
        desc = unrestricted_source.describe()
        assert "restricted" not in desc.lower()
        assert "Only these columns" not in desc


# ─────────────────────────────────────────────────────────────────────────────
# TestCacheKey
# ─────────────────────────────────────────────────────────────────────────────


class TestCacheKey:
    def test_cache_key_includes_allowed_columns(self):
        """cache_key includes :ac= suffix when allowed_columns is set."""
        ts = TableSource(
            table="public.t",
            driver="pg",
            allowed_columns=["id", "name"],
        )
        assert ":ac=" in ts.cache_key

    def test_cache_key_none_unchanged(self):
        """cache_key without allowed_columns has no :ac= suffix."""
        ts = TableSource(table="public.t", driver="pg")
        assert ":ac=" not in ts.cache_key

    def test_cache_key_different_columns_different_key(self):
        """Different allowed_columns produce different cache keys."""
        ts1 = TableSource(
            table="public.t", driver="pg", allowed_columns=["id", "name"]
        )
        ts2 = TableSource(
            table="public.t", driver="pg", allowed_columns=["id", "salary"]
        )
        assert ts1.cache_key != ts2.cache_key

    def test_cache_key_same_columns_same_key(self):
        """Same allowed_columns (regardless of order) produce the same cache key."""
        ts1 = TableSource(
            table="public.t", driver="pg", allowed_columns=["name", "id"]
        )
        ts2 = TableSource(
            table="public.t", driver="pg", allowed_columns=["id", "name"]
        )
        # Both use sorted() for hashing, so key should be identical
        assert ts1.cache_key == ts2.cache_key

    def test_cache_key_with_both_filter_and_allowed(self):
        """cache_key includes both :f= and :ac= suffixes."""
        ts = TableSource(
            table="public.t",
            driver="pg",
            permanent_filter={"region": "US"},
            allowed_columns=["id", "name"],
        )
        assert ":f=" in ts.cache_key
        assert ":ac=" in ts.cache_key


# ─────────────────────────────────────────────────────────────────────────────
# TestFetchValidation
# ─────────────────────────────────────────────────────────────────────────────


class TestFetchValidation:
    @pytest.mark.asyncio
    async def test_fetch_rejects_select_star(self, restricted_source: TableSource):
        """fetch() with SELECT * raises ValueError with helpful message."""
        with pytest.raises(ValueError, match="SELECT \\* is not allowed"):
            await restricted_source.fetch(
                sql="SELECT * FROM public.employees"
            )

    @pytest.mark.asyncio
    async def test_fetch_select_star_message_includes_allowed(
        self, restricted_source: TableSource
    ):
        """SELECT * error message lists allowed columns."""
        with pytest.raises(ValueError) as exc_info:
            await restricted_source.fetch(
                sql="SELECT * FROM public.employees"
            )
        msg = str(exc_info.value)
        assert "id" in msg or "name" in msg or "department" in msg

    @pytest.mark.asyncio
    async def test_fetch_allows_count_star(self, restricted_source: TableSource):
        """SELECT COUNT(*) is not rejected."""
        mock_df = pd.DataFrame({"count": [42]})
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await restricted_source.fetch(
                sql="SELECT COUNT(*) FROM public.employees"
            )
        # No ValueError raised
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_allows_aggregate_with_column(
        self, restricted_source: TableSource
    ):
        """SELECT id, COUNT(*) GROUP BY id is allowed."""
        mock_df = pd.DataFrame({"id": [1, 2], "count": [5, 3]})
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await restricted_source.fetch(
                sql="SELECT id, COUNT(*) FROM public.employees GROUP BY id"
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_rejects_disallowed_column(
        self, restricted_source: TableSource
    ):
        """fetch() rejects SQL referencing disallowed columns."""
        with pytest.raises(ValueError, match="salary"):
            await restricted_source.fetch(
                sql="SELECT id, salary FROM public.employees"
            )

    @pytest.mark.asyncio
    async def test_fetch_rejects_disallowed_message_actionable(
        self, restricted_source: TableSource
    ):
        """Disallowed column error message includes allowed column list."""
        with pytest.raises(ValueError) as exc_info:
            await restricted_source.fetch(
                sql="SELECT id, salary FROM public.employees"
            )
        msg = str(exc_info.value)
        assert "Allowed columns" in msg
        assert "department" in msg

    @pytest.mark.asyncio
    async def test_fetch_allows_valid_columns(self, restricted_source: TableSource):
        """fetch() with only allowed columns does not raise."""
        mock_df = pd.DataFrame(
            {"id": [1, 2], "name": ["Alice", "Bob"], "department": ["HR", "IT"]}
        )
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await restricted_source.fetch(
                sql="SELECT id, name, department FROM public.employees"
            )
        assert list(result.columns) == ["id", "name", "department"]

    @pytest.mark.asyncio
    async def test_fetch_filters_dataframe_columns(
        self, restricted_source: TableSource
    ):
        """Post-fetch filter drops columns not in allowed_columns."""
        # Simulate _run_query returning extra columns (defense-in-depth)
        mock_df = pd.DataFrame(
            {
                "id": [1],
                "name": ["Alice"],
                "department": ["HR"],
                "salary": [50000],   # should be filtered out
            }
        )
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await restricted_source.fetch(
                sql="SELECT id, name, department FROM public.employees"
            )
        assert "salary" not in result.columns
        assert set(result.columns).issubset({"id", "name", "department"})

    @pytest.mark.asyncio
    async def test_fetch_allows_nested_function_expression(
        self, restricted_source: TableSource
    ):
        """Nested function calls like COALESCE(NULLIF(col, ''), 'x') AS alias
        must not produce a false positive 'Column AS is not allowed' error.

        Regression test for Bug #1: the single-pass function-call stripper
        previously left the SQL keyword 'AS' as a residual token, which was
        then validated against allowed_columns and incorrectly rejected.
        """
        mock_df = pd.DataFrame({"id": [1], "name": ["Alice"]})
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            # COALESCE(NULLIF(name, ''), 'unknown') is a nested function on an
            # allowed column ('name'); it must not raise.
            result = await restricted_source.fetch(
                sql=(
                    "SELECT id, COALESCE(NULLIF(name, ''), 'unknown') AS display_name "
                    "FROM public.employees"
                )
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_fetch_nested_function_on_disallowed_column_not_caught(
        self, restricted_source: TableSource
    ):
        """Documents a known heuristic limitation: UPPER(salary) wrapping a
        disallowed column is NOT caught by the regex validator (the function
        call is stripped, leaving nothing to check). The post-fetch DataFrame
        filter is the safety net in this case.
        """
        # _validate_column_access will NOT raise for UPPER(salary) because
        # the function-call strip removes the entire expression.
        # The post-fetch filter will drop the result column if it is named
        # 'salary', but an alias like 'total' will pass through.
        mock_df = pd.DataFrame({"id": [1], "salary_upper": ["50000"]})
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            # No ValueError is raised — this is the documented limitation
            result = await restricted_source.fetch(
                sql="SELECT id, UPPER(salary) AS salary_upper FROM public.employees"
            )
        # 'id' is in allowed_columns so post-fetch filter keeps it
        # 'salary_upper' is an alias and not in allowed_columns, so it is dropped
        assert "id" in result.columns
        assert "salary_upper" not in result.columns

    @pytest.mark.asyncio
    async def test_fetch_all_alias_result_returned_as_is(
        self, restricted_source: TableSource
    ):
        """Documents Bug #2 behavior: when ALL result columns are aliases
        (none matching allowed_columns), the post-fetch filter returns the
        DataFrame unchanged rather than dropping everything.

        This is the intentional trade-off: dropping all rows would silently
        break valid aggregation queries (e.g. SELECT COUNT(*) AS total).
        The _validate_column_access check is the primary enforcement layer;
        the post-fetch filter is defense-in-depth for undetected column refs.
        """
        # 'total' is an alias; it is not in allowed_columns = ['id', 'name', 'department']
        mock_df = pd.DataFrame({"total": [42]})
        with patch.object(
            restricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await restricted_source.fetch(
                sql="SELECT COUNT(*) AS total FROM public.employees"
            )
        # When no allowed column names appear in the result, df is returned as-is
        assert "total" in result.columns
        assert result["total"].iloc[0] == 42

    @pytest.mark.asyncio
    async def test_no_restriction_select_star_unchanged(
        self, unrestricted_source: TableSource
    ):
        """Without allowed_columns, SELECT * does NOT raise."""
        mock_df = pd.DataFrame({"id": [1], "name": ["Alice"], "salary": [50000]})
        with patch.object(
            unrestricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await unrestricted_source.fetch(
                sql="SELECT * FROM public.employees"
            )
        # All columns preserved
        assert "salary" in result.columns

    @pytest.mark.asyncio
    async def test_no_restriction_disallowed_column_unchanged(
        self, unrestricted_source: TableSource
    ):
        """Without allowed_columns, any column reference is allowed."""
        mock_df = pd.DataFrame({"id": [1], "salary": [50000]})
        with patch.object(
            unrestricted_source, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.return_value = mock_df
            result = await unrestricted_source.fetch(
                sql="SELECT id, salary FROM public.employees"
            )
        assert "salary" in result.columns


# ─────────────────────────────────────────────────────────────────────────────
# TestAddTableSourcePassthrough
# ─────────────────────────────────────────────────────────────────────────────


class TestAddTableSourcePassthrough:
    """Tests for DatasetManager.add_table_source() allowed_columns passthrough.

    Since TableSource is imported locally inside add_table_source(), we patch
    it at the source module level.
    """

    _patch_path = (
        "parrot.tools.dataset_manager.sources.table.TableSource"
    )

    def _make_mock_ts(self, schema: dict | None = None) -> MagicMock:
        """Build a mock TableSource instance."""
        mock_ts = MagicMock(spec=TableSource)
        mock_ts._schema = schema or {"id": "integer", "name": "varchar"}
        mock_ts._row_count_estimate = None
        mock_ts.prefetch_schema = AsyncMock()
        mock_ts.prefetch_row_count = AsyncMock()
        return mock_ts

    @pytest.mark.asyncio
    async def test_add_table_source_passes_allowed_columns(self):
        """add_table_source() passes allowed_columns to TableSource constructor."""
        dm = DatasetManager(generate_guide=False)
        mock_ts = self._make_mock_ts()

        with patch(self._patch_path) as MockTS:
            MockTS.return_value = mock_ts
            await dm.add_table_source(
                name="test_table",
                table="public.test",
                driver="pg",
                allowed_columns=["id", "name"],
            )
            call_kwargs = MockTS.call_args.kwargs
            assert call_kwargs.get("allowed_columns") == ["id", "name"]

    @pytest.mark.asyncio
    async def test_add_table_source_default_none(self):
        """Omitting allowed_columns passes None to TableSource."""
        dm = DatasetManager(generate_guide=False)
        mock_ts = self._make_mock_ts({"id": "integer"})

        with patch(self._patch_path) as MockTS:
            MockTS.return_value = mock_ts
            await dm.add_table_source(
                name="test_table",
                table="public.test",
                driver="pg",
            )
            call_kwargs = MockTS.call_args.kwargs
            assert call_kwargs.get("allowed_columns") is None

    @pytest.mark.asyncio
    async def test_add_table_source_return_message_includes_restriction(self):
        """Return message mentions restriction when allowed_columns is set."""
        dm = DatasetManager(generate_guide=False)
        mock_ts = self._make_mock_ts()

        with patch(self._patch_path) as MockTS:
            MockTS.return_value = mock_ts
            result = await dm.add_table_source(
                name="test_table",
                table="public.test",
                driver="pg",
                allowed_columns=["id", "name"],
            )

        assert "restricted" in result
        assert "2 allowed columns" in result

    @pytest.mark.asyncio
    async def test_add_table_source_return_message_no_restriction(self):
        """Return message has no restriction mention when allowed_columns is None."""
        dm = DatasetManager(generate_guide=False)
        mock_ts = self._make_mock_ts()

        with patch(self._patch_path) as MockTS:
            MockTS.return_value = mock_ts
            result = await dm.add_table_source(
                name="test_table",
                table="public.test",
                driver="pg",
            )

        assert "restricted" not in result


# ─────────────────────────────────────────────────────────────────────────────
# TestIntegrationGuideAndMetadata
# ─────────────────────────────────────────────────────────────────────────────


class TestIntegrationGuideAndMetadata:
    """Integration tests: full DatasetManager → TableSource → DatasetEntry pipeline.

    Mocks only the lowest-level _run_query; real DatasetManager, TableSource,
    and DatasetEntry code runs.
    """

    @staticmethod
    def _make_schema_df() -> pd.DataFrame:
        """Full schema DataFrame from INFORMATION_SCHEMA."""
        return pd.DataFrame(
            {
                "column_name": ["id", "name", "department", "salary", "ssn"],
                "data_type": [
                    "integer", "varchar", "varchar", "numeric", "varchar"
                ],
            }
        )

    @staticmethod
    def _make_count_df() -> pd.DataFrame:
        """Count DataFrame from row-count query."""
        return pd.DataFrame({"cnt": [1000]})

    @pytest.mark.asyncio
    async def test_guide_shows_only_allowed_columns(self):
        """get_guide() only mentions allowed columns after restricted registration."""
        dm = DatasetManager()

        with patch.object(
            TableSource, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.side_effect = [
                self._make_schema_df(),
                self._make_count_df(),
            ]
            await dm.add_table_source(
                "employees",
                "public.employees",
                "pg",
                allowed_columns=["id", "name", "department"],
            )

        guide = dm.get_guide()

        # Allowed columns appear in guide
        assert "id" in guide
        assert "name" in guide
        assert "department" in guide
        # Restricted columns do NOT appear
        assert "salary" not in guide
        assert "ssn" not in guide

    @pytest.mark.asyncio
    async def test_metadata_columns_shows_only_allowed(self):
        """get_metadata() columns key contains only allowed columns."""
        dm = DatasetManager()

        with patch.object(
            TableSource, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.side_effect = [
                self._make_schema_df(),
                self._make_count_df(),
            ]
            await dm.add_table_source(
                "employees",
                "public.employees",
                "pg",
                allowed_columns=["id", "name", "department"],
            )

        meta = await dm.get_metadata("employees")

        # Dataset not loaded, so we get the unloaded info
        columns_listed = meta.get("columns", [])
        col_names = (
            list(columns_listed.keys())
            if isinstance(columns_listed, dict)
            else columns_listed
        )
        assert "id" in col_names
        assert "name" in col_names
        assert "department" in col_names
        assert "salary" not in col_names
        assert "ssn" not in col_names

    @pytest.mark.asyncio
    async def test_guide_unrestricted_shows_all_columns(self):
        """Without allowed_columns, guide shows full schema."""
        dm = DatasetManager()

        with patch.object(
            TableSource, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.side_effect = [
                self._make_schema_df(),
                self._make_count_df(),
            ]
            await dm.add_table_source(
                "employees",
                "public.employees",
                "pg",
                # No allowed_columns — full schema
            )

        guide = dm.get_guide()
        # All columns appear in guide
        assert "id" in guide
        assert "salary" in guide
        assert "ssn" in guide

    @pytest.mark.asyncio
    async def test_entry_columns_property_filtered(self):
        """DatasetEntry.columns returns only allowed columns."""
        dm = DatasetManager()

        with patch.object(
            TableSource, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.side_effect = [
                self._make_schema_df(),
                self._make_count_df(),
            ]
            await dm.add_table_source(
                "employees",
                "public.employees",
                "pg",
                allowed_columns=["id", "name"],
            )

        entry = dm._datasets["employees"]
        assert set(entry.columns) == {"id", "name"}

    @pytest.mark.asyncio
    async def test_registration_message_mentions_restriction(self):
        """The string returned by add_table_source mentions column restriction."""
        dm = DatasetManager(generate_guide=False)

        with patch.object(
            TableSource, "_run_query", new_callable=AsyncMock
        ) as mock_rq:
            mock_rq.side_effect = [
                self._make_schema_df(),
                self._make_count_df(),
            ]
            result = await dm.add_table_source(
                "employees",
                "public.employees",
                "pg",
                allowed_columns=["id", "name", "department"],
            )

        assert "restricted" in result
        assert "3 allowed columns" in result
