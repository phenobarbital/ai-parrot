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


#: A realistic Azure AD object id — a GUID, NOT a bigint. Writing this into
#: auth.user_identities.user_id is the defect issue:187ce3fe3b93 reported.
AAD_GUID = "7f1c0b2e-9a3d-4c8e-9b61-0c3f1e0a5d44"
#: The navigator-auth user id (auth.users.user_id is bigint).
NAV_USER_ID = "9000123456"


def _state_payload(*, nav_user_id: str | None = NAV_USER_ID, conv_ref: bool = True):
    """Build a Teams OAuth state as JiraOAuthManager produces it.

    Channel-specific data is nested under ``extra``; ``user_id`` is the Teams
    AAD object id at both levels, and ``nav_user_id`` (when the user is
    authenticated) rides in ``extra`` only.
    """
    extra = {"channel": "msteams", "user_id": AAD_GUID}
    if conv_ref:
        extra["conversation_reference"] = {
            "conversation": {"id": "conv-123", "tenantId": "tenant-456"},
            "bot": {"id": "bot-app-id"},
            "user": {"id": AAD_GUID, "aadObjectId": AAD_GUID},
        }
    if nav_user_id is not None:
        extra["nav_user_id"] = nav_user_id
    return {"channel": "msteams", "user_id": AAD_GUID, "extra": extra}


@pytest.fixture
def msteams_state_payload():
    """State payload for an authenticated Teams user."""
    return _state_payload()


# ---------------------------------------------------------------------------
# MSTeamsOAuthNotifier tests
# ---------------------------------------------------------------------------

def _make_success_request(app=None):
    """Build a mock request that simulates a successful OAuth callback (no ?error=)."""
    mock_request = MagicMock()
    mock_request.app = app if app is not None else {}
    # Ensure rel_url.query.get("error") returns None (no error in the callback URL)
    mock_request.rel_url.query.get.return_value = None
    return mock_request


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

        # Patch at the botbuilder.schema level since ConversationReference is
        # imported inside the function body at runtime.
        with patch(
            "botbuilder.schema.ConversationReference.deserialize",
            return_value=MagicMock(),
        ):
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
            "botbuilder.schema.ConversationReference.deserialize",
            return_value=MagicMock(),
        ):
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
            "botbuilder.schema.ConversationReference.deserialize",
            return_value=MagicMock(),
        ):
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

        mock_request = _make_success_request()

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )

        assert response.content_type == "text/html"
        assert response.status == 200

    @pytest.mark.asyncio
    async def test_html_contains_display_name(self, mock_token_set, msteams_state_payload):
        """HTML success page includes Jira display name."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_request = _make_success_request()

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )
        assert "Jane Doe" in response.text
        assert "myco.atlassian.net" in response.text  # lgtm[py/incomplete-url-substring-sanitization]

    @pytest.mark.asyncio
    async def test_html_instructs_user_to_return_to_teams(
        self, mock_token_set, msteams_state_payload
    ):
        """HTML success page tells user to return to Teams."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_request = _make_success_request()

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

        mock_request = _make_success_request(
            app={"identity_mapping_service": mock_identity_service}
        )

        await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )

        mock_identity_service.upsert_identity.assert_called_once()
        call_kwargs = mock_identity_service.upsert_identity.call_args[1]
        assert call_kwargs["auth_provider"] == "msteams"
        assert call_kwargs["nav_user_id"] == NAV_USER_ID
        assert call_kwargs["provider_user_id"] == AAD_GUID
        assert call_kwargs["auth_data"]["aad_object_id"] == AAD_GUID

    @pytest.mark.asyncio
    async def test_fires_proactive_notification_when_notifier_available(
        self, mock_token_set, msteams_state_payload
    ):
        """Schedules proactive notification when notifier is on the app."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        mock_request = _make_success_request(
            app={"msteams_jira_oauth_notifier": mock_notifier}
        )

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
            "user_id": AAD_GUID,
            # no conversation_reference
        }

        mock_notifier = MagicMock()
        mock_notifier.notify_connected = AsyncMock()

        mock_request = _make_success_request(
            app={"msteams_jira_oauth_notifier": mock_notifier}
        )

        with patch("asyncio.create_task") as mock_create_task:
            await handle_msteams_jira_callback(mock_request, mock_token_set, state_payload)
            mock_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_param_returns_error_html(self, mock_token_set, msteams_state_payload):
        """When Atlassian sends ?error=access_denied, returns error HTML."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        mock_request = MagicMock()
        mock_request.app = {}

        def _query_get(key, default=None):
            values = {"error": "access_denied", "error_description": "User denied access"}
            return values.get(key, default)
        mock_request.rel_url.query.get.side_effect = _query_get

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )
        assert response.status == 200
        assert "Authorization Failed" in response.text
        assert "User denied access" in response.text


# ---------------------------------------------------------------------------
# State-payload shape parity (regression for the FEAT-225 nesting bug)
# ---------------------------------------------------------------------------

class _FakeRedis:
    """Minimal in-memory async Redis stand-in for shape-parity tests."""

    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)


class TestStatePayloadShapeParity:
    """Drive the *real* payload JiraOAuthManager produces into the handler.

    Guards against drift between what ``create_authorization_url`` stores
    (conversation_reference nested under ``extra``) and what
    ``handle_msteams_jira_callback`` reads. The original FEAT-225 code read
    ``conversation_reference`` at top level, so the proactive confirmation
    silently no-op'd in production despite green unit tests.
    """

    @pytest.mark.asyncio
    async def test_manager_payload_drives_proactive_notification(self, mock_token_set):
        from parrot.auth.jira_oauth import JiraOAuthManager
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        fake = _FakeRedis()
        mgr = JiraOAuthManager(
            client_id="cid",
            client_secret="sec",
            redirect_uri="https://example/api/auth/jira/callback",
            redis_client=fake,
        )
        conv_ref = {
            "conversation": {"id": "conv-123", "tenantId": "tenant-456"},
            "bot": {"id": "bot-app-id"},
            "user": {"id": AAD_GUID},
        }
        _url, nonce = await mgr.create_authorization_url(
            "msteams",
            AAD_GUID,
            extra_state={
                "channel": "msteams",
                "user_id": AAD_GUID,
                "nav_user_id": NAV_USER_ID,
                "conversation_reference": conv_ref,
            },
        )
        state_payload = await mgr.consume_state(nonce)

        identity = MagicMock()
        identity.upsert_identity = AsyncMock()
        notifier = MagicMock()
        notifier.notify_connected = AsyncMock()
        mock_request = _make_success_request(
            app={
                "identity_mapping_service": identity,
                "msteams_jira_oauth_notifier": notifier,
            }
        )

        with patch("asyncio.create_task") as mock_create_task:
            await handle_msteams_jira_callback(mock_request, mock_token_set, state_payload)
            mock_create_task.assert_called_once()

        identity.upsert_identity.assert_called_once()
        call_kwargs = identity.upsert_identity.call_args[1]
        assert call_kwargs["nav_user_id"] == NAV_USER_ID
        assert call_kwargs["provider_user_id"] == AAD_GUID
        assert call_kwargs["auth_data"]["tenant_id"] == "tenant-456"


class TestNavUserIdFailsClosed:
    """The identity row must never be written with a channel-scoped id.

    Regression guard for ``issue:187ce3fe3b93``: ``/connect_jira`` used to put
    the AAD object id (a GUID) in the state's ``user_id`` and the callback
    passed it straight to ``upsert_identity(nav_user_id=...)``, where
    ``$1::text::bigint`` rejected it — so every real Teams user got the
    "could not be saved" warning. These tests need no Postgres.
    """

    @pytest.mark.asyncio
    async def test_guid_only_state_skips_identity_write(self, mock_token_set):
        """A state without nav_user_id writes nothing — and warns nobody."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        identity = MagicMock()
        identity.upsert_identity = AsyncMock()
        mock_request = _make_success_request(app={"identity_mapping_service": identity})

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, _state_payload(nav_user_id=None)
        )

        identity.upsert_identity.assert_not_called()
        assert "identity-warning" not in response.text

    @pytest.mark.asyncio
    async def test_numeric_nav_user_id_is_written(self, mock_token_set, msteams_state_payload):
        """The bigint goes to user_id, the GUID to provider_user_id."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        identity = MagicMock()
        identity.upsert_identity = AsyncMock()
        mock_request = _make_success_request(app={"identity_mapping_service": identity})

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, msteams_state_payload
        )

        call_kwargs = identity.upsert_identity.call_args[1]
        assert call_kwargs["nav_user_id"] == NAV_USER_ID
        assert call_kwargs["nav_user_id"].isdigit()
        assert call_kwargs["provider_user_id"] == AAD_GUID
        assert call_kwargs["auth_data"]["aad_object_id"] == AAD_GUID
        assert "identity-warning" not in response.text

    @pytest.mark.asyncio
    async def test_non_numeric_nav_user_id_warns_and_skips(self, mock_token_set):
        """A GUID smuggled into nav_user_id never reaches the database."""
        from parrot.integrations.msteams.oauth_callback import handle_msteams_jira_callback

        identity = MagicMock()
        identity.upsert_identity = AsyncMock()
        mock_request = _make_success_request(app={"identity_mapping_service": identity})

        response = await handle_msteams_jira_callback(
            mock_request, mock_token_set, _state_payload(nav_user_id=AAD_GUID)
        )

        identity.upsert_identity.assert_not_called()
        assert "identity-warning" in response.text
