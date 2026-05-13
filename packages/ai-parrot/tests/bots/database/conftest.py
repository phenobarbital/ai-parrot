"""Fixtures for DatabaseAgent tests."""
from __future__ import annotations

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.database.models import (
    QueryExecutionResponse,
    QueryResponse,
)
from parrot.bots.database.toolkits.base import DatabaseToolkit, TableMetadata
from parrot.models import AIMessage, CompletionUsage


# ---------------------------------------------------------------------------
# Fake DatabaseToolkit (in-memory, no real DB connection)
# ---------------------------------------------------------------------------

class _FakePostgresToolkit(DatabaseToolkit):
    """Minimal concrete DatabaseToolkit for unit tests."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        return []

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        return QueryExecutionResponse(
            success=True,
            data=[],
            row_count=0,
            execution_time_ms=0.0,
            schema_used="public",
        )


@pytest.fixture
def fake_postgres_toolkit() -> _FakePostgresToolkit:
    """In-memory PostgresToolkit with no real DB connection."""
    return _FakePostgresToolkit(
        dsn="postgresql://test:test@localhost:5432/testdb",
        allowed_schemas=["public"],
        primary_schema="public",
        database_type="postgresql",
    )


# ---------------------------------------------------------------------------
# Mock LLM client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_client() -> MagicMock:
    """AbstractClient stub recording ask() payloads, returning a canned AIMessage."""
    client = MagicMock()
    default_qr = QueryResponse(explanation="ok", query=None, data=None)
    default_response = MagicMock(
        spec=AIMessage,
        is_structured=True,
        output=default_qr,
        response="ok",
        data=None,
        session_id=None,
    )
    client.ask = AsyncMock(return_value=default_response)
    return client
