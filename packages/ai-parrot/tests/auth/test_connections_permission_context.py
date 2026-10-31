"""FEAT-775 M3: request-less PBAC on IntegrationsService (AC-14)."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import AsyncMock

import pytest

from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2.service import IntegrationsService, pdp_permission_evaluator
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
async def test_service_requestless_pbac_fails_closed(provider: SimpleNamespace) -> None:
    """Missing, failing, non-boolean, and request-less authorization all deny."""
    context = _context()

    assert await IntegrationsService().list_for_principal("nav-user", permission_context=context) == []

    async def raises(_: PermissionContext, __: Mapping[str, Any]) -> bool:
        raise RuntimeError("policy unavailable")

    assert (
        await IntegrationsService(permission_evaluator=raises).list_for_principal(
            "nav-user", permission_context=context
        )
        == []
    )

    async def truthy(_: PermissionContext, __: Mapping[str, Any]) -> object:
        return object()

    assert (
        await IntegrationsService(permission_evaluator=truthy).list_for_principal(
            "nav-user", permission_context=context
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
    """Every identity mismatch denies before credential or persistence mutation."""

    async def allow(_: PermissionContext, __: Mapping[str, Any]) -> bool:
        return True

    delete = AsyncMock()
    monkeypatch.setattr("parrot.auth.oauth2.service.delete_users_integration", delete)
    service = IntegrationsService(permission_evaluator=allow)

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

    provider.manager.create_authorization_url.assert_not_awaited()
    provider.manager.revoke.assert_not_awaited()
    delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnect_revokes_on_channel(provider: SimpleNamespace) -> None:
    """Disconnect uses the supplied channel and its trusted raw identity."""

    async def allow(_: PermissionContext, __: Mapping[str, Any]) -> bool:
        return True

    principal = _principal()
    await IntegrationsService(permission_evaluator=allow).disconnect(
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
async def test_evaluator_attributes_shape(provider: SimpleNamespace) -> None:
    """The evaluator receives the stable FEAT-773 attributes plus operation."""
    calls: list[Mapping[str, Any]] = []

    async def record(_: PermissionContext, attributes: Mapping[str, Any]) -> bool:
        calls.append(dict(attributes))
        return True

    await IntegrationsService(permission_evaluator=record).status(
        "nav-user",
        "o365",
        principal=_principal(),
        permission_context=_context(),
    )

    assert calls == [
        {
            "action": "integration:list",
            "provider": "o365",
            "scopes": [],
            "operation": "status",
        }
    ]


_POLICY_YAML = """
version: "1.0"
defaults:
  effect: deny
policies:
  - name: allow_connections_read_write
    effect: allow
    resources:
      - "uri:/api/v1/connections"
      - "uri:/api/v1/connections/o365"
      - "uri:/api/v1/connections/o365/start"
    actions:
      - "uri:read"
      - "uri:write"
    subjects:
      groups:
        - connections-users
    priority: 10
  - name: deny_connections_delete
    effect: deny
    resources:
      - "uri:/api/v1/connections"
      - "uri:/api/v1/connections/o365"
      - "uri:/api/v1/connections/o365/start"
    actions:
      - "uri:delete"
    subjects:
      groups:
        - connections-users
    priority: 20
"""


@pytest.mark.asyncio
async def test_teams_service_pbac_allow_and_deny(provider: SimpleNamespace, tmp_path: Path) -> None:
    """Real navigator-auth policies enforce the channel URI parity table."""
    pytest.importorskip("navigator_auth")
    from navigator_auth.abac.policies.evaluator import PolicyEvaluator
    from navigator_auth.abac.policies.resources import ResourceType

    from parrot.auth.permission import to_eval_context

    policy_file = tmp_path / "connections.yaml"
    policy_file.write_text(_POLICY_YAML)
    evaluator = PolicyEvaluator(cache_size=64, cache_ttl_seconds=30)
    evaluator.load_from_file(policy_file)
    service = IntegrationsService(permission_evaluator=pdp_permission_evaluator(SimpleNamespace(evaluator=evaluator)))
    context = _context()
    principal = _principal()
    direct = evaluator.check_access(
        to_eval_context(context),
        ResourceType.URI,
        "/api/v1/connections",
        "uri:read",
    )
    assert direct.allowed is True, direct
    provider_direct = evaluator.check_access(
        to_eval_context(context),
        ResourceType.URI,
        "/api/v1/connections/o365",
        "uri:read",
    )
    assert provider_direct.allowed is True, provider_direct
    connect_direct = evaluator.check_access(
        to_eval_context(context),
        ResourceType.URI,
        "/api/v1/connections/o365/start",
        "uri:write",
    )
    assert connect_direct.allowed is True, connect_direct

    assert len(await service.list_for_principal("nav-user", principal=principal, permission_context=context)) == 1
    assert (
        await service.status("nav-user", "o365", principal=principal, permission_context=context)
    ).provider == "o365"
    assert (
        await service.start_connect(
            "nav-user",
            "o365",
            channel="msteams",
            principal=principal,
            permission_context=context,
        )
    ).state == "state-1"
    with pytest.raises(PermissionError):
        await service.disconnect(
            "nav-user",
            "o365",
            channel="msteams",
            principal=principal,
            permission_context=context,
        )
    provider.manager.revoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_service_authorization_unchanged() -> None:
    """The legacy request path remains active and context denial never falls back."""
    abac = SimpleNamespace(is_allowed=AsyncMock(return_value=True))
    request = SimpleNamespace(app={"abac": abac})

    async def deny(_: PermissionContext, __: Mapping[str, Any]) -> bool:
        return False

    service = IntegrationsService(permission_evaluator=deny)
    assert await service._check_pbac(request, "integration:list", "o365") is True
    assert (
        await service._check_pbac(
            request,
            "integration:list",
            "o365",
            permission_context=_context(),
            operation="status",
        )
        is False
    )
    abac.is_allowed.assert_awaited_once_with(
        request,
        {"action": "integration:list", "provider": "o365"},
    )
