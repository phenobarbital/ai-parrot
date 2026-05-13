"""Unit tests for toolkit-level retry wiring and agent re-ask loop (FEAT-164)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import pytest

from parrot.bots.database.retries import QueryRetryConfig, RetryContext, SQLRetryHandler
from parrot.bots.database.toolkits.sql import SQLToolkit


# ---------------------------------------------------------------------------
# Fixture: bare SQLToolkit instance that bypasses DB connection setup
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_postgres_toolkit() -> SQLToolkit:
    """SQLToolkit instance with no real DB connection, for retry unit tests.

    Uses object.__new__ to skip __init__ and sets only the attributes that
    execute_query and _run_query actually read.
    """
    toolkit: SQLToolkit = object.__new__(SQLToolkit)
    toolkit.dsn = "postgresql://fake:fake@localhost/fake"
    toolkit.allowed_schemas = ["public"]
    toolkit.primary_schema = "public"
    toolkit.read_only = True
    toolkit.retry_config = None
    toolkit.cache_partition = None
    toolkit.database_type = "postgresql"
    toolkit._connection = None
    toolkit._connected = False
    toolkit.tables = []
    toolkit.use_pool = False
    toolkit.pool_params = {}
    toolkit.logger = logging.getLogger("FakeSQLToolkit")
    return toolkit


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sqltoolkit_retry_loop_invokes_handler_on_retryable_error(
    fake_postgres_toolkit: SQLToolkit,
) -> None:
    """A retryable execute_query error fires SQLRetryHandler.retry_query."""
    fake_postgres_toolkit.retry_config = QueryRetryConfig(max_retries=2)
    # "column does not exist" matches the default retry_on_errors patterns.
    fake_postgres_toolkit._run_query = AsyncMock(  # type: ignore[method-assign]
        side_effect=Exception("column does not exist")
    )
    with patch.object(
        SQLRetryHandler, "retry_query", new=AsyncMock(return_value=None)
    ) as mocked:
        result = await fake_postgres_toolkit.execute_query("SELECT x FROM t")
        assert mocked.await_count >= 1
    assert isinstance(result, RetryContext)
    assert result.query == "SELECT x FROM t"
    assert "column" in result.error


@pytest.mark.asyncio
async def test_sqltoolkit_retry_loop_skips_non_retryable_error(
    fake_postgres_toolkit: SQLToolkit,
) -> None:
    """A non-retryable error propagates immediately without calling retry_query."""
    fake_postgres_toolkit.retry_config = QueryRetryConfig(max_retries=2)
    fake_postgres_toolkit._run_query = AsyncMock(  # type: ignore[method-assign]
        side_effect=ValueError("not retryable")
    )
    with pytest.raises(ValueError, match="not retryable"):
        await fake_postgres_toolkit.execute_query("SELECT 1")
