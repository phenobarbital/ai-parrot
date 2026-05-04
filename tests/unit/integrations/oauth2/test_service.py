"""Unit tests for parrot.integrations.oauth2.service."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from parrot.integrations.oauth2.models import (
    IntegrationDescriptor,
    UsersIntegrationRow,
    UserAgentToolkitRow,
)
from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry
from parrot.integrations.oauth2.service import IntegrationsService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Ensure a fresh registry for each test."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def mock_provider() -> MagicMock:
    provider = MagicMock()
    provider.provider_id = "jira"
    provider.display_name = "Jira"
    provider.icon = "mdi:jira"
    provider.default_scopes = ["read:jira-work", "write:jira-work", "offline_access"]
    provider.manager = MagicMock()
    provider.manager.create_authorization_url = AsyncMock(
        return_value=("https://auth.atlassian.com/authorize?state=nonce123", "nonce123")
    )
    return provider


@pytest.fixture
def registered_provider(mock_provider: MagicMock) -> MagicMock:
    OAuth2ProviderRegistry().register(mock_provider)
    return mock_provider


@pytest.fixture
def sample_integration_row() -> UsersIntegrationRow:
    return UsersIntegrationRow(
        user_id="u1",
        provider="jira",
        account_id="acct-1",
        display_name="Test User",
        email="test@example.com",
        scopes=["read:jira-work"],
        connected_at=datetime.now(),
    )


@pytest.fixture
def allowed_origins_env(monkeypatch: pytest.MonkeyPatch) -> list:
    monkeypatch.setenv("WEB_OAUTH_ALLOWED_ORIGINS", "https://app.example.com")
    return ["https://app.example.com"]


# ---------------------------------------------------------------------------
# TestListForUser
# ---------------------------------------------------------------------------


class TestListForUser:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_pbac(self) -> None:
        """When request is None (no PBAC), list_for_user returns []."""
        svc = IntegrationsService()
        result = await svc.list_for_user("u1", "agent1", request=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_abac_absent(self) -> None:
        """When request.app has no 'abac', list_for_user returns []."""
        request = MagicMock()
        request.app = {}
        svc = IntegrationsService()
        result = await svc.list_for_user("u1", "agent1", request=request)
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_descriptors_with_connected_flag(
        self,
        registered_provider: MagicMock,
        sample_integration_row: UsersIntegrationRow,
    ) -> None:
        """With a mock PBAC that allows everything, returns correct descriptor."""
        request = MagicMock()
        abac = MagicMock()
        abac.is_allowed = AsyncMock(return_value=True)
        request.app = {"abac": abac}

        with (
            patch(
                "parrot.integrations.oauth2.service.get_users_integration",
                AsyncMock(return_value=sample_integration_row),
            ),
            patch(
                "parrot.integrations.oauth2.service.list_user_agent_toolkits",
                AsyncMock(return_value=[]),
            ),
        ):
            svc = IntegrationsService()
            result = await svc.list_for_user("u1", "agent1", request=request)

        assert len(result) == 1
        desc = result[0]
        assert desc.provider == "jira"
        assert desc.connected is True
        assert desc.enabled_on_agent is False  # no toolkit row

    @pytest.mark.asyncio
    async def test_returns_enabled_flag_when_toolkit_row_present(
        self,
        registered_provider: MagicMock,
        sample_integration_row: UsersIntegrationRow,
    ) -> None:
        """enabled_on_agent=True when user_agent_toolkits row exists."""
        request = MagicMock()
        abac = MagicMock()
        abac.is_allowed = AsyncMock(return_value=True)
        request.app = {"abac": abac}

        toolkit_row = UserAgentToolkitRow(
            user_id="u1",
            agent_id="agent1",
            toolkit_id="jira",
            provider="jira",
            enabled_at=datetime.now(),
        )
        with (
            patch(
                "parrot.integrations.oauth2.service.get_users_integration",
                AsyncMock(return_value=sample_integration_row),
            ),
            patch(
                "parrot.integrations.oauth2.service.list_user_agent_toolkits",
                AsyncMock(return_value=[toolkit_row]),
            ),
        ):
            svc = IntegrationsService()
            result = await svc.list_for_user("u1", "agent1", request=request)

        assert result[0].enabled_on_agent is True


# ---------------------------------------------------------------------------
# TestStartConnect
# ---------------------------------------------------------------------------


class TestStartConnect:
    @pytest.mark.asyncio
    async def test_validates_origin_raises_for_disallowed(self) -> None:
        """start_connect raises ValueError for origin not in allowed list."""
        with patch(
            "parrot.integrations.oauth2.service._get_allowed_origins",
            return_value=["https://app.example.com"],
        ):
            svc = IntegrationsService()
            with pytest.raises(ValueError, match="not in the list of allowed"):
                await svc.start_connect("u1", "agent1", "jira", "https://evil.com")

    @pytest.mark.asyncio
    async def test_raises_for_unknown_provider(self) -> None:
        """start_connect raises ValueError for unregistered provider."""
        with patch(
            "parrot.integrations.oauth2.service._get_allowed_origins",
            return_value=["https://app.example.com"],
        ):
            svc = IntegrationsService()
            with pytest.raises(ValueError, match="Unknown provider"):
                await svc.start_connect(
                    "u1", "agent1", "unknown", "https://app.example.com"
                )

    @pytest.mark.asyncio
    async def test_returns_connect_init_response(
        self, registered_provider: MagicMock
    ) -> None:
        """start_connect returns ConnectInitResponse with auth_url and state."""
        with patch(
            "parrot.integrations.oauth2.service._get_allowed_origins",
            return_value=["https://app.example.com"],
        ):
            svc = IntegrationsService()
            resp = await svc.start_connect(
                "u1", "agent1", "jira", "https://app.example.com"
            )

        assert resp.auth_url.startswith("https://auth.atlassian.com")
        assert resp.state == "nonce123"
        assert resp.expires_in == 600
        assert "read:jira-work" in resp.scopes

    @pytest.mark.asyncio
    async def test_passes_extra_state_to_manager(
        self, registered_provider: MagicMock
    ) -> None:
        """start_connect passes channel, agent_id, return_origin in extra_state."""
        with patch(
            "parrot.integrations.oauth2.service._get_allowed_origins",
            return_value=["https://app.example.com"],
        ):
            svc = IntegrationsService()
            await svc.start_connect(
                "u1", "agent1", "jira", "https://app.example.com"
            )

        call_kwargs = registered_provider.manager.create_authorization_url.call_args
        extra_state = call_kwargs.kwargs.get("extra_state") or (
            call_kwargs.args[2] if len(call_kwargs.args) > 2 else {}
        )
        assert extra_state.get("channel") == "web"
        assert extra_state.get("agent_id") == "agent1"
        assert extra_state.get("return_origin") == "https://app.example.com"


# ---------------------------------------------------------------------------
# TestConfirmEnable
# ---------------------------------------------------------------------------


class TestConfirmEnable:
    @pytest.mark.asyncio
    async def test_raises_when_no_credential(
        self, registered_provider: MagicMock
    ) -> None:
        """confirm_enable raises LookupError when no users_integrations row."""
        with patch(
            "parrot.integrations.oauth2.service.get_users_integration",
            AsyncMock(return_value=None),
        ):
            svc = IntegrationsService()
            with pytest.raises(LookupError, match="No credential found"):
                await svc.confirm_enable("u1", "agent1", "jira")

    @pytest.mark.asyncio
    async def test_returns_descriptor_with_enabled_flag(
        self,
        registered_provider: MagicMock,
        sample_integration_row: UsersIntegrationRow,
    ) -> None:
        """confirm_enable returns descriptor with connected=True, enabled_on_agent=True."""
        with (
            patch(
                "parrot.integrations.oauth2.service.get_users_integration",
                AsyncMock(return_value=sample_integration_row),
            ),
            patch(
                "parrot.integrations.oauth2.service.upsert_user_agent_toolkit",
                AsyncMock(),
            ),
        ):
            svc = IntegrationsService()
            desc = await svc.confirm_enable("u1", "agent1", "jira")

        assert isinstance(desc, IntegrationDescriptor)
        assert desc.connected is True
        assert desc.enabled_on_agent is True

    @pytest.mark.asyncio
    async def test_idempotent(
        self,
        registered_provider: MagicMock,
        sample_integration_row: UsersIntegrationRow,
    ) -> None:
        """confirm_enable is idempotent — second call succeeds without error."""
        upsert_mock = AsyncMock()
        with (
            patch(
                "parrot.integrations.oauth2.service.get_users_integration",
                AsyncMock(return_value=sample_integration_row),
            ),
            patch(
                "parrot.integrations.oauth2.service.upsert_user_agent_toolkit",
                upsert_mock,
            ),
        ):
            svc = IntegrationsService()
            await svc.confirm_enable("u1", "agent1", "jira")
            await svc.confirm_enable("u1", "agent1", "jira")

        assert upsert_mock.call_count == 2  # called twice; idempotent via upsert


# ---------------------------------------------------------------------------
# TestDisconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    @pytest.mark.asyncio
    async def test_cascade_deletes(self) -> None:
        """disconnect deletes users_integrations and user_agent_toolkits."""
        delete_toolkits_mock = AsyncMock()
        delete_credential_mock = AsyncMock()
        with (
            patch(
                "parrot.integrations.oauth2.service.delete_user_agent_toolkits_by_provider",
                delete_toolkits_mock,
            ),
            patch(
                "parrot.integrations.oauth2.service.delete_users_integration",
                delete_credential_mock,
            ),
        ):
            svc = IntegrationsService()
            resp = await svc.disconnect("u1", "agent1", "jira")

        delete_toolkits_mock.assert_called_once_with("u1", "jira")
        delete_credential_mock.assert_called_once_with("u1", "jira")
        assert resp.provider == "jira"
        assert resp.disconnected is True

    @pytest.mark.asyncio
    async def test_idempotent(self) -> None:
        """disconnect is idempotent — second call is a no-op (no-raise)."""
        with (
            patch(
                "parrot.integrations.oauth2.service.delete_user_agent_toolkits_by_provider",
                AsyncMock(),
            ),
            patch(
                "parrot.integrations.oauth2.service.delete_users_integration",
                AsyncMock(),
            ),
        ):
            svc = IntegrationsService()
            await svc.disconnect("u1", "agent1", "jira")
            await svc.disconnect("u1", "agent1", "jira")  # second call — no error


# ---------------------------------------------------------------------------
# TestPersistCredential
# ---------------------------------------------------------------------------


class TestPersistCredential:
    @pytest.mark.asyncio
    async def test_builds_row_from_token_set(self) -> None:
        """persist_credential builds UsersIntegrationRow from JiraTokenSet-like object."""
        token_set = MagicMock()
        token_set.account_id = "acct-1"
        token_set.display_name = "Test User"
        token_set.email = "test@example.com"
        token_set.scopes = ["read:jira-work", "offline_access"]
        token_set.cloud_id = "cloud-1"
        token_set.site_url = "https://example.atlassian.net"

        upsert_mock = AsyncMock()
        with patch(
            "parrot.integrations.oauth2.service.upsert_users_integration",
            upsert_mock,
        ):
            svc = IntegrationsService()
            row = await svc.persist_credential("u1", "jira", token_set)

        assert row.user_id == "u1"
        assert row.provider == "jira"
        assert row.account_id == "acct-1"
        assert row.display_name == "Test User"
        assert row.channel == "web"
        assert row.status == "active"
        upsert_mock.assert_called_once_with(row)

    @pytest.mark.asyncio
    async def test_persist_credential_calls_upsert(self) -> None:
        """persist_credential calls upsert_users_integration exactly once."""
        token_set = MagicMock()
        token_set.account_id = "a1"
        token_set.display_name = "User"
        token_set.email = None
        token_set.scopes = []
        token_set.cloud_id = None
        token_set.site_url = None

        upsert_mock = AsyncMock()
        with patch(
            "parrot.integrations.oauth2.service.upsert_users_integration",
            upsert_mock,
        ):
            svc = IntegrationsService()
            await svc.persist_credential("u1", "jira", token_set)

        upsert_mock.assert_called_once()
