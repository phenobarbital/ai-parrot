"""Unit tests for the agent-identity ContextVar module.

FEAT-228 TASK-1499.
"""

from __future__ import annotations

import asyncio

import pytest

from parrot.observability.context import agent_identity, current_agent_name


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------


def test_default_is_none() -> None:
    """Outside any agent_identity block, the var must default to None."""
    assert current_agent_name.get() is None


def test_set_and_reset() -> None:
    """Inside the block the var reads the bound name; outside it reverts."""
    with agent_identity("porygon"):
        assert current_agent_name.get() == "porygon"
    assert current_agent_name.get() is None


def test_nested_restores_outer() -> None:
    """Nested blocks restore the outer value on exit, not None."""
    with agent_identity("outer"):
        assert current_agent_name.get() == "outer"
        with agent_identity("inner"):
            assert current_agent_name.get() == "inner"
        assert current_agent_name.get() == "outer"
    assert current_agent_name.get() is None


def test_none_name_is_valid() -> None:
    """agent_identity(None) is legal; prior value is restored correctly."""
    with agent_identity("outer"):
        with agent_identity(None):
            assert current_agent_name.get() is None
        # restored to "outer", not None
        assert current_agent_name.get() == "outer"


def test_exception_still_resets() -> None:
    """The var is reset even if an exception propagates out of the block."""
    try:
        with agent_identity("broken"):
            raise RuntimeError("intentional")
    except RuntimeError:
        pass
    assert current_agent_name.get() is None


# ---------------------------------------------------------------------------
# Re-export path
# ---------------------------------------------------------------------------


def test_reexport_from_observability_package() -> None:
    """Both names must be importable from parrot.observability directly."""
    from parrot.observability import agent_identity as ai  # noqa: PLC0415
    from parrot.observability import current_agent_name as can  # noqa: PLC0415

    assert ai is agent_identity
    assert can is current_agent_name


# ---------------------------------------------------------------------------
# Async / task-local semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_task_inherits_context() -> None:
    """A task spawned inside the block sees the same value (copy-on-create)."""
    seen: list[str | None] = []

    async def reader() -> None:
        seen.append(current_agent_name.get())

    with agent_identity("async-bot"):
        task = asyncio.create_task(reader())
        await task

    assert seen == ["async-bot"]


@pytest.mark.asyncio
async def test_async_task_does_not_leak_changes_back() -> None:
    """Changes made inside a spawned task do NOT leak back to the parent."""
    async def inner() -> None:
        with agent_identity("inner-task-bot"):
            pass  # sets and immediately resets inside the task

    with agent_identity("parent-bot"):
        task = asyncio.create_task(inner())
        await task
        # parent context unchanged
        assert current_agent_name.get() == "parent-bot"
