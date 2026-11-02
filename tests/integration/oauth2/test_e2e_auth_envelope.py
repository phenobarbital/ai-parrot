"""End-to-end authorization-required serialization for both framework signals."""

from __future__ import annotations

from typing import Any

import pytest

from parrot.auth.credentials import CredentialRequired
from parrot.auth.exceptions import AuthorizationRequired
from parrot.auth.oauth2.models import AuthRequiredEnvelope
from parrot.tools import tool
from parrot.tools.manager import ToolManager


def _envelope_from_result(result: Any) -> AuthRequiredEnvelope:
    """Convert a ToolManager authorization result to the AgentTalk envelope."""
    return AuthRequiredEnvelope(**result.metadata)


@pytest.mark.asyncio
async def test_authorization_required_roundtrip_both_signals() -> None:
    """AuthorizationRequired and CredentialRequired expose equivalent metadata."""

    @tool
    async def authorization_tool() -> str:
        """Raise the toolkit authorization signal."""
        raise AuthorizationRequired(
            tool_name="authorization_tool",
            message="Jira authorization required.",
            provider="jira",
            auth_url="https://idp.example/authorize",
            scopes=["read:jira-work"],
        )

    @tool
    async def broker_tool() -> str:
        """Raise the broker credential signal."""
        raise CredentialRequired("jira", "https://idp.example/authorize", "oauth2")

    manager = ToolManager()
    manager.register_tool(authorization_tool)
    manager.register_tool(broker_tool)
    authorization_result = await manager.execute_tool("authorization_tool", {}, return_tool_result=True)
    credential_result = await manager.execute_tool("broker_tool", {}, return_tool_result=True)

    authorization_envelope = _envelope_from_result(authorization_result)
    credential_envelope = _envelope_from_result(credential_result)

    assert authorization_result.status == "authorization_required"
    assert credential_result.status == "authorization_required"
    assert authorization_envelope.type == credential_envelope.type == "auth_required"
    assert authorization_envelope.provider == credential_envelope.provider == "jira"
    assert authorization_envelope.auth_url == credential_envelope.auth_url
    assert authorization_envelope.scopes == ["read:jira-work"]
    assert credential_envelope.scopes == []
