"""Integration test: multi-toolkit runtime for DatabaseAgent (FEAT-171).

Drives ``DatabaseAgent._compute_active_tools`` with two toolkits that carry
distinct prefixes across every relevant ``OutputComponent`` flag combination
and asserts that both toolkits' tools appear in the merged result.

All stubs are in-memory so the test requires no external services.
"""
from __future__ import annotations

import warnings
from typing import List, Optional

import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent, QueryExecutionResponse
from parrot.bots.database.toolkits.base import DatabaseToolkit, TableMetadata


# ---------------------------------------------------------------------------
# Inline stub — mirrors MockDatabaseToolkit from unit conftest but is kept
# here so the integration test directory is fully self-contained.
# ---------------------------------------------------------------------------

class _MockToolkit(DatabaseToolkit):
    """Minimal in-memory stub that exposes all four database toolkit tools."""

    def __init__(self, tool_prefix: Optional[str] = "mock", **kwargs) -> None:
        super().__init__(
            dsn="mock://localhost/testdb",
            database_type="mock",
            allowed_schemas=["public"],
            primary_schema="public",
            **kwargs,
        )
        self.tool_prefix = tool_prefix  # type: ignore[assignment]

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Stub: search_schema."""
        return []

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Stub: execute_query."""
        return QueryExecutionResponse(
            success=True,
            data=[],
            row_count=0,
            execution_time_ms=0.0,
            schema_used="public",
        )

    async def generate_query(self, prompt: str) -> str:
        """Stub: generate_query."""
        return "SELECT 1"

    async def validate_query(self, query: str) -> bool:
        """Stub: validate_query."""
        return True

    async def explain_query(self, query: str) -> str:
        """Stub: explain_query."""
        return "Seq Scan on mock"

    async def start(self) -> None:
        """No-op lifecycle."""

    async def close(self) -> None:
        """No-op lifecycle."""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_toolkit_factory():
    """Factory for ``_MockToolkit`` with controllable prefix."""

    def _make(tool_prefix: Optional[str] = "mock") -> _MockToolkit:
        return _MockToolkit(tool_prefix=tool_prefix)

    return _make


@pytest.fixture
def agent_factory():
    """Construct a ``DatabaseAgent`` with a stubbed internal toolkit."""

    def _make(toolkits=None) -> DatabaseAgent:
        agent = DatabaseAgent(name="integration-test", toolkits=toolkits or [])
        agent._internal_toolkit = type("_Stub", (), {})()
        return agent

    return _make


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "components,expected_names",
    [
        (
            OutputComponent.SCHEMA_CONTEXT,
            {"db_search_schema", "mk_search_schema"},
        ),
        (
            OutputComponent.SQL_QUERY,
            {
                "db_generate_query",
                "db_validate_query",
                "mk_generate_query",
                "mk_validate_query",
            },
        ),
        (
            OutputComponent.EXECUTION_PLAN,
            {"db_explain_query", "mk_explain_query"},
        ),
        (
            OutputComponent.SQL_QUERY | OutputComponent.SCHEMA_CONTEXT,
            {
                "db_search_schema",
                "mk_search_schema",
                "db_generate_query",
                "db_validate_query",
                "mk_generate_query",
                "mk_validate_query",
            },
        ),
    ],
)
def test_databaseagent_multi_toolkit_runtime(
    agent_factory,
    mock_toolkit_factory,
    components,
    expected_names,
):
    """Spin up a ``DatabaseAgent`` with two toolkits (prefix='db' and
    prefix='mk'), exercise every ``OutputComponent`` flag combination, and
    assert the merged tool surface contains tools from BOTH toolkits.

    This is the integration-level regression test for FEAT-171's prefix-aware
    resolution: before this feature, only the first toolkit's tools were
    visible to the LLM.
    """
    agent = agent_factory(
        toolkits=[
            mock_toolkit_factory(tool_prefix="db"),
            mock_toolkit_factory(tool_prefix="mk"),
        ]
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        tools = agent._compute_active_tools(components)

    names = {getattr(t, "name", None) for t in tools}
    assert expected_names.issubset(names), (
        f"Missing tools for {components!r}: {expected_names - names}"
    )
