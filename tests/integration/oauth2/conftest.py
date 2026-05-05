"""Shared fixtures for FEAT-144 OAuth2 integration tests.

These fixtures follow the spec §4 Test Data / Fixtures contract exactly.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.oauth2.models import (
    IntegrationDescriptor,
    UserAgentToolkitRow,
    UsersIntegrationRow,
)


# ---------------------------------------------------------------------------
# Spec §4 fixtures (verbatim)
# ---------------------------------------------------------------------------


@pytest.fixture
def web_user_id() -> str:
    """Navigator user identifier for integration tests."""
    return "user-test-1234"


@pytest.fixture
def jira_token_set_factory() -> Callable[..., Any]:
    """Build a JiraTokenSet with future expiry."""
    from parrot.auth.jira_oauth import JiraTokenSet

    def _make(**overrides: Any) -> JiraTokenSet:
        base: dict[str, Any] = dict(
            access_token="at-XYZ",
            refresh_token="rt-XYZ",
            expires_at=time.time() + 3600,
            cloud_id="cloud-1",
            site_url="https://example.atlassian.net",
            account_id="acct-1",
            display_name="Test User",
            email="test@example.com",
            scopes=["read:jira-work", "write:jira-work", "offline_access"],
            granted_at=time.time(),
            last_refreshed_at=time.time(),
            available_sites=[],
        )
        base.update(overrides)
        return JiraTokenSet(**base)

    return _make


@pytest.fixture
def allowed_origins(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Patch WEB_OAUTH_ALLOWED_ORIGINS to a test-safe value."""
    monkeypatch.setenv("WEB_OAUTH_ALLOWED_ORIGINS", "https://app.example.com")
    yield ["https://app.example.com"]


# ---------------------------------------------------------------------------
# Additional helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Ensure a fresh OAuth2ProviderRegistry for each test."""
    from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry

    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


@pytest.fixture
def mock_jira_manager(jira_token_set_factory: Callable[..., Any]) -> MagicMock:
    """Mocked JiraOAuthManager — no real Atlassian calls."""
    manager = MagicMock()
    manager.create_authorization_url = AsyncMock(
        return_value=(
            "https://auth.atlassian.com/authorize?state=test-nonce-123",
            "test-nonce-123",
        )
    )
    manager.handle_callback = AsyncMock(
        return_value=(jira_token_set_factory(), {"state": "test-nonce-123"})
    )
    return manager


@pytest.fixture
def registered_jira_provider(mock_jira_manager: MagicMock) -> MagicMock:
    """Register a JiraOAuth2Provider backed by the mock manager."""
    from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider
    from parrot.integrations.oauth2.registry import OAuth2ProviderRegistry

    provider = JiraOAuth2Provider(manager=mock_jira_manager)
    OAuth2ProviderRegistry().register(provider)
    return provider


@pytest.fixture
def sample_integration_row(web_user_id: str) -> UsersIntegrationRow:
    """A valid users_integrations row for the test user."""
    return UsersIntegrationRow(
        user_id=web_user_id,
        provider="jira",
        account_id="acct-1",
        display_name="Test User",
        email="test@example.com",
        scopes=["read:jira-work", "write:jira-work", "offline_access"],
        cloud_id="cloud-1",
        site_url="https://example.atlassian.net",
        connected_at=datetime.now(tz=timezone.utc),
    )


@pytest.fixture
def sample_toolkit_row(web_user_id: str) -> UserAgentToolkitRow:
    """A valid user_agent_toolkits row for the test user."""
    return UserAgentToolkitRow(
        user_id=web_user_id,
        agent_id="test-agent",
        toolkit_id="jira",
        provider="jira",
        enabled_at=datetime.now(tz=timezone.utc),
    )


# make_mock_db is in tests/integration/oauth2/helpers.py — import from there.
