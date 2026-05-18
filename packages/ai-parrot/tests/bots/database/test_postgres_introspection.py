"""Tests for TASK-1205: PostgresToolkit pg_catalog migration (FEAT-178)."""
import asyncio
import logging
from unittest.mock import AsyncMock

import pytest

from parrot.bots.database.models import Completeness, TableMetadata
from parrot.bots.database.toolkits.postgres import PostgresToolkit
from parrot.bots.database.toolkits.sql import SQLToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pg_toolkit():
    tk = PostgresToolkit.__new__(PostgresToolkit)
    tk._inflight = {}
    tk._inflight_lock = asyncio.Lock()
    tk.logger = logging.getLogger("test.postgres_introspection")
    tk.cache_partition = None
    tk.allowed_schemas = ["pokemon"]
    return tk


# ---------------------------------------------------------------------------
# Class-attribute and structural checks
# ---------------------------------------------------------------------------

def test_metadata_source_class_attribute():
    """PostgresToolkit._metadata_source must be 'pg_catalog'."""
    assert PostgresToolkit._metadata_source == "pg_catalog"


def test_sqltoolkit_base_metadata_source():
    """Base SQLToolkit._metadata_source defaults to 'information_schema'."""
    assert SQLToolkit._metadata_source == "information_schema"


def test_indexes_query_method_exists():
    tk = _make_pg_toolkit()
    assert callable(getattr(tk, "_get_indexes_query", None))


def test_foreign_keys_query_method_exists():
    tk = _make_pg_toolkit()
    assert callable(getattr(tk, "_get_foreign_keys_query", None))


# ---------------------------------------------------------------------------
# _get_information_schema_query (now pg_catalog)
# ---------------------------------------------------------------------------

class TestInformationSchemaQuery:
    def test_uses_pg_catalog_pg_class(self):
        tk = _make_pg_toolkit()
        sql, params = tk._get_information_schema_query("stores", ["pokemon"])
        assert "pg_catalog.pg_class" in sql
        assert "pg_catalog.pg_namespace" in sql

    def test_no_information_schema_reference(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_information_schema_query("stores", ["pokemon"])
        assert "information_schema" not in sql

    def test_limit_is_caller_provided(self):
        """$3 must equal the caller-supplied limit, not a hardcoded 20."""
        tk = _make_pg_toolkit()
        _, params = tk._get_information_schema_query("stores", ["pokemon"], limit=42)
        assert params[2] == 42

    def test_default_limit_is_20(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_information_schema_query("stores", ["pokemon"])
        assert params[2] == 20

    def test_schemas_bound_as_first_param(self):
        tk = _make_pg_toolkit()
        schemas = ["s1", "s2"]
        _, params = tk._get_information_schema_query("x", schemas)
        assert params[0] == schemas

    def test_pattern_is_second_param(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_information_schema_query("stores", ["pokemon"])
        assert "%stores%" in params[1]

    def test_returns_comment_column(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_information_schema_query("x", ["s"])
        assert "comment" in sql.lower()


# ---------------------------------------------------------------------------
# _get_columns_query (pg_catalog version)
# ---------------------------------------------------------------------------

class TestColumnsQuery:
    def test_uses_pg_attribute(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_columns_query("pokemon", "stores")
        assert "pg_catalog.pg_attribute" in sql

    def test_filters_dropped_columns(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_columns_query("pokemon", "stores")
        assert "attisdropped" in sql

    def test_filters_system_columns(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_columns_query("pokemon", "stores")
        assert "attnum > 0" in sql

    def test_params_are_schema_and_table(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_columns_query("pokemon", "stores")
        assert params == ("pokemon", "stores")

    def test_no_information_schema_reference(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_columns_query("pokemon", "stores")
        assert "information_schema" not in sql

    def test_returns_column_comment(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_columns_query("pokemon", "stores")
        assert "col_description" in sql


# ---------------------------------------------------------------------------
# _get_primary_keys_query (pg_catalog version)
# ---------------------------------------------------------------------------

class TestPrimaryKeysQuery:
    def test_uses_pg_constraint(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_primary_keys_query("pokemon", "stores")
        assert "pg_catalog.pg_constraint" in sql

    def test_filters_primary_key_type(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_primary_keys_query("pokemon", "stores")
        assert "'p'" in sql

    def test_params_are_schema_and_table(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_primary_keys_query("pokemon", "stores")
        assert params == ("pokemon", "stores")


# ---------------------------------------------------------------------------
# _get_unique_constraints_query (pg_catalog version)
# ---------------------------------------------------------------------------

class TestUniqueConstraintsQuery:
    def test_uses_pg_constraint(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_unique_constraints_query("pokemon", "stores")
        assert "pg_catalog.pg_constraint" in sql

    def test_filters_unique_type(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_unique_constraints_query("pokemon", "stores")
        assert "'u'" in sql

    def test_params_are_schema_and_table(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_unique_constraints_query("pokemon", "stores")
        assert params == ("pokemon", "stores")

    def test_returns_constraint_name_and_column_name(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_unique_constraints_query("pokemon", "stores")
        assert "constraint_name" in sql
        assert "column_name" in sql


# ---------------------------------------------------------------------------
# _get_indexes_query
# ---------------------------------------------------------------------------

class TestIndexesQuery:
    def test_uses_pg_index(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_indexes_query("pokemon", "stores")
        assert "pg_catalog.pg_index" in sql

    def test_returns_uniqueness_flag(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_indexes_query("pokemon", "stores")
        assert "indisunique" in sql

    def test_returns_primary_flag(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_indexes_query("pokemon", "stores")
        assert "indisprimary" in sql

    def test_params_are_schema_and_table(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_indexes_query("pokemon", "stores")
        assert params == ("pokemon", "stores")

    def test_pg_catalog_prefixed(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_indexes_query("pokemon", "stores")
        assert "pg_catalog." in sql

    def test_schema_and_table_bound_not_interpolated(self):
        """Params must use $1/$2 placeholders."""
        tk = _make_pg_toolkit()
        sql, _ = tk._get_indexes_query("pokemon", "stores")
        assert "$1" in sql and "$2" in sql
        assert "pokemon" not in sql
        assert "stores" not in sql


# ---------------------------------------------------------------------------
# _get_foreign_keys_query
# ---------------------------------------------------------------------------

class TestForeignKeysQuery:
    def test_uses_pg_constraint(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_foreign_keys_query("networkninja", "forms")
        assert "pg_catalog.pg_constraint" in sql

    def test_filters_fk_type(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_foreign_keys_query("networkninja", "forms")
        assert "'f'" in sql

    def test_returns_referenced_table(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_foreign_keys_query("networkninja", "forms")
        assert "referenced_table" in sql

    def test_returns_on_update_on_delete(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_foreign_keys_query("networkninja", "forms")
        assert "confupdtype" in sql or "on_update" in sql
        assert "confdeltype" in sql or "on_delete" in sql

    def test_params_are_schema_and_table(self):
        tk = _make_pg_toolkit()
        _, params = tk._get_foreign_keys_query("networkninja", "forms")
        assert params == ("networkninja", "forms")

    def test_pg_catalog_prefixed(self):
        tk = _make_pg_toolkit()
        sql, _ = tk._get_foreign_keys_query("networkninja", "forms")
        assert "pg_catalog." in sql


# ---------------------------------------------------------------------------
# _build_table_metadata source stamp
# ---------------------------------------------------------------------------

class TestBuildTableMetadataSource:
    async def test_pg_toolkit_stamps_pg_catalog(self):
        """_build_table_metadata sets source='pg_catalog' for PostgresToolkit."""
        col_result = (
            [
                {
                    "column_name": "id",
                    "data_type": "integer",
                    "is_nullable": "NO",
                    "column_default": None,
                    "ordinal_position": 1,
                }
            ],
            None,
        )
        pk_result = ([{"column_name": "id"}], None)
        uq_result = ([], None)

        tk = _make_pg_toolkit()
        tk._execute_asyncdb = AsyncMock(
            side_effect=[col_result, pk_result, uq_result]
        )

        meta = await tk._build_table_metadata(
            "pokemon", "stores", table_type="BASE TABLE"
        )
        assert meta is not None
        assert meta.source == "pg_catalog"

    async def test_base_sqltoolkit_stamps_information_schema(self):
        """_build_table_metadata sets source='information_schema' for base SQLToolkit."""
        col_result = (
            [
                {
                    "column_name": "id",
                    "data_type": "integer",
                    "is_nullable": "YES",
                    "column_default": None,
                    "ordinal_position": 1,
                }
            ],
            None,
        )
        pk_result = ([], None)
        uq_result = ([], None)

        tk = SQLToolkit.__new__(SQLToolkit)
        tk._inflight = {}
        tk._inflight_lock = asyncio.Lock()
        tk.logger = logging.getLogger("test.sqltoolkit_base")
        tk.cache_partition = None
        tk._execute_asyncdb = AsyncMock(
            side_effect=[col_result, pk_result, uq_result]
        )

        meta = await tk._build_table_metadata(
            "public", "users", table_type="BASE TABLE"
        )
        assert meta is not None
        assert meta.source == "information_schema"


# ---------------------------------------------------------------------------
# Integration tests (require a live PG fixture — skipped in unit runs)
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_pg_catalog_full_introspection_matches_information_schema(
    seeded_pg, pg_toolkit
):
    """pg_catalog columns query returns at least the same names as IS."""
    sql, params = pg_toolkit._get_columns_query("pokemon", "stores")
    async with pg_toolkit._pool.acquire() as conn:
        new_rows = await conn.fetch(sql, *params)
    async with pg_toolkit._pool.acquire() as conn:
        old_rows = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=$1 AND table_name=$2",
            "pokemon", "stores",
        )
    assert {r["column_name"] for r in new_rows} == {r["column_name"] for r in old_rows}


@pytest.mark.integration
async def test_pg_catalog_indexes_query(seeded_pg, pg_toolkit):
    out_sql, params = pg_toolkit._get_indexes_query("pokemon", "stores")
    async with pg_toolkit._pool.acquire() as conn:
        rows = await conn.fetch(out_sql, *params)
    pk_rows = [r for r in rows if r["is_primary"]]
    assert len(pk_rows) == 1


@pytest.mark.integration
async def test_pg_catalog_foreign_keys_query(seeded_pg_with_fks, pg_toolkit):
    fk_sql, params = pg_toolkit._get_foreign_keys_query("networkninja", "forms")
    async with pg_toolkit._pool.acquire() as conn:
        rows = await conn.fetch(fk_sql, *params)
    assert any(r["referenced_table"] == "organizations" for r in rows)


@pytest.mark.integration
async def test_full_introspection_source_is_pg_catalog(seeded_pg, pg_toolkit):
    meta = await pg_toolkit._build_table_metadata(
        "pokemon", "stores", table_type="BASE TABLE"
    )
    assert meta is not None
    assert meta.source == "pg_catalog"
