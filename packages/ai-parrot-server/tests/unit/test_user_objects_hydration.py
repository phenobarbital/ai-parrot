"""Tests for connection-backed OAuth toolkit hydration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.handlers.user_objects import UserObjectsHandler


@pytest.mark.asyncio
async def test_hydration_from_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only active, registered connection providers hydrate toolkits."""
    rows = [
        SimpleNamespace(provider="jira", status="active"),
        SimpleNamespace(provider="o365", status="active"),
        SimpleNamespace(provider="revoked", status="revoked"),
    ]
    jira_provider = MagicMock()
    o365_provider = MagicMock()
    jira_toolkit = MagicMock()
    o365_toolkit = MagicMock()
    jira_provider.toolkit_factory.return_value = jira_toolkit
    o365_provider.toolkit_factory.return_value = o365_toolkit
    registry = MagicMock()
    registry.get.side_effect = {"jira": jira_provider, "o365": o365_provider}.get
    tool_manager = MagicMock()
    tool_manager.get_tool.return_value = None

    monkeypatch.setattr("parrot.handlers.user_objects.list_users_integrations", AsyncMock(return_value=rows))
    monkeypatch.setattr("parrot.handlers.user_objects.OAuth2ProviderRegistry", lambda: registry)
    monkeypatch.setattr("parrot.handlers.user_objects.ToolManager", lambda **kwargs: tool_manager)

    handler = UserObjectsHandler()
    result = await handler._hydrate_oauth_toolkits("user-1", "agent-1", "tool_manager", {})

    assert result is tool_manager
    assert registry.get.call_args_list == [(("jira",),), (("o365",),)]
    assert tool_manager.register_toolkit.call_args_list == [((jira_toolkit,),), ((o365_toolkit,),)]
    assert jira_provider.toolkit_factory.called
    assert o365_provider.toolkit_factory.called
