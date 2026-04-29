"""Unit tests for query-builder $N placeholder normalisation.

TASK-928 — FEAT-118: verifies that all _get_*_query builders emit $N
positional placeholders (not :name dict-style) and return tuple params,
and that _execute_asyncdb forwards the tuple via *params to conn.fetch().
"""
from __future__ import annotations

import os
import sys

# Load worktree source (must precede any parrot imports)
# __file__ is tests/unit/bots/database/toolkits/ — go 3 levels up to tests/unit/
_UNIT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir)
)
sys.path.insert(0, _UNIT_DIR)
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from parrot.bots.database.toolkits.sql import SQLToolkit  # noqa: E402
from parrot.bots.database.toolkits.postgres import PostgresToolkit  # noqa: E402
from parrot.bots.database.toolkits.bigquery import BigQueryToolkit  # noqa: E402


# ---------------------------------------------------------------------------
# SQLToolkit (base) builders
# ---------------------------------------------------------------------------

class TestSQLBuilderPlaceholders:
    """All base _get_*_query builders must emit $N and return tuple."""

    def setup_method(self):
        self.tk = SQLToolkit(dsn="postgresql://test")

    def test_information_schema_query_dollar_placeholders(self):
        sql, params = self.tk._get_information_schema_query("prog", ["auth", "public"])
        assert "$1" in sql, "Expected $1 placeholder"
        assert "$2" in sql, "Expected $2 placeholder"
        assert "$3" in sql, "Expected $3 placeholder"
        assert ":schemas" not in sql, "Old :name style must be removed"
        assert ":term" not in sql
        assert ":limit" not in sql
        assert isinstance(params, tuple), f"Expected tuple, got {type(params)}"
        assert params[0] == ["auth", "public"], "schemas list must be first param"
        assert "prog" in params[1], "search term must be in params"
        assert isinstance(params[2], int), "limit must be an int in params"

    def test_columns_query_dollar_placeholders(self):
        sql, params = self.tk._get_columns_query("auth", "programs")
        assert "$1" in sql
        assert "$2" in sql
        assert ":schema" not in sql
        assert ":table" not in sql
        assert isinstance(params, tuple)
        assert params == ("auth", "programs"), f"Expected ('auth', 'programs'), got {params}"

    def test_primary_keys_query_dollar_placeholders(self):
        sql, params = self.tk._get_primary_keys_query("auth", "programs")
        assert "$1" in sql
        assert "$2" in sql
        assert ":schema" not in sql
        assert ":table" not in sql
        assert isinstance(params, tuple)
        assert params == ("auth", "programs")

    def test_unique_constraints_query_dollar_placeholders(self):
        sql, params = self.tk._get_unique_constraints_query("auth", "programs")
        assert "$1" in sql
        assert "$2" in sql
        assert ":schema" not in sql
        assert ":table" not in sql
        assert isinstance(params, tuple)
        assert params == ("auth", "programs")


# ---------------------------------------------------------------------------
# PostgresToolkit overrides
# ---------------------------------------------------------------------------

class TestPostgresBuilderPlaceholders:
    """PG-specific overrides must also emit $N and return tuple."""

    def setup_method(self):
        self.tk = PostgresToolkit(dsn="postgresql://test")

    def test_information_schema_query_pg_dollar(self):
        sql, params = self.tk._get_information_schema_query("orders", ["public"])
        assert "pg_class" in sql.lower()
        assert "$1" in sql and "$2" in sql and "$3" in sql
        assert ":schemas" not in sql
        assert isinstance(params, tuple)
        assert params[0] == ["public"]
        assert "%orders%" in params[1]

    def test_columns_query_pg_dollar(self):
        sql, params = self.tk._get_columns_query("public", "orders")
        assert "col_description" in sql.lower()
        assert "$1" in sql and "$2" in sql
        assert ":schema" not in sql and ":table" not in sql
        assert isinstance(params, tuple)
        assert params == ("public", "orders")


# ---------------------------------------------------------------------------
# BigQueryToolkit overrides
# ---------------------------------------------------------------------------

class TestBigQueryBuilderPlaceholders:
    """BigQuery builders must return tuple (empty), values inlined safely."""

    def setup_method(self):
        self.tk = BigQueryToolkit(project_id="my-project")

    def test_information_schema_query_bq_style(self):
        sql, params = self.tk._get_information_schema_query("prog", ["my_dataset"])
        assert isinstance(params, tuple)
        assert params == (), "BQ builders should return empty tuple (values inlined)"
        assert "INFORMATION_SCHEMA" in sql.upper()
        # Values should be inlined, no :param placeholders
        assert ":term" not in sql
        assert ":limit" not in sql

    def test_columns_query_bq_style(self):
        sql, params = self.tk._get_columns_query("my_schema", "my_table")
        assert isinstance(params, tuple)
        assert params == ()
        assert "INFORMATION_SCHEMA" in sql.upper()
        assert ":table" not in sql

    def test_primary_keys_query_bq_empty(self):
        sql, params = self.tk._get_primary_keys_query("d", "t")
        assert isinstance(params, tuple)
        assert params == ()

    def test_unique_constraints_query_bq_empty(self):
        sql, params = self.tk._get_unique_constraints_query("d", "t")
        assert isinstance(params, tuple)
        assert params == ()

    def test_bq_search_term_sql_escaped(self):
        """Single quotes in search_term are escaped (SQL injection prevention)."""
        sql, params = self.tk._get_information_schema_query("O'Brien", ["dataset"])
        assert "O''Brien" in sql, "Single quotes must be doubled for SQL safety"
        assert "O'Brien" not in sql.split("O''Brien")[0]  # raw quote not in SQL


# ---------------------------------------------------------------------------
# _execute_asyncdb parameter forwarding
# ---------------------------------------------------------------------------

class TestExecuteAsyncdbParamForwarding:
    """_execute_asyncdb must forward tuple params to conn.fetch(*params)."""

    @pytest.mark.asyncio
    async def test_execute_asyncdb_forwards_tuple_params(self):
        """Params are unpacked via *params in the conn.fetch() call."""
        tk = SQLToolkit(dsn="postgresql://test")

        fetch_calls: list[tuple] = []

        async def fake_fetch(sql, *args):
            fetch_calls.append((sql, args))
            return []

        fake_conn = MagicMock()
        fake_conn.fetch = fake_fetch

        @asynccontextmanager
        async def fake_acquire():
            yield fake_conn

        tk._connection = MagicMock()  # non-None guard
        tk._acquire_asyncdb_connection = fake_acquire

        data, err = await tk._execute_asyncdb("SELECT $1, $2", params=("auth", "programs"))

        assert err is None
        assert len(fetch_calls) == 1
        assert fetch_calls[0] == ("SELECT $1, $2", ("auth", "programs"))

    @pytest.mark.asyncio
    async def test_execute_asyncdb_no_params_calls_fetch_bare(self):
        """When params=() (default), fetch is called without extra args."""
        tk = SQLToolkit(dsn="postgresql://test")

        fetch_calls: list[tuple] = []

        async def fake_fetch(sql, *args):
            fetch_calls.append((sql, args))
            return []

        fake_conn = MagicMock()
        fake_conn.fetch = fake_fetch

        @asynccontextmanager
        async def fake_acquire():
            yield fake_conn

        tk._connection = MagicMock()
        tk._acquire_asyncdb_connection = fake_acquire

        data, err = await tk._execute_asyncdb("SELECT 1")

        assert err is None
        assert fetch_calls[0] == ("SELECT 1", ())

    @pytest.mark.asyncio
    async def test_execute_asyncdb_list_param(self):
        """List params (e.g. schema list) are forwarded as a single arg."""
        tk = SQLToolkit(dsn="postgresql://test")

        fetch_calls: list[tuple] = []

        async def fake_fetch(sql, *args):
            fetch_calls.append((sql, args))
            return []

        fake_conn = MagicMock()
        fake_conn.fetch = fake_fetch

        @asynccontextmanager
        async def fake_acquire():
            yield fake_conn

        tk._connection = MagicMock()
        tk._acquire_asyncdb_connection = fake_acquire

        schemas = ["auth", "public"]
        data, err = await tk._execute_asyncdb(
            "SELECT ... WHERE schema = ANY($1)", params=(schemas,)
        )

        assert err is None
        assert fetch_calls[0] == ("SELECT ... WHERE schema = ANY($1)", (schemas,))


# ---------------------------------------------------------------------------
# _get_sample_data_query — identifier validation
# ---------------------------------------------------------------------------

class TestSampleDataQueryIdentifierValidation:
    """_get_sample_data_query raises ValueError for unsafe SQL identifiers.

    Both schema and table are passed through _validate_identifier which
    enforces the regex ``^[a-zA-Z_][a-zA-Z0-9_]*$``.  Any identifier that
    contains spaces, hyphens, SQL meta-characters, or starts with a digit
    must raise ``ValueError`` before any SQL is produced.
    """

    def setup_method(self):
        self.tk = SQLToolkit(dsn="postgresql://test")

    def test_valid_schema_and_table_returns_sql(self):
        """A well-formed schema.table pair produces a SELECT statement."""
        sql = self.tk._get_sample_data_query("public", "orders")
        assert "SELECT" in sql.upper()
        assert "public" in sql
        assert "orders" in sql

    def test_invalid_schema_raises_value_error(self):
        """Schema names with SQL-unsafe characters raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            self.tk._get_sample_data_query("public; DROP TABLE users--", "orders")

    def test_invalid_table_raises_value_error(self):
        """Table names with SQL-unsafe characters raise ValueError."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            self.tk._get_sample_data_query("public", "orders; DROP TABLE users--")

    def test_schema_with_hyphen_raises(self):
        """Hyphens are not valid SQL identifier characters."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            self.tk._get_sample_data_query("my-schema", "orders")

    def test_table_starting_with_digit_raises(self):
        """Identifiers starting with a digit are rejected."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            self.tk._get_sample_data_query("public", "1bad_table")

    def test_table_with_space_raises(self):
        """Spaces in identifiers are rejected (SQL injection vector)."""
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            self.tk._get_sample_data_query("public", "my table")
