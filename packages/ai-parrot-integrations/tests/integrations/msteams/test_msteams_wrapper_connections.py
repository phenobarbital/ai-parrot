"""FEAT-775 M1/M4: wrapper permission context and conversation references."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.msteams.auth import MSTeamsUserSession
from parrot.integrations.msteams.wrapper import MSTeamsAgentWrapper


def _session() -> MSTeamsUserSession:
    """Return a validated Teams session for wrapper helper tests."""
    return MSTeamsUserSession(
        user_key="aad-oid",
        teams_user_id="29:teams-user",
        aad_object_id="aad-oid",
        tenant_id="tenant-1",
        nav_user_id="nav-42",
        authenticated=True,
    )


def _wrapper(session: MSTeamsUserSession | None) -> MSTeamsAgentWrapper:
    """Build the lightweight wrapper needed for context and cache helper tests."""
    wrapper = object.__new__(MSTeamsAgentWrapper)
    wrapper.logger = MagicMock()
    wrapper._auth = object()
    wrapper._effective_user_id = AsyncMock(
        side_effect=lambda _turn, fallback: session.nav_user_id if session is not None else fallback
    )
    wrapper._principal_source = MagicMock()
    wrapper._principal_source.session_for_turn = AsyncMock(return_value=session)
    wrapper._convref_store = MagicMock()
    wrapper._convref_store.save = AsyncMock()
    return wrapper


def _turn(conversation_type: str = "personal") -> MagicMock:
    """Build a Bot Framework-shaped turn with an actual conversation type."""
    turn_context = MagicMock()
    turn_context.activity.conversation.conversation_type = conversation_type
    turn_context.activity.conversation.id = "19:conversation"
    turn_context.activity.from_property.id = "29:teams-user"
    return turn_context


@pytest.mark.asyncio
async def test_permission_context_reaches_ask() -> None:
    """Authenticated turns carry PBAC context; anonymous turns preserve their channel id."""
    authenticated = _wrapper(_session())
    context = await authenticated._agent_context(_turn(), "29:teams-user", "19:conversation")

    permission_context = context["permission_context"]
    assert context["user_id"] == "nav-42"
    assert permission_context.user_id == "nav-42"
    assert permission_context.channel == "msteams"
    assert permission_context.channel_user_id == "aad-oid"

    unauthenticated = _wrapper(None)
    context = await unauthenticated._agent_context(_turn(), "29:teams-user", "19:conversation")

    assert context["user_id"] == "29:teams-user"
    assert "permission_context" not in context


@pytest.mark.asyncio
async def test_conv_ref_saved_on_personal_authenticated_turn_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only authenticated personal turns refresh the notifier conversation-reference cache."""
    wrapper = _wrapper(_session())
    reference = MagicMock()
    reference.serialize.return_value = {"conversation": {"id": "19:conversation"}}
    monkeypatch.setattr(
        "parrot.integrations.msteams.wrapper.TurnContext.get_conversation_reference",
        MagicMock(return_value=reference),
    )

    await wrapper._remember_conversation(_turn())
    wrapper._convref_store.save.assert_awaited_once_with("nav-42", {"conversation": {"id": "19:conversation"}})

    wrapper._convref_store.save.reset_mock()
    await wrapper._remember_conversation(_turn("groupChat"))
    assert wrapper._convref_store.save.await_count == 0

    wrapper._principal_source.session_for_turn = AsyncMock(return_value=None)
    await wrapper._remember_conversation(_turn())
    assert wrapper._convref_store.save.await_count == 0


def test_connection_commands_registered_with_empty_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """The connector and commands exist even when no OAuth2 provider is registered at init time.

    Providers such as Jira register in a later startup callback, so construction must not be gated on the registry.
    """
    from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
    from parrot.integrations.msteams.models import MSTeamsAgentConfig

    registry = OAuth2ProviderRegistry()
    monkeypatch.setattr(registry, "all", list)
    app = MagicMock()
    app.get.return_value = None
    agent = MagicMock()
    agent.tool_manager.list_tools.return_value = []
    config = MSTeamsAgentConfig(
        name="test_bot", chatbot_id="test_bot_id", client_id="fake_id", client_secret="fake_secret"
    )

    wrapper = MSTeamsAgentWrapper(agent, config, app)

    assert wrapper._connector is not None
    assert "connect" in wrapper._command_router._handlers
    assert "connect_jira" in wrapper._command_router._handlers
    # Providers registered after construction are visible through the lazy ``provider_ids`` callable.
    sentinel = MagicMock()
    sentinel.provider_id = "late"
    monkeypatch.setattr(registry, "all", lambda: [sentinel])
    assert wrapper._connector._provider_ids() == ["late"]
