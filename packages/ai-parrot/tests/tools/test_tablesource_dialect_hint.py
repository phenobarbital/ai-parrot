"""Tests for SQL-dialect guidance surfaced to the LLM by TableSource.

A BigQuery-backed TableSource previously gave the LLM no dialect cue, so the
model emitted PostgreSQL date syntax (``CURRENT_DATE - INTERVAL '30 days'``)
which BigQuery rejects with a 400 syntax error. These tests cover the
``dialect_hint`` helper and its surfacing in ``describe()`` so the model writes
backend-correct SQL up front.
"""
import pytest

from parrot.tools.dataset_manager.sources.table import TableSource, dialect_hint


class TestDialectHint:
    @pytest.mark.parametrize(
        "driver, expected_substr",
        [
            ("bigquery", "BigQuery GoogleSQL"),
            ("bq", "BigQuery GoogleSQL"),          # alias
            ("pg", "PostgreSQL"),
            ("postgres", "PostgreSQL"),            # alias
            ("postgresql", "PostgreSQL"),          # alias
            ("mysql", "MySQL/MariaDB"),
            ("mariadb", "MySQL/MariaDB"),          # alias → mysql
        ],
    )
    def test_known_drivers_have_hints(self, driver, expected_substr):
        assert expected_substr in dialect_hint(driver)

    def test_unknown_driver_returns_empty(self):
        assert dialect_hint("sqlite") == ""
        assert dialect_hint("") == ""

    def test_bigquery_hint_warns_against_postgres_interval(self):
        """The exact mistake from the bug report is explicitly called out."""
        hint = dialect_hint("bigquery")
        assert "DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)" in hint
        assert "PostgreSQL" in hint  # names the wrong dialect it must avoid

    def test_pg_hint_keeps_interval_literal_form(self):
        assert "INTERVAL '30 days'" in dialect_hint("pg")


class TestDescribeIncludesDialect:
    def test_bigquery_describe_mentions_googlesql(self):
        ts = TableSource(table="pokemon.fso_completed", driver="bigquery")
        ts._schema = {"warehouse_alias": "string", "assigned_to": "string"}
        desc = ts.describe()
        assert "BigQuery GoogleSQL" in desc
        # Backward-compatible: still carries the existing driver/table info.
        assert "pokemon.fso_completed" in desc
        assert "via bigquery" in desc

    def test_pg_describe_mentions_postgresql(self):
        ts = TableSource(table="public.employees", driver="pg")
        ts._schema = {"id": "integer"}
        assert "PostgreSQL" in ts.describe()

    def test_unknown_driver_describe_has_no_dialect_line(self):
        ts = TableSource(table="main.t", driver="sqlite")
        ts._schema = {"id": "integer"}
        desc = ts.describe()
        assert "SQL dialect:" not in desc
