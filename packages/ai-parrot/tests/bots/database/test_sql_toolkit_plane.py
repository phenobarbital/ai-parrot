"""Tests for TASK-3692: error-driven read-repair, plane-first warm, plane-aware
validate_query and generate_query (FEAT-600 SQL Schema Plane).
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name: str, type_: str = "text"):
    return {"name": name, "type": type_, "nullable": True}


def _meta(schema: str, table: str, cols=None, completeness=Completeness.FULL, foreign_keys=None):
    return TableMetadata(
        schema=schema,
        tablename=table,
        table_type="BASE TABLE",
        full_name=f"{schema}.{table}",
        completeness=completeness,
        columns=cols if cols is not None else [_col("id", "integer")],
        foreign_keys=foreign_keys or [],
        source="information_schema",
    )


def _make_toolkit(cache=None, allowed_schemas=None, primary_schema="public"):
    tk = SQLToolkit.__new__(SQLToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = logging.getLogger("test.plane")
    tk.cache_partition = cache
    tk.allowed_schemas = allowed_schemas or ["epson", "public"]
    tk.primary_schema = primary_schema
    tk.tables = []
    tk.retry_config = None
    tk.dsn = "postgresql://fake:fake@localhost/fake"
    tk.read_only = True
    tk.database_type = "postgresql"
    tk._connection = None
    tk._connected = False
    tk.use_pool = False
    tk.pool_params = {}
    return tk


class _FakePartitionNoPlane:
    """Partition double with no plane configured."""

    plane = None

    def __init__(self):
        self.get = AsyncMock(return_value=None)
        self.get_table_metadata = AsyncMock(return_value=None)
        self.store_table_metadata = AsyncMock()


class _FakePartitionWithPlane:
    """Partition double with a (fake) schema plane configured."""

    def __init__(self, get_return=None, get_table_metadata_return=None):
        self.plane = object()  # any truthy sentinel — repair only checks it's not None
        self.get = AsyncMock(return_value=get_return)
        self.get_table_metadata = AsyncMock(return_value=get_table_metadata_return)
        self.store_table_metadata = AsyncMock()


# ---------------------------------------------------------------------------
# _repair_from_error
# ---------------------------------------------------------------------------

class TestRepairFromError:
    async def test_repair_noop_without_cache_partition(self):
        tk = _make_toolkit(cache=None)
        # Must not raise.
        await tk._repair_from_error("SELECT * FROM a.b", RuntimeError("relation does not exist"))

    async def test_repair_noop_without_plane(self):
        part = _FakePartitionNoPlane()
        tk = _make_toolkit(cache=part)
        await tk._repair_from_error("SELECT * FROM a.b", RuntimeError("relation does not exist"))
        part.store_table_metadata.assert_not_awaited()

    async def test_repair_with_plane_reintrospects_and_writes_through(self):
        part = _FakePartitionWithPlane()
        tk = _make_toolkit(cache=part)
        meta = _meta("epson", "sales")
        tk._introspect_table_full = AsyncMock(return_value=meta)

        await tk._repair_from_error(
            "SELECT * FROM epson.sales WHERE region = 'x'",
            RuntimeError('column "region" does not exist'),
        )

        tk._introspect_table_full.assert_any_await("epson", "sales")
        part.store_table_metadata.assert_any_await(meta)

    async def test_repair_swallows_introspection_errors(self):
        part = _FakePartitionWithPlane()
        tk = _make_toolkit(cache=part)
        tk._introspect_table_full = AsyncMock(side_effect=RuntimeError("boom"))

        # Must not raise even though introspection fails.
        await tk._repair_from_error("SELECT * FROM epson.sales", RuntimeError("relation does not exist"))
        part.store_table_metadata.assert_not_awaited()

    async def test_execute_query_retryable_error_triggers_repair(self):
        from parrot.bots.database.retries import QueryRetryConfig, RetryContext, SQLRetryHandler

        tk = _make_toolkit(cache=_FakePartitionWithPlane())
        tk.retry_config = QueryRetryConfig(max_retries=2)
        tk._run_query = AsyncMock(side_effect=RuntimeError("relation does not exist"))
        tk._check_query_safety = MagicMock(return_value=None)
        tk._repair_from_error = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(SQLRetryHandler, "retry_query", AsyncMock(return_value=None))
            result = await tk.execute_query("SELECT * FROM epson.sales")

        tk._repair_from_error.assert_awaited_once()
        assert isinstance(result, RetryContext)


# ---------------------------------------------------------------------------
# _warm_table_cache
# ---------------------------------------------------------------------------

class TestWarmTableCache:
    async def test_warm_skips_db_when_plane_serves(self):
        served = _meta("epson", "sales", completeness=Completeness.FULL)
        part = _FakePartitionWithPlane(get_return=served)
        tk = _make_toolkit(cache=part)
        tk.tables = ["epson.sales"]
        tk._parse_table_entry = MagicMock(return_value=("epson", "sales"))
        tk._build_table_metadata = AsyncMock()

        await tk._warm_table_cache()

        part.get.assert_any_await("epson", "sales", required=Completeness.FULL)
        tk._build_table_metadata.assert_not_awaited()

    async def test_warm_falls_back_to_db_on_miss(self):
        part = _FakePartitionWithPlane(get_return=None)
        tk = _make_toolkit(cache=part)
        tk.tables = ["epson.sales"]
        tk._parse_table_entry = MagicMock(return_value=("epson", "sales"))
        meta = _meta("epson", "sales")
        tk._build_table_metadata = AsyncMock(return_value=meta)

        await tk._warm_table_cache()

        tk._build_table_metadata.assert_awaited_once()
        part.store_table_metadata.assert_any_await(meta)

    async def test_warm_without_cache_partition_is_noop(self):
        tk = _make_toolkit(cache=None)
        tk.tables = ["epson.sales"]
        # Should return without error (no cache_partition to warm).
        await tk._warm_table_cache()


# ---------------------------------------------------------------------------
# validate_query
# ---------------------------------------------------------------------------

class TestValidateQuery:
    async def test_message_names_plane_when_plane_is_set(self):
        part = _FakePartitionWithPlane(get_table_metadata_return=None)
        tk = _make_toolkit(cache=part)

        out = await tk.validate_query("SELECT 1 FROM epson.nope")

        assert out["valid"] is False
        assert "schema plane or cache" in out["errors"][0]

    async def test_message_names_only_cache_without_plane(self):
        part = _FakePartitionNoPlane()
        tk = _make_toolkit(cache=part)

        out = await tk.validate_query("SELECT 1 FROM epson.nope")

        assert out["valid"] is False
        assert out["errors"][0].endswith("not found in cache.")
        assert "plane" not in out["errors"][0]

    async def test_valid_when_table_found(self):
        part = _FakePartitionWithPlane(get_table_metadata_return=_meta("epson", "sales"))
        tk = _make_toolkit(cache=part)

        out = await tk.validate_query("SELECT 1 FROM epson.sales")

        assert out["valid"] is True
        assert out["errors"] == []


# ---------------------------------------------------------------------------
# generate_query — plane-aware join paths
# ---------------------------------------------------------------------------

class TestGenerateQueryJoinPaths:
    async def test_appends_join_paths_when_plane_present(self):
        part = _FakePartitionWithPlane()
        tk = _make_toolkit(cache=part)
        meta = _meta(
            "epson",
            "sales",
            foreign_keys=[{"column": "store_id", "ref_schema": "epson", "ref_table": "stores", "ref_column": "id"}],
        )
        tk.describe_table = AsyncMock(return_value=meta)

        out = await tk.generate_query("show sales", target_tables=["epson.sales"])

        assert "JOIN PATHS: epson.sales.store_id -> epson.stores.id" in out

    async def test_no_join_paths_without_plane(self):
        tk = _make_toolkit(cache=_FakePartitionNoPlane())
        meta = _meta(
            "epson",
            "sales",
            foreign_keys=[{"column": "store_id", "ref_schema": "epson", "ref_table": "stores", "ref_column": "id"}],
        )
        tk.describe_table = AsyncMock(return_value=meta)

        out = await tk.generate_query("show sales", target_tables=["epson.sales"])

        assert "JOIN PATHS" not in out

    async def test_no_join_paths_without_cache_partition(self):
        tk = _make_toolkit(cache=None)
        meta = _meta(
            "epson",
            "sales",
            foreign_keys=[{"column": "store_id", "ref_schema": "epson", "ref_table": "stores", "ref_column": "id"}],
        )
        tk.describe_table = AsyncMock(return_value=meta)

        out = await tk.generate_query("show sales", target_tables=["epson.sales"])

        assert "JOIN PATHS" not in out

    async def test_join_paths_bounded_to_twenty_lines(self):
        part = _FakePartitionWithPlane()
        tk = _make_toolkit(cache=part)
        fks = [
            {"column": f"ref_{i}_id", "ref_schema": "epson", "ref_table": f"t{i}", "ref_column": "id"}
            for i in range(30)
        ]
        meta = _meta("epson", "sales", foreign_keys=fks)
        tk.describe_table = AsyncMock(return_value=meta)

        out = await tk.generate_query("show sales", target_tables=["epson.sales"])

        assert out.count("JOIN PATHS:") <= 20
