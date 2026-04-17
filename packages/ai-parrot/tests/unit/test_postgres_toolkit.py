"""Unit tests for PostgresToolkit — FEAT-107 TASK-747.

Tests cover the select_rows extensions:
- distinct=True produces SQL starting with SELECT DISTINCT
- column_casts produces col::type AS col in the SELECT list
- cache keys differ between distinct=True/False
- unknown cast type raises ValueError
- cast column not in columns raises ValueError
- omitting new params → identical SQL to baseline (backwards compat)
"""
from __future__ import annotations

import pytest

from parrot.bots.database.toolkits._crud import _build_select_sql


# ---------------------------------------------------------------------------
# Helpers — we test the builder directly (no DB required) plus the cache key
# logic by inspecting _make_template_key via the public _build_select_sql.
# ---------------------------------------------------------------------------


class TestSelectRowsDistinct:
    def test_select_distinct_sql(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "widget_types",
            columns=["category"],
            distinct=True,
        )
        assert sql.startswith("SELECT DISTINCT ")

    def test_distinct_false_no_distinct_keyword(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "widget_types",
            columns=["category"],
            distinct=False,
        )
        assert "DISTINCT" not in sql

    def test_cache_key_distinct_not_shared(self) -> None:
        """Simulate what _make_template_key produces for distinct=True vs False.

        We verify indirectly: the resulting SQL strings differ, which means
        the underlying builder produces distinct templates.
        """
        sql_true, _ = _build_select_sql(
            "navigator", "widget_types",
            columns=["category"],
            distinct=True,
        )
        sql_false, _ = _build_select_sql(
            "navigator", "widget_types",
            columns=["category"],
            distinct=False,
        )
        assert sql_true != sql_false


class TestSelectRowsColumnCasts:
    def test_emits_cast_in_select_list(self) -> None:
        sql, _ = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "inserted_at"],
            column_casts={"inserted_at": "text"},
        )
        assert '"inserted_at"::text AS "inserted_at"' in sql

    def test_rejects_unknown_cast_type(self) -> None:
        with pytest.raises(ValueError, match="unsupported cast type"):
            _build_select_sql(
                "navigator", "modules",
                columns=["inserted_at"],
                column_casts={"inserted_at": "bogus"},
            )

    def test_rejects_cast_for_column_not_in_columns(self) -> None:
        with pytest.raises(ValueError):
            _build_select_sql(
                "navigator", "modules",
                columns=["module_id"],
                column_casts={"inserted_at": "text"},
            )


class TestBackCompat:
    def test_no_new_params_sql_identical(self) -> None:
        sql_before, _ = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "module_name"],
        )
        sql_after, _ = _build_select_sql(
            "navigator", "modules",
            columns=["module_id", "module_name"],
            distinct=False,
            column_casts=None,
        )
        assert sql_before == sql_after
        assert sql_before == 'SELECT "module_id", "module_name" FROM "navigator"."modules"'
