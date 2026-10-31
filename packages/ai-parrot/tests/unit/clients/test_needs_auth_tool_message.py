"""FEAT-776 M2: _execute_tool returns a needs-auth instruction instead of None."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from parrot.clients.base import AbstractClient
from parrot.tools.abstract import ToolResult


class _FakeToolManager:
    """Minimal tool manager returning a canned result."""

    def __init__(self, result: ToolResult) -> None:
        self._result = result

    async def execute_tool(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        permission_context: Any = None,
    ) -> ToolResult:
        """Return the configured result without executing a real tool."""
        return self._result


def _client_stub(result: ToolResult) -> SimpleNamespace:
    """Build the minimal client shape read by ``_execute_tool``."""
    return SimpleNamespace(
        tool_manager=_FakeToolManager(result),
        logger=logging.getLogger("test.client.needs_auth"),
        _tool_context=None,
        _permission_context=None,
        _tool_param_names=lambda _name: None,
    )


@pytest.mark.asyncio
async def test_execute_tool_needs_auth_message() -> None:
    """Name the provider without exposing its single-use authorization URL."""
    result = ToolResult(
        success=False,
        status="authorization_required",
        result=None,
        metadata={"provider": "jira", "auth_url": "https://x/state"},
    )

    message = await AbstractClient._execute_tool(_client_stub(result), "jira_search", {})

    assert "jira" in message
    assert "https://" not in message

    fallback_result = ToolResult(success=False, status="authorization_required", result=None, metadata={})
    fallback_message = await AbstractClient._execute_tool(_client_stub(fallback_result), "jira_search", {})

    assert "the required service" in fallback_message


@pytest.mark.asyncio
async def test_execute_tool_other_statuses_unchanged() -> None:
    """Preserve successful values and the existing error exception path."""
    success = ToolResult(success=True, status="success", result={"issue": "PARROT-1"})

    assert await AbstractClient._execute_tool(_client_stub(success), "jira_search", {}) == {"issue": "PARROT-1"}

    error = ToolResult(success=False, status="error", result=None, error="tool failed")
    with pytest.raises(ValueError, match="tool failed"):
        await AbstractClient._execute_tool(_client_stub(error), "jira_search", {})
