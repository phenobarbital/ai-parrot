"""Unit tests for RetryHandler and subclasses."""
import os, sys  # noqa: E401
sys.path.insert(0, os.path.dirname(__file__))
from conftest_db import setup_worktree_imports  # noqa: E402
setup_worktree_imports()

import pytest  # noqa: E402
from parrot.bots.database.retries import (  # noqa: E402
    QueryRetryConfig,
    RetryHandler,
    SQLRetryHandler,
    FluxRetryHandler,
    DSLRetryHandler,
)


class TestRetryHandler:
    def test_retryable_error(self):
        handler = RetryHandler(config=QueryRetryConfig())
        assert handler._is_retryable_error(Exception("column does not exist"))
        assert handler._is_retryable_error(Exception("DataError: bad value"))
        assert not handler._is_retryable_error(Exception("connection refused"))

    @pytest.mark.asyncio
    async def test_retry_query_base_returns_none(self):
        handler = RetryHandler()
        result = await handler.retry_query("SELECT 1", Exception("error"), attempt=0)
        assert result is None

    @pytest.mark.asyncio
    async def test_retry_query_exceeds_max(self):
        handler = RetryHandler(config=QueryRetryConfig(max_retries=2))
        result = await handler.retry_query("SELECT 1", Exception("DataError"), attempt=5)
        assert result is None


class TestSQLRetryHandler:
    def test_extract_table_column(self):
        handler = SQLRetryHandler()
        table, col = handler._extract_table_column_from_error(
            'SELECT * FROM "public"."orders" ORDER BY created_at', Exception("type error")
        )
        assert table == "orders"
        assert col == "created_at"

    def test_retryable_sql_error(self):
        handler = SQLRetryHandler()
        assert handler._is_retryable_error(Exception("invalid input syntax for type integer"))

    def test_backward_compat_agent_param(self):
        """SQLRetryHandler accepts 'agent' keyword for backward compat."""
        mock_agent = type("Agent", (), {"logger": None})()
        handler = SQLRetryHandler(agent=mock_agent)
        assert handler.toolkit is mock_agent


class TestFluxRetryHandler:
    def test_retryable_errors(self):
        handler = FluxRetryHandler()
        assert handler._is_retryable_error(Exception("syntax error in Flux"))
        assert handler._is_retryable_error(Exception("bucket not found"))
        assert not handler._is_retryable_error(Exception("connection timeout"))


class TestDSLRetryHandler:
    def test_retryable_errors(self):
        handler = DSLRetryHandler()
        assert handler._is_retryable_error(Exception("parsing_exception"))
        assert handler._is_retryable_error(Exception("index_not_found"))
        assert not handler._is_retryable_error(Exception("connection refused"))


class TestQueryRetryConfig:
    def test_database_type_field(self):
        config = QueryRetryConfig(database_type="influxdb")
        assert config.database_type == "influxdb"

    def test_default_config(self):
        config = QueryRetryConfig()
        assert config.max_retries == 3
        assert config.database_type == "sql"
