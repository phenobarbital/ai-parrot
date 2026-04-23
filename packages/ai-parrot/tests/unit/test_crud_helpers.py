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
    _HSTORE_TYPES,
    _JSONB_CAST_TYPES,
    _JSON_TYPES,
    _SELECT_CAST_WHITELIST,
    _build_insert_sql,
    _build_select_sql,
    _build_update_sql,
    _build_upsert_sql,
    _dict_to_hstore,
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


class TestTypeSets:
    def test_hstore_excluded_from_jsonb_cast_types(self) -> None:
        assert "hstore" not in _JSONB_CAST_TYPES
        assert _JSONB_CAST_TYPES == {"json", "jsonb"}

    def test_hstore_isolated_in_hstore_types(self) -> None:
        assert _HSTORE_TYPES == {"hstore"}

    def test_json_types_still_covers_all_dict_accepting_types(self) -> None:
        assert _JSON_TYPES == _JSONB_CAST_TYPES | _HSTORE_TYPES


class TestDictToHstore:
    def test_none_returns_none(self) -> None:
        assert _dict_to_hstore(None) is None

    def test_empty_dict_returns_empty_string(self) -> None:
        assert _dict_to_hstore({}) == ""

    def test_simple_pair(self) -> None:
        assert _dict_to_hstore({"k": "v"}) == '"k"=>"v"'

    def test_multiple_pairs(self) -> None:
        out = _dict_to_hstore({"a": "1", "b": "2"})
        # dict insertion order is preserved in Python 3.7+
        assert out == '"a"=>"1", "b"=>"2"'

    def test_coerces_non_string_values(self) -> None:
        assert _dict_to_hstore({"n": 42}) == '"n"=>"42"'

    def test_none_value_emits_unquoted_null(self) -> None:
        assert _dict_to_hstore({"k": None}) == '"k"=>NULL'

    def test_escapes_quotes_and_backslashes(self) -> None:
        out = _dict_to_hstore({'k"q': 'v\\x'})
        assert out == '"k\\"q"=>"v\\\\x"'

    def test_rejects_non_dict(self) -> None:
        with pytest.raises(TypeError, match="hstore columns require a dict"):
            _dict_to_hstore("not a dict")


class TestBuildInsertSqlHstore:
    def test_hstore_column_gets_hstore_cast(self) -> None:
        sql, _ = _build_insert_sql(
            "navigator", "dashboards",
            columns=["dashboard_id", "cond_definition"],
            hstore_cols=frozenset({"cond_definition"}),
        )
        assert "$2::hstore" in sql
        assert "$2::text::jsonb" not in sql

    def test_jsonb_and_hstore_in_same_insert_keep_distinct_casts(self) -> None:
        sql, _ = _build_insert_sql(
            "navigator", "dashboards",
            columns=["dashboard_id", "params", "cond_definition"],
            json_cols=frozenset({"params"}),
            hstore_cols=frozenset({"cond_definition"}),
        )
        assert "$2::text::jsonb" in sql  # params
        assert "$3::hstore" in sql  # cond_definition

    def test_plain_columns_unaffected(self) -> None:
        sql, _ = _build_insert_sql(
            "navigator", "dashboards",
            columns=["dashboard_id", "name"],
            hstore_cols=frozenset({"cond_definition"}),  # not in columns → noop
        )
        assert "::hstore" not in sql
        assert "::jsonb" not in sql


class TestBuildUpsertSqlHstore:
    def test_hstore_column_gets_hstore_cast(self) -> None:
        sql, _ = _build_upsert_sql(
            "navigator", "dashboards",
            columns=["dashboard_id", "cond_definition"],
            conflict_cols=["dashboard_id"],
            hstore_cols=frozenset({"cond_definition"}),
        )
        assert "$2::hstore" in sql


class TestBuildUpdateSqlHstore:
    def test_hstore_column_gets_hstore_cast_in_set_clause(self) -> None:
        sql, _ = _build_update_sql(
            "navigator", "dashboards",
            set_columns=["cond_definition"],
            where_columns=["dashboard_id"],
            hstore_cols=frozenset({"cond_definition"}),
        )
        assert '"cond_definition" = $1::hstore' in sql

    def test_mixed_hstore_and_jsonb_in_set_clause(self) -> None:
        sql, _ = _build_update_sql(
            "navigator", "dashboards",
            set_columns=["params", "cond_definition"],
            where_columns=["dashboard_id"],
            json_cols=frozenset({"params"}),
            hstore_cols=frozenset({"cond_definition"}),
        )
        assert '"params" = $1::text::jsonb' in sql
        assert '"cond_definition" = $2::hstore' in sql
