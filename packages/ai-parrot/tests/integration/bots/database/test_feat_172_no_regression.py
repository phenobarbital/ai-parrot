"""Integration smoke test: FEAT-172 must not break the canonical sql_analyst config.

The ``sql_analyst`` plugin uses a single ``PostgresToolkit(tool_prefix="db")``.
This test pins the invariant that:
  - ``configure()`` succeeds without raising for that config.
  - ``_internal_toolkit`` is set after ``configure()``.
  - The canonical tool surface (``db_search_schema``, ``db_generate_query``,
    ``db_validate_query``, ``db_explain_query``) is exposed by
    ``_compute_active_tools``.
  - No collision warning fires on the request path.

All stubs are in-memory so the test requires no external services.

Implements the integration test row from FEAT-172 spec §4
(TASK-1211 — "SQL Analyst no-regression integration test").
"""
from __future__ import annotations

import logging
from typing import List, Optional

import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent, QueryExecutionResponse
from parrot.bots.database.toolkits.base import DatabaseToolkit, TableMetadata


# ---------------------------------------------------------------------------
# Inline stub — mirrors the canonical sql_analyst PostgresToolkit surface.
# Kept here so this integration test is fully self-contained (following the
# pattern established by test_multi_toolkit.py).
# ---------------------------------------------------------------------------


class _SqlAnalystMockToolkit(DatabaseToolkit):
    """In-memory stub that exposes exactly the four tools that the
    canonical ``sql_analyst`` PostgresToolkit(tool_prefix='db') exposes:
    ``db_search_schema``, ``db_generate_query``, ``db_validate_query``,
    ``db_explain_query``.
    """

    tool_prefix: str = "db"

    def __init__(self, database_type: str = "sql_analyst", **kwargs) -> None:
        """Initialise with a fake DSN.

        Args:
            database_type: Unique type string used to build the toolkit's
                ``tk_id`` inside ``configure()`` and avoid CacheManager
                namespace collisions.
            **kwargs: Forwarded to ``DatabaseToolkit.__init__``.
        """
        super().__init__(
            dsn="mock://localhost/testdb",
            database_type=database_type,
            allowed_schemas=["public"],
            primary_schema="public",
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Abstract method implementations
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
    # The four canonical sql_analyst tools
    # ------------------------------------------------------------------

    async def generate_query(self, prompt: str) -> str:
        """Generate a SQL query for the given *prompt*."""
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


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_sql_analyst_unchanged_after_feat_172(caplog):
    """Canonical sql_analyst config: one PostgresToolkit(tool_prefix='db').

    configure() must succeed, the expected tool surface must be exposed, and
    no warnings must be emitted by _compute_active_tools during normal
    operation (no collision, no tool_prefix=None deprecation).

    This test pins the FEAT-172 no-regression invariant: the validation
    passes introduced in configure() must not break a correctly-configured
    single-toolkit agent.
    """
    tk = _SqlAnalystMockToolkit()
    agent = DatabaseAgent(name="sql_analyst", toolkits=[tk])

    # configure() must not raise for a valid, well-prefixed toolkit.
    await agent.configure()
    assert agent._internal_toolkit is not None, (
        "configure() must set _internal_toolkit on success"
    )

    # _compute_active_tools must surface the canonical sql_analyst tools.
    with caplog.at_level(logging.WARNING):
        tools = agent._compute_active_tools(
            OutputComponent.SQL_QUERY
            | OutputComponent.SCHEMA_CONTEXT
            | OutputComponent.EXECUTION_PLAN,
        )

    names = {getattr(t, "name", None) for t in tools}
    expected = {
        "db_search_schema",
        "db_generate_query",
        "db_validate_query",
        "db_explain_query",
    }
    assert expected.issubset(names), (
        f"Missing from canonical tool surface: {expected - names}"
    )

    # No collision warning should fire on the normal request path.
    collision_warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "collision" in r.getMessage()
    ]
    assert collision_warnings == [], (
        f"Unexpected collision warnings on clean path: {collision_warnings}"
    )
