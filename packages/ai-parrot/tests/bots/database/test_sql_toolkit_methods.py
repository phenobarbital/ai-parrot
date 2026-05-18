"""Tests for TASK-1204: search_schema, describe_table, generate_query (FEAT-178)."""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.sql import SQLToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name: str, type_: str = "text"):
    return {"name": name, "type": type_, "nullable": True}


def _meta(schema: str, table: str, cols=None, completeness=Completeness.FULL):
    return TableMetadata(
        schema=schema,
        tablename=table,
        table_type="BASE TABLE",
        full_name=f"{schema}.{table}",
        completeness=completeness,
        columns=cols if cols is not None else [_col("id", "integer"), _col("state_code")],
        source="information_schema",
    )


def _stub(schema: str, table: str):
    return _meta(schema, table, cols=[], completeness=Completeness.NAME_ONLY)


def _make_toolkit(cache=None, allowed_schemas=None):
    tk = SQLToolkit.__new__(SQLToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = logging.getLogger("test.methods")
    tk.cache_partition = cache
    tk.allowed_schemas = allowed_schemas or ["pokemon", "altice"]
    return tk


# ---------------------------------------------------------------------------
# search_schema
# ---------------------------------------------------------------------------

class TestSearchSchema:
    async def test_merges_cache_and_db(self):
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[
            _meta("altice", "store_inventory"),
            _meta("altice", "store_groups"),
        ])
        cache._extract_search_keywords = MagicMock(return_value=["store"])
        cache._calculate_relevance_score = MagicMock(return_value=5.0)

        tk = _make_toolkit(cache=cache)
        tk._search_in_database = AsyncMock(return_value=[
            _meta("pokemon", "stores", cols=[{"name": "state_code"}]),
        ])

        out = await tk.search_schema("stores", limit=10)
        names = {(m.schema, m.tablename) for m in out}
        assert ("pokemon", "stores") in names
        assert ("altice", "store_inventory") in names

    async def test_no_early_return(self):
        """DB is always queried even when cache returns results."""
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[_meta("altice", "store_inventory")])
        cache._extract_search_keywords = MagicMock(return_value=["store"])
        cache._calculate_relevance_score = MagicMock(return_value=5.0)

        tk = _make_toolkit(cache=cache)
        db_mock = AsyncMock(return_value=[_meta("pokemon", "stores")])
        tk._search_in_database = db_mock

        await tk.search_schema("store")
        db_mock.assert_awaited_once()

    async def test_deduplicates_prefers_higher_completeness(self):
        """On (schema, tablename) collision the FULL entry wins over NAME_ONLY."""
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[
            _stub("pokemon", "stores"),  # NAME_ONLY from cache
        ])
        cache._extract_search_keywords = MagicMock(return_value=["stores"])
        cache._calculate_relevance_score = MagicMock(return_value=1.0)

        tk = _make_toolkit(cache=cache)
        tk._search_in_database = AsyncMock(return_value=[
            _meta("pokemon", "stores"),  # FULL from DB
        ])

        out = await tk.search_schema("stores")
        stores = [m for m in out if m.tablename == "stores"]
        assert len(stores) == 1
        assert stores[0].completeness == Completeness.FULL

    async def test_no_cache_falls_back_to_db_only(self):
        tk = _make_toolkit(cache=None)
        db_mock = AsyncMock(return_value=[_meta("pokemon", "stores")])
        tk._search_in_database = db_mock

        out = await tk.search_schema("stores")
        db_mock.assert_awaited_once()
        assert len(out) == 1

    async def test_empty_results(self):
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[])
        cache._extract_search_keywords = MagicMock(return_value=[])
        cache._calculate_relevance_score = MagicMock(return_value=0.0)

        tk = _make_toolkit(cache=cache)
        tk._search_in_database = AsyncMock(return_value=[])

        out = await tk.search_schema("nonexistent_xyz")
        assert out == []


# ---------------------------------------------------------------------------
# describe_table
# ---------------------------------------------------------------------------

class TestDescribeTable:
    async def test_returns_full_from_cache(self):
        """Cache hit with FULL completeness — no DB call."""
        cache = MagicMock()
        full = _meta("pokemon", "stores")
        cache.get = AsyncMock(return_value=full)

        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock()

        out = await tk.describe_table("pokemon", "stores")
        assert out is full
        tk._introspect_table_full.assert_not_awaited()

    async def test_promotes_stub_to_full(self):
        """Cache returns None (stub below FULL) → introspect + store."""
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.store_table_metadata = AsyncMock()

        full = _meta("pokemon", "stores")
        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock(return_value=full)

        out = await tk.describe_table("pokemon", "stores")
        assert out is full
        assert out.completeness == Completeness.FULL
        cache.store_table_metadata.assert_awaited_once_with(full)

    async def test_returns_none_for_missing_table(self):
        """Introspect returns None → describe_table returns None."""
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.store_table_metadata = AsyncMock()

        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock(return_value=None)

        out = await tk.describe_table("pokemon", "ghost_table")
        assert out is None
        cache.store_table_metadata.assert_not_awaited()

    async def test_no_cache_still_introspects(self):
        tk = _make_toolkit(cache=None)
        full = _meta("pokemon", "stores")
        tk._introspect_table_full = AsyncMock(return_value=full)

        out = await tk.describe_table("pokemon", "stores")
        assert out is full

    async def test_coalesces_concurrent_calls(self):
        """Two concurrent describe_table calls share one _build_table_metadata call."""
        call_count = 0

        async def fake_build(schema, table, table_type, comment=None):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.03)
            return _meta(schema, table)

        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.store_table_metadata = AsyncMock()

        tk = _make_toolkit(cache=cache)
        tk._build_table_metadata = fake_build

        results = await asyncio.gather(
            tk.describe_table("pokemon", "stores"),
            tk.describe_table("pokemon", "stores"),
        )
        assert call_count == 1
        assert all(r is not None for r in results)


# ---------------------------------------------------------------------------
# generate_query
# ---------------------------------------------------------------------------

class TestGenerateQuery:
    async def test_calls_describe_for_each_qualified_target(self):
        tk = _make_toolkit(cache=None)
        describe_mock = AsyncMock(side_effect=lambda s, t: _meta(s, t))
        tk.describe_table = describe_mock

        await tk.generate_query("show forms", target_tables=["a.x", "b.y"])
        assert describe_mock.await_count == 2
        describe_mock.assert_any_await("a", "x")
        describe_mock.assert_any_await("b", "y")

    async def test_skeleton_has_real_columns(self):
        tk = _make_toolkit(cache=None)
        tk.describe_table = AsyncMock(
            return_value=_meta("pokemon", "stores", cols=[_col("state_code"), _col("region")])
        )

        out = await tk.generate_query("show stores", target_tables=["pokemon.stores"])
        assert "state_code" in out
        assert "SELECT" in out
        assert "FROM pokemon.stores" in out

    async def test_no_target_tables_calls_search_schema(self):
        tk = _make_toolkit(cache=None)
        search_mock = AsyncMock(return_value=[_meta("pokemon", "stores")])
        tk.search_schema = search_mock
        tk.describe_table = AsyncMock(return_value=_meta("pokemon", "stores"))

        await tk.generate_query("show stores")
        search_mock.assert_awaited_once()

    async def test_bare_table_name_resolved_via_allowed_schemas(self):
        tk = _make_toolkit(cache=None, allowed_schemas=["s1", "s2"])
        calls = []

        async def fake_describe(schema, table):
            calls.append((schema, table))
            if schema == "s2":
                return _meta(schema, table)
            return None

        tk.describe_table = fake_describe

        out = await tk.generate_query("x", target_tables=["t"])
        # s1 returns None, s2 returns the meta — only one entry in output
        assert "s2.t" in out
        assert ("s1", "t") in calls
        assert ("s2", "t") in calls

    async def test_no_tables_resolved_returns_empty_skeleton(self):
        tk = _make_toolkit(cache=None)
        tk.describe_table = AsyncMock(return_value=None)

        out = await tk.generate_query("x", target_tables=["pokemon.ghost"])
        assert "no tables resolved" in out.lower()
