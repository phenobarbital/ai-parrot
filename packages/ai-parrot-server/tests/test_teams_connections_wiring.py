"""FEAT-775 M7: Teams connection wiring (AC-6, AC-14)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

pytest.importorskip("botbuilder.schema", reason="needs the msteams extra (botbuilder)")

from botbuilder.schema import Activity, ChannelAccount, ConversationAccount  # noqa: E402

from parrot.auth.oauth2.events import ChannelNotifierRegistry, ConnectionEvent, ConnectionEventPublisher
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry
from parrot.auth.permission import build_principal_context
from parrot.auth.principal import Principal
from parrot.integrations.manager import (
    _channel_service_factory,
    _connection_publisher,
    _register_channel_notifiers,
    _register_teams_notifier,
)
from parrot.integrations.msteams.commands import MSTeamsCommandRouter
from parrot.integrations.msteams.commands.connect_commands import TeamsConnector, register_connection_commands
from parrot.integrations.msteams.connections import MSTeamsConnectionNotifier


class FakeProvider(OAuth2Provider):
    """Minimal Jira provider for the command-to-callback wiring test."""

    provider_id = "jira"
    display_name = "Jira"
    default_scopes = ["read:jira"]

    def __init__(self, manager: Mock) -> None:
        self._manager = manager

    @property
    def manager(self) -> Mock:
        """Return the recording OAuth manager."""
        return self._manager

    def toolkit_factory(self, credential_resolver: object) -> object:
        """Implement the provider interface; tool construction is not used here."""
        return Mock()


class AllowAuthorizer:
    """``ConnectionAuthorizer`` double that allows every connection action."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def authorize(self, principal: Any, action: str, provider_id: Any, scopes: list[str]) -> bool:
        """Record and allow."""
        self.calls.append((principal, action, provider_id, scopes))
        return True


class RecordingTurnContext:
    """Capture a proactive Teams message."""

    def __init__(self) -> None:
        self.activities: list[Any] = []

    async def send_activity(self, activity: Any) -> None:
        """Record an outgoing activity."""
        self.activities.append(activity)


class RecordingAdapter:
    """Execute proactive callbacks and retain the resulting activities."""

    def __init__(self) -> None:
        self.turn_context = RecordingTurnContext()

    async def continue_conversation(self, reference: Any, callback: Any, app_id: str) -> None:
        """Run the callback as the adapter selected for ``app_id``."""
        await callback(self.turn_context)


@pytest.fixture(autouse=True)
def fresh_registries() -> None:
    """Isolate the process-wide notifier and provider registries."""
    ChannelNotifierRegistry._reset()
    OAuth2ProviderRegistry._reset()
    yield
    ChannelNotifierRegistry._reset()
    OAuth2ProviderRegistry._reset()


def test_registry_holds_teams_notifier_only() -> None:
    """The msteams channel is owned only by the generic connection notifier."""
    app: dict[str, Any] = {}

    registry = _register_channel_notifiers(app)

    notifier = registry.get("msteams")
    assert isinstance(notifier, MSTeamsConnectionNotifier)
    assert [item.channel for item in registry.all()].count("msteams") == 1


def test_registration_order_jira_before_and_after_teams() -> None:
    """Jira-first and Teams-first setup retain the app's same notifier instance."""
    jira_first_app: dict[str, Any] = {}
    _connection_publisher(jira_first_app)
    jira_first = jira_first_app["msteams_connection_notifier"]
    _register_teams_notifier(jira_first_app)
    assert ChannelNotifierRegistry().get("msteams") is jira_first

    ChannelNotifierRegistry._reset()
    teams_first_app: dict[str, Any] = {}
    _register_teams_notifier(teams_first_app)
    teams_first = teams_first_app["msteams_connection_notifier"]
    _connection_publisher(teams_first_app)
    assert ChannelNotifierRegistry().get("msteams") is teams_first


@pytest.mark.asyncio
async def test_factory_injects_connection_authorizer_or_denies() -> None:
    """Teams services share app["connection_authorizer"]; without it context authorization is denied."""
    db_pool = object()
    redis = object()
    authorizer = AllowAuthorizer()
    app: dict[str, Any] = {"authdb": db_pool, "redis": redis}
    factory = _channel_service_factory(app)
    # Installed after the factory is built (server startup order) — still picked up per call.
    app["connection_authorizer"] = authorizer
    allowed = factory()
    assert allowed._authorizer is authorizer
    assert allowed._vault_token_sync._pool is db_pool
    assert allowed._vault_token_sync._redis is redis

    denied = _channel_service_factory({})()
    context = build_principal_context("42", channel="msteams", tenant_id="tenant-1", roles=frozenset())
    context.channel_user_id = "aad-42"
    principal = Principal(
        user_id="42",
        canonical_identity="aad-42",
        tenant_id="tenant-1",
        channel="msteams",
        channel_user_id="aad-42",
    )
    assert await denied.list_for_principal("42", principal=principal, permission_context=context) == []


@pytest.mark.asyncio
async def test_teams_connect_end_to_end() -> None:
    """A /connect card's callback state routes the connected message to its issuing bot."""
    oauth_manager = Mock()
    oauth_manager.get_valid_token = AsyncMock(return_value=None)
    oauth_manager.create_authorization_url = AsyncMock(
        return_value=("https://jira.example/authorize?state=state-1", "state-1")
    )
    OAuth2ProviderRegistry().register(FakeProvider(oauth_manager))

    app: dict[str, Any] = {"connection_authorizer": AllowAuthorizer()}
    _register_teams_notifier(app)
    notifier = app["msteams_connection_notifier"]
    adapter = RecordingAdapter()
    notifier.attach("app-1", adapter)

    session = SimpleNamespace(nav_user_id="42", aad_object_id="aad-42", tenant_id="tenant-1")
    principal = Principal(
        user_id="42",
        canonical_identity="aad-42",
        tenant_id="tenant-1",
        channel="msteams",
        channel_user_id="aad-42",
    )
    principal_source = Mock()
    principal_source.session_for_turn = AsyncMock(return_value=session)
    principal_source.principal_for_turn = AsyncMock(return_value=principal)
    connector = TeamsConnector(
        principal_source=principal_source,
        service_factory=_channel_service_factory(app),
        provider_ids=lambda: ["jira"],
        bot_app_id="app-1",
        auth_enabled=True,
    )
    router = MSTeamsCommandRouter()
    register_connection_commands(router, connector=connector)

    turn_context = Mock()
    turn_context.activity = Activity(
        type="message",
        channel_id="msteams",
        service_url="https://service.example",
        conversation=ConversationAccount(id="conversation-1", conversation_type="personal"),
        from_property=ChannelAccount(id="aad-42"),
        recipient=ChannelAccount(id="28:app-1"),
    )
    turn_context.turn_state = {}
    turn_context.send_activity = AsyncMock()

    with patch("parrot.auth.oauth2.service.get_users_integration", AsyncMock(return_value=None)):
        assert await router.try_dispatch("/connect jira", turn_context) is True

    card_activity = turn_context.send_activity.await_args.args[0]
    assert card_activity.attachments[0].content["actions"][0]["url"] == ("https://jira.example/authorize?state=state-1")
    callback_extra = oauth_manager.create_authorization_url.await_args.kwargs["extra_state"]
    assert callback_extra["conversation_reference"]["conversation"]["id"] == "conversation-1"

    await ConnectionEventPublisher(notifiers=ChannelNotifierRegistry()).publish(
        ConnectionEvent(
            kind="connection.completed",
            user_id="42",
            provider="jira",
            account_id="jira-account",
            display_name="Ada",
            channel="msteams",
            occurred_at=1.0,
        ),
        {"extra": callback_extra},
    )

    assert adapter.turn_context.activities[0].text == "Jira connected as **Ada**. Ask again to use it."
