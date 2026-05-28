"""Unit tests for TelegramAgentConfig Azure SSO configuration changes.

Tests cover:
- azure_auth_url field presence and defaults
- env var resolution via {NAME}_AZURE_AUTH_URL
- Derivation from auth_url when azure_auth_url is not set
- from_dict() reads azure_auth_url from YAML dict
- validate() errors for azure auth_method without URL
- Backward compatibility: existing basic/oauth2 configs unchanged
"""
import pytest
from unittest.mock import patch

from parrot.integrations.telegram.models import TelegramAgentConfig, TelegramBotsConfig


class TestAzureConfigField:
    """Tests for the azure_auth_url field itself."""

    def test_default_azure_auth_url_is_none(self):
        """Default azure_auth_url is None for basic auth config."""
        cfg = TelegramAgentConfig(name="Test", chatbot_id="test", bot_token="t:k")
        assert cfg.azure_auth_url is None

    def test_explicit_azure_auth_url(self):
        """azure_auth_url can be set explicitly."""
        cfg = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
        )
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_azure_url_derived_from_auth_url_with_login_suffix(self):
        """azure_auth_url derived from auth_url ending with /login."""
        cfg = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
        )
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_azure_url_derived_without_login_suffix(self):
        """azure_auth_url derived from auth_url without /login."""
        cfg = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth",
        )
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_azure_url_not_derived_for_non_azure_method(self):
        """azure_auth_url is not derived when auth_method is not azure."""
        cfg = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="basic",
            auth_url="https://nav.example.com/api/v1/auth/login",
        )
        assert cfg.azure_auth_url is None

    def test_explicit_azure_auth_url_not_overwritten(self):
        """Explicit azure_auth_url is not overwritten by derivation logic."""
        cfg = TelegramAgentConfig(
            name="Test",
            chatbot_id="test",
            bot_token="t:k",
            auth_method="azure",
            auth_url="https://nav.example.com/api/v1/auth/login",
            azure_auth_url="https://custom.example.com/azure/",
        )
        assert cfg.azure_auth_url == "https://custom.example.com/azure/"


class TestAzureEnvVarResolution:
    """Tests for azure_auth_url env var fallback."""

    def test_azure_auth_url_from_env_var(self):
        """azure_auth_url resolved from {NAME}_AZURE_AUTH_URL env var."""
        with patch(
            "parrot.integrations.telegram.models.config.get",
            side_effect=lambda key: (
                "https://env.example.com/api/v1/auth/azure/"
                if key == "TEST_AZURE_AUTH_URL"
                else None
            ),
        ):
            cfg = TelegramAgentConfig(
                name="Test",
                chatbot_id="test",
                bot_token="t:k",
                auth_method="azure",
            )
            assert cfg.azure_auth_url == "https://env.example.com/api/v1/auth/azure/"


class TestAzureFromDict:
    """Tests for from_dict() with azure fields."""

    def test_from_dict_with_azure_auth_url(self):
        """from_dict reads azure_auth_url."""
        cfg = TelegramAgentConfig.from_dict("Bot", {
            "chatbot_id": "bot",
            "bot_token": "t:k",
            "auth_method": "azure",
            "azure_auth_url": "https://nav.example.com/api/v1/auth/azure/",
        })
        assert cfg.auth_method == "azure"
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_from_dict_without_azure_url_derives_from_auth_url(self):
        """from_dict derives azure_auth_url from auth_url when not set."""
        cfg = TelegramAgentConfig.from_dict("Bot", {
            "chatbot_id": "bot",
            "bot_token": "t:k",
            "auth_method": "azure",
            "auth_url": "https://nav.example.com/api/v1/auth/login",
        })
        assert cfg.azure_auth_url == "https://nav.example.com/api/v1/auth/azure/"

    def test_from_dict_missing_azure_url_key_returns_none(self):
        """from_dict returns None azure_auth_url if not in dict and auth_method is basic."""
        cfg = TelegramAgentConfig.from_dict("Bot", {
            "chatbot_id": "bot",
            "bot_token": "t:k",
        })
        assert cfg.azure_auth_url is None


class TestAzureValidation:
    """Tests for TelegramBotsConfig.validate() with azure auth_method."""

    def test_validate_azure_no_urls_returns_error(self):
        """Validation error when azure has no URL source."""
        bots = TelegramBotsConfig(agents={
            "Bad": TelegramAgentConfig(
                name="Bad",
                chatbot_id="bad",
                bot_token="t:k",
                auth_method="azure",
                # No azure_auth_url, no auth_url
            ),
        })
        errors = bots.validate()
        assert any("azure" in e.lower() for e in errors)

    def test_validate_azure_with_explicit_url_no_error(self):
        """No validation error when azure_auth_url is set explicitly."""
        bots = TelegramBotsConfig(agents={
            "Good": TelegramAgentConfig(
                name="Good",
                chatbot_id="good",
                bot_token="t:k",
                auth_method="azure",
                azure_auth_url="https://nav.example.com/api/v1/auth/azure/",
            ),
        })
        errors = bots.validate()
        assert not any("azure" in e.lower() for e in errors)

    def test_validate_azure_with_auth_url_no_error(self):
        """No validation error when azure_auth_url is derived from auth_url."""
        bots = TelegramBotsConfig(agents={
            "Good": TelegramAgentConfig(
                name="Good",
                chatbot_id="good",
                bot_token="t:k",
                auth_method="azure",
                auth_url="https://nav.example.com/api/v1/auth/login",
            ),
        })
        errors = bots.validate()
        assert not any("azure" in e.lower() for e in errors)


class TestBackwardCompat:
    """Ensure existing basic and oauth2 configs are not broken."""

    def test_basic_auth_config_unchanged(self):
        """BasicAuth config works without azure_auth_url."""
        cfg = TelegramAgentConfig(
            name="Legacy",
            chatbot_id="legacy",
            bot_token="t:k",
            auth_url="https://nav.example.com/api/v1/auth/login",
            login_page_url="https://static.example.com/login.html",
        )
        assert cfg.auth_method == "basic"
        assert cfg.azure_auth_url is None

    def test_oauth2_config_unchanged(self):
        """OAuth2 config works without azure_auth_url."""
        cfg = TelegramAgentConfig(
            name="Oauth",
            chatbot_id="oauth",
            bot_token="t:k",
            auth_method="oauth2",
            oauth2_client_id="cid",
            oauth2_client_secret="csec",
            oauth2_redirect_uri="https://example.com/callback",
        )
        assert cfg.auth_method == "oauth2"
        assert cfg.azure_auth_url is None
