"""Unit tests for :mod:`parrot.tools.jira_connect_tool` (TASK-755, FEAT-107)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.tools.abstract import ToolResult
from parrot.tools.jira_connect_tool import (
    JiraConnectTool,
    hotswap_to_full_toolkit,
    setup_jira_oauth_session,
)
from parrot.tools.manager import ToolManager


class TestJiraConnectTool:
    @pytest.mark.asyncio
    async def test_returns_auth_url(self) -> None:
        resolver = MagicMock()
        resolver.get_auth_url = AsyncMock(
            return_value="https://auth.atlassian.com/authorize?state=abc",
        )
        tool = JiraConnectTool(
            credential_resolver=resolver, channel="agentalk", user_id="u1",
        )

        result = await tool._execute()

        assert isinstance(result, ToolResult)
        assert result.status == "authorization_required"
        assert "auth.atlassian.com" in result.result
        assert result.metadata["auth_url"].startswith("https://auth.atlassian.com")
        assert result.metadata["provider"] == "jira"
        assert result.metadata["channel"] == "agentalk"
        resolver.get_auth_url.assert_awaited_once_with("agentalk", "u1")

    @pytest.mark.asyncio
    async def test_reason_is_prefixed(self) -> None:
        resolver = MagicMock()
        resolver.get_auth_url = AsyncMock(return_value="https://auth.url")
        tool = JiraConnectTool(resolver, "agentalk", "u1")

        result = await tool._execute(reason="You asked about Jira tickets")

        assert "You asked about Jira tickets" in result.result

    def test_tool_name_and_description(self) -> None:
        resolver = MagicMock()
        tool = JiraConnectTool(resolver, "agentalk", "u1")
        assert tool.name == "connect_jira"
        assert "Jira" in tool.description


class TestSetupJiraOAuthSession:
    @pytest.mark.asyncio
    async def test_registers_placeholder_when_no_tokens(self) -> None:
        resolver = MagicMock()
        resolver.is_connected = AsyncMock(return_value=False)
        resolver.get_auth_url = AsyncMock(return_value="https://auth.url")
        manager = ToolManager()

        await setup_jira_oauth_session(
            manager, resolver, channel="agentalk", user_id="u1",
        )

        assert "connect_jira" in manager._tools
        assert isinstance(manager._tools["connect_jira"], JiraConnectTool)

    @pytest.mark.asyncio
    async def test_registers_full_toolkit_when_tokens_present(self) -> None:
        resolver = MagicMock()
        resolver.is_connected = AsyncMock(return_value=True)

        manager = ToolManager()
        manager.register_toolkit = MagicMock()
        toolkit = MagicMock()

        build = AsyncMock(return_value=toolkit)
        await setup_jira_oauth_session(
            manager,
            resolver,
            channel="agentalk",
            user_id="u1",
            build_full_toolkit=build,
        )

        build.assert_awaited_once()
        manager.register_toolkit.assert_called_once_with(toolkit)

    @pytest.mark.asyncio
    async def test_falls_back_to_placeholder_when_no_builder(self) -> None:
        resolver = MagicMock()
        resolver.is_connected = AsyncMock(return_value=True)
        resolver.get_auth_url = AsyncMock(return_value="https://auth.url")
        manager = ToolManager()

        await setup_jira_oauth_session(
            manager, resolver, channel="agentalk", user_id="u1",
        )

        assert "connect_jira" in manager._tools


class TestHotSwap:
    @pytest.mark.asyncio
    async def test_removes_placeholder_and_registers_toolkit(self) -> None:
        resolver = MagicMock()
        resolver.get_auth_url = AsyncMock(return_value="https://auth.url")
        manager = ToolManager()
        manager.add_tool(
            JiraConnectTool(resolver, "agentalk", "u1")
        )
        assert "connect_jira" in manager._tools

        manager.register_toolkit = MagicMock(return_value=["full_tool_a"])
        toolkit = MagicMock()

        result = await hotswap_to_full_toolkit(
            manager, AsyncMock(return_value=toolkit),
        )

        assert "connect_jira" not in manager._tools
        manager.register_toolkit.assert_called_once_with(toolkit)
        assert result == ["full_tool_a"]

    @pytest.mark.asyncio
    async def test_no_placeholder_still_registers_toolkit(self) -> None:
        manager = ToolManager()
        manager.register_toolkit = MagicMock(return_value=[])
        toolkit = MagicMock()

        await hotswap_to_full_toolkit(
            manager, AsyncMock(return_value=toolkit),
        )

        manager.register_toolkit.assert_called_once_with(toolkit)

    @pytest.mark.asyncio
    async def test_sync_tools_to_llm_called_when_available(self) -> None:
        manager = ToolManager()
        manager.register_toolkit = MagicMock(return_value=[])
        bot = MagicMock()
        bot._sync_tools_to_llm = MagicMock()
        toolkit = MagicMock()

        await hotswap_to_full_toolkit(
            manager, AsyncMock(return_value=toolkit), bot=bot,
        )

        bot._sync_tools_to_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_tools_to_llm_missing_is_ok(self) -> None:
        manager = ToolManager()
        manager.register_toolkit = MagicMock(return_value=[])
        bot = MagicMock(spec=[])  # no _sync_tools_to_llm attribute
        toolkit = MagicMock()

        # Must not raise — hot-swap is best-effort.
        await hotswap_to_full_toolkit(
            manager, AsyncMock(return_value=toolkit), bot=bot,
        )

    @pytest.mark.asyncio
    async def test_sync_tools_to_llm_awaitable_is_awaited(self) -> None:
        manager = ToolManager()
        manager.register_toolkit = MagicMock(return_value=[])
        bot = MagicMock()
        sync_mock = AsyncMock()
        bot._sync_tools_to_llm = sync_mock

        await hotswap_to_full_toolkit(
            manager, AsyncMock(return_value=MagicMock()), bot=bot,
        )

        sync_mock.assert_awaited_once()
