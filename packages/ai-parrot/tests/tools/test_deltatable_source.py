"""
Unit tests for DeltaTableSource DataSource subclass.

Tests cover:
- prefetch_schema() — calls conn.schema() and returns column→type dict
- fetch(sql=...) — calls conn.query() with DuckDB SQL and tablename
- fetch(columns=[...]) — calls conn.to_df(columns=...)
- fetch(filter=...) — calls conn.query(sentence=filter)
- fetch() with no params — full table via conn.to_df()
- cache_key format: delta:{md5(path)[:12]}
- describe() includes path and table name
- create_from_parquet() creates Delta table from Parquet file
- Row count estimation
"""
import hashlib
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.dataset_manager.sources.deltatable import (
    DeltaTableSource,
    _is_s3_path,
    _is_gcs_path,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_delta_conn():
    """Mock asyncdb delta connection."""
    conn = AsyncMock()
    # schema() is a synchronous method in asyncdb drivers
    conn.schema = MagicMock(return_value={
        "pickup_datetime": "timestamp",
        "passenger_count": "int64",
        "fare_amount": "float64",
    })
    conn.to_df = AsyncMock(
        return_value=(
            pd.DataFrame({
                "passenger_count": [1, 2],
                "fare_amount": [10.5, 20.0],
            }),
            None,
        )
    )
    conn.query = AsyncMock(
        return_value=(
            pd.DataFrame({
                "passenger_count": [6],
                "fare_amount": [35.0],
            }),
            None,
        )
    )
    return conn


@pytest.fixture
def mock_delta_driver(mock_delta_conn):
    """Mock asyncdb delta driver that returns mock_delta_conn."""
    driver = MagicMock()
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_delta_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    driver.connection = AsyncMock(return_value=cm)
    return driver


@pytest.fixture
def delta_source():
    """DeltaTableSource instance for testing (local path)."""
    return DeltaTableSource(
        path="/data/taxi_trips",
        name="taxi_trips",
        table_name="TAXI",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestPathHelpers:
    def test_is_s3_path_true(self):
        assert _is_s3_path("s3://my-bucket/path") is True

    def test_is_s3_path_s3a(self):
        assert _is_s3_path("s3a://my-bucket/path") is True

    def test_is_s3_path_false(self):
        assert _is_s3_path("/local/path") is False
        assert _is_s3_path("gs://bucket/path") is False

    def test_is_gcs_path_true(self):
        assert _is_gcs_path("gs://my-bucket/path") is True
        assert _is_gcs_path("gcs://my-bucket/path") is True

    def test_is_gcs_path_false(self):
        assert _is_gcs_path("s3://bucket/path") is False
        assert _is_gcs_path("/local/path") is False


class TestDeltaTableSourceCacheKey:
    def test_cache_key_format(self, delta_source):
        """cache_key format: delta:{md5(path)[:12]}."""
        expected_hash = hashlib.md5("/data/taxi_trips".encode()).hexdigest()[:12]
        assert delta_source.cache_key == f"delta:{expected_hash}"

    def test_cache_key_different_paths_are_different(self):
        src1 = DeltaTableSource(path="/data/a", name="a")
        src2 = DeltaTableSource(path="/data/b", name="b")
        assert src1.cache_key != src2.cache_key

    def test_cache_key_s3_path(self):
        src = DeltaTableSource(path="s3://bucket/table", name="t")
        expected_hash = hashlib.md5("s3://bucket/table".encode()).hexdigest()[:12]
        assert src.cache_key == f"delta:{expected_hash}"


class TestDeltaTableSourceDescribe:
    def test_describe_includes_path(self, delta_source):
        """describe() includes the path."""
        desc = delta_source.describe()
        assert "taxi_trips" in desc

    def test_describe_includes_table_name(self, delta_source):
        """describe() includes the table_name."""
        desc = delta_source.describe()
        assert "TAXI" in desc

    def test_describe_includes_column_count_after_prefetch(self, delta_source):
        """describe() shows column count after schema is set."""
        delta_source._schema = {"a": "int64", "b": "float64"}
        desc = delta_source.describe()
        assert "2 columns" in desc

    def test_describe_includes_row_count_when_set(self, delta_source):
        """describe() shows row count estimate when available."""
        delta_source._row_count_estimate = 1_500_000
        desc = delta_source.describe()
        assert "1,500,000" in desc

    def test_describe_truncates_long_path(self):
        """describe() truncates very long paths."""
        long_path = "s3://my-very-long-bucket-name/deeply/nested/path/to/table"
        src = DeltaTableSource(path=long_path, name="t")
        desc = src.describe()
        assert len(desc) < 300  # Should not be excessively long

    def test_describe_default_table_name(self):
        """DeltaTableSource uses uppercased name as default table_name."""
        src = DeltaTableSource(path="/data/orders", name="orders")
        assert src._table_name == "ORDERS"


class TestDeltaTableSourcePrefetchSchema:
    @pytest.mark.asyncio
    async def test_prefetch_schema_calls_conn_schema(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """prefetch_schema() calls conn.schema() and returns column→type dict."""
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            result = await delta_source.prefetch_schema()

        mock_delta_conn.schema.assert_called_once()
        assert result == {
            "pickup_datetime": "timestamp",
            "passenger_count": "int64",
            "fare_amount": "float64",
        }

    @pytest.mark.asyncio
    async def test_prefetch_schema_stores_in_schema(
        self, delta_source, mock_delta_driver
    ):
        """prefetch_schema() stores result in self._schema."""
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            await delta_source.prefetch_schema()

        assert len(delta_source._schema) == 3

    @pytest.mark.asyncio
    async def test_prefetch_schema_raises_on_error(self, delta_source):
        """prefetch_schema() raises RuntimeError when driver fails."""
        failing_driver = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=IOError("Table not found"))
        cm.__aexit__ = AsyncMock(return_value=False)
        failing_driver.connection = AsyncMock(return_value=cm)

        with patch.object(delta_source, "_get_driver", return_value=failing_driver):
            with pytest.raises(RuntimeError, match="failed to prefetch schema"):
                await delta_source.prefetch_schema()


class TestDeltaTableSourceFetch:
    @pytest.mark.asyncio
    async def test_fetch_with_sql(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch(sql=...) calls conn.query() with tablename."""
        sql = "SELECT * FROM TAXI WHERE fare_amount > 30"
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            result = await delta_source.fetch(sql=sql)

        mock_delta_conn.query.assert_called_once_with(
            sentence=sql, tablename="TAXI", factory="pandas"
        )
        assert isinstance(result, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_fetch_with_columns(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch(columns=[...]) calls conn.to_df(columns=...)."""
        columns = ["passenger_count", "fare_amount"]
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            result = await delta_source.fetch(columns=columns)

        mock_delta_conn.to_df.assert_called_once_with(columns=columns, factory="pandas")
        assert isinstance(result, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_fetch_with_filter(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch(filter=...) calls conn.query(sentence=filter)."""
        filter_expr = "fare_amount > 30.0 AND passenger_count = 1"
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            result = await delta_source.fetch(filter=filter_expr)

        mock_delta_conn.query.assert_called_once_with(
            sentence=filter_expr, factory="pandas"
        )
        assert isinstance(result, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_fetch_full_table(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch() with no params calls conn.to_df() for full table."""
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            result = await delta_source.fetch()

        mock_delta_conn.to_df.assert_called_once_with(factory="pandas")
        mock_delta_conn.query.assert_not_called()
        assert isinstance(result, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_fetch_sql_error_raises(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch() raises RuntimeError when SQL query returns error."""
        mock_delta_conn.query = AsyncMock(return_value=(None, "Query failed"))
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            with pytest.raises(RuntimeError, match="SQL query failed"):
                await delta_source.fetch(sql="SELECT * FROM TAXI")

    @pytest.mark.asyncio
    async def test_fetch_columns_error_raises(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch() raises RuntimeError when column fetch returns error."""
        mock_delta_conn.to_df = AsyncMock(return_value=(None, "Column error"))
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            with pytest.raises(RuntimeError, match="column fetch failed"):
                await delta_source.fetch(columns=["fare_amount"])

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_df_when_result_none(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """fetch() returns empty DataFrame when result is None."""
        mock_delta_conn.to_df = AsyncMock(return_value=(None, None))
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            result = await delta_source.fetch()

        assert isinstance(result, pd.DataFrame)
        assert result.empty


class TestDeltaTableSourcePrefetchRowCount:
    @pytest.mark.asyncio
    async def test_prefetch_row_count(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """prefetch_row_count() stores estimated row count."""
        mock_delta_conn.query = AsyncMock(
            return_value=(pd.DataFrame({"cnt": [1000]}), None)
        )
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            count = await delta_source.prefetch_row_count()

        assert count == 1000
        assert delta_source._row_count_estimate == 1000

    @pytest.mark.asyncio
    async def test_prefetch_row_count_returns_none_on_error(
        self, delta_source, mock_delta_driver, mock_delta_conn
    ):
        """prefetch_row_count() returns None when query returns error."""
        mock_delta_conn.query = AsyncMock(return_value=(None, "count failed"))
        with patch.object(delta_source, "_get_driver", return_value=mock_delta_driver):
            count = await delta_source.prefetch_row_count()

        assert count is None


class TestDeltaTableSourceCreateFromParquet:
    @pytest.mark.asyncio
    async def test_create_from_parquet(self):
        """create_from_parquet() calls driver.create() with correct args."""
        mock_driver_class = MagicMock()
        mock_driver_instance = AsyncMock()
        mock_driver_instance.create = AsyncMock()
        mock_driver_class.return_value = mock_driver_instance

        mock_delta_mod = MagicMock()
        mock_delta_mod.delta = mock_driver_class

        with patch("parrot.tools.dataset_manager.sources.deltatable.lazy_import",
                   return_value=mock_delta_mod):
            await DeltaTableSource.create_from_parquet(
                delta_path="/data/output",
                parquet_path="/data/input.parquet",
                table_name="OUTPUT",
                mode="overwrite",
            )

        mock_driver_instance.create.assert_called_once_with(
            "/data/output",
            "/data/input.parquet",
            name="OUTPUT",
            mode="overwrite",
        )

    @pytest.mark.asyncio
    async def test_create_from_parquet_raises_on_failure(self):
        """create_from_parquet() raises RuntimeError when driver.create fails."""
        mock_driver_class = MagicMock()
        mock_driver_instance = AsyncMock()
        mock_driver_instance.create = AsyncMock(
            side_effect=Exception("Storage permission denied")
        )
        mock_driver_class.return_value = mock_driver_instance

        mock_delta_mod = MagicMock()
        mock_delta_mod.delta = mock_driver_class

        with patch("parrot.tools.dataset_manager.sources.deltatable.lazy_import",
                   return_value=mock_delta_mod):
            with pytest.raises(RuntimeError, match="failed to create Delta table"):
                await DeltaTableSource.create_from_parquet(
                    delta_path="/data/output",
                    parquet_path="/data/input.parquet",
                )
