"""Unit tests for DataSource implementations."""
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from parrot.tools.dataset_manager.sources import (
    InMemorySource,
    MultiQuerySlugSource,
    QuerySlugSource,
    SQLQuerySource,
)


class TestInMemorySource:
    """Tests for InMemorySource."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({"a": [1, 2, 3], "b": [1.1, 2.2, 3.3], "c": ["x", "y", "z"]})

    @pytest.fixture()
    def source(self, sample_df: pd.DataFrame) -> InMemorySource:
        return InMemorySource(df=sample_df, name="test_frame")

    # --- prefetch_schema ---

    @pytest.mark.asyncio
    async def test_prefetch_schema_returns_col_dtype_map(self, source: InMemorySource, sample_df: pd.DataFrame) -> None:
        schema = await source.prefetch_schema()
        assert set(schema.keys()) == {"a", "b", "c"}
        assert schema["a"] == str(sample_df["a"].dtype)
        assert schema["b"] == str(sample_df["b"].dtype)
        assert schema["c"] == str(sample_df["c"].dtype)

    @pytest.mark.asyncio
    async def test_prefetch_schema_no_io(self, source: InMemorySource) -> None:
        # Should complete instantly — no network/disk I/O
        schema = await source.prefetch_schema()
        assert isinstance(schema, dict)

    # --- fetch ---

    @pytest.mark.asyncio
    async def test_fetch_returns_same_dataframe(self, source: InMemorySource, sample_df: pd.DataFrame) -> None:
        result = await source.fetch()
        assert result is sample_df

    @pytest.mark.asyncio
    async def test_fetch_ignores_params(self, source: InMemorySource, sample_df: pd.DataFrame) -> None:
        result = await source.fetch(limit=10, offset=5)
        assert result is sample_df

    # --- cache_key ---

    def test_cache_key_format(self, source: InMemorySource) -> None:
        assert source.cache_key == "mem:test_frame"

    def test_cache_key_uses_name(self) -> None:
        df = pd.DataFrame({"x": [1]})
        src = InMemorySource(df=df, name="my_dataset")
        assert src.cache_key == "mem:my_dataset"

    # --- describe ---

    def test_describe_includes_shape(self, source: InMemorySource, sample_df: pd.DataFrame) -> None:
        rows, cols = sample_df.shape
        description = source.describe()
        assert str(rows) in description
        assert str(cols) in description

    def test_describe_empty_dataframe(self) -> None:
        df = pd.DataFrame()
        src = InMemorySource(df=df, name="empty")
        desc = src.describe()
        assert "0 rows" in desc or "0" in desc

    # --- import ---

    def test_importable_from_sources_package(self) -> None:
        from parrot.tools.dataset_manager.sources import InMemorySource as IMS  # noqa: F401
        assert IMS is InMemorySource


class TestQuerySlugSource:
    """Tests for QuerySlugSource."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({"id": [1, 2], "name": ["alice", "bob"]})

    @pytest.fixture()
    def source(self) -> QuerySlugSource:
        return QuerySlugSource(slug="my_report")

    # --- cache_key ---

    def test_cache_key_format(self, source: QuerySlugSource) -> None:
        assert source.cache_key == "qs:my_report"

    def test_cache_key_uses_slug(self) -> None:
        src = QuerySlugSource(slug="other_slug")
        assert src.cache_key == "qs:other_slug"

    # --- describe ---

    def test_describe_contains_slug(self, source: QuerySlugSource) -> None:
        assert "my_report" in source.describe()

    # --- fetch ---

    @pytest.mark.asyncio
    async def test_fetch_passes_params_as_conditions(self, source: QuerySlugSource, sample_df: pd.DataFrame) -> None:
        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(return_value=(sample_df, None))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_qs_instance) as mock_qs_cls:
            result = await source.fetch(region="us", limit=10)

        mock_qs_cls.assert_called_once_with(slug="my_report", conditions={"region": "us", "limit": 10})
        assert result is sample_df

    @pytest.mark.asyncio
    async def test_fetch_raises_on_qs_error(self, source: QuerySlugSource) -> None:
        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(return_value=(None, "connection refused"))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_qs_instance):
            with pytest.raises(RuntimeError, match="my_report"):
                await source.fetch()

    @pytest.mark.asyncio
    async def test_fetch_raises_when_no_dataframe_returned(self, source: QuerySlugSource) -> None:
        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(return_value=("not-a-df", None))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_qs_instance):
            with pytest.raises(RuntimeError, match="did not return a DataFrame"):
                await source.fetch()

    # --- prefetch_schema ---

    @pytest.mark.asyncio
    async def test_prefetch_schema_returns_col_dtype_map(self, source: QuerySlugSource, sample_df: pd.DataFrame) -> None:
        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(return_value=(sample_df, None))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_qs_instance) as mock_qs_cls:
            schema = await source.prefetch_schema()

        mock_qs_cls.assert_called_once_with(slug="my_report", conditions={"querylimit": 1})
        assert set(schema.keys()) == {"id", "name"}

    @pytest.mark.asyncio
    async def test_prefetch_schema_returns_empty_on_qs_error(self, source: QuerySlugSource) -> None:
        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(return_value=(None, "error"))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_qs_instance):
            schema = await source.prefetch_schema()

        assert schema == {}

    @pytest.mark.asyncio
    async def test_prefetch_schema_returns_empty_on_exception(self, source: QuerySlugSource) -> None:
        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(side_effect=RuntimeError("network failure"))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_qs_instance):
            schema = await source.prefetch_schema()

        assert schema == {}

    @pytest.mark.asyncio
    async def test_prefetch_schema_disabled_returns_empty(self) -> None:
        src = QuerySlugSource(slug="my_report", prefetch_schema_enabled=False)
        # Should return {} immediately without calling QS
        with patch("parrot.tools.dataset_manager.sources.query_slug.QS") as mock_qs_cls:
            schema = await src.prefetch_schema()
        mock_qs_cls.assert_not_called()
        assert schema == {}

    # --- import ---

    def test_importable_from_sources_package(self) -> None:
        from parrot.tools.dataset_manager.sources import QuerySlugSource as QSS  # noqa: F401
        assert QSS is QuerySlugSource


class TestMultiQuerySlugSource:
    """Tests for MultiQuerySlugSource."""

    @pytest.fixture()
    def slugs(self) -> list:
        return ["report_a", "report_b"]

    @pytest.fixture()
    def source(self, slugs: list) -> MultiQuerySlugSource:
        return MultiQuerySlugSource(slugs=slugs)

    @pytest.fixture()
    def df_a(self) -> pd.DataFrame:
        return pd.DataFrame({"id": [1, 2], "val": [10, 20]})

    @pytest.fixture()
    def df_b(self) -> pd.DataFrame:
        return pd.DataFrame({"id": [3], "val": [30]})

    # --- cache_key ---

    def test_cache_key_format_sorted(self, source: MultiQuerySlugSource) -> None:
        assert source.cache_key == "multiqs:report_a:report_b"

    def test_cache_key_slugs_sorted(self) -> None:
        src = MultiQuerySlugSource(slugs=["zzz", "aaa"])
        assert src.cache_key == "multiqs:aaa:zzz"

    # --- describe ---

    def test_describe_contains_all_slugs(self, source: MultiQuerySlugSource) -> None:
        desc = source.describe()
        assert "report_a" in desc
        assert "report_b" in desc

    # --- fetch ---

    @pytest.mark.asyncio
    async def test_fetch_concatenates_results(
        self, source: MultiQuerySlugSource, df_a: pd.DataFrame, df_b: pd.DataFrame
    ) -> None:
        call_count = 0

        def make_mock_qs(slug, conditions):
            nonlocal call_count
            mock = MagicMock()
            if slug == "report_a":
                mock.query = AsyncMock(return_value=(df_a, None))
            else:
                mock.query = AsyncMock(return_value=(df_b, None))
            call_count += 1
            return mock

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", side_effect=make_mock_qs):
            result = await source.fetch(region="us")

        assert len(result) == 3  # 2 rows from df_a + 1 from df_b
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_passes_params_as_conditions(
        self, source: MultiQuerySlugSource, df_a: pd.DataFrame, df_b: pd.DataFrame
    ) -> None:
        calls = []

        def make_mock_qs(slug, conditions):
            calls.append((slug, conditions))
            mock = MagicMock()
            mock.query = AsyncMock(return_value=(df_a, None))
            return mock

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", side_effect=make_mock_qs):
            await source.fetch(limit=5)

        assert all(c[1] == {"limit": 5} for c in calls)

    @pytest.mark.asyncio
    async def test_fetch_raises_when_all_slugs_fail(self, source: MultiQuerySlugSource) -> None:
        mock_instance = MagicMock()
        mock_instance.query = AsyncMock(return_value=(None, "error"))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_instance):
            with pytest.raises(RuntimeError, match="no slug returned data"):
                await source.fetch()

    @pytest.mark.asyncio
    async def test_fetch_skips_failed_slugs(
        self, source: MultiQuerySlugSource, df_a: pd.DataFrame
    ) -> None:
        def make_mock_qs(slug, conditions):
            mock = MagicMock()
            if slug == "report_a":
                mock.query = AsyncMock(return_value=(df_a, None))
            else:
                mock.query = AsyncMock(return_value=(None, "error"))
            return mock

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", side_effect=make_mock_qs):
            result = await source.fetch()

        assert len(result) == len(df_a)

    # --- prefetch_schema ---

    @pytest.mark.asyncio
    async def test_prefetch_schema_merges_schemas(
        self, source: MultiQuerySlugSource, df_a: pd.DataFrame, df_b: pd.DataFrame
    ) -> None:
        def make_mock_qs(slug, conditions):
            mock = MagicMock()
            mock.query = AsyncMock(return_value=(df_a, None))
            return mock

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", side_effect=make_mock_qs):
            schema = await source.prefetch_schema()

        assert "id" in schema
        assert "val" in schema

    @pytest.mark.asyncio
    async def test_prefetch_schema_silent_on_failure(self, source: MultiQuerySlugSource) -> None:
        mock_instance = MagicMock()
        mock_instance.query = AsyncMock(side_effect=RuntimeError("fail"))

        with patch("parrot.tools.dataset_manager.sources.query_slug.QS", return_value=mock_instance):
            schema = await source.prefetch_schema()

        assert schema == {}

    # --- import ---

    def test_importable_from_sources_package(self) -> None:
        from parrot.tools.dataset_manager.sources import MultiQuerySlugSource as MQSS  # noqa: F401
        assert MQSS is MultiQuerySlugSource


class TestSQLQuerySource:
    """Tests for SQLQuerySource."""

    SQL_SIMPLE = "SELECT * FROM tickers WHERE symbol = {symbol}"
    SQL_MULTI = "SELECT * FROM data WHERE symbol = {symbol} AND date >= {start_date}"
    SQL_NO_PARAMS = "SELECT 1"

    @pytest.fixture()
    def source(self) -> SQLQuerySource:
        return SQLQuerySource(sql=self.SQL_SIMPLE, driver="pg", dsn="postgresql://localhost/test")

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({"symbol": ["AAPL"], "price": [150.0]})

    # --- cache_key ---

    def test_cache_key_format(self, source: SQLQuerySource) -> None:
        import hashlib
        expected_md5 = hashlib.md5(self.SQL_SIMPLE.encode()).hexdigest()[:8]
        assert source.cache_key == f"sql:pg:{expected_md5}"

    def test_cache_key_changes_with_sql(self) -> None:
        src_a = SQLQuerySource(sql="SELECT 1", driver="pg", dsn="dsn://x")
        src_b = SQLQuerySource(sql="SELECT 2", driver="pg", dsn="dsn://x")
        assert src_a.cache_key != src_b.cache_key

    def test_cache_key_changes_with_driver(self) -> None:
        src_pg = SQLQuerySource(sql="SELECT 1", driver="pg", dsn="dsn://x")
        src_mysql = SQLQuerySource(sql="SELECT 1", driver="mysql", dsn="dsn://x")
        assert src_pg.cache_key != src_mysql.cache_key

    # --- describe ---

    def test_describe_contains_driver(self, source: SQLQuerySource) -> None:
        assert "pg" in source.describe()

    def test_describe_contains_sql_prefix(self, source: SQLQuerySource) -> None:
        desc = source.describe()
        assert "SELECT" in desc

    def test_describe_truncates_long_sql(self) -> None:
        long_sql = "SELECT " + "a, " * 100 + "b FROM t"
        src = SQLQuerySource(sql=long_sql, driver="pg", dsn="dsn://x")
        assert len(src.describe()) < len(long_sql) + 50
        assert "..." in src.describe()

    def test_describe_no_truncation_short_sql(self) -> None:
        src = SQLQuerySource(sql="SELECT 1", driver="pg", dsn="dsn://x")
        assert "..." not in src.describe()

    # --- prefetch_schema ---

    @pytest.mark.asyncio
    async def test_prefetch_schema_returns_empty_dict(self, source: SQLQuerySource) -> None:
        schema = await source.prefetch_schema()
        assert schema == {}

    # --- _escape_value ---

    def test_escape_int(self, source: SQLQuerySource) -> None:
        assert source._escape_value(42) == "42"

    def test_escape_float(self, source: SQLQuerySource) -> None:
        assert source._escape_value(3.14) == "3.14"

    def test_escape_string(self, source: SQLQuerySource) -> None:
        assert source._escape_value("AAPL") == "'AAPL'"

    def test_escape_string_with_single_quote(self, source: SQLQuerySource) -> None:
        # O'Brien → 'O''Brien'
        assert source._escape_value("O'Brien") == "'O''Brien'"

    def test_escape_string_multiple_quotes(self, source: SQLQuerySource) -> None:
        assert source._escape_value("it's a 'test'") == "'it''s a ''test'''"

    def test_escape_date(self, source: SQLQuerySource) -> None:
        from datetime import date
        assert source._escape_value(date(2024, 1, 15)) == "'2024-01-15'"

    def test_escape_datetime(self, source: SQLQuerySource) -> None:
        from datetime import datetime
        assert source._escape_value(datetime(2024, 1, 15, 10, 30)) == "'2024-01-15T10:30:00'"

    def test_escape_bool_true(self, source: SQLQuerySource) -> None:
        assert source._escape_value(True) == "TRUE"

    def test_escape_bool_false(self, source: SQLQuerySource) -> None:
        assert source._escape_value(False) == "FALSE"

    # --- fetch — validation ---

    @pytest.mark.asyncio
    async def test_fetch_raises_on_missing_param(self, source: SQLQuerySource) -> None:
        with pytest.raises(ValueError, match="missing required params"):
            await source.fetch()  # 'symbol' not provided

    @pytest.mark.asyncio
    async def test_fetch_raises_lists_missing_params(self) -> None:
        src = SQLQuerySource(sql=self.SQL_MULTI, driver="pg", dsn="dsn://x")
        with pytest.raises(ValueError, match="missing required params"):
            await src.fetch(symbol="AAPL")  # start_date missing

    @pytest.mark.asyncio
    async def test_fetch_no_params_sql_works(self, sample_df: pd.DataFrame) -> None:
        src = SQLQuerySource(sql=self.SQL_NO_PARAMS, driver="pg", dsn="dsn://x")
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=(sample_df, None))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db):
            result = await src.fetch()

        assert result is sample_df

    # --- fetch — execution ---

    @pytest.mark.asyncio
    async def test_fetch_interpolates_and_executes(self, source: SQLQuerySource, sample_df: pd.DataFrame) -> None:
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=(sample_df, None))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db) as mock_asyncdb:
            result = await source.fetch(symbol="AAPL")

        # Verify AsyncDB was created with correct driver and dsn
        mock_asyncdb.assert_called_once_with("pg", dsn="postgresql://localhost/test")
        # Verify escaped SQL was passed to query
        call_args = mock_conn.query.call_args[0][0]
        assert "'AAPL'" in call_args
        assert result is sample_df

    @pytest.mark.asyncio
    async def test_fetch_escapes_string_params(self, sample_df: pd.DataFrame) -> None:
        src = SQLQuerySource(
            sql="SELECT * FROM t WHERE name = {name}",
            driver="pg",
            dsn="dsn://x",
        )
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=(sample_df, None))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db):
            await src.fetch(name="O'Brien")

        executed_sql = mock_conn.query.call_args[0][0]
        assert "O''Brien" in executed_sql

    @pytest.mark.asyncio
    async def test_fetch_raises_on_asyncdb_error(self, source: SQLQuerySource) -> None:
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=(None, "connection refused"))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db):
            with pytest.raises(RuntimeError, match="query failed"):
                await source.fetch(symbol="AAPL")

    @pytest.mark.asyncio
    async def test_fetch_raises_when_not_dataframe(self, source: SQLQuerySource) -> None:
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=({"rows": []}, None))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db):
            with pytest.raises(RuntimeError, match="did not return a DataFrame"):
                await source.fetch(symbol="AAPL")

    # --- dsn resolution ---

    def test_dsn_none_calls_get_default_credentials(self) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.sql.get_default_credentials",
            return_value="postgresql://default/db",
        ) as mock_gdc:
            src = SQLQuerySource(sql="SELECT 1", driver="pg")

        mock_gdc.assert_called_once_with("pg")
        assert src.dsn == "postgresql://default/db"

    def test_dsn_provided_skips_get_default_credentials(self) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.sql.get_default_credentials",
        ) as mock_gdc:
            src = SQLQuerySource(sql="SELECT 1", driver="pg", dsn="my://dsn")

        mock_gdc.assert_not_called()
        assert src.dsn == "my://dsn"

    def test_dsn_none_resolves_to_none_when_no_default(self) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.sql.get_default_credentials",
            return_value=None,
        ):
            src = SQLQuerySource(sql="SELECT 1", driver="mysql")

        assert src.dsn is None

    # --- import ---

    def test_importable_from_sources_package(self) -> None:
        from parrot.tools.dataset_manager.sources import SQLQuerySource as SQLS  # noqa: F401
        assert SQLS is SQLQuerySource


# ─────────────────────────────────────────────────────────────────────────────
# TableSource
# ─────────────────────────────────────────────────────────────────────────────

class TestTableSource:
    """Tests for TableSource — schema prefetch and SQL validation."""

    @pytest.fixture()
    def pg_schema_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "column_name": ["visit_date", "visits", "revenue"],
            "data_type": ["date", "integer", "numeric"],
        })

    def _make_mock_db(self, result_df: pd.DataFrame):
        """Return a mocked AsyncDB that yields result_df from conn.query()."""
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=(result_df, None))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)
        return mock_db

    # --- prefetch_schema ---

    @pytest.mark.asyncio
    async def test_prefetch_pg_uses_information_schema(self, pg_schema_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db")
        mock_db = self._make_mock_db(pg_schema_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            schema = await source.prefetch_schema()

        assert schema == {"visit_date": "date", "visits": "integer", "revenue": "numeric"}

    @pytest.mark.asyncio
    async def test_prefetch_bigquery_uses_information_schema(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        bq_df = pd.DataFrame({
            "column_name": ["date", "visits"],
            "data_type": ["DATE", "INT64"],
        })
        source = TableSource(table="my_dataset.my_table", driver="bigquery", dsn=None)
        mock_db = self._make_mock_db(bq_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            schema = await source.prefetch_schema()

        assert schema == {"date": "DATE", "visits": "INT64"}

    @pytest.mark.asyncio
    async def test_prefetch_mysql_uses_information_schema(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        mysql_df = pd.DataFrame({
            "column_name": ["id", "name"],
            "data_type": ["int", "varchar"],
        })
        source = TableSource(table="mydb.users", driver="mysql", dsn="mysql://localhost/mydb")
        mock_db = self._make_mock_db(mysql_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            schema = await source.prefetch_schema()

        assert schema == {"id": "int", "name": "varchar"}

    @pytest.mark.asyncio
    async def test_prefetch_unknown_driver_uses_limit0_fallback(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        # LIMIT 0 returns empty df with columns
        empty_df = pd.DataFrame({"col_a": pd.Series(dtype="int64"), "col_b": pd.Series(dtype="float64")})
        source = TableSource(table="myschema.mytable", driver="unknown_driver", dsn="dsn://x")
        mock_db = self._make_mock_db(empty_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            schema = await source.prefetch_schema()

        assert "col_a" in schema
        assert "col_b" in schema

    @pytest.mark.asyncio
    async def test_prefetch_strict_schema_raises_on_error(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db", strict_schema=True)
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(return_value=(None, "connection refused"))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            with pytest.raises(RuntimeError):
                await source.prefetch_schema()

    @pytest.mark.asyncio
    async def test_prefetch_soft_schema_continues_on_error(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db", strict_schema=False)
        mock_conn = MagicMock()
        mock_conn.output_format = MagicMock()
        mock_conn.query = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_db = MagicMock()
        mock_db.connection = AsyncMock(return_value=mock_conn)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            schema = await source.prefetch_schema()

        assert schema == {}

    # --- fetch SQL validation ---

    @pytest.mark.asyncio
    async def test_fetch_passes_when_sql_references_table(self, pg_schema_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        data_df = pd.DataFrame({"visit_date": ["2024-01-01"], "visits": [100]})
        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db")
        mock_db = self._make_mock_db(data_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            result = await source.fetch(sql="SELECT * FROM public.orders LIMIT 10")

        assert result is data_df

    @pytest.mark.asyncio
    async def test_fetch_raises_when_sql_missing_table(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db")
        with pytest.raises(ValueError, match="must reference"):
            await source.fetch(sql="SELECT * FROM other_table")

    @pytest.mark.asyncio
    async def test_fetch_raises_when_no_sql(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db")
        with pytest.raises(ValueError, match="requires a 'sql'"):
            await source.fetch()

    # --- cache_key ---

    def test_cache_key_format(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db")
        assert source.cache_key == "table:pg:public.orders"

    def test_cache_key_normalizes_driver(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        source = TableSource(table="ds.tbl", driver="postgresql", dsn="pg://localhost/db")
        assert source.cache_key == "table:pg:ds.tbl"

    # --- import ---

    def test_importable_from_sources_package(self) -> None:
        from parrot.tools.dataset_manager.sources import TableSource as TS  # noqa: F401
        assert TS.__name__ == "TableSource"


# ─────────────────────────────────────────────────────────────────────────────
# DatasetEntry
# ─────────────────────────────────────────────────────────────────────────────

class TestDatasetEntry:
    """Tests for DatasetEntry lifecycle wrapper."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "visits": [100, 150],
            "revenue": [1000.0, 1500.0],
        })

    @pytest.fixture()
    def mock_source(self, sample_df: pd.DataFrame):
        src = MagicMock()
        src.fetch = AsyncMock(return_value=sample_df)
        src.cache_key = "mem:test"
        src.describe = MagicMock(return_value="Mock source")
        src._schema = {}
        return src

    # --- materialize ---

    @pytest.mark.asyncio
    async def test_materialize_calls_source_fetch(self, mock_source, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="test", source=mock_source, auto_detect_types=False)
        df = await entry.materialize()

        mock_source.fetch.assert_called_once()
        assert df is sample_df
        assert entry._df is sample_df

    @pytest.mark.asyncio
    async def test_materialize_cached_skips_fetch(self, mock_source, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="test", source=mock_source, auto_detect_types=False)
        await entry.materialize()
        await entry.materialize()  # second call should skip fetch

        assert mock_source.fetch.call_count == 1

    @pytest.mark.asyncio
    async def test_materialize_force_refresh_re_fetches(self, mock_source, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="test", source=mock_source, auto_detect_types=False)
        await entry.materialize()
        await entry.materialize(force=True)

        assert mock_source.fetch.call_count == 2

    # --- evict ---

    @pytest.mark.asyncio
    async def test_evict_clears_df_and_column_types(self, mock_source, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="test", source=mock_source, auto_detect_types=True)
        await entry.materialize()
        assert entry.loaded is True

        entry.evict()

        assert entry._df is None
        assert entry._column_types is None
        assert entry.loaded is False

    def test_evict_preserves_source(self, mock_source) -> None:
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="test", source=mock_source)
        entry.evict()
        assert entry.source is mock_source

    # --- to_info for unloaded TableSource ---

    def test_to_info_unloaded_table_source_exposes_schema(self) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        # Use a real TableSource instance so isinstance checks in to_info() work
        src = TableSource(table="public.orders", driver="pg", dsn="pg://localhost/db")
        src._schema = {"visit_date": "date", "visits": "integer"}

        entry = DatasetEntry(name="orders", source=src)
        info = entry.to_info(alias="df1")

        assert info.loaded is False
        assert info.source_type == "table"
        assert "visit_date" in info.columns
        assert "visits" in info.columns
        assert info.column_types == {"visit_date": "date", "visits": "integer"}


# ─────────────────────────────────────────────────────────────────────────────
# DatasetManager — new TASK-219 API
# ─────────────────────────────────────────────────────────────────────────────

class TestDatasetManagerNewAPI:
    """Tests for the new DatasetManager registration and materialization API."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "visits": [100, 150],
            "revenue": [1000.0, 1500.0],
        })

    @pytest.fixture()
    def dm(self):
        from parrot.tools.dataset_manager import DatasetManager
        return DatasetManager()

    # --- add_table_source ---

    @pytest.mark.asyncio
    async def test_add_table_source_calls_prefetch(self, dm) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource

        mock_source = MagicMock(spec=TableSource)
        mock_source._schema = {"visit_date": "date", "visits": "integer"}
        mock_source.cache_key = "table:pg:public.orders"
        mock_source.describe = MagicMock(return_value="Table 'public.orders' via pg")
        mock_source.prefetch_schema = AsyncMock(return_value=mock_source._schema)

        # Patch at the module level where TableSource is defined (since tool.py imports it locally)
        with patch("parrot.tools.dataset_manager.sources.table.TableSource", return_value=mock_source):
            msg = await dm.add_table_source("orders", table="public.orders", driver="pg", dsn="pg://x")

        mock_source.prefetch_schema.assert_called_once()
        assert "orders" in dm._datasets
        assert "2 columns" in msg

    # --- add_sql_source ---

    def test_add_sql_source_registers_without_prefetch(self, dm) -> None:
        msg = dm.add_sql_source("sql_ds", sql="SELECT * FROM t WHERE id = {id}", driver="pg", dsn="pg://x")
        assert "sql_ds" in dm._datasets
        assert dm._datasets["sql_ds"].loaded is False
        assert "pg" in msg

    # --- backward compat ---

    def test_add_query_wraps_in_query_slug_source(self, dm) -> None:
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        dm.add_query("lazy_ds", "my_slug")
        entry = dm._datasets["lazy_ds"]
        assert isinstance(entry.source, QuerySlugSource)
        assert entry.source.slug == "my_slug"

    def test_add_dataframe_wraps_in_inmemory_source(self, dm, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.sources.memory import InMemorySource

        dm.add_dataframe("inmem_ds", sample_df)
        entry = dm._datasets["inmem_ds"]
        assert isinstance(entry.source, InMemorySource)
        assert entry.loaded is True

    # --- materialize with Redis mock ---

    @pytest.mark.asyncio
    async def test_materialize_redis_hit_skips_fetch(self, dm, sample_df: pd.DataFrame) -> None:
        import io

        buf = io.BytesIO()
        sample_df.to_parquet(buf, index=False, compression="snappy")
        parquet_bytes = buf.getvalue()

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=parquet_bytes)
        mock_redis.aclose = AsyncMock()

        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=sample_df)
        mock_source.cache_key = "mem:test"
        mock_source._schema = {}
        mock_source.has_builtin_cache = False
        mock_source.describe = MagicMock(return_value="Mock source")

        from parrot.tools.dataset_manager.tool import DatasetEntry
        entry = DatasetEntry(name="test_ds", source=mock_source, auto_detect_types=False)
        dm._datasets["test_ds"] = entry

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            df = await dm.materialize("test_ds")

        mock_source.fetch.assert_not_called()
        assert df.shape == sample_df.shape

    @pytest.mark.asyncio
    async def test_materialize_redis_miss_calls_fetch(self, dm, sample_df: pd.DataFrame) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=sample_df)
        mock_source.cache_key = "mem:test"
        mock_source._schema = {}
        mock_source.has_builtin_cache = False
        mock_source.describe = MagicMock(return_value="Mock source")

        from parrot.tools.dataset_manager.tool import DatasetEntry
        entry = DatasetEntry(name="test_ds", source=mock_source, auto_detect_types=False)
        dm._datasets["test_ds"] = entry

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            df = await dm.materialize("test_ds")

        mock_source.fetch.assert_called_once()
        assert df is sample_df

    @pytest.mark.asyncio
    async def test_materialize_force_refresh_bypasses_redis(self, dm, sample_df: pd.DataFrame) -> None:
        import io

        buf = io.BytesIO()
        sample_df.to_parquet(buf, index=False, compression="snappy")

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=buf.getvalue())  # Redis has data
        mock_redis.setex = AsyncMock()
        mock_redis.aclose = AsyncMock()

        mock_source = MagicMock()
        mock_source.fetch = AsyncMock(return_value=sample_df)
        mock_source.cache_key = "mem:test"
        mock_source._schema = {}
        mock_source.has_builtin_cache = False
        mock_source.describe = MagicMock(return_value="Mock source")

        from parrot.tools.dataset_manager.tool import DatasetEntry
        entry = DatasetEntry(name="test_ds", source=mock_source, auto_detect_types=False)
        dm._datasets["test_ds"] = entry

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            await dm.materialize("test_ds", force_refresh=True)

        # fetch was called despite Redis having data
        mock_source.fetch.assert_called_once()

    # --- eviction ---

    def test_evict_single_releases_df(self, dm, sample_df: pd.DataFrame) -> None:
        dm.add_dataframe("ds1", sample_df)
        assert dm._datasets["ds1"].loaded is True

        result = dm.evict("ds1")

        assert dm._datasets["ds1"].loaded is False
        assert "evicted" in result.lower()
        assert dm._datasets["ds1"].source is not None  # source retained

    def test_evict_all_releases_all_dfs(self, dm, sample_df: pd.DataFrame) -> None:
        dm.add_dataframe("ds1", sample_df)
        dm.add_dataframe("ds2", sample_df)

        result = dm.evict_all()

        assert dm._datasets["ds1"].loaded is False
        assert dm._datasets["ds2"].loaded is False
        assert "2" in result

    def test_evict_unactive_only_evicts_inactive(self, dm, sample_df: pd.DataFrame) -> None:
        dm.add_dataframe("active_ds", sample_df, is_active=True)
        dm.add_dataframe("inactive_ds", sample_df, is_active=False)

        result = dm.evict_unactive()

        assert dm._datasets["active_ds"].loaded is True
        assert dm._datasets["inactive_ds"].loaded is False
        assert "1" in result

    # --- LLM tools ---

    @pytest.mark.asyncio
    async def test_list_available_shows_unloaded_table_with_schema(self, dm) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        src = MagicMock(spec=TableSource)
        src._schema = {"visit_date": "date", "visits": "integer"}
        src.cache_key = "table:pg:public.orders"
        src.describe = MagicMock(return_value="Table 'public.orders' via pg")

        entry = DatasetEntry(name="orders", source=src, auto_detect_types=False)
        dm._datasets["orders"] = entry

        result = await dm.list_available()
        assert len(result) == 1
        info = result[0]
        assert info["loaded"] is False
        assert "visit_date" in info["columns"]

    @pytest.mark.asyncio
    async def test_get_metadata_unloaded_returns_schema(self, dm) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        src = MagicMock(spec=TableSource)
        src._schema = {"col_a": "integer", "col_b": "text"}
        src.cache_key = "table:pg:public.test"
        src.describe = MagicMock(return_value="Table 'public.test' via pg")

        entry = DatasetEntry(name="test_tbl", source=src, auto_detect_types=False)
        dm._datasets["test_tbl"] = entry

        result = await dm.get_metadata("test_tbl")
        assert result["loaded"] is False
        assert "col_a" in result.get("columns", [])

    @pytest.mark.asyncio
    async def test_fetch_dataset_table_source_requires_sql(self, dm) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        src = MagicMock(spec=TableSource)
        src._schema = {"col": "int"}
        src.cache_key = "table:pg:public.orders"
        src.describe = MagicMock(return_value="orders")
        # fetch raises ValueError when no sql
        src.fetch = AsyncMock(side_effect=ValueError("requires a 'sql'"))

        entry = DatasetEntry(name="orders", source=src, auto_detect_types=False)
        dm._datasets["orders"] = entry

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()
        mock_redis.aclose = AsyncMock()

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            result = await dm.fetch_dataset("orders")

        assert isinstance(result, dict) and "error" in result

    @pytest.mark.asyncio
    async def test_evict_dataset_tool_frees_memory(self, dm, sample_df: pd.DataFrame) -> None:
        dm.add_dataframe("ds1", sample_df)
        assert dm._datasets["ds1"].loaded is True

        result = await dm.evict_dataset("ds1")

        assert dm._datasets["ds1"].loaded is False
        assert "evicted" in result.lower()

    @pytest.mark.asyncio
    async def test_get_source_schema_before_load(self, dm) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        src = MagicMock(spec=TableSource)
        src._schema = {"col_a": "integer", "col_b": "text"}
        src.cache_key = "table:pg:public.test"
        src.describe = MagicMock(return_value="Table 'public.test' via pg (2 columns known)")

        entry = DatasetEntry(name="test_tbl", source=src, auto_detect_types=False)
        entry._column_types = None  # not yet materialized
        dm._datasets["test_tbl"] = entry

        result = await dm.get_source_schema("test_tbl")
        assert "col_a" in result
        assert "col_b" in result

    def test_llm_guide_renders_mixed_states(self, dm, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        # Add a loaded in-memory dataset
        dm.add_dataframe("local_data", sample_df)

        # Add an unloaded table source
        src = MagicMock(spec=TableSource)
        src._schema = {"visit_date": "date", "visits": "integer"}
        src.cache_key = "table:pg:public.orders"
        src.describe = MagicMock(return_value="Table 'public.orders' via pg")
        entry = DatasetEntry(name="orders", source=src, auto_detect_types=False)
        dm._datasets["orders"] = entry

        guide = dm._generate_dataframe_guide()

        assert "local_data" in guide
        assert "DATAFRAME" in guide or "loaded" in guide.lower()
        assert "orders" in guide
        assert "TABLE" in guide or "not loaded" in guide.lower()

    def test_cache_key_shared_across_managers(self) -> None:
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        slug = "shared_report"
        src1 = QuerySlugSource(slug=slug)
        src2 = QuerySlugSource(slug=slug)
        assert src1.cache_key == src2.cache_key == f"qs:{slug}"


class TestAddDataset:
    """Tests for DatasetManager.add_dataset — eager-load unified method."""

    @pytest.fixture()
    def dm(self):
        from parrot.tools.dataset_manager import DatasetManager
        return DatasetManager()

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({"x": [1, 2], "y": [3, 4]})

    # --- validation ---

    @pytest.mark.asyncio
    async def test_rejects_no_source(self, dm) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            await dm.add_dataset("bad")

    @pytest.mark.asyncio
    async def test_rejects_multiple_sources(self, dm, sample_df) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            await dm.add_dataset("bad", dataframe=sample_df, query_slug="slug")

    @pytest.mark.asyncio
    async def test_query_requires_driver(self, dm) -> None:
        with pytest.raises(ValueError, match="driver is required"):
            await dm.add_dataset("bad", query="SELECT 1")

    @pytest.mark.asyncio
    async def test_table_requires_driver(self, dm) -> None:
        with pytest.raises(ValueError, match="driver is required"):
            await dm.add_dataset("bad", table="public.t")

    # --- dataframe mode ---

    @pytest.mark.asyncio
    async def test_dataframe_mode(self, dm, sample_df) -> None:
        msg = await dm.add_dataset("my_df", dataframe=sample_df)
        assert "my_df" in dm._datasets
        entry = dm._datasets["my_df"]
        assert entry.loaded
        assert entry.df.shape == (2, 2)
        assert "2 rows" in msg

    # --- query_slug mode ---

    @pytest.mark.asyncio
    async def test_query_slug_mode(self, dm, sample_df) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource.fetch",
            new_callable=AsyncMock,
            return_value=sample_df,
        ):
            msg = await dm.add_dataset("qs_ds", query_slug="my_slug")

        entry = dm._datasets["qs_ds"]
        assert entry.loaded
        assert entry.df.equals(sample_df)

    @pytest.mark.asyncio
    async def test_query_slug_passes_conditions(self, dm, sample_df) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource.fetch",
            new_callable=AsyncMock,
            return_value=sample_df,
        ) as mock_fetch:
            await dm.add_dataset(
                "qs_cond", query_slug="slug", conditions={"year": 2025}
            )
        mock_fetch.assert_called_once_with(year=2025)

    # --- query (SQL template) mode ---

    @pytest.mark.asyncio
    async def test_sql_query_mode(self, dm, sample_df) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.sql.SQLQuerySource.fetch",
            new_callable=AsyncMock,
            return_value=sample_df,
        ):
            msg = await dm.add_dataset(
                "sql_ds",
                query="SELECT * FROM t WHERE id = {id}",
                driver="pg",
                conditions={"id": 42},
            )

        entry = dm._datasets["sql_ds"]
        assert entry.loaded
        assert entry.df.equals(sample_df)

    # --- table mode ---

    @pytest.mark.asyncio
    async def test_table_mode_with_sql(self, dm, sample_df) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.table.TableSource.fetch",
            new_callable=AsyncMock,
            return_value=sample_df,
        ) as mock_fetch:
            await dm.add_dataset(
                "tbl_ds",
                table="schema.orders",
                driver="pg",
                sql="SELECT id, total FROM schema.orders WHERE total > 100",
            )
        mock_fetch.assert_called_once_with(
            sql="SELECT id, total FROM schema.orders WHERE total > 100"
        )
        assert dm._datasets["tbl_ds"].loaded

    @pytest.mark.asyncio
    async def test_table_mode_default_sql(self, dm, sample_df) -> None:
        with patch(
            "parrot.tools.dataset_manager.sources.table.TableSource.fetch",
            new_callable=AsyncMock,
            return_value=sample_df,
        ) as mock_fetch:
            await dm.add_dataset("tbl_all", table="public.t", driver="pg")
        mock_fetch.assert_called_once_with(sql="SELECT * FROM public.t")

    # --- result is InMemorySource ---

    @pytest.mark.asyncio
    async def test_result_is_in_memory(self, dm, sample_df) -> None:
        from parrot.tools.dataset_manager.sources.memory import InMemorySource

        with patch(
            "parrot.tools.dataset_manager.sources.query_slug.QuerySlugSource.fetch",
            new_callable=AsyncMock,
            return_value=sample_df,
        ):
            await dm.add_dataset("check_src", query_slug="slug")

        entry = dm._datasets["check_src"]
        assert isinstance(entry.source, InMemorySource)
