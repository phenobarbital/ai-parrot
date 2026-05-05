"""E2E integration test: Telegram OAuth flow regression guard.

Test
----
- test_e2e_telegram_unaffected (spec §4 test 5)

Verifies that the Telegram-channel OAuth2 callback path is byte-for-byte
unchanged after FEAT-144 lands:
  - The web branch (_handle_web_callback) is NOT invoked.
  - persist_credential() (IntegrationsService) is NOT called.
  - No users_integrations write occurs.
  - The Telegram stamper and notifier paths are exercised as before.
"""
from __future__ import annotations

from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from .helpers import make_mock_db as _make_mock_db


class TestE2ETelegramUnaffected:
    """Telegram callback path regression guard."""

    @pytest.mark.asyncio
    async def test_telegram_channel_does_not_invoke_web_branch(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """When state_payload.channel == 'telegram', _handle_web_callback is skipped."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        state_payload = {
            "channel": "telegram",
            "user_id": "tg-user-99",
            "extra": {"chat_id": "99"},
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
            "parrot.auth.routes._handle_web_callback",
            new_callable=AsyncMock,
        ) as mock_web_callback:
            response = await jira_oauth_callback(request)

        # Web branch must NOT be called
        mock_web_callback.assert_not_called()
        # Response is the old Telegram success HTML
        assert response.content_type == "text/html"
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_telegram_channel_calls_stamper(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """When state_payload.channel == 'telegram', stamper is called."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        state_payload = {
            "channel": "telegram",
            "user_id": "tg-user-42",
            "extra": {"chat_id": "42"},
        }

        mock_manager = MagicMock()
        mock_manager.handle_callback = AsyncMock(
            return_value=(token_set, state_payload)
        )

        stamper_called_with: list = []

        def mock_stamper(user_id: str, ts: Any) -> None:
            stamper_called_with.append((user_id, ts))

        app = web.Application()
        app["jira_oauth_manager"] = mock_manager
        app["jira_oauth_notifier"] = None
        app["telegram_jira_session_stamper"] = mock_stamper

        request = make_mocked_request(
            "GET",
            "/api/auth/jira/callback?code=test-code&state=test-state",
            app=app,
        )

        response = await jira_oauth_callback(request)

        # Stamper must have been called for this user
        assert len(stamper_called_with) == 1
        assert stamper_called_with[0][0] == "tg-user-42"
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_telegram_channel_no_documentdb_write(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """Telegram path must NOT write to users_integrations (web-only persistence)."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        state_payload = {
            "channel": "telegram",
            "user_id": "tg-user-55",
            "extra": {},
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
            "parrot.integrations.oauth2.persistence.DocumentDb",
            mock_db_cls,
        ):
            response = await jira_oauth_callback(request)

        # NO DocumentDB write should happen for Telegram path
        mock_db.update_one.assert_not_called()
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_default_channel_falls_back_to_telegram_behavior(
        self,
        jira_token_set_factory: Callable[..., Any],
    ) -> None:
        """When channel is absent from state_payload, it defaults to 'telegram' behavior."""
        from aiohttp import web
        from aiohttp.test_utils import make_mocked_request

        from parrot.auth.routes import jira_oauth_callback

        token_set = jira_token_set_factory()
        # No 'channel' key — simulates legacy state_payload
        state_payload = {"user_id": "legacy-user", "extra": {}}

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
            "parrot.auth.routes._handle_web_callback",
            new_callable=AsyncMock,
        ) as mock_web_callback:
            with patch(
                "parrot.integrations.oauth2.persistence.DocumentDb",
                mock_db_cls,
            ):
                response = await jira_oauth_callback(request)

        # Legacy path: web branch NOT called
        mock_web_callback.assert_not_called()
        # No DocumentDB write
        mock_db.update_one.assert_not_called()
        assert response.status == 200
