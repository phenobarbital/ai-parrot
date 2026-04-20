"""Unit tests for JiraPostAuthProvider (FEAT-108 / TASK-758)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.telegram.post_auth import PostAuthProvider
from parrot.integrations.telegram.post_auth_jira import JiraPostAuthProvider


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------


def _make_token_set(**overrides):
    defaults = dict(
        access_token="at-123",
        refresh_token="rt-456",
        cloud_id="cloud-abc",
        site_url="https://site.atlassian.net",
        account_id="acc-789",
        display_name="Jira User",
        email="jira@example.com",
    )
    defaults.update(overrides)
    mock = MagicMock(spec_set=list(defaults.keys()))
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


@pytest.fixture
def mock_oauth_manager():
    m = AsyncMock()
    m.create_authorization_url = AsyncMock(
        return_value=(
            "https://auth.atlassian.com/authorize?client_id=xxx",
            "nonce-12345678",
        )
    )
    m.handle_callback = AsyncMock(
        return_value=(
            _make_token_set(),
            {
                "channel": "telegram",
                "user_id": "123456",
                "extra": {
                    "flow": "combined",
                    "telegram_id": 123456,
                    "telegram_username": "jdoe",
                    "nav_user_id": "nav-user-1",
                },
            },
        )
    )
    return m


@pytest.fixture
def mock_vault_sync():
    v = AsyncMock()
    v.store_tokens = AsyncMock()
    return v


@pytest.fixture
def mock_identity_service():
    s = AsyncMock()
    s.upsert_identity = AsyncMock()
    return s


@pytest.fixture
def provider(mock_oauth_manager, mock_identity_service, mock_vault_sync):
    return JiraPostAuthProvider(
        mock_oauth_manager, mock_identity_service, mock_vault_sync
    )


@pytest.fixture
def session():
    s = MagicMock()
    s.telegram_id = 123456
    s.telegram_username = "jdoe"
    s.nav_user_id = "nav-user-1"
    s.nav_display_name = "John Doe"
    s.nav_email = "jdoe@example.com"
    return s


# ----------------------------------------------------------------------
# build_auth_url
# ----------------------------------------------------------------------


class TestBuildAuthUrl:
    async def test_returns_atlassian_url(
        self, provider, session, mock_oauth_manager
    ):
        url = await provider.build_auth_url(
            session, MagicMock(), "https://example.com"
        )
        assert url.startswith("https://auth.atlassian.com/authorize")
        mock_oauth_manager.create_authorization_url.assert_awaited_once()

    async def test_passes_telegram_channel_and_id(
        self, provider, session, mock_oauth_manager
    ):
        await provider.build_auth_url(
            session, MagicMock(), "https://example.com"
        )
        kwargs = mock_oauth_manager.create_authorization_url.call_args.kwargs
        assert kwargs["channel"] == "telegram"
        assert kwargs["user_id"] == "123456"

    async def test_embeds_primary_auth_in_extra_state(
        self, provider, session, mock_oauth_manager
    ):
        await provider.build_auth_url(
            session, MagicMock(), "https://example.com"
        )
        extra = mock_oauth_manager.create_authorization_url.call_args.kwargs[
            "extra_state"
        ]
        assert extra["flow"] == "combined"
        assert extra["telegram_id"] == 123456
        assert extra["telegram_username"] == "jdoe"
        assert extra["nav_user_id"] == "nav-user-1"
        assert extra["nav_display_name"] == "John Doe"
        assert extra["nav_email"] == "jdoe@example.com"
        assert extra["callback_base_url"] == "https://example.com"


# ----------------------------------------------------------------------
# handle_result
# ----------------------------------------------------------------------


class TestHandleResultSuccess:
    async def test_returns_true_on_clean_exchange(
        self, provider, session, mock_vault_sync, mock_identity_service
    ):
        data = {"code": "auth-code", "state": "nonce-123"}
        result = await provider.handle_result(
            data, session, {"user_id": "nav-user-1"}
        )
        assert result is True
        mock_vault_sync.store_tokens.assert_awaited_once()
        assert mock_identity_service.upsert_identity.await_count == 2

    async def test_vault_called_with_jira_provider_and_flat_keys(
        self, provider, session, mock_vault_sync
    ):
        await provider.handle_result(
            {"code": "c", "state": "s"}, session, {"user_id": "nav-user-1"}
        )
        kwargs = mock_vault_sync.store_tokens.call_args.kwargs
        assert kwargs["nav_user_id"] == "nav-user-1"
        assert kwargs["provider"] == "jira"
        tokens = kwargs["tokens"]
        assert tokens["access_token"] == "at-123"
        assert tokens["refresh_token"] == "rt-456"
        assert tokens["cloud_id"] == "cloud-abc"
        assert tokens["site_url"] == "https://site.atlassian.net"
        assert tokens["account_id"] == "acc-789"

    async def test_identity_upsert_creates_telegram_and_jira_records(
        self, provider, session, mock_identity_service
    ):
        await provider.handle_result(
            {"code": "c", "state": "s"},
            session,
            {
                "user_id": "nav-user-1",
                "display_name": "John Doe",
                "email": "jdoe@example.com",
            },
        )
        calls = mock_identity_service.upsert_identity.await_args_list
        providers = [c.kwargs["auth_provider"] for c in calls]
        assert set(providers) == {"telegram", "jira"}

        tg_call = next(c for c in calls
                       if c.kwargs["auth_provider"] == "telegram")
        assert tg_call.kwargs["auth_data"]["telegram_id"] == 123456
        assert tg_call.kwargs["auth_data"]["username"] == "jdoe"

        jira_call = next(c for c in calls
                         if c.kwargs["auth_provider"] == "jira")
        assert jira_call.kwargs["auth_data"]["account_id"] == "acc-789"
        assert jira_call.kwargs["auth_data"]["cloud_id"] == "cloud-abc"
        assert jira_call.kwargs["auth_data"]["site_url"] == "https://site.atlassian.net"

    async def test_falls_back_to_extra_state_user_id(
        self, provider, session, mock_vault_sync
    ):
        session.nav_user_id = None  # Force fallback
        await provider.handle_result(
            {"code": "c", "state": "s"}, session, {}  # No primary_auth_data
        )
        # Should still succeed using the extra.nav_user_id in the state payload.
        kwargs = mock_vault_sync.store_tokens.call_args.kwargs
        assert kwargs["nav_user_id"] == "nav-user-1"


class TestHandleResultFailure:
    async def test_missing_code_returns_false(
        self, provider, session
    ):
        result = await provider.handle_result(
            {"state": "s"}, session, {}
        )
        assert result is False

    async def test_missing_state_returns_false(
        self, provider, session
    ):
        result = await provider.handle_result(
            {"code": "c"}, session, {}
        )
        assert result is False

    async def test_oauth_exchange_failure_returns_false(
        self, provider, session, mock_oauth_manager, mock_vault_sync
    ):
        mock_oauth_manager.handle_callback.side_effect = ValueError(
            "Invalid state"
        )
        result = await provider.handle_result(
            {"code": "bad", "state": "bad"}, session, {}
        )
        assert result is False
        # No side effects on vault if the OAuth exchange fails.
        mock_vault_sync.store_tokens.assert_not_called()

    async def test_vault_failure_does_not_block_success(
        self, provider, session, mock_vault_sync
    ):
        """Vault write errors are swallowed — core auth still succeeds."""
        mock_vault_sync.store_tokens.side_effect = RuntimeError(
            "vault unavailable"
        )
        result = await provider.handle_result(
            {"code": "c", "state": "s"}, session, {"user_id": "nav-user-1"}
        )
        # Vault failed but the OAuth succeeded → overall True.
        assert result is True

    async def test_identity_failure_does_not_block_success(
        self, provider, session, mock_identity_service
    ):
        mock_identity_service.upsert_identity.side_effect = RuntimeError(
            "db down"
        )
        result = await provider.handle_result(
            {"code": "c", "state": "s"}, session, {"user_id": "nav-user-1"}
        )
        assert result is True


# ----------------------------------------------------------------------
# Protocol conformance
# ----------------------------------------------------------------------


class TestProtocolConformance:
    def test_satisfies_protocol(self, provider):
        assert isinstance(provider, PostAuthProvider)

    def test_provider_name_is_jira(self):
        assert JiraPostAuthProvider.provider_name == "jira"
