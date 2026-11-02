"""Regression tests for the retained Teams Jira command aliases."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _context() -> MagicMock:
    """Build a command-router-compatible turn context."""
    context = MagicMock()
    context.turn_state = {}
    context.send_activity = AsyncMock()
    return context


@pytest.mark.asyncio
async def test_jira_aliases_map_to_generic() -> None:
    """Each legacy Jira alias delegates to the generic connector operation."""
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter
    from parrot.integrations.msteams.commands.jira_commands import register_jira_commands

    connector = MagicMock()
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.status = AsyncMock()
    router = MSTeamsCommandRouter()
    register_jira_commands(router, connector)
    context = _context()

    assert await router.try_dispatch("/connect_jira", context)
    connector.connect.assert_awaited_once_with(context, "jira")
    assert await router.try_dispatch("/disconnect_jira", context)
    connector.disconnect.assert_awaited_once_with(context, "jira")
    assert await router.try_dispatch("/jira_status", context)
    connector.status.assert_awaited_once_with(context, "jira")
    assert await router.try_dispatch_plain("jira", context)
    assert await router.try_dispatch_plain("integrations", context)
    assert connector.status.await_args_list[-2:] == [((context,), {}), ((context,), {})]


def test_msteams_channel_constant() -> None:
    """The compatibility channel constant remains available to callers."""
    from parrot.integrations.msteams.commands.jira_commands import _MSTEAMS_CHANNEL

    assert _MSTEAMS_CHANNEL == "msteams"
