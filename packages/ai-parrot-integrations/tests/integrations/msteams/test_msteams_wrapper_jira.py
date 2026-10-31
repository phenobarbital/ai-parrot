"""Unit tests for the Teams wrapper's generic connection command wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import web

from parrot.integrations.msteams.connections import CONNECTION_NOTIFIER_KEY
from parrot.integrations.msteams.models import MSTeamsAgentConfig
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

def test_connection_service_factory_is_constructor_parameter() -> None:
    """The wrapper exposes an injectable factory after the legacy manager argument."""
    import inspect

    from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper

    parameters = list(inspect.signature(MSTeamsAgentWrapper.__init__).parameters)
    assert parameters.index("connection_service_factory") == parameters.index("oauth_manager") + 1


def test_default_connection_service_has_no_evaluator() -> None:
    """The fallback service preserves the task's fail-closed evaluator default."""
    from parrot.integrations.msteams.wrapper import _default_connection_service

    service = _default_connection_service()

    assert service._permission_evaluator is None


@pytest.mark.asyncio
async def test_wrapper_attaches_each_bot() -> None:
    """Two wrappers share one notifier while retaining their own proactive adapters."""
    app = web.Application()
    agent = MagicMock()
    agent.ask = AsyncMock()
    agent.tool_manager.list_tools.return_value = []
    first = MSTeamsAgentWrapper(
        agent,
        MSTeamsAgentConfig(name="first", chatbot_id="first", client_id="app-1", client_secret="secret"),
        app,
    )
    second = MSTeamsAgentWrapper(
        agent,
        MSTeamsAgentConfig(name="second", chatbot_id="second", client_id="app-2", client_secret="secret"),
        app,
    )

    notifier = app[CONNECTION_NOTIFIER_KEY]
    assert notifier._adapters == {"app-1": first.adapter, "app-2": second.adapter}
