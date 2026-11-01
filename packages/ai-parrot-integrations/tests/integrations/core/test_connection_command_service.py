"""FEAT-776 M5 unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.oauth2.models import ConnectInitResponse, IntegrationDescriptor
from parrot.auth.oauth2.registry import OAuth2Provider, OAuth2ProviderRegistry
from parrot.auth.permission import PermissionContext
from parrot.auth.principal import Principal
from parrot.integrations.core.auth.connections import ConnectionCommandService


class FakeProvider(OAuth2Provider):
    """Minimal provider whose manager can be withdrawn during a command."""

    def __init__(self, provider_id: str, display_name: str, manager: Any, scopes: list[str]) -> None:
        self.provider_id = provider_id
        self.display_name = display_name
        self.icon = None
        self._manager = manager
        self.default_scopes = scopes

    @property
    def manager(self) -> Any:
        """Return the currently available OAuth manager."""
        return self._manager

    def toolkit_factory(self, credential_resolver: Any) -> Any:
        """Provide the abstract method; command tests do not build toolkits."""
        return MagicMock()


@pytest.fixture
def provider_registry() -> OAuth2ProviderRegistry:
    """Register connectable, MCP, unavailable, and non-allowlisted providers."""
    OAuth2ProviderRegistry._reset()
    registry = OAuth2ProviderRegistry()
    registry.register(FakeProvider("jira", "Jira", object(), ["read"]))
    registry.register(FakeProvider("o365", "Microsoft 365", object(), ["files.read"]))
    registry.register(FakeProvider("mcp:internal", "Internal", object(), ["read"]))
    registry.register(FakeProvider("dummy", "Dummy", None, ["read"]))
    yield registry
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def principal() -> Principal:
    """Return the trusted channel principal used by command calls."""
    return Principal(user_id="1042", channel="telegram", channel_user_id="42")


@pytest.fixture
def fake_integrations_service() -> MagicMock:
    """Return a fake service with default disconnected status and OAuth response."""
    return MagicMock(
        status=AsyncMock(
            return_value=IntegrationDescriptor(
                provider="jira", display_name="Jira", status="disconnected", scopes_granted=[]
            )
        ),
        start_connect=AsyncMock(
            return_value=ConnectInitResponse(auth_url="https://login.example", state="state", scopes=["read"])
        ),
        disconnect=AsyncMock(),
        list_for_principal=AsyncMock(return_value=[]),
    )


def _commands(
    service: MagicMock, registry: OAuth2ProviderRegistry, allowlist: list[str] | None = None
) -> ConnectionCommandService:
    """Build the channel-neutral service under test."""
    return ConnectionCommandService(service=service, app={}, channel="telegram", allowlist=allowlist, registry=registry)


def test_connectable_providers_filter(
    provider_registry: OAuth2ProviderRegistry, fake_integrations_service: MagicMock
) -> None:
    """Only managed, non-MCP, allowlisted providers are exposed and resolvable."""
    commands = _commands(fake_integrations_service, provider_registry, allowlist=["o365", "jira"])

    assert [provider.provider_id for provider in commands.connectable_providers()] == ["jira", "o365"]
    assert commands.resolve_provider("OFFICE365").provider_id == "o365"
    assert commands.resolve_provider("mcp:internal") is None
    assert commands.resolve_provider("dummy") is None


@pytest.mark.asyncio
async def test_connect_outcomes(
    provider_registry: OAuth2ProviderRegistry,
    fake_integrations_service: MagicMock,
    principal: Principal,
) -> None:
    """Map login, unknown, covered grant, URL, denial, and unavailable outcomes."""
    commands = _commands(fake_integrations_service, provider_registry)
    context = MagicMock(spec=PermissionContext)

    assert (await commands.connect(None, "jira", extra_state={}, permission_context=context)).kind == "needs_login"
    assert (
        await commands.connect(principal, "missing", extra_state={}, permission_context=context)
    ).kind == "unknown_provider"

    fake_integrations_service.status.return_value = IntegrationDescriptor(
        provider="jira", display_name="Jira", status="connected", scopes_granted=["read"], display_account_name="Ada"
    )
    covered = await commands.connect(principal, "jira", extra_state={}, permission_context=context)
    assert (covered.kind, covered.account_display_name) == ("already_connected", "Ada")
    fake_integrations_service.start_connect.assert_not_awaited()

    fake_integrations_service.status.return_value = IntegrationDescriptor(
        provider="jira", display_name="Jira", status="disconnected", scopes_granted=[]
    )
    started = await commands.connect(principal, "jira", extra_state={"chat_id": 1}, permission_context=context)
    assert (started.kind, started.auth_url) == ("auth_url", "https://login.example")

    fake_integrations_service.status.side_effect = PermissionError()
    assert (await commands.connect(principal, "jira", extra_state={}, permission_context=context)).kind == "denied"
    fake_integrations_service.status.side_effect = None

    provider_registry.get("jira")._manager = None
    assert (await commands.connect(principal, "jira", extra_state={}, permission_context=context)).kind == "unavailable"
    provider_registry.get("jira")._manager = object()

    fake_integrations_service.list_for_principal.return_value = [
        IntegrationDescriptor(provider="jira", display_name="Jira", status="connected", display_account_name="Ada"),
        IntegrationDescriptor(provider="dummy", display_name="Dummy", status="disconnected"),
    ]
    statuses = await commands.statuses(principal, permission_context=context)
    assert [status.model_dump() for status in statuses] == [
        {"provider_id": "jira", "display_name": "Jira", "status": "connected", "account_display_name": "Ada"}
    ]

    assert (await commands.disconnect(principal, "jira", permission_context=context)).kind == "disconnected"
    fake_integrations_service.disconnect.assert_awaited_once_with(
        "1042", "jira", channel="telegram", principal=principal, permission_context=context
    )


@pytest.mark.asyncio
async def test_scopes_never_from_user(
    provider_registry: OAuth2ProviderRegistry,
    fake_integrations_service: MagicMock,
    principal: Principal,
) -> None:
    """Explicit commands use defaults; automatic trusted offers are deduplicated and sorted."""
    commands = _commands(fake_integrations_service, provider_registry)
    context = MagicMock(spec=PermissionContext)
    fake_integrations_service.status.return_value = IntegrationDescriptor(
        provider="jira", display_name="Jira", status="disconnected", scopes_granted=[]
    )

    await commands.connect(principal, "jira", extra_state={}, permission_context=context)
    assert fake_integrations_service.start_connect.await_args.kwargs["scopes"] == ["read"]

    fake_integrations_service.status.return_value = IntegrationDescriptor(
        provider="jira", display_name="Jira", status="connected", scopes_granted=["read"]
    )
    outcome = await commands.connect(
        principal,
        "jira",
        extra_state={},
        permission_context=context,
        scopes=["write", "read", "write"],
    )
    assert outcome.kind == "auth_url"
    assert fake_integrations_service.start_connect.await_args.kwargs["scopes"] == ["read", "write"]
