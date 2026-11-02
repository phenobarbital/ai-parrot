"""FEAT-775 M3: request-less authorization on IntegrationsService (AC-14).

Teams callers pass a ``PermissionContext`` that is only an identity check; the decision itself goes through the
same ``ConnectionAuthorizer`` Slack and the CLI use (issue:3a7ee22eb09a).
"""

from types import SimpleNamespace
from typing import Any, List, Optional, Tuple
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.permission import PermissionContext, UserSession
from parrot.auth.principal import Principal


def _context(
    *,
    user_id: str = "nav-user",
    tenant_id: str = "tenant-1",
    channel: str = "msteams",
    channel_user_id: str = "teams-oid",
    groups: tuple[str, ...] = ("connections-users",),
) -> PermissionContext:
    """Build a verified channel permission context."""
    return PermissionContext(
        session=UserSession(
            user_id=user_id,
            tenant_id=tenant_id,
            roles=frozenset(),
            metadata={"groups": list(groups)},
        ),
        channel=channel,
        channel_user_id=channel_user_id,
    )


def _principal(
    *,
    user_id: str = "nav-user",
    tenant_id: str = "tenant-1",
    channel: str = "msteams",
    channel_user_id: str = "teams-oid",
) -> Principal:
    """Build the matching platform principal."""
    return Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        channel=channel,
        channel_user_id=channel_user_id,
    )


class RecordingAuthorizer:
    """``ConnectionAuthorizer`` double that records calls and returns a fixed decision."""

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
        """Record the call, then raise or return the configured decision."""
        self.calls.append((principal, action, provider_id, list(scopes)))
        if self.error is not None:
            raise self.error
        return self.decision


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Register one provider and isolate its persistence side effects."""
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
    monkeypatch.setattr(
        "parrot.auth.oauth2.service.list_users_integrations",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "parrot.auth.oauth2.service.get_users_integration",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "parrot.auth.oauth2.service.delete_users_integration",
        AsyncMock(),
    )
    yield registered
    OAuth2ProviderRegistry._reset()


@pytest.mark.asyncio
async def test_service_requestless_authorization_fails_closed(provider: SimpleNamespace) -> None:
    """Missing authorizer, missing principal, errors and non-boolean decisions all deny."""
    context = _context()
    principal = _principal()

    assert (
        await IntegrationsService().list_for_principal("nav-user", principal=principal, permission_context=context)
        == []
    )
    assert (
        await IntegrationsService(authorizer=RecordingAuthorizer()).list_for_principal(
            "nav-user", permission_context=context
        )
        == []
    )
    assert (
        await IntegrationsService(
            authorizer=RecordingAuthorizer(error=RuntimeError("policy unavailable"))
        ).list_for_principal("nav-user", principal=principal, permission_context=context)
        == []
    )
    assert (
        await IntegrationsService(authorizer=RecordingAuthorizer(decision=object())).list_for_principal(
            "nav-user", principal=principal, permission_context=context
        )
        == []
    )
    assert await IntegrationsService().list_for_principal("nav-user") == []
    provider.manager.create_authorization_url.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context", "principal", "channel"),
    [
        (_context(user_id="other-user"), _principal(), "msteams"),
        (_context(), _principal(user_id="other-user"), "msteams"),
        (_context(), _principal(tenant_id="other-tenant"), "msteams"),
        (_context(), _principal(channel_user_id="other-oid"), "msteams"),
        (_context(), _principal(), "telegram"),
    ],
)
async def test_service_context_target_mismatch_denied(
    provider: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    context: PermissionContext,
    principal: Principal,
    channel: str,
) -> None:
    """Every identity mismatch denies before the authorizer, credentials or persistence are touched."""
    authorizer = RecordingAuthorizer()
    delete = AsyncMock()
    monkeypatch.setattr("parrot.auth.oauth2.service.delete_users_integration", delete)
    service = IntegrationsService(authorizer=authorizer)

    with pytest.raises(PermissionError):
        await service.start_connect(
            "nav-user",
            "o365",
            channel=channel,
            principal=principal,
            permission_context=context,
        )
    with pytest.raises(PermissionError):
        await service.disconnect(
            "nav-user",
            "o365",
            channel=channel,
            principal=principal,
            permission_context=context,
        )

    assert authorizer.calls == []
    provider.manager.create_authorization_url.assert_not_awaited()
    provider.manager.revoke.assert_not_awaited()
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_revokes_on_channel(provider: SimpleNamespace) -> None:
    """Disconnect uses the supplied channel and its trusted raw identity."""
    principal = _principal()
    await IntegrationsService(authorizer=RecordingAuthorizer()).disconnect(
        "nav-user",
        "o365",
        channel="msteams",
        principal=principal,
        permission_context=_context(),
    )

    provider.manager.revoke.assert_awaited_once_with(
        channel="msteams",
        user_id="nav-user",
        channel_user_id="teams-oid",
    )


@pytest.mark.asyncio
async def test_teams_calls_use_connection_authorizer(provider: SimpleNamespace) -> None:
    """Teams operations reach the shared authorizer with ``integration:*`` actions, like Slack and the CLI."""
    authorizer = RecordingAuthorizer()
    service = IntegrationsService(authorizer=authorizer)
    principal = _principal()
    context = _context()

    assert len(await service.list_for_principal("nav-user", principal=principal, permission_context=context)) == 1
    await service.status("nav-user", "o365", principal=principal, permission_context=context)
    await service.start_connect("nav-user", "o365", channel="msteams", principal=principal, permission_context=context)
    await service.disconnect("nav-user", "o365", channel="msteams", principal=principal, permission_context=context)

    assert [(call[1], call[2], call[3]) for call in authorizer.calls] == [
        ("integration:list", None, []),
        ("integration:list", "o365", []),
        ("integration:list", "o365", []),
        ("integration:connect", "o365", ["User.Read"]),
        ("integration:disconnect", "o365", ["User.Read"]),
    ]
    assert all(call[0] is principal for call in authorizer.calls)


@pytest.mark.asyncio
async def test_authorizer_deny_blocks_teams_operations(provider: SimpleNamespace) -> None:
    """An authorizer deny stops every Teams operation before any OAuth side effect."""
    service = IntegrationsService(authorizer=RecordingAuthorizer(decision=False))
    principal = _principal()
    context = _context()

    assert await service.list_for_principal("nav-user", principal=principal, permission_context=context) == []
    with pytest.raises(PermissionError):
        await service.status("nav-user", "o365", principal=principal, permission_context=context)
    with pytest.raises(PermissionError):
        await service.start_connect(
            "nav-user", "o365", channel="msteams", principal=principal, permission_context=context
        )
    with pytest.raises(PermissionError):
        await service.disconnect("nav-user", "o365", channel="msteams", principal=principal, permission_context=context)
    provider.manager.create_authorization_url.assert_not_awaited()
    provider.manager.revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_service_authorization_unchanged(provider: SimpleNamespace) -> None:
    """The web request path still uses request PBAC; a context call never falls back to it."""
    abac = SimpleNamespace(is_allowed=AsyncMock(return_value=True))
    request = SimpleNamespace(app={"abac": abac})
    authorizer = RecordingAuthorizer(decision=False)
    service = IntegrationsService(authorizer=authorizer)

    assert await service._check_pbac(request, "integration:list", "o365") is True
    with pytest.raises(PermissionError):
        await service.status("nav-user", "o365", request, principal=_principal(), permission_context=_context())
    abac.is_allowed.assert_awaited_once_with(
        request,
        {"action": "integration:list", "provider": "o365"},
    )
    assert len(authorizer.calls) == 1
