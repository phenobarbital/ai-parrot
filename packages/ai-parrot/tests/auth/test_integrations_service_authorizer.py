"""IntegrationsService request-independent authorization (FEAT-777 AC-14)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.auth.oauth2.authorization import ConnectionAuthorizer
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal


class RecordingAuthorizer:
    """Authorizer double returning a fixed decision and recording calls."""

    def __init__(self, decision: Any) -> None:
        self.decision = decision
        self.calls: List[tuple] = []

    async def authorize(self, principal: Principal, action: str, provider_id: Optional[str], scopes: List[str]) -> Any:
        self.calls.append((principal.user_id, action, provider_id, list(scopes)))
        return self.decision


class RaisingAuthorizer:
    """Authorizer double that raises while evaluating a request."""

    async def authorize(self, principal: Principal, action: str, provider_id: Optional[str], scopes: List[str]) -> bool:
        del principal, action, provider_id, scopes
        raise RuntimeError("PDP unavailable")


@pytest.fixture
def principal() -> Principal:
    """Return a Slack-bound principal."""
    return Principal(user_id="1042", channel="slack", channel_user_id="T01:U02")


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Keep provider registry state isolated between tests."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


def provider() -> MagicMock:
    """Return a provider double with async manager operations."""
    item = MagicMock()
    item.provider_id = "jira"
    item.display_name = "Jira"
    item.icon = "mdi:jira"
    item.default_scopes = ["read:jira-work"]
    item.manager.create_authorization_url = AsyncMock(return_value=("https://idp/authorize", "nonce"))
    OAuth2ProviderRegistry().register(item)
    return item


def test_protocol_runtime_checkable() -> None:
    """The injected authorizer contract supports runtime protocol checks."""
    assert isinstance(RecordingAuthorizer(True), ConnectionAuthorizer)


@pytest.mark.asyncio
async def test_no_request_no_authorizer_denies(principal: Principal) -> None:
    """A request-free call without an injected authorizer fails closed."""
    assert await IntegrationsService()._authorize(None, principal, "1042", "integration:list") is False


@pytest.mark.asyncio
async def test_principal_mismatch_denies(principal: Principal) -> None:
    """A principal cannot authorize a different user id."""
    authorizer = RecordingAuthorizer(True)
    service = IntegrationsService(authorizer=authorizer)
    assert await service._authorize(None, principal, "9999", "integration:list") is False
    assert authorizer.calls == []


@pytest.mark.asyncio
async def test_truthy_non_bool_denies(principal: Principal) -> None:
    """Only the literal True decision grants access."""
    assert await IntegrationsService(authorizer=RecordingAuthorizer(object()))._authorize(
        None, principal, "1042", "integration:list"
    ) is False
    assert await IntegrationsService(authorizer=RecordingAuthorizer(True))._authorize(
        None, principal, "1042", "integration:list"
    ) is True


@pytest.mark.asyncio
async def test_authorizer_exception_denies(principal: Principal) -> None:
    """Authorizer failures are swallowed and deny the operation."""
    assert await IntegrationsService(authorizer=RaisingAuthorizer())._authorize(
        None, principal, "1042", "integration:list"
    ) is False


@pytest.mark.asyncio
async def test_list_for_principal_uses_authorizer(principal: Principal) -> None:
    """Collection and provider listing checks use the injected authorizer."""
    provider()
    authorizer = RecordingAuthorizer(True)
    with (
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[])),
        patch.object(IntegrationsService, "_token_status", AsyncMock(return_value="connected")),
    ):
        items = await IntegrationsService(authorizer=authorizer).list_for_principal("1042", principal=principal)

    assert len(items) == 1
    assert [(call[1], call[2]) for call in authorizer.calls] == [
        ("integration:list", None),
        ("integration:list", "jira"),
    ]


@pytest.mark.asyncio
async def test_start_connect_denied_creates_no_state(principal: Principal) -> None:
    """A denied request-free connect does not create OAuth state."""
    item = provider()
    service = IntegrationsService(authorizer=RecordingAuthorizer(False))
    with pytest.raises(PermissionError):
        await service.start_connect("1042", "jira", channel="slack", principal=principal)
    item.manager.create_authorization_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_path_unchanged() -> None:
    """A request uses web PBAC and bypasses the injected authorizer."""
    authorizer = RecordingAuthorizer(True)
    request = SimpleNamespace(app={})
    assert await IntegrationsService(authorizer=authorizer)._authorize(request, None, "1", "integration:list") is False
    assert authorizer.calls == []
