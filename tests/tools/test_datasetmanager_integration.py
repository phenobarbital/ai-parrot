"""Integration tests for DatasetManager — full lifecycle with mocked drivers and Redis.

Covers:
- TableSource full flow (pg + BigQuery)
- SQL source parameterized queries + Redis cache hit/miss
- QuerySlug materialize and cache
- Backward compat: add_dataframe / add_query
- Parquet round-trip dtype and value preservation
- Mixed source types in one manager
- Cache key sharing across two DatasetManager instances
"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_asyncdb_mock(result_df: pd.DataFrame, errors=None):
    """Build a fully-mocked AsyncDB instance that returns result_df on query()."""
    mock_conn = MagicMock()
    mock_conn.output_format = MagicMock()
    mock_conn.query = AsyncMock(return_value=(result_df, errors))
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_db = MagicMock()
    mock_db.connection = AsyncMock(return_value=mock_conn)
    return mock_db, mock_conn


def _make_redis_mock(cached_df: pd.DataFrame | None = None):
    """Build a mock Redis client.

    If cached_df is provided, ``get`` returns Parquet bytes for that DataFrame.
    Otherwise ``get`` returns None (cache miss).
    """
    mock_redis = AsyncMock()
    if cached_df is not None:
        buf = io.BytesIO()
        cached_df.to_parquet(buf, index=False, compression="snappy")
        mock_redis.get = AsyncMock(return_value=buf.getvalue())
    else:
        mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()
    mock_redis.aclose = AsyncMock()
    return mock_redis


def _make_dm():
    from parrot.tools.dataset_manager import DatasetManager
    return DatasetManager()


# ─────────────────────────────────────────────────────────────────────────────
# TestTableSourceFullFlow
# ─────────────────────────────────────────────────────────────────────────────

class TestTableSourceFullFlow:
    """End-to-end flow: register TableSource → schema prefetch → materialize."""

    @pytest.fixture()
    def pg_schema_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "column_name": ["visit_date", "visits"],
            "data_type": ["date", "integer"],
        })

    @pytest.fixture()
    def pg_data_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "visit_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "visits": [100, 200],
        })

    @pytest.fixture()
    def bq_schema_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "column_name": ["event_date", "revenue"],
            "data_type": ["DATE", "FLOAT64"],
        })

    @pytest.fixture()
    def bq_data_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "event_date": pd.to_datetime(["2024-01-01"]),
            "revenue": [9999.5],
        })

    @pytest.mark.asyncio
    async def test_table_source_full_flow_pg(
        self, pg_schema_df: pd.DataFrame, pg_data_df: pd.DataFrame
    ) -> None:
        """Full pg lifecycle: register → schema prefetch → guide → materialize."""
        dm = _make_dm()
        mock_db, mock_conn = _make_asyncdb_mock(pg_schema_df)

        # 1. Add table source — triggers INFORMATION_SCHEMA prefetch
        with patch("asyncdb.AsyncDB", return_value=mock_db):
            msg = await dm.add_table_source(
                "orders",
                table="public.orders",
                driver="pg",
                dsn="pg://localhost/db",
            )

        entry = dm._datasets["orders"]

        # 2. Source registered, not yet materialized
        assert "orders" in dm._datasets
        assert entry.loaded is False
        assert "2 columns" in msg

        # 3. list_available() includes column names from schema
        available = await dm.list_available()
        assert len(available) == 1
        info = available[0]
        assert info["loaded"] is False
        assert "visit_date" in info.get("columns", [])
        assert "visits" in info.get("columns", [])

        # 4. LLM guide shows TABLE — not loaded with column list
        guide = dm._generate_dataframe_guide()
        assert "orders" in guide
        assert "TABLE" in guide or "not loaded" in guide.lower()
        assert "visit_date" in guide or "visits" in guide

        # 5. Materialize — fetch data
        mock_redis = _make_redis_mock(cached_df=None)  # cache miss
        mock_data_db, _ = _make_asyncdb_mock(pg_data_df)

        with patch("asyncdb.AsyncDB", return_value=mock_data_db):
            with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
                result = await dm.materialize(
                    "orders", sql="SELECT * FROM public.orders LIMIT 10"
                )

        assert entry.loaded is True
        assert result.shape == pg_data_df.shape

    @pytest.mark.asyncio
    async def test_table_source_full_flow_bigquery(
        self, bq_schema_df: pd.DataFrame, bq_data_df: pd.DataFrame
    ) -> None:
        """Full BigQuery lifecycle with mocked driver."""
        dm = _make_dm()
        mock_db, _ = _make_asyncdb_mock(bq_schema_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            msg = await dm.add_table_source(
                "bq_events",
                table="my_dataset.events",
                driver="bigquery",
                dsn=None,
            )

        entry = dm._datasets["bq_events"]
        assert entry.loaded is False
        assert "2 columns" in msg

        # Verify schema was captured
        available = await dm.list_available()
        info = available[0]
        assert "event_date" in info.get("columns", [])
        assert "revenue" in info.get("columns", [])

    @pytest.mark.asyncio
    async def test_table_source_sql_validation_integration(self) -> None:
        """fetch_dataset with wrong table in SQL should raise ValueError."""
        dm = _make_dm()
        schema_df = pd.DataFrame({
            "column_name": ["visit_date", "visits"],
            "data_type": ["date", "integer"],
        })
        mock_db, _ = _make_asyncdb_mock(schema_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            await dm.add_table_source(
                "finance_visits",
                table="troc.finance_visits_details",
                driver="pg",
                dsn="pg://localhost/db",
            )

        mock_redis = _make_redis_mock(cached_df=None)

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            # SQL references wrong table — should return an error message
            result = await dm.fetch_dataset(
                "finance_visits",
                sql="SELECT * FROM orders LIMIT 10",
            )

        # fetch_dataset catches ValueError and returns error dict
        assert isinstance(result, dict) and "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# TestSQLSourceFlow
# ─────────────────────────────────────────────────────────────────────────────

class TestSQLSourceFlow:
    """Parameterized SQL queries + Redis cache hit/miss verification."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "order_id": [1, 2, 3],
            "total": [100.0, 200.0, 300.0],
        })

    @pytest.mark.asyncio
    async def test_sql_source_parameterized_query(self, sample_df: pd.DataFrame) -> None:
        """Parameterized SQL materializes, caches to Redis, then hits cache on second call."""
        dm = _make_dm()
        dm.add_sql_source(
            "report",
            sql="SELECT * FROM orders WHERE date >= {start}",
            driver="pg",
            dsn="pg://localhost/db",
        )

        # First call: Redis miss → fetch → cache written
        mock_redis_miss = _make_redis_mock(cached_df=None)
        mock_db, _ = _make_asyncdb_mock(sample_df)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db):
            with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis_miss)):
                df1 = await dm.materialize("report", start="2024-01-01")

        assert df1 is not None
        assert df1.shape == sample_df.shape
        mock_redis_miss.setex.assert_called_once()

        # Second call: Redis hit → no fetch
        # Evict memory so dm actually checks Redis
        dm.evict("report")
        mock_redis_hit = _make_redis_mock(cached_df=sample_df)
        source = dm._datasets["report"].source
        source.fetch = AsyncMock(return_value=sample_df)

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis_hit)):
            df2 = await dm.materialize("report", start="2024-01-01")

        source.fetch.assert_not_called()
        assert df2.shape == sample_df.shape

    @pytest.mark.asyncio
    async def test_sql_source_force_refresh(self, sample_df: pd.DataFrame) -> None:
        """force_refresh=True bypasses Redis and calls source.fetch again."""
        dm = _make_dm()
        dm.add_sql_source(
            "report",
            sql="SELECT * FROM orders WHERE date >= {start}",
            driver="pg",
            dsn="pg://localhost/db",
        )

        # Redis has cached data, but force_refresh should still call fetch
        mock_redis = _make_redis_mock(cached_df=sample_df)
        mock_db, _ = _make_asyncdb_mock(sample_df)

        # Spy on source.fetch
        source = dm._datasets["report"].source
        source.fetch = AsyncMock(return_value=sample_df)

        with patch("parrot.tools.dataset_manager.sources.sql.AsyncDB", return_value=mock_db):
            with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
                await dm.materialize("report", force_refresh=True, start="2024-01-01")

        source.fetch.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# TestQuerySlugFlow
# ─────────────────────────────────────────────────────────────────────────────

class TestQuerySlugFlow:
    """QuerySlugSource: DatasetManager skips Redis; caching is QS's responsibility."""

    @pytest.fixture()
    def slug_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "day": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "count": [50, 75],
        })

    @pytest.mark.asyncio
    async def test_query_slug_skips_redis_cache(self, slug_df: pd.DataFrame) -> None:
        """QS-backed sources bypass DatasetManager's Redis layer entirely."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        dm = _make_dm()
        dm.add_query("daily", query_slug="troc_daily_report")

        entry = dm._datasets["daily"]
        assert isinstance(entry.source, QuerySlugSource)
        assert entry.source.has_builtin_cache is True

        mock_redis = _make_redis_mock(cached_df=None)
        entry.source.fetch = AsyncMock(return_value=slug_df)

        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            df1 = await dm.materialize("daily")

        assert df1.shape == slug_df.shape
        # DatasetManager must NOT write to Redis for QS sources
        mock_redis.setex.assert_not_called()
        # DatasetManager must NOT read from Redis for QS sources
        mock_redis.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_slug_second_call_uses_memory(self, slug_df: pd.DataFrame) -> None:
        """Second materialize() without eviction returns in-memory df (no QS call)."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        dm = _make_dm()
        dm.add_query("daily", query_slug="troc_daily_report")

        entry = dm._datasets["daily"]
        entry.source.fetch = AsyncMock(return_value=slug_df)

        await dm.materialize("daily")
        entry.source.fetch.reset_mock()

        # Second call: already in memory, fetch must not be called again
        await dm.materialize("daily")
        entry.source.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_query_slug_force_refresh_bubbles_to_qs(self, slug_df: pd.DataFrame) -> None:
        """force_refresh=True passes refresh=True into QS conditions."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        dm = _make_dm()
        dm.add_query("daily", query_slug="troc_daily_report")

        entry = dm._datasets["daily"]
        entry.source.fetch = AsyncMock(return_value=slug_df)

        await dm.materialize("daily", force_refresh=True)

        entry.source.fetch.assert_called_once_with(force_refresh=True)


# ─────────────────────────────────────────────────────────────────────────────
# TestBackwardCompat
# ─────────────────────────────────────────────────────────────────────────────

class TestBackwardCompat:
    """Existing add_dataframe and add_query APIs must be unchanged."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})

    def test_backward_compat_add_dataframe_wraps_inmemory(self, sample_df: pd.DataFrame) -> None:
        """add_dataframe still creates an InMemorySource-backed entry."""
        from parrot.tools.dataset_manager.sources.memory import InMemorySource

        dm = _make_dm()
        dm.add_dataframe("local", df=sample_df)

        entry = dm._datasets["local"]
        assert isinstance(entry.source, InMemorySource)
        assert entry.loaded is True

    @pytest.mark.asyncio
    async def test_backward_compat_add_dataframe_materialize(self, sample_df: pd.DataFrame) -> None:
        """materialize() on InMemorySource returns the same DataFrame."""
        dm = _make_dm()
        dm.add_dataframe("local", df=sample_df)

        mock_redis = _make_redis_mock(cached_df=None)
        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            result = await dm.materialize("local")

        assert result is not None
        assert result.shape == sample_df.shape

    def test_backward_compat_add_query_wraps_queryslugsource(self) -> None:
        """add_query still creates a QuerySlugSource-backed entry."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        dm = _make_dm()
        dm.add_query("slug_data", query_slug="some_slug")

        entry = dm._datasets["slug_data"]
        assert isinstance(entry.source, QuerySlugSource)
        assert entry.source.slug == "some_slug"
        assert entry.loaded is False

    def test_backward_compat_dataset_entry_with_df_kwarg(self, sample_df: pd.DataFrame) -> None:
        """DatasetEntry(df=...) backward-compat constructor works."""
        from parrot.tools.dataset_manager.sources.memory import InMemorySource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="legacy_df", df=sample_df)
        assert isinstance(entry.source, InMemorySource)
        assert entry.loaded is True

    def test_backward_compat_dataset_entry_with_query_slug_kwarg(self) -> None:
        """DatasetEntry(query_slug=...) backward-compat constructor works."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        entry = DatasetEntry(name="legacy_slug", query_slug="my_slug")
        assert isinstance(entry.source, QuerySlugSource)
        assert entry.source.slug == "my_slug"
        assert entry.loaded is False


# ─────────────────────────────────────────────────────────────────────────────
# TestParquetRoundtrip
# ─────────────────────────────────────────────────────────────────────────────

class TestParquetRoundtrip:
    """Parquet serialization preserves dtypes and values exactly."""

    @pytest.fixture()
    def typed_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "int_col": pd.array([1, 2, 3], dtype="int64"),
            "float_col": pd.array([1.1, 2.2, 3.3], dtype="float64"),
            "dt_col": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "str_col": pd.array(["a", "b", "c"], dtype="object"),
        })

    def _roundtrip(self, df: pd.DataFrame) -> pd.DataFrame:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False, compression="snappy")
        return pd.read_parquet(io.BytesIO(buf.getvalue()))

    def test_parquet_roundtrip_dtypes(self, typed_df: pd.DataFrame) -> None:
        result = self._roundtrip(typed_df)
        for col in typed_df.columns:
            assert result[col].dtype == typed_df[col].dtype, (
                f"dtype mismatch for column '{col}': "
                f"{result[col].dtype} != {typed_df[col].dtype}"
            )

    def test_parquet_roundtrip_values(self, typed_df: pd.DataFrame) -> None:
        result = self._roundtrip(typed_df)
        pd.testing.assert_frame_equal(result, typed_df)

    @pytest.mark.asyncio
    async def test_parquet_roundtrip_via_redis_cache(self, typed_df: pd.DataFrame) -> None:
        """DatasetManager caching preserves dtypes end-to-end via Redis setex/get."""
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        dm = _make_dm()

        # Use SQLQuerySource (no built-in cache) so materialize goes through Redis
        src = SQLQuerySource(sql="SELECT 1", driver="pg", dsn="postgresql://localhost/test")
        src.fetch = AsyncMock(return_value=typed_df)
        entry = DatasetEntry(name="typed_ds", source=src, auto_detect_types=False)
        dm._datasets["typed_ds"] = entry

        # First materialize — Redis miss → fetch → write Parquet to Redis
        mock_redis_miss = _make_redis_mock(cached_df=None)
        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis_miss)):
            await dm.materialize("typed_ds")

        # Capture what was written to Redis
        assert mock_redis_miss.setex.called
        call_args = mock_redis_miss.setex.call_args[0]
        parquet_bytes = call_args[2]  # setex(key, ttl, value)

        assert isinstance(parquet_bytes, bytes)
        restored = pd.read_parquet(io.BytesIO(parquet_bytes))
        for col in typed_df.columns:
            assert restored[col].dtype == typed_df[col].dtype


# ─────────────────────────────────────────────────────────────────────────────
# TestMultipleSourcesMixed
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleSourcesMixed:
    """All 4 source types coexist in a single DatasetManager."""

    @pytest.fixture()
    def sample_df(self) -> pd.DataFrame:
        return pd.DataFrame({"x": [1, 2], "y": [3.0, 4.0]})

    @pytest.mark.asyncio
    async def test_multiple_sources_same_manager(self, sample_df: pd.DataFrame) -> None:
        from parrot.tools.dataset_manager.sources.memory import InMemorySource
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.sources.table import TableSource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        dm = _make_dm()

        # 1. InMemorySource
        dm.add_dataframe("mem_entry", df=sample_df)

        # 2. QuerySlugSource
        dm.add_query("slug_entry", query_slug="my_slug")

        # 3. SQLQuerySource
        dm.add_sql_source(
            "sql_entry",
            sql="SELECT * FROM t WHERE id = {id}",
            driver="pg",
            dsn="pg://localhost/db",
        )

        # 4. TableSource (requires async prefetch)
        schema_df = pd.DataFrame({
            "column_name": ["col_a", "col_b"],
            "data_type": ["integer", "text"],
        })
        mock_db, _ = _make_asyncdb_mock(schema_df)
        with patch("asyncdb.AsyncDB", return_value=mock_db):
            await dm.add_table_source(
                "table_entry",
                table="public.orders",
                driver="pg",
                dsn="pg://localhost/db",
            )

        # list_available returns all 4
        available = await dm.list_available()
        names = {info["name"] for info in available}
        assert {"mem_entry", "slug_entry", "sql_entry", "table_entry"}.issubset(names)

        # Verify source_type values
        by_name = {info["name"]: info for info in available}
        assert by_name["mem_entry"]["source_type"] in ("memory", "dataframe")
        assert by_name["slug_entry"]["source_type"] == "query_slug"
        assert by_name["sql_entry"]["source_type"] == "sql"
        assert by_name["table_entry"]["source_type"] == "table"

        # get_metadata for table_entry returns schema despite loaded=False
        meta = await dm.get_metadata("table_entry")
        assert meta["loaded"] is False
        assert "col_a" in meta.get("columns", [])

        # Materialize only InMemorySource
        mock_redis = _make_redis_mock(cached_df=None)
        with patch.object(dm, "_get_redis_connection", AsyncMock(return_value=mock_redis)):
            await dm.materialize("mem_entry")

        assert dm._datasets["mem_entry"].loaded is True
        assert dm._datasets["slug_entry"].loaded is False
        assert dm._datasets["sql_entry"].loaded is False
        assert dm._datasets["table_entry"].loaded is False


# ─────────────────────────────────────────────────────────────────────────────
# TestCacheKeySharing
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheKeySharing:
    """Two DatasetManager instances share the same Redis key for same slug."""

    @pytest.fixture()
    def shared_df(self) -> pd.DataFrame:
        return pd.DataFrame({"metric": [10, 20, 30]})

    def test_cache_key_identical_for_same_slug(self) -> None:
        """cache_key is deterministic — same slug → same key in both managers."""
        from parrot.tools.dataset_manager.sources.query_slug import QuerySlugSource

        slug = "shared_report"
        src1 = QuerySlugSource(slug=slug)
        src2 = QuerySlugSource(slug=slug)

        assert src1.cache_key == src2.cache_key == f"qs:{slug}"

    @pytest.mark.asyncio
    async def test_cache_key_shared_across_managers(self, shared_df: pd.DataFrame) -> None:
        """Manager1 materializes; Manager2 gets Redis hit without calling source.

        Uses SQLQuerySource (no built-in cache) to exercise DatasetManager's
        Redis layer. QS-backed sources are excluded because QS manages its own
        caching — DatasetManager intentionally skips Redis for them.
        """
        from parrot.tools.dataset_manager.sources.sql import SQLQuerySource
        from parrot.tools.dataset_manager.tool import DatasetEntry

        sql = "SELECT * FROM shared_report"
        dm1 = _make_dm()
        dm2 = _make_dm()

        src1 = SQLQuerySource(sql=sql, driver="pg", dsn="postgresql://localhost/test")
        src2 = SQLQuerySource(sql=sql, driver="pg", dsn="postgresql://localhost/test")

        dm1._datasets["report"] = DatasetEntry(name="report", source=src1)
        dm2._datasets["report"] = DatasetEntry(name="report", source=src2)

        # Confirm both sources share the same cache key
        assert src1.cache_key == src2.cache_key

        # Materialize in dm1 — Redis miss → fetch → write
        src1.fetch = AsyncMock(return_value=shared_df)
        mock_redis_write = _make_redis_mock(cached_df=None)

        with patch.object(dm1, "_get_redis_connection", AsyncMock(return_value=mock_redis_write)):
            df1 = await dm1.materialize("report")

        assert df1.shape == shared_df.shape
        mock_redis_write.setex.assert_called_once()

        # Materialize in dm2 — Redis hit → source NOT called
        src2.fetch = AsyncMock(return_value=shared_df)
        mock_redis_hit = _make_redis_mock(cached_df=shared_df)

        with patch.object(dm2, "_get_redis_connection", AsyncMock(return_value=mock_redis_hit)):
            df2 = await dm2.materialize("report")

        src2.fetch.assert_not_called()
        assert df2.shape == shared_df.shape


# ─────────────────────────────────────────────────────────────────────────────
# Permanent Filter Integration
# ─────────────────────────────────────────────────────────────────────────────

class TestPermanentFilterIntegration:
    """Integration tests for permanent_filter propagation through DatasetManager."""

    def test_add_query_with_permanent_filter(self) -> None:
        """add_query(permanent_filter=...) propagates to QuerySlugSource."""
        dm = _make_dm()
        pf = {"tenant": "pokemon"}
        dm.add_query(name="sales", query_slug="sales_slug", permanent_filter=pf)

        entry = dm._datasets["sales"]
        assert entry.source._permanent_filter == pf

    @pytest.mark.asyncio
    async def test_add_table_source_with_permanent_filter(self) -> None:
        """add_table_source(permanent_filter=...) propagates to TableSource."""
        dm = _make_dm()
        pf = {"status": "active"}

        # Mock the schema prefetch
        schema_df = pd.DataFrame({
            "column_name": ["id", "status"],
            "data_type": ["integer", "text"],
        })
        mock_db, _ = _make_asyncdb_mock(schema_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            await dm.add_table_source(
                name="orders",
                table="public.orders",
                driver="pg",
                dsn="pg://localhost/db",
                permanent_filter=pf,
            )

        entry = dm._datasets["orders"]
        assert entry.source._permanent_filter == pf

    @pytest.mark.asyncio
    async def test_add_dataset_query_slug_permanent_filter(self) -> None:
        """add_dataset(query_slug=..., permanent_filter=...) propagates to QuerySlugSource."""
        dm = _make_dm()
        pf = {"region": "US"}
        result_df = pd.DataFrame({"id": [1, 2], "region": ["US", "US"]})

        mock_qs_instance = MagicMock()
        mock_qs_instance.query = AsyncMock(return_value=(result_df, None))

        with patch(
            "parrot.tools.dataset_manager.sources.query_slug.QS",
            return_value=mock_qs_instance,
        ) as mock_qs_cls:
            await dm.add_dataset(
                name="us_sales",
                query_slug="sales",
                permanent_filter=pf,
            )

        # Verify the QS was called with permanent filter merged in
        call_conditions = mock_qs_cls.call_args[1]["conditions"]
        assert call_conditions["region"] == "US"

    @pytest.mark.asyncio
    async def test_add_dataset_table_permanent_filter(self) -> None:
        """add_dataset(table=..., permanent_filter=...) propagates to TableSource."""
        dm = _make_dm()
        pf = {"status": "active"}
        data_df = pd.DataFrame({"id": [1], "status": ["active"]})
        mock_db, mock_conn = _make_asyncdb_mock(data_df)

        with patch("asyncdb.AsyncDB", return_value=mock_db):
            await dm.add_dataset(
                name="active_orders",
                table="public.orders",
                driver="pg",
                dsn="pg://localhost/db",
                permanent_filter=pf,
            )

        # Verify the SQL included the permanent filter
        call_args = mock_conn.query.call_args[0][0]
        assert "WHERE status = 'active'" in call_args

    def test_add_dataset_no_filter_compat(self) -> None:
        """Omitting permanent_filter preserves existing behavior."""
        dm = _make_dm()
        dm.add_query(name="sales", query_slug="sales_slug")

        entry = dm._datasets["sales"]
        assert entry.source._permanent_filter == {}
