"""Unit tests for :class:`AuthorizationRequired` and its handling by
:class:`parrot.tools.manager.ToolManager` (TASK-748, FEAT-107).

Covers:
    - Exception attributes, defaults, and catchability.
    - ``ToolManager.execute_tool`` converts the exception into a
      :class:`ToolResult` with ``status='authorization_required'`` and the
      ``auth_url`` / ``provider`` / ``scopes`` / ``tool_name`` metadata.
    - Generic exceptions still propagate (no regression).
"""
from __future__ import annotations

import pytest

from parrot.auth.exceptions import AuthorizationRequired
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


class _RaisingTool(AbstractTool):
    """AbstractTool subclass that raises :class:`AuthorizationRequired`."""

    name = "jira_create_issue"
    description = "Raises AuthorizationRequired for testing."

    def __init__(self) -> None:
        super().__init__(name=self.name, description=self.description)

    async def _execute(self, **kwargs):  # noqa: D401 - test helper
        raise AuthorizationRequired(
            tool_name=self.name,
            message="Jira authorization required",
            auth_url="https://auth.atlassian.com/authorize?foo=bar",
            provider="jira",
            scopes=["read:jira-work", "write:jira-work"],
        )


class _BoomTool(AbstractTool):
    name = "boom"
    description = "Raises a plain RuntimeError."

    def __init__(self) -> None:
        super().__init__(name=self.name, description=self.description)

    async def _execute(self, **kwargs):
        raise RuntimeError("boom")


class TestAuthorizationRequired:
    def test_exception_attributes(self) -> None:
        exc = AuthorizationRequired(
            tool_name="jira_create_issue",
            message="Jira authorization required",
            auth_url="https://auth.atlassian.com/authorize?foo=bar",
            provider="jira",
            scopes=["read:jira-work", "write:jira-work"],
        )
        assert exc.tool_name == "jira_create_issue"
        assert exc.message == "Jira authorization required"
        assert exc.auth_url.startswith("https://")
        assert exc.provider == "jira"
        assert "read:jira-work" in exc.scopes

    def test_exception_defaults(self) -> None:
        exc = AuthorizationRequired(
            tool_name="some_tool",
            message="Auth needed",
        )
        assert exc.provider == "unknown"
        assert exc.scopes == []
        assert exc.auth_url is None

    def test_exception_is_catchable(self) -> None:
        with pytest.raises(AuthorizationRequired):
            raise AuthorizationRequired(
                tool_name="test", message="test"
            )


class TestToolManagerAuthRequired:
    @pytest.mark.asyncio
    async def test_auth_required_to_tool_result(self) -> None:
        manager = ToolManager()
        manager.add_tool(_RaisingTool())

        result = await manager.execute_tool("jira_create_issue", {})

        assert isinstance(result, ToolResult)
        assert result.status == "authorization_required"
        assert result.success is False

    @pytest.mark.asyncio
    async def test_auth_required_preserves_metadata(self) -> None:
        manager = ToolManager()
        manager.add_tool(_RaisingTool())

        result = await manager.execute_tool("jira_create_issue", {})

        meta = result.metadata
        assert meta["auth_url"] == "https://auth.atlassian.com/authorize?foo=bar"
        assert meta["provider"] == "jira"
        assert meta["tool_name"] == "jira_create_issue"
        assert meta["scopes"] == ["read:jira-work", "write:jira-work"]

    @pytest.mark.asyncio
    async def test_generic_exceptions_still_propagate(self) -> None:
        """Generic exceptions are wrapped into ToolResult(status='error') by
        ``AbstractTool.execute`` and then re-raised by ``ToolManager`` as
        ``ValueError`` — they do NOT produce an ``authorization_required``
        result.
        """
        manager = ToolManager()
        manager.add_tool(_BoomTool())

        with pytest.raises(ValueError, match="boom"):
            await manager.execute_tool("boom", {})
