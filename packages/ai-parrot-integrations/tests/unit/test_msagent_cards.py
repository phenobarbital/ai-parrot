"""Unit tests for TASK-1673: MSAgentSDK card rendering by auth_kind.

Tests:
- static_key miss → Adaptive Card emitted (application/vnd.microsoft.card.adaptive)
- oauth2 miss → OAuthCard emitted (application/vnd.microsoft.card.oauth)
- obo miss → OAuthCard emitted (same as oauth2)
- No dead _resolver_var in auth.py
- No local CredentialRequired in auth.py (unified on canonical)
- broker + identity_mapper wired into ParrotM365Agent
"""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers to avoid the Cython chain triggered by parrot.utils.helpers
# ---------------------------------------------------------------------------

def _make_parrot_utils_stub() -> ModuleType:
    """Return a minimal stub for parrot.utils.helpers that avoids Cython."""
    stub = ModuleType("parrot.utils.helpers")
    stub.RequestContext = MagicMock(return_value=MagicMock())
    return stub


def _make_parrot_utils_types_stub() -> ModuleType:
    stub = ModuleType("parrot.utils.types")
    stub.SafeDict = dict
    return stub


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeTurnContext:
    """Minimal TurnContext double — captures send_activity calls."""

    def __init__(self, text: str = "hello", user_id: str = "user-123") -> None:
        self.activity = MagicMock()
        self.activity.text = text
        self.activity.conversation = MagicMock()
        self.activity.conversation.id = "session-001"
        from_prop = MagicMock()
        from_prop.aad_object_id = user_id
        from_prop.aadObjectId = None
        from_prop.id = user_id
        from_prop.email = None
        from_prop.name = "Test User"
        self.activity.from_property = from_prop

        self._sent: list[Any] = []

    async def send_activity(self, activity: Any) -> None:
        self._sent.append(activity)

    @property
    def sent(self) -> list[Any]:
        return self._sent


def _make_agent(broker=None, identity_mapper=None):
    """Build a ParrotM365Agent with a fake parrot_agent."""
    from parrot.integrations.msagentsdk.agent import ParrotM365Agent

    parrot_agent = MagicMock()
    parrot_agent.ask = AsyncMock()
    return ParrotM365Agent(
        parrot_agent=parrot_agent,
        broker=broker,
        identity_mapper=identity_mapper,
    )


# ---------------------------------------------------------------------------
# Card rendering — _emit_adaptive_card (tested directly — no Cython chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_adaptive_card_content():
    """_emit_adaptive_card sends an Adaptive Card attachment."""
    agent = _make_agent()
    capture_url = "https://app.example.com/auth/fireflies/capture"

    sent_activities: list[Any] = []
    ctx = FakeTurnContext()
    ctx.send_activity = AsyncMock(side_effect=lambda a: sent_activities.append(a))

    await agent._emit_adaptive_card(ctx, capture_url, "fireflies")

    assert len(sent_activities) == 1
    activity = sent_activities[0]
    attachments = getattr(activity, "attachments", []) or []
    assert len(attachments) == 1
    att = attachments[0]
    # SDK converts dict to Attachment Pydantic model — access via attribute.
    content_type = getattr(att, "content_type", None) or (att.get("contentType") if isinstance(att, dict) else None)
    assert content_type == "application/vnd.microsoft.card.adaptive"
    card_body = getattr(att, "content", None) or (att.get("content") if isinstance(att, dict) else None)
    assert card_body["type"] == "AdaptiveCard"
    # Action URL must be the capture URL
    assert card_body["actions"][0]["url"] == capture_url


@pytest.mark.asyncio
async def test_emit_adaptive_card_url_in_fallback_text():
    """_emit_adaptive_card includes capture URL in the plaintext fallback."""
    agent = _make_agent()
    capture_url = "https://app.example.com/auth/fireflies/capture"
    sent_activities: list[Any] = []
    ctx = FakeTurnContext()
    ctx.send_activity = AsyncMock(side_effect=lambda a: sent_activities.append(a))

    await agent._emit_adaptive_card(ctx, capture_url, "fireflies")

    activity = sent_activities[0]
    text = getattr(activity, "text", "") or ""
    assert capture_url in text


# ---------------------------------------------------------------------------
# Card rendering — _emit_oauth_card (tested directly — no Cython chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_oauth_card_content():
    """_emit_oauth_card sends an OAuthCard attachment."""
    agent = _make_agent()
    sent_activities: list[Any] = []
    ctx = FakeTurnContext()
    ctx.send_activity = AsyncMock(side_effect=lambda a: sent_activities.append(a))

    await agent._emit_oauth_card(ctx, "graph_sso", "o365")

    assert len(sent_activities) == 1
    activity = sent_activities[0]
    attachments = getattr(activity, "attachments", []) or []
    assert len(attachments) == 1
    att = attachments[0]
    content_type = getattr(att, "content_type", None) or (att.get("contentType") if isinstance(att, dict) else None)
    assert content_type == "application/vnd.microsoft.card.oauth"
    card_content = getattr(att, "content", None) or (att.get("content") if isinstance(att, dict) else None)
    assert card_content["connectionName"] == "graph_sso"


# ---------------------------------------------------------------------------
# Card routing — _handle_message dispatch (patched to avoid Cython chain)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_static_key_miss_routes_to_adaptive_card():
    """CredentialRequired(auth_kind='static_key') → _emit_adaptive_card called."""
    from parrot.auth.credentials import CredentialRequired

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    # Inject stubs so parrot.utils.helpers doesn't trigger Cython
    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        agent = _make_agent()
        capture_url = "https://example.com/auth/ff/capture"
        agent.parrot_agent.ask.side_effect = CredentialRequired(
            provider="fireflies",
            auth_url=capture_url,
            auth_kind="static_key",
        )
        ctx = FakeTurnContext(text="find my meetings")

        with patch.object(agent, "_emit_adaptive_card", new_callable=AsyncMock) as mock_emit:
            await agent._handle_message(ctx)

        mock_emit.assert_awaited_once()
        # capture_url is the second positional arg
        assert mock_emit.call_args[0][1] == capture_url


@pytest.mark.asyncio
async def test_oauth2_miss_routes_to_oauth_card():
    """CredentialRequired(auth_kind='oauth2') → _emit_oauth_card called."""
    from parrot.auth.credentials import CredentialRequired

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        agent = _make_agent()
        agent.parrot_agent.ask.side_effect = CredentialRequired(
            provider="jira",
            auth_url="https://auth.atlassian.com/authorize",
            auth_kind="oauth2",
        )
        ctx = FakeTurnContext(text="create jira issue")

        with patch.object(agent, "_emit_oauth_card", new_callable=AsyncMock) as mock_oauth:
            await agent._handle_message(ctx)

        mock_oauth.assert_awaited_once()


@pytest.mark.asyncio
async def test_obo_miss_routes_to_oauth_card():
    """CredentialRequired(auth_kind='obo') → _emit_oauth_card called."""
    from parrot.auth.credentials import CredentialRequired

    _types_stub = _make_parrot_utils_types_stub()
    _helpers_stub = _make_parrot_utils_stub()

    with patch.dict(sys.modules, {
        "parrot.utils.types": _types_stub,
        "parrot.utils.helpers": _helpers_stub,
    }):
        agent = _make_agent()
        agent.parrot_agent.ask.side_effect = CredentialRequired(
            provider="workiq",
            auth_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            auth_kind="obo",
        )
        ctx = FakeTurnContext(text="summarise emails")

        with patch.object(agent, "_emit_oauth_card", new_callable=AsyncMock) as mock_oauth:
            await agent._handle_message(ctx)

        mock_oauth.assert_awaited_once()


# ---------------------------------------------------------------------------
# _resolver_var and local CredentialRequired removed from auth.py
# ---------------------------------------------------------------------------


def test_resolver_var_not_in_auth_module():
    """_resolver_var has been removed from msagentsdk.auth (dead code, TASK-1673)."""
    import parrot.integrations.msagentsdk.auth as auth_mod

    assert not hasattr(auth_mod, "_resolver_var"), (
        "_resolver_var should have been removed from msagentsdk.auth (TASK-1673)"
    )


def test_local_credential_required_removed():
    """Local CredentialRequired has been removed from msagentsdk.auth (TASK-1673)."""
    import parrot.integrations.msagentsdk.auth as auth_mod

    assert not hasattr(auth_mod, "CredentialRequired"), (
        "Local CredentialRequired should have been removed; "
        "use parrot.auth.credentials.CredentialRequired instead."
    )


def test_obo_exchange_stub_removed():
    """_obo_exchange stub has been removed from BFTokenServiceResolver (TASK-1673)."""
    from parrot.integrations.msagentsdk.auth import BFTokenServiceResolver

    assert not hasattr(BFTokenServiceResolver, "_obo_exchange"), (
        "_obo_exchange stub should have been removed (OBO now flows via broker obo strategy)"
    )


# ---------------------------------------------------------------------------
# Broker + identity_mapper wiring
# ---------------------------------------------------------------------------


def test_broker_stored_on_agent():
    """broker= is stored as _broker on ParrotM365Agent."""
    from parrot.auth.broker import CredentialBroker

    broker = CredentialBroker()
    agent = _make_agent(broker=broker)
    assert agent._broker is broker


def test_identity_mapper_stored_on_agent():
    """identity_mapper= is stored as _identity_mapper on ParrotM365Agent."""
    from parrot.auth.identity import CanonicalIdentityMapper

    mapper = CanonicalIdentityMapper()
    agent = _make_agent(identity_mapper=mapper)
    assert agent._identity_mapper is mapper
