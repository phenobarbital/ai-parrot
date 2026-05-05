"""Unit tests for parrot.integrations.oauth2.jira_provider."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from parrot.integrations.oauth2.jira_provider import JiraOAuth2Provider


class TestJiraOAuth2Provider:
    """Tests for JiraOAuth2Provider."""

    @pytest.fixture
    def mock_manager(self) -> MagicMock:
        return MagicMock(name="JiraOAuthManager")

    def test_provider_id(self, mock_manager: MagicMock) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        assert p.provider_id == "jira"

    def test_display_name(self, mock_manager: MagicMock) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        assert p.display_name == "Jira"

    def test_icon(self, mock_manager: MagicMock) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        assert p.icon == "mdi:jira"

    def test_default_scopes(self, mock_manager: MagicMock) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        assert "read:jira-work" in p.default_scopes
        assert "write:jira-work" in p.default_scopes
        assert "offline_access" in p.default_scopes

    def test_pbac_action_namespace(self, mock_manager: MagicMock) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        assert p.pbac_action_namespace == "integration"

    def test_manager_property(self, mock_manager: MagicMock) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        assert p.manager is mock_manager

    def test_toolkit_factory_returns_jira_toolkit(
        self, mock_manager: MagicMock
    ) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        resolver = MagicMock(name="OAuthCredentialResolver")
        toolkit = p.toolkit_factory(resolver)
        from parrot_tools.jiratoolkit import JiraToolkit

        assert isinstance(toolkit, JiraToolkit)

    def test_toolkit_factory_sets_auth_type(
        self, mock_manager: MagicMock
    ) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        resolver = MagicMock(name="OAuthCredentialResolver")
        toolkit = p.toolkit_factory(resolver)
        assert toolkit.auth_type == "oauth2_3lo"

    def test_toolkit_factory_sets_credential_resolver(
        self, mock_manager: MagicMock
    ) -> None:
        p = JiraOAuth2Provider(manager=mock_manager)
        resolver = MagicMock(name="OAuthCredentialResolver")
        toolkit = p.toolkit_factory(resolver)
        assert toolkit.credential_resolver is resolver
