"""Unit tests for DatabaseAgent.configure() validation (FEAT-172).

Verifies that configure() enforces:
  - Non-empty tool_prefix on every attached toolkit (Pass A).
  - Identifier-safe tool_prefix matching ^[A-Za-z][A-Za-z0-9_]*$ (Pass B).
  - No fully-qualified tool-name collision across toolkits (Pass C).

Also verifies that the runtime collision warning emitted by
_compute_active_tools ends with the FEAT-172 defensive-fallback suffix.
"""
from __future__ import annotations

import re

import pytest

from parrot.bots.database.agent import (
    DatabaseAgent,
    _TOOL_PREFIX_PATTERN,
)
from parrot.bots.database.models import OutputComponent


# ---------------------------------------------------------------------------
# TestPrefixPresence (Pass A)
# ---------------------------------------------------------------------------


class TestPrefixPresence:
    """configure() must reject toolkits with None or empty tool_prefix."""

    async def test_rejects_none_prefix(self, mock_toolkit_factory):
        """A toolkit with tool_prefix=None raises ValueError."""
        tk = mock_toolkit_factory(tool_prefix=None)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(ValueError, match=r"must declare a non-empty"):
            await agent.configure()

    async def test_rejects_empty_prefix(self, mock_toolkit_factory):
        """A toolkit with tool_prefix='' raises ValueError."""
        tk = mock_toolkit_factory(tool_prefix="")
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(ValueError, match=r"must declare a non-empty"):
            await agent.configure()


# ---------------------------------------------------------------------------
# TestPrefixShape (Pass B)
# ---------------------------------------------------------------------------


class TestPrefixShape:
    """configure() must reject non-identifier-safe prefixes and accept valid ones."""

    @pytest.mark.parametrize("bad", ["my-db", "db ", "123db", "db.foo"])
    async def test_rejects_non_identifier_prefix(
        self,
        mock_toolkit_factory,
        bad: str,
    ):
        """Prefixes that don't match the pattern raise ValueError mentioning the regex."""
        tk = mock_toolkit_factory(tool_prefix=bad)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(
            ValueError,
            match=re.escape(_TOOL_PREFIX_PATTERN.pattern),
        ):
            await agent.configure()

    @pytest.mark.parametrize(
        "good",
        ["db", "pg", "bq", "influx", "elastic_v2", "X1"],
    )
    async def test_accepts_identifier_prefixes(
        self,
        mock_toolkit_factory,
        good: str,
    ):
        """Valid identifier-safe prefixes must not raise."""
        tk = mock_toolkit_factory(tool_prefix=good)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        await agent.configure()  # must not raise


# ---------------------------------------------------------------------------
# TestCollision (Pass C)
# ---------------------------------------------------------------------------


class TestCollision:
    """configure() must detect fully-qualified tool-name collisions."""

    async def test_rejects_collision_same_prefix(self, mock_toolkit_factory):
        """Two toolkits with the same prefix collide on every shared name."""
        tk_a = mock_toolkit_factory(tool_prefix="dup")
        tk_b = mock_toolkit_factory(tool_prefix="dup")
        agent = DatabaseAgent(name="t", toolkits=[tk_a, tk_b])
        with pytest.raises(ValueError, match=r"Tool name collision"):
            await agent.configure()

    async def test_rejects_collision_idempotent_naming(
        self,
        mock_toolkit_factory,
    ):
        """Idempotent prefix rewrite: a method named 'db_search_schema' on a
        toolkit with tool_prefix='db' resolves to 'db_search_schema' (unchanged).
        A method named 'search_schema' on the same toolkit also resolves to
        'db_search_schema'.  configure() must detect this collision."""
        # tk_a: method `db_search_schema` with prefix `"db"` → full name `db_search_schema`
        tk_a = mock_toolkit_factory(
            tool_prefix="db",
            method_name="db_search_schema",
        )
        # tk_b: method `search_schema` with prefix `"db"` → full name `db_search_schema`
        tk_b = mock_toolkit_factory(
            tool_prefix="db",
            method_name="search_schema",
        )
        agent = DatabaseAgent(name="t", toolkits=[tk_a, tk_b])
        with pytest.raises(ValueError, match=r"Tool name collision"):
            await agent.configure()

    async def test_accepts_distinct_prefixes_same_logical_name(
        self,
        mock_toolkit_factory,
    ):
        """Two toolkits with distinct prefixes do not collide even when they
        share the same logical method names."""
        tk_a = mock_toolkit_factory(tool_prefix="db")
        tk_b = mock_toolkit_factory(tool_prefix="mk")
        agent = DatabaseAgent(name="t", toolkits=[tk_a, tk_b])
        await agent.configure()  # must not raise


# ---------------------------------------------------------------------------
# TestPartialStateSafety
# ---------------------------------------------------------------------------


class TestPartialStateSafety:
    """After a configure() ValueError, _internal_toolkit must still be None."""

    async def test_failed_validation_leaves_internal_toolkit_none(
        self,
        mock_toolkit_factory,
    ):
        """_internal_toolkit stays None when configure() raises."""
        tk = mock_toolkit_factory(tool_prefix=None)
        agent = DatabaseAgent(name="t", toolkits=[tk])
        with pytest.raises(ValueError):
            await agent.configure()
        assert agent._internal_toolkit is None


# ---------------------------------------------------------------------------
# TestRuntimeWarningSuffix (Module 2)
# ---------------------------------------------------------------------------


class TestRuntimeWarningSuffix:
    """The runtime collision warning from _compute_active_tools must end with
    the FEAT-172 defensive-fallback note."""

    async def test_runtime_collision_warning_has_new_suffix(
        self,
        mock_toolkit_factory,
        caplog,
    ):
        """Force a runtime collision by appending a second toolkit after
        configure() (bypassing Pass C).  The warning must contain the
        expected suffix string."""
        import logging

        agent = DatabaseAgent(
            name="t",
            toolkits=[mock_toolkit_factory(tool_prefix="db")],
        )
        await agent.configure()

        # Append a colliding toolkit AFTER configure() to bypass Pass C
        agent.toolkits.append(mock_toolkit_factory(tool_prefix="db"))

        with caplog.at_level(logging.WARNING):
            agent._compute_active_tools(OutputComponent.SCHEMA_CONTEXT)

        msgs = [r.getMessage() for r in caplog.records]
        assert any(
            "should have been caught at configure() time" in m for m in msgs
        ), f"Expected suffix not found in warning messages: {msgs}"
