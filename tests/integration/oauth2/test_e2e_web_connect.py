"""End-to-end web OAuth flow for principal-keyed connections."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.auth.oauth2.models import UsersIntegrationRow
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.auth.oauth2_routes import make_oauth2_callback
from parrot.auth.oauth2.service import IntegrationsService
from parrot.auth.principal import Principal

from .test_connections_isolation_matrix import FakeCredentialStore, FakeManager, MemRedis
from .helpers import make_mock_db as _make_mock_db


@pytest.mark.asyncio
async def test_e2e_web_connect_principal_keyed(
    web_user_id: str,
) -> None:
    """A web callback persists the principal connection and lists it as active."""
    manager = FakeManager(
        "client",
        "https://app.example.com/oauth/callback",
        client_secret="secret",
        redis_client=MemRedis(),
        credential_store=FakeCredentialStore(),
    )
    OAuth2ProviderRegistry().register(JiraOAuth2Provider(manager=manager))
    web_user_id = "1042"
    principal = Principal(user_id=web_user_id, channel="web", channel_user_id=web_user_id)
    _, nonce = await manager.create_authorization_url(
        "web",
        web_user_id,
        principal=principal,
        extra_state={"provider_id": "jira", "return_origin": "https://app.example.com"},
    )

    app = web.Application()
    app["oauth2_manager_jira"] = manager
    request = make_mocked_request("GET", f"/api/auth/jira/callback?code=code-1&state={nonce}", app=app)
    mock_db_cls, mock_db = _make_mock_db()
    mock_db.read_one = AsyncMock(return_value=None)

    with (
        patch("parrot.auth.oauth2_routes.WEB_OAUTH_ALLOWED_ORIGINS", ["https://app.example.com"]),
        patch("parrot.auth.oauth2.persistence.DocumentDb", mock_db_cls),
    ):
        response = await make_oauth2_callback("jira")(request)

    assert response.status == 200
    assert "success: true" in response.text
    assert await manager.get_valid_token("web", web_user_id) is not None

    row = UsersIntegrationRow(
        user_id=web_user_id,
        provider="jira",
        account_id="account-1",
        display_name="Test Account",
        channels=["web"],
        scopes=["read"],
        connected_at=datetime.now(tz=timezone.utc),
    )
    list_request = MagicMock()
    list_request.app = {"abac": MagicMock(is_allowed=AsyncMock(return_value=True))}
    list_request.get = MagicMock(return_value=None)
    with (
        patch("parrot.auth.oauth2.service.list_users_integrations", AsyncMock(return_value=[row])),
        patch.object(IntegrationsService, "_token_status", AsyncMock(return_value="connected")),
    ):
        descriptors = await IntegrationsService().list_for_principal(web_user_id, request=list_request)

    assert descriptors[0].provider == "jira"
    assert descriptors[0].status == "connected"
    assert descriptors[0].account_id == "account-1"


@pytest.mark.asyncio
async def test_web_connect_rejects_state_without_principal() -> None:
    """The generic callback fails closed when a state has no Navigator principal."""
    manager = MagicMock()
    manager.handle_callback = AsyncMock(
        return_value=(
            MagicMock(),
            {"channel": "web", "extra": {"return_origin": "https://app.example.com"}},
        )
    )
    app = web.Application()
    app["oauth2_manager_jira"] = manager
    request = make_mocked_request("GET", "/api/auth/jira/callback?code=c&state=s", app=app)

    with patch("parrot.auth.oauth2_routes.WEB_OAUTH_ALLOWED_ORIGINS", ["https://app.example.com"]):
        response = await make_oauth2_callback("jira")(request)

    assert response.status == 400
    assert "missing_user" in response.text
