"""Tests for AgentCrew lifecycle hooks (FEAT-157 TASK-1065).

Verifies hook registration, status-based dispatch, sync/async callback
support, error isolation, ordering, and the no-hooks noop case.

Uses the canonical AgentCrew from ``parrot.bots.flows.crew`` and
``FlowResult`` / ``FlowStatus`` from ``parrot.bots.flows.core.result``.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

from parrot.bots.flows.crew import AgentCrew
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def crew():
    """Minimal AgentCrew for hook testing (no agents, no LLM)."""
    return AgentCrew(name="test-crew")


@pytest.fixture
def completed_result():
    """FlowResult with status='completed'."""
    return FlowResult(output="done", status=FlowStatus.COMPLETED)


@pytest.fixture
def failed_result():
    """FlowResult with status='failed'."""
    return FlowResult(
        output=None,
        status=FlowStatus.FAILED,
        errors={"agent1": "boom"},
    )


@pytest.fixture
def partial_result():
    """FlowResult with status='partial'."""
    return FlowResult(
        output="partial output",
        status=FlowStatus.PARTIAL,
        errors={"agent2": "failed"},
    )


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------


class TestHookRegistration:
    def test_on_complete_registration(self, crew):
        """Registering a callback adds it to _on_complete_hooks."""
        hook = MagicMock()
        crew.on_complete(hook)
        assert hook in crew._on_complete_hooks

    def test_on_error_registration(self, crew):
        """Registering a callback adds it to _on_error_hooks."""
        hook = MagicMock()
        crew.on_error(hook)
        assert hook in crew._on_error_hooks

    def test_multiple_on_complete_hooks_registered_in_order(self, crew):
        """Multiple on_complete hooks are stored in registration order."""
        h1, h2, h3 = MagicMock(), MagicMock(), MagicMock()
        crew.on_complete(h1)
        crew.on_complete(h2)
        crew.on_complete(h3)
        assert crew._on_complete_hooks == [h1, h2, h3]

    def test_multiple_on_error_hooks_registered_in_order(self, crew):
        """Multiple on_error hooks are stored in registration order."""
        h1, h2 = MagicMock(), MagicMock()
        crew.on_error(h1)
        crew.on_error(h2)
        assert crew._on_error_hooks == [h1, h2]

    def test_initial_hook_lists_are_empty(self, crew):
        """A freshly created AgentCrew has empty hook lists."""
        assert crew._on_complete_hooks == []
        assert crew._on_error_hooks == []


# ---------------------------------------------------------------------------
# Status-based dispatch
# ---------------------------------------------------------------------------


class TestFireHooksDispatch:
    async def test_completed_fires_on_complete_only(
        self, crew, completed_result
    ):
        """completed status → on_complete hooks fire; on_error does not."""
        on_complete = MagicMock()
        on_error = MagicMock()
        crew.on_complete(on_complete)
        crew.on_error(on_error)
        await crew._fire_hooks(completed_result)
        on_complete.assert_called_once_with("test-crew", completed_result)
        on_error.assert_not_called()

    async def test_failed_fires_on_error_only(self, crew, failed_result):
        """failed status → on_error hooks fire; on_complete does not."""
        on_complete = MagicMock()
        on_error = MagicMock()
        crew.on_complete(on_complete)
        crew.on_error(on_error)
        await crew._fire_hooks(failed_result)
        on_complete.assert_not_called()
        on_error.assert_called_once_with("test-crew", failed_result)

    async def test_partial_fires_both(self, crew, partial_result):
        """partial status → both on_complete AND on_error hooks fire."""
        on_complete = MagicMock()
        on_error = MagicMock()
        crew.on_complete(on_complete)
        crew.on_error(on_error)
        await crew._fire_hooks(partial_result)
        on_complete.assert_called_once_with("test-crew", partial_result)
        on_error.assert_called_once_with("test-crew", partial_result)

    async def test_no_hooks_is_noop(self, crew, completed_result):
        """_fire_hooks with no registered hooks does not raise."""
        # Should not raise
        await crew._fire_hooks(completed_result)


# ---------------------------------------------------------------------------
# Callback receives correct arguments
# ---------------------------------------------------------------------------


class TestHookArguments:
    async def test_hook_receives_crew_name_and_result(
        self, crew, completed_result
    ):
        """Callback receives (crew_name: str, result: FlowResult)."""
        received = {}

        def capture_hook(name, result):
            received["name"] = name
            received["result"] = result

        crew.on_complete(capture_hook)
        await crew._fire_hooks(completed_result)
        assert received["name"] == "test-crew"
        assert received["result"] is completed_result


# ---------------------------------------------------------------------------
# Sync and async callback support
# ---------------------------------------------------------------------------


class TestHookCallbackTypes:
    async def test_sync_hook_supported(self, crew, completed_result):
        """A synchronous callback is called without errors."""
        called_with = {}

        def sync_hook(name, result):
            called_with["name"] = name
            called_with["result"] = result

        crew.on_complete(sync_hook)
        await crew._fire_hooks(completed_result)
        assert called_with["name"] == "test-crew"
        assert called_with["result"] is completed_result

    async def test_async_hook_supported(self, crew, completed_result):
        """An async callback is properly awaited."""
        called_with = {}

        async def async_hook(name, result):
            called_with["name"] = name
            called_with["result"] = result

        crew.on_complete(async_hook)
        await crew._fire_hooks(completed_result)
        assert called_with["name"] == "test-crew"
        assert called_with["result"] is completed_result

    async def test_async_mock_hook_supported(self, crew, completed_result):
        """AsyncMock callback is properly awaited."""
        hook = AsyncMock()
        crew.on_complete(hook)
        await crew._fire_hooks(completed_result)
        hook.assert_awaited_once_with("test-crew", completed_result)


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------


class TestHookErrorIsolation:
    async def test_sync_exception_does_not_block_subsequent_hooks(
        self, crew, completed_result
    ):
        """A raising sync hook does not prevent subsequent hooks from firing."""
        calls = []

        def bad_hook(name, result):
            raise RuntimeError("hook exploded")

        def good_hook(name, result):
            calls.append("good")

        crew.on_complete(bad_hook)
        crew.on_complete(good_hook)
        await crew._fire_hooks(completed_result)
        assert calls == ["good"]

    async def test_async_exception_does_not_block_subsequent_hooks(
        self, crew, completed_result
    ):
        """A raising async hook does not prevent subsequent hooks from firing."""
        calls = []

        async def bad_hook(name, result):
            raise RuntimeError("async hook exploded")

        async def good_hook(name, result):
            calls.append("good")

        crew.on_complete(bad_hook)
        crew.on_complete(good_hook)
        await crew._fire_hooks(completed_result)
        assert calls == ["good"]

    async def test_exception_in_hook_does_not_raise_to_caller(
        self, crew, completed_result
    ):
        """Hook exceptions are swallowed — _fire_hooks itself does not raise."""

        def exploding_hook(name, result):
            raise ValueError("kaboom")

        crew.on_complete(exploding_hook)
        # Must not raise
        await crew._fire_hooks(completed_result)


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------


class TestHookOrdering:
    async def test_on_complete_hooks_fire_in_registration_order(
        self, crew, completed_result
    ):
        """on_complete hooks fire in the order they were registered."""
        order = []
        crew.on_complete(lambda n, r: order.append("first"))
        crew.on_complete(lambda n, r: order.append("second"))
        crew.on_complete(lambda n, r: order.append("third"))
        await crew._fire_hooks(completed_result)
        assert order == ["first", "second", "third"]

    async def test_partial_fires_complete_before_error_hooks(
        self, crew, partial_result
    ):
        """For partial status, on_complete hooks fire before on_error hooks."""
        order = []
        crew.on_complete(lambda n, r: order.append("complete"))
        crew.on_error(lambda n, r: order.append("error"))
        await crew._fire_hooks(partial_result)
        assert order == ["complete", "error"]
