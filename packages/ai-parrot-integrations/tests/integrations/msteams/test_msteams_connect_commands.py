"""FEAT-775 M3: TeamsConnector."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from botbuilder.schema import Activity, ChannelAccount, ConversationAccount

from parrot.auth.oauth2.models import IntegrationDescriptor
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry
from parrot.auth.principal import Principal
from parrot.integrations.msteams.commands.connect_commands import LOGIN_FIRST, PERSONAL_ONLY, TeamsConnector


class FakeProvider(OAuth2Provider):
    """Minimal registered provider used by connector tests."""

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
        """Implement the provider abstract interface for fixture registration."""
        return Mock()


def descriptor(
    status: str = "disconnected",
    scopes_granted: list[str] | None = None,
    display_account_name: str | None = None,
) -> IntegrationDescriptor:
    """Create a minimal connection descriptor."""
    return IntegrationDescriptor(
        provider="jira",
        display_name="Jira",
        status=status,
        scopes_granted=scopes_granted or [],
        display_account_name=display_account_name,
    )


@pytest.fixture(autouse=True)
def registered_provider() -> Mock:
    """Register an isolated Jira provider with an async legacy-token reader."""
    OAuth2ProviderRegistry._reset()
    manager = Mock()
    manager.get_valid_token = AsyncMock(return_value=None)
    OAuth2ProviderRegistry().register(FakeProvider(manager))
    yield manager
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def principal() -> Principal:
    """Return the trusted principal for a Teams turn."""
    return Principal(
        user_id="42",
        canonical_identity="aad-42",
        tenant_id="tenant-1",
        channel="msteams",
        channel_user_id="aad-42",
    )


@pytest.fixture
def session() -> SimpleNamespace:
    """Return a session shape accepted by the Teams context builder."""
    return SimpleNamespace(nav_user_id="42", aad_object_id="aad-42", tenant_id="tenant-1")


@pytest.fixture
def turn_context() -> Mock:
    """Return a personal Teams turn context with serializable conversation data."""
    activity = Activity(
        type="message",
        channel_id="msteams",
        service_url="https://service.example",
        conversation=ConversationAccount(id="conversation-1", conversation_type="personal"),
        from_property=ChannelAccount(id="aad-42"),
        recipient=ChannelAccount(id="28:app-1"),
    )
    context = Mock()
    context.activity = activity
    context.turn_state = {}
    context.send_activity = AsyncMock()
    return context


@pytest.fixture
def service() -> Mock:
    """Return a recording integration service with disconnected status by default."""
    value = Mock()
    value.status = AsyncMock(return_value=descriptor())
    value.start_connect = AsyncMock(return_value=SimpleNamespace(auth_url="https://auth.example"))
    value.persist_credential = AsyncMock()
    value.disconnect = AsyncMock()
    value.list_for_principal = AsyncMock(return_value=[descriptor()])
    return value


@pytest.fixture
def connector(service: Mock, session: SimpleNamespace, principal: Principal) -> tuple[TeamsConnector, Mock]:
    """Build a connector and expose its recording principal source."""
    source = Mock()
    source.session_for_turn = AsyncMock(return_value=session)
    source.principal_for_turn = AsyncMock(return_value=principal)
    return (
        TeamsConnector(
            principal_source=source,
            service_factory=lambda: service,
            provider_ids=lambda: ["jira"],
            bot_app_id="app-1",
            auth_enabled=True,
        ),
        source,
    )


@pytest.mark.asyncio
async def test_connect_requires_principal(connector: tuple[TeamsConnector, Mock], service: Mock, turn_context: Mock) -> None:
    """A missing session replies with login instructions and creates no state."""
    value, source = connector
    source.session_for_turn.return_value = None

    await value.connect(turn_context, "jira")

    turn_context.send_activity.assert_awaited_once_with(LOGIN_FIRST)
    service.start_connect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("conversation_type", ["group", "channel", None])
async def test_connect_personal_only(
    connector: tuple[TeamsConnector, Mock], service: Mock, turn_context: Mock, conversation_type: str | None
) -> None:
    """Group, channel, and unknown conversation types do not invoke services."""
    turn_context.activity.conversation.conversation_type = conversation_type

    await connector[0].connect(turn_context, "jira")

    turn_context.send_activity.assert_awaited_once_with(PERSONAL_ONLY)
    service.start_connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_connect_calls_start_connect_with_teams_state(
    connector: tuple[TeamsConnector, Mock], service: Mock, principal: Principal, turn_context: Mock
) -> None:
    """Connect supplies the Teams principal, trusted context, channel, and callback state."""
    await connector[0].connect(turn_context, "jira")

    call = service.start_connect.await_args
    assert call.args == ("42", "jira")
    assert call.kwargs["channel"] == "msteams"
    assert call.kwargs["principal"] == principal
    assert call.kwargs["permission_context"].channel_user_id == "aad-42"
    assert call.kwargs["extra_state"]["bot_app_id"] == "app-1"
    assert call.kwargs["extra_state"]["conversation_reference"]["conversation"]["id"] == "conversation-1"


@pytest.mark.asyncio
async def test_connect_already_connected(
    connector: tuple[TeamsConnector, Mock], service: Mock, turn_context: Mock
) -> None:
    """A grant covering requested scopes skips consent and reports the account."""
    service.status.return_value = descriptor("connected", ["read:jira"], "Ada")

    await connector[0].connect(turn_context, "jira")

    turn_context.send_activity.assert_awaited_once_with("Jira is already connected as **Ada**.")
    service.start_connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_teams_connect_scope_union_and_upgrade(
    connector: tuple[TeamsConnector, Mock], service: Mock, turn_context: Mock
) -> None:
    """An insufficient active grant requests the sorted union of offered scopes."""
    service.status.return_value = descriptor("connected", ["read:jira"])

    await connector[0].connect(turn_context, "jira", scopes=["write:jira", "read:jira", "write:jira"])

    assert service.start_connect.await_args.kwargs["scopes"] == ["read:jira", "write:jira"]


@pytest.mark.asyncio
async def test_pbac_denied_renders_message(connector: tuple[TeamsConnector, Mock], service: Mock, turn_context: Mock) -> None:
    """PBAC denials produce the provider-specific refusal."""
    service.status.side_effect = PermissionError()

    await connector[0].connect(turn_context, "jira")

    turn_context.send_activity.assert_awaited_once_with("You're not allowed to use Jira connections.")


@pytest.mark.asyncio
async def test_teams_preexisting_jira_connection_kept(
    connector: tuple[TeamsConnector, Mock], registered_provider: Mock, service: Mock, turn_context: Mock
) -> None:
    """A valid legacy token is migrated and reported rather than re-consented."""
    token = Mock()
    registered_provider.get_valid_token.return_value = token
    service.status.side_effect = [descriptor(), descriptor("connected", ["read:jira"], "Ada")]

    await connector[0].connect(turn_context, "jira")

    service.persist_credential.assert_awaited_once_with(
        "42", "jira", token, channel="msteams", canonical_identity="aad-42"
    )
    service.start_connect.assert_not_awaited()
    turn_context.send_activity.assert_awaited_once_with("Jira is already connected as **Ada**.")


@pytest.mark.asyncio
async def test_legacy_window_closed_requires_consent(
    connector: tuple[TeamsConnector, Mock], registered_provider: Mock, service: Mock, turn_context: Mock
) -> None:
    """No legacy token leaves a disconnected descriptor and starts consent."""
    registered_provider.get_valid_token.return_value = None

    await connector[0].connect(turn_context, "jira")

    service.persist_credential.assert_not_awaited()
    service.start_connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_channel_aware(
    connector: tuple[TeamsConnector, Mock], service: Mock, principal: Principal, turn_context: Mock
) -> None:
    """Disconnect sends the Teams channel, trusted principal, and permission context."""
    await connector[0].disconnect(turn_context, "jira")

    call = service.disconnect.await_args
    assert call.args == ("42", "jira")
    assert call.kwargs["channel"] == "msteams"
    assert call.kwargs["principal"] == principal
    assert call.kwargs["permission_context"].channel_user_id == "aad-42"
