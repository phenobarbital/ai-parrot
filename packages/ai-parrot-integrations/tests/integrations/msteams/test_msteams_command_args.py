"""FEAT-775 M2: router command arguments."""

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msteams.commands import MSTeamsCommandRouter, command_args


def _turn():
    """Build a minimal turn context with mutable turn state."""
    tc = MagicMock()
    tc.turn_state = {}
    tc.send_activity = AsyncMock()
    return tc


@pytest.mark.asyncio
async def test_router_stashes_args_text_and_card():
    """Store the same trimmed arguments for typed and card-routed commands."""
    router = MSTeamsCommandRouter()
    captured = []

    async def handler(turn_context):
        captured.append(command_args(turn_context))

    router.register("connect", handler)
    turn_context = _turn()

    assert await router.try_dispatch("/connect jira", turn_context) is True
    assert await router.try_dispatch("/connect   jira  ", turn_context) is True
    assert await router.try_dispatch("/connect", turn_context) is True

    assert captured == ["jira", "jira", ""]
    assert list(inspect.signature(handler).parameters) == ["turn_context"]


@pytest.mark.asyncio
async def test_plain_dispatch_clears_args():
    """Plain-text dispatch clears stale command arguments."""
    router = MSTeamsCommandRouter()
    router.register("integrations", AsyncMock())
    turn_context = _turn()
    turn_context.turn_state["msteams.command_args"] = "stale"

    assert await router.try_dispatch_plain("integrations", turn_context) is True
    assert command_args(turn_context) == ""


def test_command_args_without_turn_state():
    """Return an empty string when a turn context has no turn state."""
    assert command_args(object()) == ""
