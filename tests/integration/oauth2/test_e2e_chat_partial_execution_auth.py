"""Mutation before auth never replays (FEAT-777 AC-7)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from parrot.auth.broker import CredentialBroker
from parrot.auth.credentials import CredentialResolver
from parrot.auth.oauth2.models import AuthRequiredEnvelope
from parrot.auth.pending import collect_auth_requirements
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.retry_safety import track_turn
from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.manager import ToolManager

pytestmark = pytest.mark.asyncio


class _MutationTool(AbstractTool):
    """Tool whose side effect must not be replayed after a later auth failure."""

    name = "mutation_tool"
    description = "Performs one observable mutation."
    executions = 0

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Increment the observable mutation counter exactly once per invocation."""
        del kwargs
        type(self).executions += 1
        return ToolResult(status="success", result="mutated", metadata={})


class _AuthTool(AbstractTool):
    """Tool gated by a missing credential so it returns authorization_required."""

    name = "auth_tool"
    description = "Needs a provider token."
    credential_provider = "jira"

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Never run because the credential gate stops the tool first."""
        del kwargs
        raise AssertionError("auth_tool body should not run")


class _MissingCredentialResolver(CredentialResolver):
    """Credential resolver that always requires authorization."""

    async def resolve(self, channel: str, user_id: str) -> None:
        """Return no credential for the current principal."""
        del channel, user_id
        return None

    async def get_auth_url(self, channel: str, user_id: str) -> str:
        """Return the provider authorization URL used in the envelope."""
        del channel, user_id
        return "https://app.example.com/connect/jira"


def _broker() -> CredentialBroker:
    """Build the real broker seam with a resolver that has no token."""
    broker = CredentialBroker()
    broker.register("jira", _MissingCredentialResolver())
    return broker


def _permission_context() -> PermissionContext:
    """Build a chat permission context for the test principal."""
    return PermissionContext(
        session=UserSession(user_id="1042", tenant_id="tenant", roles=frozenset()),
        channel="web",
    )


@pytest.mark.parametrize("mode", ["non_streaming", "streaming"])
async def test_e2e_chat_partial_execution_auth(mode: str) -> None:
    """A completed mutation makes the auth response unsafe in both transport modes."""
    manager = ToolManager()
    manager.add_tool(_MutationTool())
    manager.add_tool(_AuthTool())
    manager.set_broker(_broker())
    _MutationTool.executions = 0

    with track_turn() as tracker, collect_auth_requirements() as pending:
        mutation = await manager.execute_tool("mutation_tool", {}, permission_context=_permission_context())
        auth_result = await manager.execute_tool(
            "auth_tool", {}, permission_context=_permission_context(), return_tool_result=True
        )

    assert mutation == "mutated"
    assert auth_result.status == "authorization_required"
    assert _MutationTool.executions == 1
    assert len(pending) == 1
    assert tracker.bodies_started == 1
    assert tracker.retry_safe(auth_requirements=len(pending), reported_tool_calls=2) is False

    envelope = AuthRequiredEnvelope(
        provider=pending[0].provider,
        tool_name=pending[0].tool_name,
        auth_url=pending[0].auth_url,
        scopes=[],
        message=pending[0].message,
        retry_safe=False,
    )
    if mode == "non_streaming":
        response = envelope
        assert response.retry_safe is False
    else:
        trailer = "\n\x00" + json.dumps(
            {"auth_required": envelope.model_dump(mode="json"), "retry_safe": envelope.retry_safe}
        )
        decoded = json.loads(trailer.removeprefix("\n\x00"))
        assert decoded["auth_required"]["type"] == "auth_required"
        assert decoded["retry_safe"] is False

    # A connection.completed notification must not resend an unsafe originating turn.
    if envelope.retry_safe:
        await manager.execute_tool("mutation_tool", {}, permission_context=_permission_context())
    assert _MutationTool.executions == 1
