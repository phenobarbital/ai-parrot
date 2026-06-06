"""Unit tests for SlackOAuthNotifier and handle_slack_jira_callback (FEAT-225 / TASK-1469)."""
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
def slack_state_payload():
    """State payload for a Slack-originated OAuth callback."""
    return {
        "channel": "slack",
        "team_id": "T0001",
        "slack_user_id": "U1234",
        "user_id": "T0001:U1234",
    }


# ---------------------------------------------------------------------------
# SlackOAuthNotifier tests
# ---------------------------------------------------------------------------

class TestSlackOAuthNotifier:
    @pytest.mark.asyncio
    async def test_notify_connected_sends_dm(self):
        """notify_connected calls chat_postMessage with the user's Slack ID."""
        from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier

        with patch(
            "parrot.integrations.slack.oauth_callback.SlackOAuthNotifier.__init__",
            lambda self, token: None,
        ):
            notifier = SlackOAuthNotifier.__new__(SlackOAuthNotifier)
            notifier._bot_token = "xoxb-test"
            notifier.logger = MagicMock()
            mock_client = MagicMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})
            notifier._client = mock_client

            await notifier.notify_connected("T001", "U123", "Jane", "myco.atlassian.net")

            mock_client.chat_postMessage.assert_called_once()
            call_kwargs = mock_client.chat_postMessage.call_args[1]
            assert call_kwargs.get("channel") == "U123" or mock_client.chat_postMessage.call_args[0][0] == "U123"

    @pytest.mark.asyncio
    async def test_notify_failure_sends_dm(self):
        """notify_failure calls chat_postMessage with failure message."""
        from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier

        with patch(
            "parrot.integrations.slack.oauth_callback.SlackOAuthNotifier.__init__",
            lambda self, token: None,
        ):
            notifier = SlackOAuthNotifier.__new__(SlackOAuthNotifier)
            notifier._bot_token = "xoxb-test"
            notifier.logger = MagicMock()
            mock_client = MagicMock()
            mock_client.chat_postMessage = AsyncMock(return_value={"ok": True})
            notifier._client = mock_client

            await notifier.notify_failure("T001", "U123", "expired nonce")

            mock_client.chat_postMessage.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_connected_swallows_exceptions(self):
        """notify_connected does not raise when chat_postMessage fails."""
        from parrot.integrations.slack.oauth_callback import SlackOAuthNotifier

        with patch(
            "parrot.integrations.slack.oauth_callback.SlackOAuthNotifier.__init__",
            lambda self, token: None,
        ):
            notifier = SlackOAuthNotifier.__new__(SlackOAuthNotifier)
            notifier._bot_token = "xoxb-test"
            notifier.logger = MagicMock()
            mock_client = MagicMock()
            mock_client.chat_postMessage = AsyncMock(side_effect=Exception("API error"))
            notifier._client = mock_client

            # Should not raise
            await notifier.notify_connected("T001", "U123", "Jane", "site.net")


# ---------------------------------------------------------------------------
# handle_slack_jira_callback tests
# ---------------------------------------------------------------------------

def _make_success_request(app=None):
    """Build a mock request that simulates a successful OAuth callback (no ?error=)."""
    mock_request = MagicMock()
    mock_request.app = app if app is not None else {}
    # Ensure rel_url.query.get("error") returns None (no error in the callback URL)
    mock_request.rel_url.query.get.return_value = None
    return mock_request


class TestHandleSlackJiraCallback:
    @pytest.mark.asyncio
    async def test_returns_html_success_page(self, mock_token_set, slack_state_payload):
        """Returns an HTML response with 200 status."""
        from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback

        mock_request = _make_success_request()

        response = await handle_slack_jira_callback(
            mock_request, mock_token_set, slack_state_payload
        )

        assert response.content_type == "text/html"
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_writes_identity_when_service_available(
        self, mock_token_set, slack_state_payload
    ):
        """Calls identity_mapping_service.upsert_identity when available."""
        from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback

        mock_identity_service = MagicMock()
        mock_identity_service.upsert_identity = AsyncMock()

        mock_request = _make_success_request(
            app={"identity_mapping_service": mock_identity_service}
        )

        await handle_slack_jira_callback(
            mock_request, mock_token_set, slack_state_payload
        )

        mock_identity_service.upsert_identity.assert_called_once_with(
            nav_user_id="T0001:U1234",
            auth_provider="slack",
            auth_data={"team_id": "T0001", "slack_user_id": "U1234"},
            display_name="Jane Doe",
            email="jane@myco.com",
        )

    @pytest.mark.asyncio
    async def test_fires_dm_notification_when_notifier_available(
        self, mock_token_set, slack_state_payload
    ):
        """Schedules DM notification when notifier is on the app."""
        from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        mock_request = _make_success_request(
            app={"slack_jira_oauth_notifier": mock_notifier}
        )

        with patch("asyncio.create_task") as mock_create_task:
            await handle_slack_jira_callback(
                mock_request, mock_token_set, slack_state_payload
            )
            mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_identity_write_when_service_missing(
        self, mock_token_set, slack_state_payload
    ):
        """Does not fail when identity_mapping_service is absent."""
        from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback

        mock_request = _make_success_request()  # no identity service

        response = await handle_slack_jira_callback(
            mock_request, mock_token_set, slack_state_payload
        )
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_html_contains_display_name(self, mock_token_set, slack_state_payload):
        """HTML success page includes the user's Jira display name."""
        from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback

        mock_request = _make_success_request()

        response = await handle_slack_jira_callback(
            mock_request, mock_token_set, slack_state_payload
        )
        body = response.text
        assert "Jane Doe" in body
        assert "myco.atlassian.net" in body

    @pytest.mark.asyncio
    async def test_error_param_returns_error_html(self, mock_token_set, slack_state_payload):
        """When Atlassian sends ?error=access_denied, returns error HTML."""
        from parrot.integrations.slack.oauth_callback import handle_slack_jira_callback

        mock_request = MagicMock()
        mock_request.app = {}
        # Simulate Atlassian sending back an error
        def _query_get(key, default=None):
            values = {"error": "access_denied", "error_description": "User denied access"}
            return values.get(key, default)
        mock_request.rel_url.query.get.side_effect = _query_get

        response = await handle_slack_jira_callback(
            mock_request, mock_token_set, slack_state_payload
        )
        assert response.status == 200
        assert "Authorization Failed" in response.text
        assert "User denied access" in response.text
