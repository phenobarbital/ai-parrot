"""Shared fixtures for DatabaseAgent unit tests (FEAT-171 / FEAT-172).

Provides ``MockDatabaseToolkit`` — a minimal in-memory stub that implements
the ``DatabaseToolkit`` interface.  ``AbstractToolkit._generate_tools`` auto-
discovers all public async methods as tools; ``tool_prefix`` (controlled at
construction time) governs the fully-qualified names registered with the
agent.

FEAT-172 extension: ``mock_toolkit_factory`` now accepts ``method_name``
and ``methods`` parameters to control the exact set of tools exposed by the
returned stub, enabling negative-path tests for configure() validation.

Examples::

    mk = MockDatabaseToolkit(tool_prefix="mk")  # mk_search_schema, …
    db = MockDatabaseToolkit(tool_prefix="db")  # db_search_schema, …
    no = MockDatabaseToolkit(tool_prefix=None)   # search_schema, …
"""
from __future__ import annotations

import itertools
from typing import List, Optional

import pytest

from parrot.bots.database.toolkits.base import DatabaseToolkit, TableMetadata
from parrot.bots.database.models import QueryExecutionResponse

# Monotonically increasing counter used to generate unique database_type
# values across factory calls.  Each MockDatabaseToolkit instance produced
# by mock_toolkit_factory gets its own suffix (mock_0, mock_1, …) so that
# the tk_id computed inside DatabaseAgent.configure() is always unique even
# when multiple toolkit instances are attached to the same agent.
_MOCK_COUNTER = itertools.count()


class MockDatabaseToolkit(DatabaseToolkit):
    """Minimal stub toolkit for unit testing.

    All public async methods are auto-discovered by
    ``AbstractToolkit._generate_tools`` as coroutine functions and registered
    under ``{tool_prefix}_{method_name}`` (or the bare method name when
    ``tool_prefix`` is ``None``).

    ``tool_prefix`` defaults to ``"mock"`` but callers should always pass an
    explicit value so the expected tool names are unambiguous in tests.

    ``database_type`` is intentionally configurable so that multiple instances
    can coexist in the same ``DatabaseAgent.configure()`` call without
    triggering a CacheManager partition-namespace collision (each instance gets
    a unique ``tk_id = f"{database_type}_{primary_schema}"``).
    """

    def __init__(
        self,
        tool_prefix: Optional[str] = "mock",
        database_type: str = "mock",
        **kwargs,
    ) -> None:
        """Initialise with a fake DSN and a controllable tool prefix.

        Args:
            tool_prefix: Namespace applied to exposed tool names.  Pass
                ``None`` to exercise the legacy no-prefix path in
                ``DatabaseAgent._compute_active_tools``.
            database_type: Database type string used to build the toolkit's
                ``tk_id`` inside ``configure()``.  Unique values prevent
                CacheManager namespace collisions when multiple mock toolkits
                are attached to the same agent.
            **kwargs: Forwarded to ``DatabaseToolkit.__init__``.
        """
        super().__init__(
            dsn="mock://localhost/testdb",
            database_type=database_type,
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

    Extended in FEAT-172 to accept ``method_name`` and ``methods``
    parameters so negative-path tests can control the tool surface
    precisely (e.g. to exercise the idempotent-prefix edge case).

    Args:
        tool_prefix: Namespace applied to tool names.  Pass ``None``,
            ``""``, or any arbitrary string to exercise prefix
            validation paths.  Passed through without coercion.
        method_name: When given, the returned toolkit exposes **only**
            this single async method (plus the required abstract-method
            stubs for ``DatabaseToolkit``).  Mutually exclusive with
            ``methods``.
        methods: When given, the returned toolkit exposes **exactly**
            these async methods (plus the required abstract-method stubs
            if they are absent).  Mutually exclusive with ``method_name``.

    Usage::

        def test_something(mock_toolkit_factory):
            tk_db = mock_toolkit_factory(tool_prefix="db")
            tk_mk = mock_toolkit_factory(tool_prefix="mk")
            tk_no_prefix = mock_toolkit_factory(tool_prefix=None)
            # Single-method variant (FEAT-172 collision edge-case):
            tk_a = mock_toolkit_factory(tool_prefix="db", method_name="db_search_schema")
            tk_b = mock_toolkit_factory(tool_prefix="db", method_name="search_schema")
            # Multi-method variant (integration smoke test):
            tk = mock_toolkit_factory(
                tool_prefix="db",
                methods=["search_schema", "generate_query"],
            )
    """

    # The async methods that MockDatabaseToolkit already provides.
    _STANDARD_TOOL_METHODS: set = {
        "search_schema",
        "execute_query",
        "generate_query",
        "validate_query",
        "explain_query",
    }

    def _make(
        tool_prefix: Optional[str] = "mock",
        method_name: Optional[str] = None,
        methods: Optional[List[str]] = None,
    ) -> MockDatabaseToolkit:
        # Unique database_type avoids CacheManager partition-namespace
        # collisions when multiple mock toolkits are configured in the same
        # DatabaseAgent (tk_id = f"{database_type}_{primary_schema}").
        unique_db_type = f"mock_{next(_MOCK_COUNTER)}"

        # Fast path: no method filtering requested.
        if method_name is None and methods is None:
            return MockDatabaseToolkit(
                tool_prefix=tool_prefix,
                database_type=unique_db_type,
            )

        # Determine the exact set of tool methods to expose.
        if method_name is not None:
            tool_methods: List[str] = [method_name]
        else:
            tool_methods = list(methods)  # type: ignore[arg-type]

        tool_methods_set = set(tool_methods)

        # Standard methods that should NOT be exposed → exclude_tools.
        to_exclude = tuple(m for m in _STANDARD_TOOL_METHODS if m not in tool_methods_set)

        # Methods not in the standard set → need dynamic async stubs.
        to_add = [m for m in tool_methods if m not in _STANDARD_TOOL_METHODS]

        # Build the extra async stubs as functions, avoiding closure issues
        # by using a factory helper.
        def _make_async_stub(stub_name: str):
            async def _stub(self, *args, **kwargs):
                return None

            _stub.__doc__ = f"Stub for {stub_name}."
            _stub.__name__ = stub_name
            return _stub

        class_attrs: dict = {"exclude_tools": to_exclude}
        for mname in to_add:
            class_attrs[mname] = _make_async_stub(mname)

        _DynamicMock = type("_DynamicMockToolkit", (MockDatabaseToolkit,), class_attrs)
        mock = _DynamicMock(
            tool_prefix=tool_prefix,
            database_type=unique_db_type,
        )
        return mock

    return _make


@pytest.fixture
def postgres_toolkit_fixture(mock_toolkit_factory) -> MockDatabaseToolkit:
    """A ``MockDatabaseToolkit`` with the canonical ``tool_prefix="db"``.

    Used for the no-regression test that pins the tool surface of the
    ``sql_analyst`` plugin (one ``PostgresToolkit(tool_prefix="db")``).
    """
    return mock_toolkit_factory(tool_prefix="db")
