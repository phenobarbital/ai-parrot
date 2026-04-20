"""Unit tests for _crud helper functions — FEAT-107 TASK-747.

Tests cover the extensions to _build_select_sql:
- distinct=True emits SELECT DISTINCT
- column_casts applies ::type AS col syntax
- unsupported cast type raises ValueError
- cast key not in columns raises ValueError
- backwards compatibility: no new params → identical SQL
"""
from __future__ import annotations

import pytest

from parrot.bots.database.toolkits._crud import (
    _SELECT_CAST_WHITELIST,
    _build_select_sql,
)


class TestBuildSelectSqlDistinct:
    def test_distinct_true_emits_select_distinct(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "widget_types",
            columns=["category"],
            distinct=True,
        )
        assert sql.startswith("SELECT DISTINCT ")

    def test_distinct_false_emits_select(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "widget_types",
            columns=["category"],
            distinct=False,
        )
        assert sql.startswith("SELECT ")
        assert "DISTINCT" not in sql

    def test_distinct_default_is_false(self) -> None:
        sql, _ = _build_select_sql("navigator", "widget_types", columns=["id"])
        assert "DISTINCT" not in sql


class TestBuildSelectSqlColumnCasts:
    def test_cast_emits_type_alias(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "inserted_at"],
            column_casts={"inserted_at": "text"},
        )
        assert '"inserted_at"::text AS "inserted_at"' in sql

    def test_non_cast_column_unmodified(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "inserted_at"],
            column_casts={"inserted_at": "text"},
        )
        assert '"module_id"' in sql
        assert "module_id::text" not in sql

    def test_all_whitelisted_types_accepted(self) -> None:
        for cast_type in _SELECT_CAST_WHITELIST:
            sql, _ = _build_select_sql(
                "navigator", "modules",
                columns=["col"],
                column_casts={"col": cast_type},
            )
            assert f"::{cast_type}" in sql

    def test_rejects_unknown_cast_type(self) -> None:
        with pytest.raises(ValueError, match="unsupported cast type"):
            _build_select_sql(
                "navigator", "modules",
                columns=["inserted_at"],
                column_casts={"inserted_at": "bogus"},
            )

    def test_rejects_cast_key_not_in_columns(self) -> None:
        with pytest.raises(ValueError):
            _build_select_sql(
                "navigator", "modules",
                columns=["module_id"],
                column_casts={"inserted_at": "text"},
            )

    def test_no_cast_when_column_casts_is_none(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "inserted_at"],
            column_casts=None,
        )
        assert "::" not in sql


class TestBuildSelectSqlBackwardsCompat:
    def test_no_new_params_produces_same_sql_as_baseline(self) -> None:
        """Omitting both new params must not change the SQL output."""
        baseline, param_order = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "module_name"],
        )
        new, new_param_order = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "module_name"],
            distinct=False,
            column_casts=None,
        )
        assert baseline == new
        assert param_order == new_param_order

    def test_baseline_sql_shape(self) -> None:
        sql, params = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "module_name"],
        )
        assert sql == 'SELECT "module_id", "module_name" FROM "navigator"."modules"'
        assert params == []


class TestSelectCastWhitelist:
    def test_whitelist_contains_expected_types(self) -> None:
        expected = {"text", "uuid", "json", "jsonb", "integer", "bigint",
                    "numeric", "timestamp", "date"}
        assert expected == _SELECT_CAST_WHITELIST
