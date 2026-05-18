"""Unit tests for DatabaseAgent._compute_active_tools (FEAT-171).

Verifies prefix-aware tool resolution, collision deduplication, and the
legacy ``tool_prefix=None`` graceful-degradation path.
"""
from __future__ import annotations

import warnings

import pytest

from parrot.bots.database.agent import DatabaseAgent
from parrot.bots.database.models import OutputComponent


# ---------------------------------------------------------------------------
# Shared helper fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_factory():
    """Return a factory that constructs a ``DatabaseAgent`` in isolation.

    The agent's ``_internal_toolkit`` is stubbed with a bare object so
    Pass 1 does not bail out early but also does not add any internal tools
    to the output (keeping test assertions focused on Pass 2 / toolkit tools).
    """

    def _make(toolkits=None) -> DatabaseAgent:
        agent = DatabaseAgent(name="test-agent", toolkits=toolkits or [])
        # Inject a minimal stub so _internal_toolkit is not None.
        agent._internal_toolkit = type("_InternalStub", (), {})()
        return agent

    return _make


# ---------------------------------------------------------------------------
# TestPrefixAwareResolution
# ---------------------------------------------------------------------------


class TestPrefixAwareResolution:
    """Verify that toolkit tools are resolved using each toolkit's prefix."""

    def test_compute_active_tools_default_prefix(
        self, agent_factory, mock_toolkit_factory
    ):
        """A toolkit with tool_prefix='db' exposes db_search_schema under
        SCHEMA_CONTEXT — regression pin for the existing sql_analyst config."""
        agent = agent_factory(toolkits=[mock_toolkit_factory(tool_prefix="db")])
        tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert "db_search_schema" in names

    def test_compute_active_tools_custom_prefix(
        self, agent_factory, mock_toolkit_factory
    ):
        """A toolkit with tool_prefix='mk' exposes mk_search_schema under
        SCHEMA_CONTEXT.  Before FEAT-171 this would return no toolkit tools
        because the map hard-coded 'db_search_schema'."""
        agent = agent_factory(toolkits=[mock_toolkit_factory(tool_prefix="mk")])
        tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert "mk_search_schema" in names

    def test_compute_active_tools_two_toolkits_distinct_prefixes(
        self, agent_factory, mock_toolkit_factory
    ):
        """Two toolkits with distinct prefixes both surface their tools."""
        agent = agent_factory(
            toolkits=[
                mock_toolkit_factory(tool_prefix="db"),
                mock_toolkit_factory(tool_prefix="mk"),
            ]
        )
        tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert {"db_search_schema", "mk_search_schema"}.issubset(names)


# ---------------------------------------------------------------------------
# TestCollisionLogging
# ---------------------------------------------------------------------------


class TestCollisionLogging:
    """Verify that same-prefix collisions are logged and deduplicated."""

    def test_compute_active_tools_logs_collision(
        self, agent_factory, mock_toolkit_factory, caplog
    ):
        """Two toolkits sharing the same prefix collide on the same
        fully-qualified name.  The warning message must contain both the
        current OutputComponent name ('SCHEMA_CONTEXT') and the word
        'collision'."""
        import logging

        agent = agent_factory(
            toolkits=[
                mock_toolkit_factory(tool_prefix="db"),
                mock_toolkit_factory(tool_prefix="db"),
            ]
        )
        with caplog.at_level(logging.WARNING):
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)

        msgs = [r.getMessage() for r in caplog.records]
        assert any(
            "SCHEMA_CONTEXT" in m and "collision" in m for m in msgs
        ), f"Expected collision warning with SCHEMA_CONTEXT in: {msgs}"

    def test_collision_warning_deduplicated_across_turns(
        self, agent_factory, mock_toolkit_factory, caplog
    ):
        """The same collision is logged at most once per agent lifetime even
        when _compute_active_tools is called multiple times (e.g., once per
        LLM turn)."""
        import logging

        agent = agent_factory(
            toolkits=[
                mock_toolkit_factory(tool_prefix="db"),
                mock_toolkit_factory(tool_prefix="db"),
            ]
        )
        with caplog.at_level(logging.WARNING):
            for _ in range(3):
                agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)

        collision_records = [
            r for r in caplog.records if "collision" in r.getMessage()
        ]
        assert len(collision_records) == 1, (
            f"Expected exactly 1 collision log, got {len(collision_records)}"
        )
        # Also verify the internal dedup set grew by exactly 1 entry.
        assert len(agent._logged_collisions) == 1


# ---------------------------------------------------------------------------
# TestLegacyNonePrefix
# ---------------------------------------------------------------------------


class TestLegacyNonePrefix:
    """Verify graceful degradation and one-time DeprecationWarning for
    toolkits that declare tool_prefix=None."""

    def test_none_prefix_graceful_resolution(
        self, agent_factory, mock_toolkit_factory
    ):
        """A toolkit with tool_prefix=None resolves tools by logical name
        (e.g., 'search_schema') and surfaces correctly under SCHEMA_CONTEXT."""
        agent = agent_factory(
            toolkits=[mock_toolkit_factory(tool_prefix=None)]
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tools = agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
        names = {getattr(t, "name", None) for t in tools}
        assert "search_schema" in names

    def test_none_prefix_emits_deprecation_warning_once(
        self, agent_factory, mock_toolkit_factory
    ):
        """First call emits a DeprecationWarning mentioning FEAT-172;
        subsequent calls for the same toolkit instance emit nothing."""
        tk = mock_toolkit_factory(tool_prefix=None)
        agent = agent_factory(toolkits=[tk])

        # First call — must warn
        with pytest.warns(DeprecationWarning, match="FEAT-172"):
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)

        # Second call — must NOT warn again for the same toolkit instance
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)
            dep_warnings = [
                w for w in caught if issubclass(w.category, DeprecationWarning)
            ]
        assert len(dep_warnings) == 0, (
            "DeprecationWarning should fire only once per toolkit instance"
        )
        # Dedup set has exactly one entry (the toolkit's id)
        assert id(tk) in agent._warned_none_prefix


# ---------------------------------------------------------------------------
# TestNoRegression
# ---------------------------------------------------------------------------


class TestNoRegression:
    """Regression test: sql_analyst tool surface must be byte-identical
    before and after FEAT-171."""

    def test_no_regression_sql_analyst_path(
        self, agent_factory, postgres_toolkit_fixture
    ):
        """One PostgresToolkit(tool_prefix='db') must expose exactly the same
        toolkit tools as before: db_search_schema, db_generate_query,
        db_validate_query, db_explain_query."""
        agent = agent_factory(toolkits=[postgres_toolkit_fixture])
        tools = agent._compute_active_tools(
            OutputComponent.SQL_QUERY
            | OutputComponent.SCHEMA_CONTEXT
            | OutputComponent.EXECUTION_PLAN
        )
        names = {getattr(t, "name", None) for t in tools}
        expected = {
            "db_search_schema",
            "db_generate_query",
            "db_validate_query",
            "db_explain_query",
        }
        assert expected.issubset(names), (
            f"Missing from tool surface: {expected - names}"
        )
