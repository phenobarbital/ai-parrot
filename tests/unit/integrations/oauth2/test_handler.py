"""Compatibility handler and generic OAuth callback tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from parrot.auth.oauth2.models import ConnectInitResponse, DisconnectResponse, IntegrationDescriptor
from parrot.auth.oauth2_base import CredentialPersistenceError
from parrot.auth.oauth2_routes import make_oauth2_callback


def handler_request(method: str, suffix: str) -> web.Request:
    """Build an authenticated request for the legacy agent-scoped handler."""
    request = make_mocked_request(
        method,
        f"/api/v1/agents/integrations/agent-1/jira/{suffix}" if suffix else "/api/v1/agents/integrations/agent-1",
        headers={"Origin": "https://app.example.com"},
    )
    request["authenticated"] = True
    request["user_id"] = "42"
    request.match_info["agent_id"] = "agent-1"
    request.match_info["provider"] = "jira"
    return request


@pytest.mark.asyncio
async def test_get_keeps_agent_scoped_alias() -> None:
    """The existing GET route still delegates through list_for_user."""
    request = handler_request("GET", "")
    with (
        patch("navigator_auth.decorators.get_session", AsyncMock(return_value=None)),
        patch("parrot.handlers.integrations.IntegrationsService") as service_class,
    ):
        service_class.return_value.list_for_user = AsyncMock(return_value=[])
        from parrot.handlers.integrations import IntegrationsHandler

        response = await IntegrationsHandler(request).get()

    assert json.loads(response.body) == []
    service_class.return_value.list_for_user.assert_awaited_once_with("42", "agent-1", request=request)


@pytest.mark.asyncio
async def test_post_connect_uses_principal_service_signature() -> None:
    """The compatibility route no longer forwards agent_id to start_connect."""
    request = handler_request("POST", "connect")
    response_model = ConnectInitResponse(auth_url="https://idp", state="nonce", scopes=["read"])
    with (
        patch("parrot.handlers.integrations.WEB_OAUTH_ALLOWED_ORIGINS", ["https://app.example.com"]),
        patch("parrot.handlers.integrations.IntegrationsService") as service_class,
        patch.object(request, "json", AsyncMock(return_value={})),
    ):
        service_class.return_value.start_connect = AsyncMock(return_value=response_model)
        from parrot.handlers.integrations import IntegrationsHandler

        response = await IntegrationsHandler(request)._post_connect()

    assert response.status == 200
    service_class.return_value.start_connect.assert_awaited_once_with(
        "42", "jira", "https://app.example.com", request=request
    )


@pytest.mark.asyncio
async def test_post_connect_permission_denial_is_403() -> None:
    """PBAC denial is surfaced without creating OAuth state."""
    request = handler_request("POST", "connect")
    with (
        patch("parrot.handlers.integrations.WEB_OAUTH_ALLOWED_ORIGINS", ["https://app.example.com"]),
        patch("parrot.handlers.integrations.IntegrationsService") as service_class,
        patch.object(request, "json", AsyncMock(return_value={})),
    ):
        service_class.return_value.start_connect = AsyncMock(side_effect=PermissionError)
        from parrot.handlers.integrations import IntegrationsHandler

        response = await IntegrationsHandler(request)._post_connect()

    assert response.status == 403
    assert json.loads(response.body) == {"error": "forbidden"}


@pytest.mark.asyncio
async def test_confirm_enable_removed_enable_route_noop() -> None:
    """POST /enable returns status and performs no enablement write."""
    request = handler_request("POST", "enable")
    descriptor = IntegrationDescriptor(provider="jira", display_name="Jira", status="connected")
    with (
        patch("navigator_auth.decorators.get_session", AsyncMock(return_value=None)),
        patch("parrot.handlers.integrations.IntegrationsService") as service_class,
    ):
        service_class.return_value.status = AsyncMock(return_value=descriptor)
        from parrot.handlers.integrations import IntegrationsHandler

        response = await IntegrationsHandler(request)._post_enable()

    assert response.status == 200
    service_class.return_value.status.assert_awaited_once_with("42", "jira", request=request)
    assert json.loads(response.body)["integration"]["status"] == "connected"


@pytest.mark.asyncio
async def test_delete_uses_principal_service_signature() -> None:
    """DELETE forwards the authenticated request for PBAC evaluation."""
    request = handler_request("DELETE", "")
    result = DisconnectResponse(provider="jira")
    with (
        patch("navigator_auth.decorators.get_session", AsyncMock(return_value=None)),
        patch("parrot.handlers.integrations.IntegrationsService") as service_class,
    ):
        service_class.return_value.disconnect = AsyncMock(return_value=result)
        from parrot.handlers.integrations import IntegrationsHandler

        response = await IntegrationsHandler(request).delete()

    assert response.status == 200
    service_class.return_value.disconnect.assert_awaited_once_with("42", "jira", request=request)


@pytest.mark.asyncio
async def test_generic_callback_persists_non_web_channel() -> None:
    """Every successful channel callback records principal-level metadata."""
    tokens = SimpleNamespace(display_name="User", account_id="account-1")
    manager = SimpleNamespace(
        handle_callback=AsyncMock(
            return_value=(
                tokens,
                {
                    "channel": "telegram",
                    "nav_user_id": "42",
                    "canonical_identity": "person@example.com",
                },
            )
        )
    )
    request = make_mocked_request(
        "GET",
        "/callback?code=code&state=state",
        app={"oauth2_manager_jira": manager},
    )
    persist = AsyncMock()
    with patch("parrot.auth.oauth2_routes.IntegrationsService") as service_class:
        service_class.return_value.persist_credential = persist
        response = await make_oauth2_callback("jira")(request)

    assert response.status == 200
    persist.assert_awaited_once()
    assert persist.await_args.args == ("42", "jira", tokens)
    assert persist.await_args.kwargs == {
        "channel": "telegram",
        "canonical_identity": "person@example.com",
    }


@pytest.mark.asyncio
async def test_callback_credential_persistence_error_has_no_success_page() -> None:
    """A durable-write failure is a 500 error page, never a success response."""
    manager = SimpleNamespace(
        handle_callback=AsyncMock(side_effect=CredentialPersistenceError("vault write failed"))
    )
    request = make_mocked_request(
        "GET",
        "/callback?code=code&state=state",
        app={"oauth2_manager_jira": manager},
    )

    response = await make_oauth2_callback("jira")(request)

    assert response.status == 500
    assert "could not be saved" in response.text
    assert "Connected" not in response.text
