"""Shared fixtures for DatabaseAgent unit tests (FEAT-171).

Provides ``MockDatabaseToolkit`` — a minimal in-memory stub that implements
the ``DatabaseToolkit`` interface.  ``AbstractToolkit._generate_tools`` auto-
discovers all public async methods as tools; ``tool_prefix`` (controlled at
construction time) governs the fully-qualified names registered with the
agent.

Examples::

    mk = MockDatabaseToolkit(tool_prefix="mk")  # mk_search_schema, …
    db = MockDatabaseToolkit(tool_prefix="db")  # db_search_schema, …
    no = MockDatabaseToolkit(tool_prefix=None)   # search_schema, …
"""
from __future__ import annotations

from typing import List, Optional

import pytest

from parrot.bots.database.toolkits.base import DatabaseToolkit, TableMetadata
from parrot.bots.database.models import QueryExecutionResponse


class MockDatabaseToolkit(DatabaseToolkit):
    """Minimal stub toolkit for unit testing.

    All public async methods are auto-discovered by
    ``AbstractToolkit._generate_tools`` as coroutine functions and registered
    under ``{tool_prefix}_{method_name}`` (or the bare method name when
    ``tool_prefix`` is ``None``).

    ``tool_prefix`` defaults to ``"mock"`` but callers should always pass an
    explicit value so the expected tool names are unambiguous in tests.
    """

    def __init__(self, tool_prefix: Optional[str] = "mock", **kwargs) -> None:
        """Initialise with a fake DSN and a controllable tool prefix.

        Args:
            tool_prefix: Namespace applied to exposed tool names.  Pass
                ``None`` to exercise the legacy no-prefix path in
                ``DatabaseAgent._compute_active_tools``.
            **kwargs: Forwarded to ``DatabaseToolkit.__init__``.
        """
        super().__init__(
            dsn="mock://localhost/testdb",
            database_type="mock",
            allowed_schemas=["public"],
            primary_schema="public",
            **kwargs,
        )
        # Override as instance attribute so it takes effect before the lazy
        # _generate_tools() call (which reads self.tool_prefix at that point).
        self.tool_prefix = tool_prefix  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Abstract method implementations (DatabaseToolkit ABC)
    # ------------------------------------------------------------------

    async def search_schema(
        self,
        search_term: str,
        schema_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[TableMetadata]:
        """Stub: search the mock schema for *search_term*."""
        return []

    async def execute_query(
        self,
        query: str,
        limit: int = 1000,
        timeout: int = 30,
    ) -> QueryExecutionResponse:
        """Stub: execute a query against the mock database."""
        return QueryExecutionResponse(
            success=True,
            data=[],
            row_count=0,
            execution_time_ms=0.0,
            schema_used="public",
        )

    # ------------------------------------------------------------------
    # Additional toolkit tools (discovered by _generate_tools)
    # ------------------------------------------------------------------

    async def generate_query(self, prompt: str) -> str:
        """Generate a SQL query for *prompt*."""
        return "SELECT 1"

    async def validate_query(self, query: str) -> bool:
        """Validate *query* against the mock schema."""
        return True

    async def explain_query(self, query: str) -> str:
        """Return a mock execution plan for *query*."""
        return "Seq Scan on mock"

    # ------------------------------------------------------------------
    # Lifecycle stubs
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """No-op lifecycle hook."""

    async def close(self) -> None:
        """No-op lifecycle hook."""


@pytest.fixture
def mock_toolkit_factory():
    """Return a factory that builds ``MockDatabaseToolkit`` instances.

    Usage::

        def test_something(mock_toolkit_factory):
            tk_db = mock_toolkit_factory(tool_prefix="db")
            tk_mk = mock_toolkit_factory(tool_prefix="mk")
            tk_no_prefix = mock_toolkit_factory(tool_prefix=None)
    """

    def _make(tool_prefix: Optional[str] = "mock") -> MockDatabaseToolkit:
        return MockDatabaseToolkit(tool_prefix=tool_prefix)

    return _make


@pytest.fixture
def postgres_toolkit_fixture(mock_toolkit_factory) -> MockDatabaseToolkit:
    """A ``MockDatabaseToolkit`` with the canonical ``tool_prefix="db"``.

    Used for the no-regression test that pins the tool surface of the
    ``sql_analyst`` plugin (one ``PostgresToolkit(tool_prefix="db")``).
    """
    return mock_toolkit_factory(tool_prefix="db")
