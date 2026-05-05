"""E2E integration tests: happy-path web connect → enable → disconnect.

Tests
-----
- test_e2e_web_connect_jira_happy_path (spec §4 test 1)
- test_e2e_disconnect_removes_credential_and_enablement (spec §4 test 3)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from parrot.integrations.oauth2.models import (
    ConnectInitResponse,
    IntegrationDescriptor,
    UsersIntegrationRow,
)
from parrot.integrations.oauth2.service import IntegrationsService


from .helpers import make_mock_db as _make_mock_db


class TestE2EWebConnectJiraHappyPath:
    """Full connect → callback → enable chain — no real Atlassian, no real DB."""

    @pytest.mark.asyncio
    async def test_start_connect_returns_auth_url_and_state(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
        allowed_origins: list[str],
    ) -> None:
        """IntegrationsService.start_connect validates origin and returns auth_url."""
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.service._get_allowed_origins",
            return_value=["https://app.example.com"],
        ):
            result = await svc.start_connect(
                user_id=web_user_id,
                agent_id="test-agent",
                provider_id="jira",
                return_origin="https://app.example.com",
            )

        assert isinstance(result, ConnectInitResponse)
        assert "auth.atlassian.com" in result.auth_url
        assert result.state == "test-nonce-123"
        assert "read:jira-work" in result.scopes

    @pytest.mark.asyncio
    async def test_start_connect_invalid_origin_raises_value_error(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
        allowed_origins: list[str],
    ) -> None:
        """start_connect raises ValueError for disallowed return_origin."""
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.service._get_allowed_origins",
            return_value=["https://app.example.com"],
        ):
            with pytest.raises(ValueError, match="not in the list of allowed"):
                await svc.start_connect(
                    user_id=web_user_id,
                    agent_id="test-agent",
                    provider_id="jira",
                    return_origin="https://evil.example.com",
                )

    @pytest.mark.asyncio
    async def test_persist_credential_writes_integration_row(
        self,
        web_user_id: str,
        jira_token_set_factory: Callable[..., Any],
        registered_jira_provider: MagicMock,
    ) -> None:
        """persist_credential writes a UsersIntegrationRow to DocumentDB."""
        mock_db_cls, mock_db = _make_mock_db()
        token_set = jira_token_set_factory()
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            row = await svc.persist_credential(
                user_id=web_user_id,
                provider_id="jira",
                token_set=token_set,
            )

        assert isinstance(row, UsersIntegrationRow)
        assert row.user_id == web_user_id
        assert row.provider == "jira"
        assert row.account_id == "acct-1"
        assert row.channel == "web"
        # Verify DocumentDB upsert was called exactly once
        mock_db.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_enable_writes_toolkit_row(
        self,
        web_user_id: str,
        sample_integration_row: UsersIntegrationRow,
        registered_jira_provider: MagicMock,
    ) -> None:
        """confirm_enable upserts a user_agent_toolkits row and returns descriptor."""
        mock_db_cls, mock_db = _make_mock_db()
        # read_one returns the credential row
        mock_db.read_one = AsyncMock(return_value=sample_integration_row.model_dump())
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            descriptor = await svc.confirm_enable(
                user_id=web_user_id,
                agent_id="test-agent",
                provider_id="jira",
            )

        assert isinstance(descriptor, IntegrationDescriptor)
        assert descriptor.connected is True
        assert descriptor.enabled_on_agent is True
        assert descriptor.provider == "jira"
        # update_one called twice: read_one for credential + upsert toolkit row
        mock_db.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_happy_path_connect_persist_enable(
        self,
        web_user_id: str,
        jira_token_set_factory: Callable[..., Any],
        sample_integration_row: UsersIntegrationRow,
        registered_jira_provider: MagicMock,
        allowed_origins: list[str],
    ) -> None:
        """Full chain: start_connect → persist_credential → confirm_enable."""
        mock_db_cls, mock_db = _make_mock_db()
        token_set = jira_token_set_factory()
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            with patch(
                "parrot.integrations.oauth2.service._get_allowed_origins",
                return_value=["https://app.example.com"],
            ):
                # Step 1: start connect
                connect_resp = await svc.start_connect(
                    user_id=web_user_id,
                    agent_id="test-agent",
                    provider_id="jira",
                    return_origin="https://app.example.com",
                )
                assert connect_resp.auth_url

                # Step 2: persist credential (simulating callback completion)
                row = await svc.persist_credential(
                    user_id=web_user_id,
                    provider_id="jira",
                    token_set=token_set,
                )
                assert row.user_id == web_user_id

                # Step 3: confirm enable — re-reads credential row
                mock_db.read_one = AsyncMock(
                    return_value=sample_integration_row.model_dump()
                )
                descriptor = await svc.confirm_enable(
                    user_id=web_user_id,
                    agent_id="test-agent",
                    provider_id="jira",
                )
                assert descriptor.connected is True
                assert descriptor.enabled_on_agent is True


class TestE2EDisconnectRemovesCredentialAndEnablement:
    """Disconnect cascade: removes both persistence rows."""

    @pytest.mark.asyncio
    async def test_disconnect_cascade_deletes_both_collections(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
    ) -> None:
        """disconnect() calls delete_many on both collections."""
        mock_db_cls, mock_db = _make_mock_db()
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            response = await svc.disconnect(
                user_id=web_user_id,
                agent_id="test-agent",
                provider_id="jira",
            )

        assert response.provider == "jira"
        assert response.disconnected is True
        # delete_many called twice: once for user_agent_toolkits, once for users_integrations
        assert mock_db.delete_many.call_count == 2

    @pytest.mark.asyncio
    async def test_disconnect_is_idempotent(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
    ) -> None:
        """Calling disconnect twice does not raise — it is a no-op on second call."""
        mock_db_cls, mock_db = _make_mock_db()
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            resp1 = await svc.disconnect(
                user_id=web_user_id,
                agent_id="test-agent",
                provider_id="jira",
            )
            resp2 = await svc.disconnect(
                user_id=web_user_id,
                agent_id="test-agent",
                provider_id="jira",
            )

        assert resp1.disconnected is True
        assert resp2.disconnected is True
        # delete_many called 4 times total (2 per call)
        assert mock_db.delete_many.call_count == 4

    @pytest.mark.asyncio
    async def test_confirm_enable_raises_when_no_credential(
        self,
        web_user_id: str,
        registered_jira_provider: MagicMock,
    ) -> None:
        """confirm_enable raises LookupError when users_integrations row absent."""
        mock_db_cls, mock_db = _make_mock_db()
        mock_db.read_one = AsyncMock(return_value=None)
        svc = IntegrationsService()

        with patch(
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            with pytest.raises(LookupError, match="No credential found"):
                await svc.confirm_enable(
                    user_id=web_user_id,
                    agent_id="test-agent",
                    provider_id="jira",
                )


class TestE2EWebCallbackOriginRejection:
    """Defense-in-depth: _handle_web_callback rejects tampered return_origin."""

    @pytest.mark.asyncio
    async def test_callback_rejects_invalid_return_origin(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """_handle_web_callback returns 400 when state's return_origin is not allowed."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        # State payload contains an evil return_origin that was not in the allowlist
        state_payload = {
            "channel": "web",
            "user_id": "web-user-1",
            "extra": {
                "return_origin": "https://evil.example.com",
                "provider_id": "jira",
                "agent_id": "test-agent",
            },
        }

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(
            return_value=(token_set, state_payload)
        )

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = None
        app["telegram_jira_session_stamper"] = None

        request = make_mocked_request(
            "GET",
            "/api/auth/jira/callback?code=test-code&state=test-state",
            app=app,
        )

        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ):
            response = await jira_oauth_callback(request)

        # The callback must reject the tampered origin
        assert response.status == 400
        assert response.content_type == "text/html"

    @pytest.mark.asyncio
    async def test_callback_accepts_valid_return_origin(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """_handle_web_callback succeeds when return_origin matches the allowlist."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        state_payload = {
            "channel": "web",
            "user_id": "web-user-1",
            "extra": {
                "return_origin": "https://app.example.com",
                "provider_id": "jira",
                "agent_id": "test-agent",
            },
        }

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(
            return_value=(token_set, state_payload)
        )

        mock_db_cls, mock_db = _make_mock_db()

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = None
        app["telegram_jira_session_stamper"] = None

        request = make_mocked_request(
            "GET",
            "/api/auth/jira/callback?code=test-code&state=test-state",
            app=app,
        )

        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ):
            with patch(
                "parrot.integrations.oauth2.persistence.DocumentDb",
                mock_db_cls,
            ):
                response = await jira_oauth_callback(request)

        assert response.status == 200
        assert response.content_type == "text/html"

    @pytest.mark.asyncio
    async def test_callback_reads_provider_id_from_state(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """_handle_web_callback uses provider_id from state, not a hardcoded 'jira'."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        # provider_id set to "github" — callback must persist using that provider
        state_payload = {
            "channel": "web",
            "user_id": "web-user-2",
            "extra": {
                "return_origin": "https://app.example.com",
                "provider_id": "github",
                "agent_id": "test-agent",
            },
        }

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(
            return_value=(token_set, state_payload)
        )

        mock_db_cls, mock_db = _make_mock_db()
        persist_calls: list = []

        async def fake_persist(user_id: str, provider_id: str, ts: Any) -> MagicMock:
            persist_calls.append((user_id, provider_id))
            return MagicMock()

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = None
        app["telegram_jira_session_stamper"] = None

        request = make_mocked_request(
            "GET",
            "/api/auth/jira/callback?code=test-code&state=test-state",
            app=app,
        )

        with patch(
            "parrot.auth.routes.WEB_OAUTH_ALLOWED_ORIGINS",
            ["https://app.example.com"],
        ):
            with patch(
                "parrot.auth.routes.IntegrationsService.persist_credential",
                side_effect=fake_persist,
            ):
                response = await jira_oauth_callback(request)

        assert response.status == 200
        assert len(persist_calls) == 1
        # provider_id must be "github", not the old hardcoded "jira"
        assert persist_calls[0][1] == "github"
