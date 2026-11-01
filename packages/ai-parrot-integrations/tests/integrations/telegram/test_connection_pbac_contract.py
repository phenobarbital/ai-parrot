"""FEAT-776 M3: Telegram consumes FEAT-775's request-less PBAC contract."""

from types import SimpleNamespace
from typing import Any, List, Optional, Tuple
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.authorization import ConnectionAuthorizer
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal


def _ctx(user_id: str = "1042", channel: str = "telegram") -> PermissionContext:
    """Build a Telegram permission context for a Navigator user."""
    return PermissionContext(
        session=UserSession(user_id=user_id, tenant_id="default", roles=frozenset()),
        channel=channel,
        channel_user_id="88123",
    )


def _principal(user_id: str = "1042") -> Principal:
    """Build the Navigator principal bound to the Telegram identity."""
    return Principal(user_id=user_id, tenant_id="default", channel="telegram", channel_user_id="88123")


class RecordingAuthorizer:
    """Connection-authorizer fake recording every request-less decision."""

    def __init__(self, decision: Any = True, error: Optional[Exception] = None) -> None:
        self.decision = decision
        self.error = error
        self.calls: List[Tuple[Principal, str, Optional[str], List[str]]] = []

    async def authorize(
        self,
        principal: Principal,
        action: str,
        provider_id: Optional[str],
        scopes: List[str],
    ) -> Any:
        """Record one decision request and return the configured result."""
        self.calls.append((principal, action, provider_id, list(scopes)))
        if self.error is not None:
            raise self.error
        return self.decision


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Register one provider and isolate persistence dependencies."""
    OAuth2ProviderRegistry._reset()
    manager = SimpleNamespace(
        create_authorization_url=AsyncMock(return_value=("https://login.example", "state-1")),
        revoke=AsyncMock(),
    )
    registered = SimpleNamespace(
        provider_id="o365",
        display_name="Office 365",
        icon=None,
        default_scopes=["User.Read"],
        manager=manager,
    )
    OAuth2ProviderRegistry().register(registered)
    monkeypatch.setattr("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[]))
    monkeypatch.setattr("parrot.auth.oauth2.service.get_users_integration", AsyncMock(return_value=None))
    monkeypatch.setattr("parrot.auth.oauth2.service.delete_users_integration", AsyncMock())
    yield registered
    OAuth2ProviderRegistry._reset()


@pytest.mark.asyncio
async def test_channel_pbac_fails_closed(provider: SimpleNamespace) -> None:
    """Telegram authorization denies missing, mismatched, failed, and non-true decisions."""
    principal = _principal()
    cases = [
        (IntegrationsService(), principal, _ctx()),
        (IntegrationsService(authorizer=RecordingAuthorizer()), None, _ctx()),
        (IntegrationsService(authorizer=RecordingAuthorizer()), principal, _ctx(user_id="other-user")),
        (IntegrationsService(authorizer=RecordingAuthorizer(error=RuntimeError("policy unavailable"))), principal, _ctx()),
        (IntegrationsService(authorizer=RecordingAuthorizer(decision=object())), principal, _ctx()),
    ]

    for service, case_principal, context in cases:
        assert await service.list_for_principal("1042", principal=case_principal, permission_context=context) == []
        with pytest.raises(PermissionError):
            await service.start_connect(
                "1042",
                "o365",
                channel="telegram",
                principal=case_principal,
                permission_context=context,
            )

    provider.manager.create_authorization_url.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_pbac_uses_navigator_principal(provider: SimpleNamespace) -> None:
    """Telegram passes the Navigator principal, never its raw Telegram identity."""
    authorizer = RecordingAuthorizer()
    principal = _principal()
    assert isinstance(authorizer, ConnectionAuthorizer)

    await IntegrationsService(authorizer=authorizer).start_connect(
        "1042",
        "o365",
        channel="telegram",
        principal=principal,
        permission_context=_ctx(),
    )

    assert authorizer.calls == [(principal, "integration:connect", "o365", ["User.Read"])]
    assert authorizer.calls[0][0].user_id == "1042"
    assert authorizer.calls[0][0].user_id != "88123"


@pytest.mark.asyncio
async def test_service_request_less_pbac_branch(provider: SimpleNamespace) -> None:
    """Permission-context calls select the authorizer even when an HTTP request is supplied."""
    authorizer = RecordingAuthorizer()
    principal = _principal()
    request = SimpleNamespace(app={"abac": SimpleNamespace(is_allowed=AsyncMock(return_value=False))})
    service = IntegrationsService(authorizer=authorizer)

    assert len(await service.list_for_principal("1042", principal=principal, permission_context=_ctx())) == 1
    await service.status("1042", "o365", principal=principal, permission_context=_ctx())
    await service.start_connect(
        "1042",
        "o365",
        channel="telegram",
        principal=principal,
        permission_context=_ctx(),
    )
    await service.disconnect(
        "1042",
        "o365",
        request=request,
        channel="telegram",
        principal=principal,
        permission_context=_ctx(),
    )

    assert [(action, provider_id, scopes) for _, action, provider_id, scopes in authorizer.calls] == [
        ("integration:list", None, []),
        ("integration:list", "o365", []),
        ("integration:list", "o365", []),
        ("integration:connect", "o365", ["User.Read"]),
        ("integration:disconnect", "o365", ["User.Read"]),
    ]
    request.app["abac"].is_allowed.assert_not_awaited()
    provider.manager.revoke.assert_awaited_once_with(
        channel="telegram",
        user_id="1042",
        channel_user_id="88123",
    )
