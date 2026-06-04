"""Unit tests for MSTeamsOAuthNotifier and handle_msteams_jira_callback (FEAT-225 / TASK-1472)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_token_set():
    """Minimal JiraTokenSet mock."""
    token = MagicMock()
    token.display_name = "Jane Doe"
    token.site_url = "https://myco.atlassian.net"
    token.email = "jane@myco.com"
    return token


@pytest.fixture
def msteams_state_payload():
    """State payload for an MS Teams-originated OAuth callback."""
    return {
        "channel": "msteams",
        "user_id": "aad-obj-123",
        "conversation_reference": {
            "conversation": {"id": "conv-123", "tenantId": "tenant-456"},
            "bot": {"id": "bot-app-id"},
            "user": {"id": "aad-obj-123", "aadObjectId": "aad-obj-123"},
        },
    }


# ---------------------------------------------------------------------------
# MSTeamsOAuthNotifier tests
# ---------------------------------------------------------------------------

class TestMSTeamsOAuthNotifier:
    @pytest.mark.asyncio
    async def test_notify_connected_calls_continue_conversation(self):
        """notify_connected calls adapter.continue_conversation."""
        from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier

        adapter = MagicMock()
        adapter.continue_conversation = AsyncMock()
        notifier = MSTeamsOAuthNotifier(adapter=adapter, app_id="test-app-id")

        conv_ref_dict = {
            "conversation": {"id": "conv-123"},
            "bot": {"id": "bot-1"},
            "user": {"id": "user-1"},
            "channelId": "msteams",
            "serviceUrl": "https://smba.trafficmanager.net/",
        }

        with patch(
            "parrot.integrations.msteams.oauth_callback.ConversationReference"
        ) as mock_conv_ref_cls:
            mock_conv_ref = MagicMock()
            mock_conv_ref_cls.return_value.deserialize = MagicMock(return_value=mock_conv_ref)

            await notifier.notify_connected(conv_ref_dict, "Jane Doe", "myco.atlassian.net")

        adapter.continue_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_failure_calls_continue_conversation(self):
        """notify_failure calls adapter.continue_conversation."""
        from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier

        adapter = MagicMock()
        adapter.continue_conversation = AsyncMock()
        notifier = MSTeamsOAuthNotifier(adapter=adapter, app_id="test-app-id")

        conv_ref_dict = {"conversation": {"id": "conv-123"}}

        with patch(
            "parrot.integrations.msteams.oauth_callback.ConversationReference"
        ) as mock_conv_ref_cls:
            mock_conv_ref = MagicMock()
            mock_conv_ref_cls.return_value.deserialize = MagicMock(return_value=mock_conv_ref)

            await notifier.notify_failure(conv_ref_dict, "expired nonce")

        adapter.continue_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_connected_swallows_exceptions(self):
        """notify_connected does not raise when adapter.continue_conversation fails."""
        from parrot.integrations.msteams.oauth_callback import MSTeamsOAuthNotifier

        adapter = MagicMock()
        adapter.continue_conversation = AsyncMock(side_effect=Exception("adapter error"))
        notifier = MSTeamsOAuthNotifier(adapter=adapter, app_id="test-app-id")

        with patch(
            "parrot.integrations.msteams.oauth_callback.ConversationReference"
        ) as mock_conv_ref_cls:
            mock_conv_ref = MagicMock()
            mock_conv_ref_cls.return_value.deserialize = MagicMock(return_value=mock_conv_ref)

            # Should not raise
            await notifier.notify_connected({"conversation": {"id": "c"}}, "Jane", "site")


# ---------------------------------------------------------------------------
# handle_msteams_jira_callback tests
# ---------------------------------------------------------------------------

class TestHandleMSTeamsJiraCallback:
    @pytest.mark.asyncio
    async def test_returns_html_success_page(self, mock_token_set, msteams_state_payload):
        """Returns an HTML response with 200 status."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_request = MagicMock()
        mock_request.app = {}

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )

        assert response.content_type == "text/html"
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_html_contains_display_name(self, mock_token_set, msteams_state_payload):
        """HTML success page includes Jira display name."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_request = MagicMock()
        mock_request.app = {}

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )
        assert "Jane Doe" in response.text
        assert "myco.atlassian.net" in response.text

    @pytest.mark.asyncio
    async def test_html_instructs_user_to_return_to_teams(
        self, mock_token_set, msteams_state_payload
    ):
        """HTML success page tells user to return to Teams."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_request = MagicMock()
        mock_request.app = {}

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )
        assert "Teams" in response.text or "teams" in response.text.lower()

    @pytest.mark.asyncio
    async def test_writes_identity_when_service_available(
        self, mock_token_set, msteams_state_payload
    ):
        """Calls identity_mapping_service.upsert_identity when available."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_identity_service = MagicMock()
        mock_identity_service.upsert_identity = AsyncMock()

        mock_request = MagicMock()
        mock_request.app = {"identity_mapping_service": mock_identity_service}

        await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )

        mock_identity_service.upsert_identity.assert_called_once()
        call_kwargs = mock_identity_service.upsert_identity.call_args[1]
        assert call_kwargs["auth_provider"] == "msteams"
        assert call_kwargs["nav_user_id"] == "aad-obj-123"

    @pytest.mark.asyncio
    async def test_fires_proactive_notification_when_notifier_available(
        self, mock_token_set, msteams_state_payload
    ):
        """Schedules proactive notification when notifier is on the app."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        mock_request = MagicMock()
        mock_request.app = {"msteams_jira_oauth_notifier": mock_notifier}

        with patch("asyncio.create_task") as mock_create_task:
            await handle_msteams_jira_callback(
                mock_request, mock_token_set, msteams_state_payload
            )
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_notification_without_conv_ref(self, mock_token_set):
        """No notification fired when conversation_reference is absent."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        state_payload = {
            "channel": "msteams",
            "user_id": "aad-obj-123",
            # no conversation_reference
        }

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        mock_request = MagicMock()
        mock_request.app = {"msteams_jira_oauth_notifier": mock_notifier}

        with patch("asyncio.create_task") as mock_create_task:
            await handle_msteams_jira_callback(mock_request, mock_token_set, state_payload)
            mock_create_task.assert_not_called()
