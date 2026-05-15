"""Regression and integration tests for FEAT-178: cache contract & tool workflow.

Covers the two production bugs:
 1. pokemon.stores disappearing from search results when stored as NAME_ONLY stub.
 2. networkninja JOIN generating empty columns because stubs were not promoted to FULL.
"""
from __future__ import annotations

import asyncio
import logging
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.database.cache import CachePartition
from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.toolkits.sql import SQLToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _col(name: str, type_: str = "text") -> dict:
    return {"name": name, "type": type_, "nullable": True}


def _meta(
    schema: str,
    table: str,
    cols: list | None = None,
    completeness: Completeness = Completeness.FULL,
) -> TableMetadata:
    cols = cols or [_col("id", "integer"), _col("state_code")]
    return TableMetadata(
        schema=schema,
        tablename=table,
        table_type="BASE TABLE",
        full_name=f'"{schema}"."{table}"',
        completeness=completeness,
        columns=cols,
        source="pg_catalog",
    )


def _stub(schema: str, table: str) -> TableMetadata:
    return TableMetadata(
        schema=schema,
        tablename=table,
        table_type="BASE TABLE",
        full_name=f'"{schema}"."{table}"',
        completeness=Completeness.NAME_ONLY,
        source="frontend",
    )


def _make_toolkit(
    cache: object | None = None,
    allowed_schemas: list | None = None,
) -> SQLToolkit:
    tk = SQLToolkit.__new__(SQLToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = logging.getLogger("test.regression")
    tk.cache_partition = cache
    tk.allowed_schemas = allowed_schemas or ["pokemon", "networkninja"]
    return tk


# ---------------------------------------------------------------------------
# Completeness gating
# ---------------------------------------------------------------------------

class TestCompletenessGating:
    def test_name_only_does_not_satisfy_full(self, stub_metadata):
        assert not stub_metadata.satisfies(Completeness.FULL)

    def test_name_only_satisfies_name_only(self, stub_metadata):
        assert stub_metadata.satisfies(Completeness.NAME_ONLY)

    def test_full_satisfies_all_levels(self, full_metadata):
        for level in Completeness:
            assert full_metadata.satisfies(level)

    def test_with_columns_satisfies_name_only_but_not_full(self):
        meta = _meta("s", "t", completeness=Completeness.WITH_COLUMNS)
        assert meta.satisfies(Completeness.NAME_ONLY)
        assert not meta.satisfies(Completeness.FULL)

    def test_ordering_is_strictly_increasing(self):
        assert Completeness.NAME_ONLY < Completeness.WITH_COLUMNS < Completeness.FULL


# ---------------------------------------------------------------------------
# YAML context regression
# ---------------------------------------------------------------------------

class TestYamlContextRegression:
    def test_name_only_stub_emits_warning(self, stub_metadata):
        ctx = stub_metadata.to_yaml_context()
        assert "_warning" in ctx
        assert "db_describe_table" in ctx

    def test_full_metadata_does_not_emit_warning(self, full_metadata):
        ctx = full_metadata.to_yaml_context()
        assert "_warning" not in ctx

    def test_full_metadata_columns_appear_in_context(self, full_metadata):
        ctx = full_metadata.to_yaml_context()
        assert "state_code" in ctx
        assert "store_id" in ctx

    def test_with_columns_stub_emits_warning(self):
        meta = _meta("s", "t", completeness=Completeness.WITH_COLUMNS)
        ctx = meta.to_yaml_context()
        assert "_warning" in ctx


# ---------------------------------------------------------------------------
# search_schema regression (Bug 1: NAME_ONLY stubs vanishing)
# ---------------------------------------------------------------------------

class TestSearchSchemaRegressionUnit:
    """NAME_ONLY stubs from cache must NOT be discarded by search_schema."""

    async def test_name_only_stub_included_in_search_results(self):
        stub = _stub("pokemon", "stores")
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[stub])
        cache._extract_search_keywords = MagicMock(return_value=["store"])
        cache._calculate_relevance_score = MagicMock(return_value=1.0)

        tk = _make_toolkit(cache=cache)
        tk._search_in_database = AsyncMock(return_value=[])

        results = await tk.search_schema("store")
        assert any(
            r.schema == "pokemon" and r.tablename == "stores" for r in results
        )

    async def test_db_results_merged_with_cache_results(self):
        cache_meta = _stub("pokemon", "stores")
        db_meta = _stub("pokemon", "trainers")
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[cache_meta])
        cache._extract_search_keywords = MagicMock(return_value=["poke"])
        cache._calculate_relevance_score = MagicMock(return_value=0.5)

        tk = _make_toolkit(cache=cache)
        tk._search_in_database = AsyncMock(return_value=[db_meta])

        results = await tk.search_schema("poke")
        names = {r.tablename for r in results}
        assert "stores" in names
        assert "trainers" in names

    async def test_higher_completeness_preferred_on_collision(self):
        stub = _stub("pokemon", "stores")
        full = _meta("pokemon", "stores", cols=[_col("id")], completeness=Completeness.FULL)
        cache = MagicMock()
        cache.search = AsyncMock(return_value=[stub])
        cache._extract_search_keywords = MagicMock(return_value=["store"])
        cache._calculate_relevance_score = MagicMock(return_value=1.0)

        tk = _make_toolkit(cache=cache)
        tk._search_in_database = AsyncMock(return_value=[full])

        results = await tk.search_schema("store")
        assert len(results) == 1
        assert results[0].completeness == Completeness.FULL

    async def test_search_without_cache_still_returns_db_results(self):
        db_meta = _stub("pokemon", "stores")
        tk = _make_toolkit(cache=None)
        tk._search_in_database = AsyncMock(return_value=[db_meta])

        results = await tk.search_schema("store")
        assert any(r.tablename == "stores" for r in results)


# ---------------------------------------------------------------------------
# describe_table regression
# ---------------------------------------------------------------------------

class TestDescribeTableRegressionUnit:
    """describe_table must promote NAME_ONLY stubs to FULL (never return empty columns)."""

    async def test_describe_table_promotes_stub_to_full(self):
        full = _meta("pokemon", "stores", cols=[_col("store_id"), _col("state_code")])
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.store_table_metadata = AsyncMock()

        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock(return_value=full)

        result = await tk.describe_table("pokemon", "stores")
        assert result is not None
        assert result.completeness == Completeness.FULL
        assert {c["name"] for c in result.columns} >= {"store_id", "state_code"}

    async def test_describe_table_stores_result_in_cache(self):
        full = _meta("pokemon", "stores", cols=[_col("store_id")])
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.store_table_metadata = AsyncMock()

        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock(return_value=full)

        await tk.describe_table("pokemon", "stores")
        cache.store_table_metadata.assert_awaited_once_with(full)

    async def test_describe_table_returns_cached_full_without_introspect(self):
        full = _meta("pokemon", "stores", cols=[_col("id")])
        cache = MagicMock()
        cache.get = AsyncMock(return_value=full)

        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock()

        result = await tk.describe_table("pokemon", "stores")
        assert result is full
        tk._introspect_table_full.assert_not_awaited()

    async def test_describe_table_returns_none_when_table_missing(self):
        cache = MagicMock()
        cache.get = AsyncMock(return_value=None)
        cache.store_table_metadata = AsyncMock()

        tk = _make_toolkit(cache=cache)
        tk._introspect_table_full = AsyncMock(return_value=None)

        result = await tk.describe_table("pokemon", "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# generate_query regression (Bug 2: JOIN with empty columns)
# ---------------------------------------------------------------------------

class TestGenerateQueryRegressionUnit:
    """generate_query must never produce empty column lists (the JOIN bug)."""

    async def test_generate_query_uses_real_columns(self):
        full = _meta("pokemon", "stores", cols=[_col("store_id"), _col("state_code")])
        tk = _make_toolkit()
        tk.describe_table = AsyncMock(return_value=full)

        out = await tk.generate_query("stores in alaska", target_tables=["pokemon.stores"])
        assert "state_code" in out
        assert "SELECT" in out

    async def test_generate_query_does_not_emit_asterisk_when_columns_known(self):
        full = _meta(
            "pokemon", "stores",
            cols=[_col("store_id"), _col("store_name"), _col("state_code")],
        )
        tk = _make_toolkit()
        tk.describe_table = AsyncMock(return_value=full)

        out = await tk.generate_query("list stores", target_tables=["pokemon.stores"])
        assert "SELECT *" not in out
        assert "store_id" in out

    async def test_generate_query_join_calls_describe_for_both_tables(self):
        forms = _meta("networkninja", "forms", cols=[_col("form_id"), _col("org_id")])
        orgs = _meta(
            "networkninja", "organizations",
            cols=[_col("org_id"), _col("organization")],
        )
        call_log: List[tuple] = []

        async def _fake_describe(schema: str, table: str):
            call_log.append((schema, table))
            return forms if table == "forms" else orgs

        tk = _make_toolkit()
        tk.describe_table = _fake_describe

        out = await tk.generate_query(
            "join forms with organizations",
            target_tables=["networkninja.forms", "networkninja.organizations"],
        )
        described = {(s, t) for s, t in call_log}
        assert ("networkninja", "forms") in described
        assert ("networkninja", "organizations") in described
        assert "form_id" in out or "org_id" in out

    async def test_generate_query_falls_back_to_search_when_no_target_tables(self):
        stores = _meta("pokemon", "stores", cols=[_col("store_id"), _col("state_code")])
        tk = _make_toolkit()
        tk.search_schema = AsyncMock(return_value=[stores])
        tk.describe_table = AsyncMock(return_value=stores)

        out = await tk.generate_query("how many stores are in alaska")
        assert "SELECT" in out
        tk.search_schema.assert_awaited_once()


# ---------------------------------------------------------------------------
# Metadata source regression
# ---------------------------------------------------------------------------

class TestMetadataSourceRegression:
    def test_postgres_toolkit_source_is_pg_catalog(self):
        assert PostgresToolkit._metadata_source == "pg_catalog"

    def test_base_toolkit_source_is_information_schema(self):
        assert SQLToolkit._metadata_source == "information_schema"


# ---------------------------------------------------------------------------
# CachePartition in-memory regression (no Redis)
# ---------------------------------------------------------------------------

class TestCachePartitionUnit:
    async def test_store_and_retrieve_full_metadata(self, full_metadata):
        cache = CachePartition(namespace="reg_full", redis_pool=None)
        await cache.store_table_metadata(full_metadata)
        result = await cache.get("pokemon", "stores", required=Completeness.FULL)
        assert result is not None
        assert result.completeness == Completeness.FULL

    async def test_name_only_does_not_pass_full_gate(self, stub_metadata):
        cache = CachePartition(namespace="reg_gate", redis_pool=None)
        await cache.store_table_metadata(stub_metadata)
        result = await cache.get("pokemon", "stores", required=Completeness.FULL)
        assert result is None

    async def test_name_only_passes_name_only_gate(self, stub_metadata):
        cache = CachePartition(namespace="reg_pass", redis_pool=None)
        await cache.store_table_metadata(stub_metadata)
        result = await cache.get("pokemon", "stores", required=Completeness.NAME_ONLY)
        assert result is not None

    async def test_ttl_by_completeness_defaults_are_set(self):
        cache = CachePartition(namespace="reg_ttl", redis_pool=None)
        assert cache.ttl_by_completeness[int(Completeness.NAME_ONLY)] == 86400
        assert cache.ttl_by_completeness[int(Completeness.WITH_COLUMNS)] == 21600
        assert cache.ttl_by_completeness[int(Completeness.FULL)] == 3600


# ---------------------------------------------------------------------------
# Frontend pre-warm completeness tagging (skip if module not available)
# ---------------------------------------------------------------------------

def test_frontend_pre_warm_completeness_tagging():
    """Verify the Completeness enum values match the navigator-plugins contract."""
    try:
        import navigator_plugins  # type: ignore  # noqa: F401
    except ImportError:
        pytest.skip("navigator_plugins not installed — downstream contract test skipped")

    assert Completeness.NAME_ONLY == 1
    assert Completeness.WITH_COLUMNS == 2
    assert Completeness.FULL == 3


# ---------------------------------------------------------------------------
# Integration tests (require PARROT_TEST_PG_DSN + live PostgreSQL)
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_pokemon_stores_alaska_regression(
    seeded_pg, pg_toolkit, test_cache_partition
):
    """End-to-end: NAME_ONLY stub → search_schema → describe_table → generate_query."""
    pg_toolkit.cache_partition = test_cache_partition

    await test_cache_partition.store_table_metadata(
        TableMetadata(
            schema="pokemon",
            tablename="stores",
            table_type="BASE TABLE",
            full_name='"pokemon"."stores"',
            completeness=Completeness.NAME_ONLY,
            source="frontend",
        )
    )

    hits = await pg_toolkit.search_schema("store")
    assert any(h.schema == "pokemon" and h.tablename == "stores" for h in hits)

    described = await pg_toolkit.describe_table("pokemon", "stores")
    assert described is not None
    assert described.completeness == Completeness.FULL
    assert {c["name"] for c in described.columns} >= {"store_id", "store_name", "state_code"}

    out = await pg_toolkit.generate_query(
        "stores in alaska", target_tables=["pokemon.stores"],
    )
    assert "state_code" in out
    assert "SELECT" in out


@pytest.mark.integration
async def test_networkninja_join_regression(
    seeded_pg, pg_toolkit, test_cache_partition
):
    """End-to-end: JOIN query resolves columns for both tables via describe_table."""
    pg_toolkit.cache_partition = test_cache_partition

    for table in ("forms", "organizations"):
        await test_cache_partition.store_table_metadata(
            TableMetadata(
                schema="networkninja",
                tablename=table,
                table_type="BASE TABLE",
                full_name=f'"networkninja"."{table}"',
                completeness=Completeness.NAME_ONLY,
                source="frontend",
            )
        )

    out = await pg_toolkit.generate_query(
        "join forms with organizations",
        target_tables=["networkninja.forms", "networkninja.organizations"],
    )
    assert "form_id" in out or "form_name" in out
    assert "org_id" in out or "organization" in out


@pytest.mark.integration
async def test_no_columns_yaml_does_not_silently_succeed(
    seeded_pg, pg_toolkit, test_cache_partition
):
    """NAME_ONLY stub's to_yaml_context always emits _warning in the full toolkit flow."""
    pg_toolkit.cache_partition = test_cache_partition

    stub = TableMetadata(
        schema="pokemon",
        tablename="stores",
        table_type="BASE TABLE",
        full_name='"pokemon"."stores"',
        completeness=Completeness.NAME_ONLY,
        source="frontend",
    )
    await test_cache_partition.store_table_metadata(stub)

    cached = await test_cache_partition.get(
        "pokemon", "stores", required=Completeness.NAME_ONLY
    )
    assert cached is not None
    ctx = cached.to_yaml_context()
    assert "_warning" in ctx


@pytest.mark.integration
async def test_pg_catalog_full_introspection_matches_information_schema(
    seeded_pg, pg_toolkit
):
    """pg_catalog columns query returns the same column names as information_schema."""
    sql, params = pg_toolkit._get_columns_query("pokemon", "stores")
    async with pg_toolkit._pool.acquire() as conn:
        new_rows = await conn.fetch(sql, *params)
    async with pg_toolkit._pool.acquire() as conn:
        old_rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=$1 AND table_name=$2",
            "pokemon",
            "stores",
        )
    assert {r["column_name"] for r in new_rows} == {r["column_name"] for r in old_rows}
