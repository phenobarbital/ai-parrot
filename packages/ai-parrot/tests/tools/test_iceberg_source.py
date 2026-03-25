"""
Unit tests for IcebergSource DataSource subclass.

Tests cover:
- prefetch_schema() — calls load_table + schema() and returns column→type dict
- fetch(sql=...) — calls driver.query() with table_id and factory
- fetch() without sql — calls driver.to_df() for full table
- cache_key format
- describe() includes table_id and catalog info
- create_table_from_df() creates namespace, infers schema, writes data
"""
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch

from parrot.tools.dataset_manager.sources.iceberg import IcebergSource, _infer_pyarrow_schema


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def catalog_params() -> dict:
    return {
        "type": "rest",
        "uri": "http://localhost:8181",
        "warehouse": "demo",
    }


@pytest.fixture
def sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "city": ["Berlin", "Tokyo", "Lima"],
        "population": [3432000, 13960000, 9750000],
        "country": ["DE", "JP", "PE"],
    })


@pytest.fixture
def mock_iceberg_conn():
    """Mock asyncdb iceberg connection (inside async with block)."""
    conn = AsyncMock()
    # schema() is a synchronous method in asyncdb drivers
    conn.schema = MagicMock(return_value={
        "city": "string",
        "population": "int64",
        "country": "string",
    })
    conn.to_df = AsyncMock(
        return_value=pd.DataFrame({
            "city": ["Berlin"],
            "population": [3432000],
            "country": ["DE"],
        })
    )
    conn.query = AsyncMock(
        return_value=(
            pd.DataFrame({"city": ["Tokyo"], "population": [13960000]}),
            None,
        )
    )
    conn.load_table = AsyncMock()
    conn.create_namespace = AsyncMock()
    conn.create_table = AsyncMock()
    conn.write = AsyncMock()
    return conn


@pytest.fixture
def mock_iceberg_driver(mock_iceberg_conn):
    """Mock asyncdb iceberg driver that returns mock_iceberg_conn."""
    driver = MagicMock()
    # connection() returns an async context manager
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_iceberg_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    driver.connection = AsyncMock(return_value=cm)
    return driver


@pytest.fixture
def iceberg_source(catalog_params):
    """IcebergSource instance for testing."""
    return IcebergSource(
        table_id="demo.cities",
        name="cities",
        catalog_params=catalog_params,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestIcebergSourceCacheKey:
    def test_cache_key_format(self, iceberg_source):
        """cache_key format: iceberg:{table_id}."""
        assert iceberg_source.cache_key == "iceberg:demo.cities"

    def test_cache_key_with_different_table(self, catalog_params):
        source = IcebergSource(
            table_id="prod.orders",
            name="orders",
            catalog_params=catalog_params,
        )
        assert source.cache_key == "iceberg:prod.orders"


class TestIcebergSourceDescribe:
    def test_describe_includes_table_id(self, iceberg_source):
        """describe() includes table_id."""
        desc = iceberg_source.describe()
        assert "demo.cities" in desc

    def test_describe_includes_catalog_type(self, iceberg_source):
        """describe() includes catalog type."""
        desc = iceberg_source.describe()
        assert "rest" in desc

    def test_describe_after_schema_prefetch(self, iceberg_source, catalog_params):
        """describe() shows column count after schema is set."""
        iceberg_source._schema = {"city": "string", "population": "int64"}
        desc = iceberg_source.describe()
        assert "2 columns" in desc

    def test_describe_with_row_count(self, iceberg_source):
        """describe() shows row count estimate when set."""
        iceberg_source._row_count_estimate = 42000
        desc = iceberg_source.describe()
        assert "42,000" in desc


class TestIcebergSourcePrefetchSchema:
    @pytest.mark.asyncio
    async def test_prefetch_schema_calls_load_table_and_schema(
        self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn
    ):
        """prefetch_schema() calls load_table + schema() and returns column→type dict."""
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            result = await iceberg_source.prefetch_schema()

        mock_iceberg_conn.load_table.assert_called_once_with("demo.cities")
        mock_iceberg_conn.schema.assert_called_once()
        assert result == {"city": "string", "population": "int64", "country": "string"}

    @pytest.mark.asyncio
    async def test_prefetch_schema_stores_in_schema(
        self, iceberg_source, mock_iceberg_driver
    ):
        """prefetch_schema() stores result in self._schema."""
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            await iceberg_source.prefetch_schema()

        assert iceberg_source._schema == {
            "city": "string",
            "population": "int64",
            "country": "string",
        }

    @pytest.mark.asyncio
    async def test_prefetch_schema_raises_on_error(self, iceberg_source, catalog_params):
        """prefetch_schema() raises RuntimeError when driver fails."""
        failing_driver = MagicMock()
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(side_effect=ConnectionError("Cannot connect to catalog"))
        cm.__aexit__ = AsyncMock(return_value=False)
        failing_driver.connection = AsyncMock(return_value=cm)

        with patch.object(iceberg_source, "_get_driver", return_value=failing_driver):
            with pytest.raises(RuntimeError, match="failed to prefetch schema"):
                await iceberg_source.prefetch_schema()


class TestIcebergSourceFetch:
    @pytest.mark.asyncio
    async def test_fetch_with_sql(self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn):
        """fetch(sql=...) calls driver.query() with table_id and factory."""
        sql = "SELECT city, population FROM demo.cities WHERE population > 5000000"
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            result = await iceberg_source.fetch(sql=sql)

        mock_iceberg_conn.query.assert_called_once_with(
            sql, table_id="demo.cities", factory="pandas"
        )
        assert isinstance(result, pd.DataFrame)
        assert "city" in result.columns

    @pytest.mark.asyncio
    async def test_fetch_full_table(self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn):
        """fetch() without sql calls driver.to_df() for full table."""
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            result = await iceberg_source.fetch()

        mock_iceberg_conn.to_df.assert_called_once_with("demo.cities", factory="pandas")
        mock_iceberg_conn.query.assert_not_called()
        assert isinstance(result, pd.DataFrame)

    @pytest.mark.asyncio
    async def test_fetch_with_sql_error_raises(
        self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn
    ):
        """fetch() raises RuntimeError when driver returns error."""
        mock_iceberg_conn.query = AsyncMock(return_value=(None, "Query execution failed"))
        sql = "SELECT * FROM demo.cities"
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            with pytest.raises(RuntimeError, match="SQL query failed"):
                await iceberg_source.fetch(sql=sql)

    @pytest.mark.asyncio
    async def test_fetch_full_table_returns_empty_df_on_none(
        self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn
    ):
        """fetch() returns empty DataFrame when to_df returns None."""
        mock_iceberg_conn.to_df = AsyncMock(return_value=None)
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            result = await iceberg_source.fetch()

        assert isinstance(result, pd.DataFrame)
        assert result.empty


class TestIcebergSourcePrefetchRowCount:
    @pytest.mark.asyncio
    async def test_prefetch_row_count(
        self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn
    ):
        """prefetch_row_count() stores estimated row count."""
        mock_iceberg_conn.query = AsyncMock(
            return_value=(pd.DataFrame({"cnt": [42]}), None)
        )
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            count = await iceberg_source.prefetch_row_count()

        assert count == 42
        assert iceberg_source._row_count_estimate == 42

    @pytest.mark.asyncio
    async def test_prefetch_row_count_returns_none_on_error(
        self, iceberg_source, mock_iceberg_driver, mock_iceberg_conn
    ):
        """prefetch_row_count() returns None when query fails."""
        mock_iceberg_conn.query = AsyncMock(return_value=(None, "count failed"))
        with patch.object(iceberg_source, "_get_driver", return_value=mock_iceberg_driver):
            count = await iceberg_source.prefetch_row_count()

        assert count is None
        assert iceberg_source._row_count_estimate is None


class TestIcebergCreateTableFromDf:
    @pytest.mark.asyncio
    async def test_create_table_from_df(self, mock_iceberg_conn, sample_df):
        """create_table_from_df creates namespace, infers schema, writes df."""
        await IcebergSource.create_table_from_df(
            driver=mock_iceberg_conn,
            df=sample_df,
            table_id="demo.cities",
            namespace="demo",
            mode="append",
        )

        mock_iceberg_conn.create_namespace.assert_called_once_with("demo")
        mock_iceberg_conn.create_table.assert_called_once()
        # Verify table_id and schema were passed
        create_call_args = mock_iceberg_conn.create_table.call_args
        assert create_call_args[0][0] == "demo.cities"
        assert "schema" in create_call_args[1]

        mock_iceberg_conn.write.assert_called_once_with(sample_df, "demo.cities", mode="append")

    @pytest.mark.asyncio
    async def test_create_table_from_df_default_mode(self, mock_iceberg_conn, sample_df):
        """create_table_from_df uses append mode by default."""
        await IcebergSource.create_table_from_df(
            driver=mock_iceberg_conn,
            df=sample_df,
            table_id="demo.test",
            namespace="demo",
        )
        mock_iceberg_conn.write.assert_called_once_with(
            sample_df, "demo.test", mode="append"
        )

    @pytest.mark.asyncio
    async def test_create_table_from_df_namespace_error_continues(
        self, mock_iceberg_conn, sample_df
    ):
        """create_table_from_df continues when namespace already exists."""
        mock_iceberg_conn.create_namespace = AsyncMock(
            side_effect=Exception("Namespace already exists")
        )
        # Should not raise — namespace errors are logged and ignored
        await IcebergSource.create_table_from_df(
            driver=mock_iceberg_conn,
            df=sample_df,
            table_id="demo.cities",
            namespace="demo",
        )
        mock_iceberg_conn.create_table.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_table_from_df_raises_on_create_failure(
        self, mock_iceberg_conn, sample_df
    ):
        """create_table_from_df raises RuntimeError when create_table fails."""
        mock_iceberg_conn.create_table = AsyncMock(side_effect=Exception("Storage error"))
        with pytest.raises(RuntimeError, match="failed to create table"):
            await IcebergSource.create_table_from_df(
                driver=mock_iceberg_conn,
                df=sample_df,
                table_id="demo.cities",
                namespace="demo",
            )

    @pytest.mark.asyncio
    async def test_create_table_from_df_raises_on_write_failure(
        self, mock_iceberg_conn, sample_df
    ):
        """create_table_from_df raises RuntimeError when write fails."""
        mock_iceberg_conn.write = AsyncMock(side_effect=Exception("Write error"))
        with pytest.raises(RuntimeError, match="failed to write data"):
            await IcebergSource.create_table_from_df(
                driver=mock_iceberg_conn,
                df=sample_df,
                table_id="demo.cities",
                namespace="demo",
            )


class TestInferPyarrowSchema:
    def test_infer_schema_string_columns(self, sample_df):
        """_infer_pyarrow_schema infers string type for object columns."""
        import pyarrow as pa
        schema = _infer_pyarrow_schema(sample_df)
        city_field = next(f for f in schema if f.name == "city")
        assert city_field.type == pa.string()

    def test_infer_schema_int_columns(self, sample_df):
        """_infer_pyarrow_schema infers int64 type for int columns."""
        import pyarrow as pa
        schema = _infer_pyarrow_schema(sample_df)
        pop_field = next(f for f in schema if f.name == "population")
        assert pop_field.type == pa.int64()

    def test_infer_schema_field_count(self, sample_df):
        """_infer_pyarrow_schema produces correct number of fields."""
        schema = _infer_pyarrow_schema(sample_df)
        assert len(schema) == len(sample_df.columns)
