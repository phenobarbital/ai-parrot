"""FEAT-775 M5: needs-auth collector."""
from __future__ import annotations

import asyncio

import pytest

from parrot.auth.credentials import AuthRequiredPayload, CredentialRequired
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.pending import collect_auth_requirements, record_auth_requirement
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager


def _payload(provider: str = "jira") -> AuthRequiredPayload:
    """Build a minimal needs-auth payload for collector assertions."""
    return AuthRequiredPayload(provider=provider, scopes=["read"])


class _AuthorizationRequiredTool(AbstractTool):
    """Tool that raises the legacy needs-auth exception."""

    name = "authorization_required_tool"
    description = "Raises AuthorizationRequired for testing."

    async def _execute(self, **kwargs: object) -> ToolResult:
        raise AuthorizationRequired(
            tool_name=self.name,
            message="Authorize Jira.",
            auth_url="https://auth.example.test/jira",
            provider="jira",
            scopes=["read:jira-work"],
        )


class _CredentialRequiredTool(AbstractTool):
    """Tool that raises the structured credential needs-auth exception."""

    name = "credential_required_tool"
    description = "Raises CredentialRequired for testing."

    async def _execute(self, **kwargs: object) -> ToolResult:
        raise CredentialRequired("o365", "https://auth.example.test/o365", "oauth2")


def test_collector_unbound_is_noop() -> None:
    """Unbound recording neither raises nor leaks into a later collector."""
    record_auth_requirement(_payload())

    with collect_auth_requirements() as collected:
        assert collected == []


@pytest.mark.asyncio
async def test_collector_sees_appends_from_child_tasks() -> None:
    """Child tasks append to the mutable collector from their copied context."""

    async def record(provider: str) -> None:
        record_auth_requirement(_payload(provider))

    with collect_auth_requirements() as collected:
        await asyncio.gather(record("jira"), record("o365"))
        assert [payload.provider for payload in collected] == ["jira", "o365"]

    with collect_auth_requirements() as collected:
        assert collected == []


@pytest.mark.asyncio
async def test_toolmanager_records_needs_auth() -> None:
    """ToolManager records each unified needs-auth exception exactly once."""
    manager = ToolManager(include_search_tool=False)
    manager.add_tool(_AuthorizationRequiredTool())
    manager.add_tool(_CredentialRequiredTool())

    with collect_auth_requirements() as collected:
        authorization_result = await manager.execute_tool("authorization_required_tool", {})
        credential_result = await manager.execute_tool("credential_required_tool", {})

        assert authorization_result.status == "authorization_required"
        assert credential_result.status == "authorization_required"
        assert [payload.provider for payload in collected] == ["jira", "o365"]
        assert [payload.tool_name for payload in collected] == [
            "authorization_required_tool",
            "credential_required_tool",
        ]
