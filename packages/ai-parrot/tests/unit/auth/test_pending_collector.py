"""Tests for parrot.auth.pending (FEAT-776 M1)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


class _AuthorizationRequiredTool(AbstractTool):
    """Test tool that requires OAuth authorization."""

    name = "jira_create_issue"
    description = "Raises AuthorizationRequired for testing."

    def __init__(self) -> None:
        """Initialize the test tool."""
        super().__init__(name=self.name, description=self.description)

    async def _execute(self, **kwargs: Any) -> Any:
        """Raise the authorization signal consumed by ToolManager."""
        raise AuthorizationRequired(
            tool_name=self.name,
            message="Jira authorization required",
            auth_url="https://auth.atlassian.com/authorize?foo=bar",
            provider="jira",
            scopes=["read:jira-work"],
        )


class _CredentialRequiredTool(AbstractTool):
    """Test tool that requires a broker credential."""

    name = "github_create_issue"
    description = "Raises CredentialRequired for testing."

    def __init__(self) -> None:
        """Initialize the test tool."""
        super().__init__(name=self.name, description=self.description)

    async def _execute(self, **kwargs: Any) -> Any:
        """Raise the credential signal consumed by ToolManager."""
        raise CredentialRequired(
            provider="github",
            auth_url="https://github.com/login/oauth/authorize",
            auth_kind="oauth2",
        )


def test_collector_unbound_is_noop() -> None:
    """An unbound collector silently ignores needs-auth payloads."""
    record_auth_requirement(AuthRequiredPayload(provider="jira"))

    with collect_auth_requirements() as pending:
        assert pending == []


@pytest.mark.asyncio
async def test_collector_sees_appends_from_child_tasks() -> None:
    """Child tasks append to the parent collector and exceptions reset it."""

    async def record(provider: str) -> None:
        record_auth_requirement(AuthRequiredPayload(provider=provider))

    with collect_auth_requirements() as pending:
        await asyncio.gather(record("jira"), record("github"))
        assert [payload.provider for payload in pending] == ["jira", "github"]

    with pytest.raises(RuntimeError, match="collector reset"):
        with collect_auth_requirements() as pending:
            record_auth_requirement(AuthRequiredPayload(provider="slack"))
            assert [payload.provider for payload in pending] == ["slack"]
            raise RuntimeError("collector reset")

    with collect_auth_requirements() as pending:
        assert pending == []


@pytest.mark.asyncio
async def test_toolmanager_records_needs_auth() -> None:
    """ToolManager records both needs-auth exception payloads while bound."""
    manager = ToolManager()
    manager.add_tool(_AuthorizationRequiredTool())
    manager.add_tool(_CredentialRequiredTool())

    with collect_auth_requirements() as pending:
        authorization_result = await manager.execute_tool("jira_create_issue", {})
        credential_result = await manager.execute_tool("github_create_issue", {})

    assert isinstance(authorization_result, ToolResult)
    assert authorization_result.status == "authorization_required"
    assert isinstance(credential_result, ToolResult)
    assert credential_result.status == "authorization_required"
    assert [payload.provider for payload in pending] == ["jira", "github"]
