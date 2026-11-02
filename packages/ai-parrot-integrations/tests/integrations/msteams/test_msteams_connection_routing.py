"""FEAT-775 M3 generic command-routing tests (AC-4)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _context() -> MagicMock:
    """Build a minimal turn context accepted by the command router."""
    context = MagicMock()
    context.turn_state = {}
    context.send_activity = AsyncMock()
    return context


def _router_and_connector():
    """Create a real router registered against an async connector double."""
    from parrot.integrations.msteams.commands import MSTeamsCommandRouter
    from parrot.integrations.msteams.commands.connect_commands import register_connection_commands

    connector = MagicMock()
    connector.connect = AsyncMock()
    connector.disconnect = AsyncMock()
    connector.status = AsyncMock()
    connector.pick_provider = AsyncMock()
    router = MSTeamsCommandRouter()
    register_connection_commands(router, connector=connector)
    return router, connector


@pytest.mark.asyncio
async def test_connect_with_and_without_provider() -> None:
    """Connect routes a normalized provider or displays the provider picker."""
    router, connector = _router_and_connector()
    context = _context()

    assert await router.try_dispatch("/connect Jira", context)
    connector.connect.assert_awaited_once_with(context, "jira")
    assert await router.try_dispatch("/connect", context)
    connector.pick_provider.assert_awaited_once_with(context)


@pytest.mark.asyncio
async def test_card_submit_equals_typed() -> None:
    """The card command payload follows the same router path as typed text."""
    router, connector = _router_and_connector()
    typed_context = _context()
    card_context = _context()

    assert await router.try_dispatch("/connect jira", typed_context)
    assert await router.try_dispatch("/connect jira", card_context)
    assert connector.connect.await_args_list == [
        ((typed_context, "jira"), {}),
        ((card_context, "jira"), {}),
    ]


@pytest.mark.asyncio
async def test_disconnect_requires_provider() -> None:
    """Disconnect without an argument responds with usage and makes no service call."""
    router, connector = _router_and_connector()
    context = _context()

    assert await router.try_dispatch("/disconnect", context)
    context.send_activity.assert_awaited_once_with("Usage: `/disconnect <provider>`")
    connector.disconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connections_plain_and_slash() -> None:
    """Connections serves slash and plain triggers, with an optional provider."""
    router, connector = _router_and_connector()
    slash_context = _context()
    plain_context = _context()
    provider_context = _context()

    assert await router.try_dispatch("/connections", slash_context)
    assert await router.try_dispatch_plain("connections", plain_context)
    assert await router.try_dispatch("/connections jira", provider_context)
    assert connector.status.await_args_list == [
        ((slash_context, None), {}),
        ((plain_context, None), {}),
        ((provider_context, "jira"), {}),
    ]
