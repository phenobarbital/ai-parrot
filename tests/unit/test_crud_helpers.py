"""Tests for _crud.py Pydantic model builder + SQL template builders (TASK-741/742 / FEAT-106).

Uses conftest_db.py to load the worktree's source so changes under
packages/ai-parrot/src/ are visible here rather than the installed package.
"""
from __future__ import annotations

import os
import sys

# Load worktree source
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest
from pydantic import ValidationError

from parrot.bots.database.toolkits._crud import (
    _build_pydantic_model,
    _columns_key_from_metadata,
    _build_insert_sql,
    _build_upsert_sql,
    _build_update_sql,
    _build_delete_sql,
    _build_select_sql,
)
from parrot.bots.database.models import TableMetadata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_metadata() -> TableMetadata:
    """TableMetadata with integer, varchar, and jsonb columns."""
    return TableMetadata(
        schema="test",
        tablename="t",
        table_type="BASE TABLE",
        full_name='"test"."t"',
        columns=[
            {"name": "id",   "type": "integer", "nullable": False, "default": None},
            {"name": "name", "type": "varchar", "nullable": False, "default": None},
            {"name": "data", "type": "jsonb",   "nullable": True,  "default": "'{}'"},
        ],
        primary_keys=["id"],
    )


# ===========================================================================
# TASK-741: Dynamic Pydantic model builder (lru_cache)
# ===========================================================================

class TestColumnsKeyFromMetadata:
    def test_returns_tuple_of_tuples(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        assert isinstance(key, tuple)
        assert all(isinstance(x, tuple) and len(x) == 4 for x in key)

    def test_json_flag_set_for_jsonb(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        data_entry = next(x for x in key if x[0] == "data")
        assert data_entry[3] is True  # is_json

    def test_non_json_flag_not_set(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        id_entry = next(x for x in key if x[0] == "id")
        assert id_entry[3] is False  # not is_json


class TestBuildPydanticModel:
    def test_columns_key_shape(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        assert isinstance(key, tuple)
        assert all(isinstance(x, tuple) and len(x) == 4 for x in key)

    def test_lru_hits(self, fixture_metadata: TableMetadata) -> None:
        _build_pydantic_model.cache_clear()
        key = _columns_key_from_metadata(fixture_metadata)
        m1 = _build_pydantic_model("test_t", key)
        m2 = _build_pydantic_model("test_t", key)
        assert m1 is m2
        assert _build_pydantic_model.cache_info().hits >= 1

    def test_rejects_unknown_field(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_t_unknown", key)
        with pytest.raises(ValidationError):
            Model(nope=1)

    def test_jsonb_accepts_dict(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_t_json", key)
        instance = Model(data={"k": "v"})
        assert instance.data == {"k": "v"}

    def test_jsonb_accepts_list(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_t_jsonlist", key)
        instance = Model(data=[1, 2, 3])
        assert instance.data == [1, 2, 3]

    def test_cache_clear(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        _build_pydantic_model("clearme", key)
        assert _build_pydantic_model.cache_info().currsize >= 1
        _build_pydantic_model.cache_clear()
        assert _build_pydantic_model.cache_info().currsize == 0

    def test_all_fields_optional_with_none_default(self, fixture_metadata: TableMetadata) -> None:
        key = _columns_key_from_metadata(fixture_metadata)
        Model = _build_pydantic_model("test_optional", key)
        # No args supplied → all None (all fields optional)
        instance = Model()
        assert instance.id is None
        assert instance.name is None
        assert instance.data is None


# ===========================================================================
# TASK-742: SQL template builders
# ===========================================================================

class TestBuildInsertSql:
    def test_basic_no_returning(self) -> None:
        sql, params = _build_insert_sql("public", "t", ["a", "b"])
        assert sql == 'INSERT INTO "public"."t" ("a", "b") VALUES ($1, $2)'
        assert params == ["a", "b"]

    def test_with_returning(self) -> None:
        sql, params = _build_insert_sql("public", "t", ["a"], returning=["id"])
        assert 'RETURNING "id"' in sql

    def test_jsonb_cast(self) -> None:
        sql, _ = _build_insert_sql(
            "public", "t", ["a", "data"], json_cols=frozenset({"data"})
        )
        assert "$2::text::jsonb" in sql

    def test_no_returning_clause_when_none(self) -> None:
        sql, _ = _build_insert_sql("public", "t", ["a"])
        assert "RETURNING" not in sql

    def test_multiple_returning_cols(self) -> None:
        sql, _ = _build_insert_sql("public", "t", ["a"], returning=["id", "created_at"])
        assert '"id"' in sql
        assert '"created_at"' in sql


class TestBuildUpsertSql:
    def test_conflict_cols_required(self) -> None:
        with pytest.raises(ValueError):
            _build_upsert_sql("public", "t", ["a"], conflict_cols=None, update_cols=["a"])

    def test_explicit_conflict_cols(self) -> None:
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["a", "b", "c"],
            conflict_cols=["a"],
            update_cols=["b", "c"],
        )
        assert 'ON CONFLICT ("a")' in sql
        assert '"b" = EXCLUDED."b"' in sql
        assert '"c" = EXCLUDED."c"' in sql

    def test_composite_conflict(self) -> None:
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["a", "b", "c"],
            conflict_cols=["a", "b"],
            update_cols=["c"],
        )
        assert 'ON CONFLICT ("a", "b")' in sql

    def test_do_nothing_when_update_cols_empty(self) -> None:
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["a", "b"],
            conflict_cols=["a"],
            update_cols=[],
        )
        assert "DO NOTHING" in sql
        assert "DO UPDATE" not in sql

    def test_default_update_cols_excludes_conflict(self) -> None:
        """When update_cols=None, non-conflict columns are updated."""
        sql, _ = _build_upsert_sql(
            "public", "t",
            columns=["id", "name", "email"],
            conflict_cols=["id"],
            update_cols=None,
        )
        assert "DO UPDATE" in sql
        assert '"name" = EXCLUDED."name"' in sql
        assert '"email" = EXCLUDED."email"' in sql
        # conflict col itself should NOT appear in SET
        assert '"id" = EXCLUDED."id"' not in sql

    def test_upsert_param_order_is_insert_columns(self) -> None:
        _, params = _build_upsert_sql(
            "public", "t",
            columns=["a", "b"],
            conflict_cols=["a"],
            update_cols=["b"],
        )
        assert params == ["a", "b"]


class TestBuildUpdateSql:
    def test_basic(self) -> None:
        sql, params = _build_update_sql(
            "public", "t", set_columns=["a", "b"], where_columns=["id"]
        )
        assert '"a" = $1' in sql
        assert '"b" = $2' in sql
        assert '"id" = $3' in sql
        assert params == ["a", "b", "id"]

    def test_jsonb_cast(self) -> None:
        sql, _ = _build_update_sql(
            "public", "t",
            set_columns=["data"],
            where_columns=["id"],
            json_cols=frozenset({"data"}),
        )
        assert "$1::text::jsonb" in sql

    def test_empty_where_rejects(self) -> None:
        with pytest.raises(ValueError):
            _build_update_sql("public", "t", set_columns=["a"], where_columns=[])

    def test_with_returning(self) -> None:
        sql, _ = _build_update_sql(
            "public", "t",
            set_columns=["a"],
            where_columns=["id"],
            returning=["id"],
        )
        assert 'RETURNING "id"' in sql


class TestBuildDeleteSql:
    def test_basic(self) -> None:
        sql, params = _build_delete_sql("public", "t", where_columns=["id"])
        assert 'DELETE FROM "public"."t" WHERE "id" = $1' in sql
        assert params == ["id"]

    def test_with_returning(self) -> None:
        sql, _ = _build_delete_sql("public", "t", where_columns=["id"], returning=["id"])
        assert 'RETURNING "id"' in sql

    def test_empty_where_rejects(self) -> None:
        with pytest.raises(ValueError):
            _build_delete_sql("public", "t", where_columns=[])

    def test_composite_where(self) -> None:
        sql, params = _build_delete_sql("public", "t", where_columns=["a", "b"])
        assert '"a" = $1' in sql
        assert '"b" = $2' in sql
        assert params == ["a", "b"]


class TestBuildSelectSql:
    def test_with_where_and_order(self) -> None:
        sql, params = _build_select_sql(
            "public", "t",
            columns=["a", "b"],
            where_columns=["a"],
            order_by=["b DESC"],
            limit=10,
        )
        assert 'SELECT "a", "b"' in sql
        assert '"a" = $1' in sql
        assert 'ORDER BY "b" DESC' in sql
        assert "LIMIT 10" in sql
        assert params == ["a"]

    def test_select_star_when_no_columns(self) -> None:
        sql, _ = _build_select_sql("public", "t", columns=None, where_columns=None)
        assert sql.startswith('SELECT * FROM "public"."t"')

    def test_no_where_clause_when_empty(self) -> None:
        sql, params = _build_select_sql("public", "t", columns=["id"], where_columns=[])
        assert "WHERE" not in sql
        assert params == []

    def test_no_limit_when_none(self) -> None:
        sql, _ = _build_select_sql("public", "t")
        assert "LIMIT" not in sql

    def test_invalid_order_direction_rejects(self) -> None:
        with pytest.raises(ValueError, match="only ASC and DESC"):
            _build_select_sql("public", "t", order_by=["col NULLS FIRST"])

    def test_order_by_asc(self) -> None:
        sql, _ = _build_select_sql("public", "t", order_by=["col ASC"])
        assert 'ORDER BY "col" ASC' in sql

    def test_invalid_identifier_rejects(self) -> None:
        with pytest.raises(ValueError):
            _build_insert_sql("public", "t; DROP TABLE t; --", ["a"])
