"""Tests for TelegramAgentConfig OAuth2 fields (TASK-241)."""

from unittest.mock import patch

from parrot.integrations.telegram.models import (
    TelegramAgentConfig,
    TelegramBotsConfig,
)


class TestConfigAuthMethodDefault:
    """Verify auth_method defaults and backward compatibility."""

    def test_auth_method_defaults_to_basic(self):
        cfg = TelegramAgentConfig(name="TestBot", chatbot_id="test")
        assert cfg.auth_method == "basic"

    def test_oauth2_provider_defaults_to_google(self):
        cfg = TelegramAgentConfig(name="TestBot", chatbot_id="test")
        assert cfg.oauth2_provider == "google"

    def test_oauth2_fields_default_to_none(self):
        cfg = TelegramAgentConfig(name="TestBot", chatbot_id="test")
        assert cfg.oauth2_client_id is None
        assert cfg.oauth2_client_secret is None
        assert cfg.oauth2_scopes is None
        assert cfg.oauth2_redirect_uri is None

    def test_existing_config_unchanged(self):
        """Existing configs without auth_method produce identical behavior."""
        cfg = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test",
            bot_token="test:token",
            auth_url="https://nav.example.com/api/auth",
            login_page_url="https://static.example.com/login.html",
        )
        assert cfg.auth_method == "basic"
        assert cfg.auth_url == "https://nav.example.com/api/auth"
        assert cfg.login_page_url == "https://static.example.com/login.html"


class TestConfigOAuth2Fields:
    """Verify OAuth2 fields are set correctly."""

    def test_oauth2_config(self):
        cfg = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test",
            bot_token="test:token",
            auth_method="oauth2",
            oauth2_provider="google",
            oauth2_client_id="client-id.apps.googleusercontent.com",
            oauth2_client_secret="client-secret",
            oauth2_scopes=["openid", "email", "profile"],
            oauth2_redirect_uri="https://example.com/oauth2/callback",
        )
        assert cfg.auth_method == "oauth2"
        assert cfg.oauth2_provider == "google"
        assert cfg.oauth2_client_id == "client-id.apps.googleusercontent.com"
        assert cfg.oauth2_client_secret == "client-secret"
        assert cfg.oauth2_scopes == ["openid", "email", "profile"]
        assert cfg.oauth2_redirect_uri == "https://example.com/oauth2/callback"


class TestConfigOAuth2EnvFallback:
    """Verify OAuth2 credentials resolve from env vars."""

    @patch("parrot.integrations.telegram.models.config")
    def test_oauth2_client_id_from_env(self, mock_config):
        mock_config.get = lambda key, **kw: {
            "TESTBOT_TELEGRAM_TOKEN": None,
            "NAVIGATOR_AUTH_URL": None,
            "TESTBOT_OAUTH2_CLIENT_ID": "env-client-id",
            "TESTBOT_OAUTH2_CLIENT_SECRET": "env-secret",
        }.get(key)

        cfg = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test",
            bot_token="test:token",
            auth_method="oauth2",
        )
        assert cfg.oauth2_client_id == "env-client-id"
        assert cfg.oauth2_client_secret == "env-secret"

    @patch("parrot.integrations.telegram.models.config")
    def test_explicit_values_not_overridden_by_env(self, mock_config):
        mock_config.get = lambda key, **kw: {
            "TESTBOT_TELEGRAM_TOKEN": None,
            "NAVIGATOR_AUTH_URL": None,
            "TESTBOT_OAUTH2_CLIENT_ID": "env-client-id",
            "TESTBOT_OAUTH2_CLIENT_SECRET": "env-secret",
        }.get(key)

        cfg = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test",
            bot_token="test:token",
            auth_method="oauth2",
            oauth2_client_id="explicit-id",
            oauth2_client_secret="explicit-secret",
        )
        assert cfg.oauth2_client_id == "explicit-id"
        assert cfg.oauth2_client_secret == "explicit-secret"

    def test_env_not_resolved_for_basic_auth(self):
        """When auth_method is basic, OAuth2 env vars are NOT resolved."""
        cfg = TelegramAgentConfig(
            name="TestBot",
            chatbot_id="test",
            bot_token="test:token",
            auth_method="basic",
        )
        assert cfg.oauth2_client_id is None
        assert cfg.oauth2_client_secret is None


class TestFromDict:
    """Verify from_dict() parses OAuth2 fields."""

    def test_from_dict_basic_auth_default(self):
        data = {"chatbot_id": "test", "bot_token": "test:token"}
        cfg = TelegramAgentConfig.from_dict("TestBot", data)
        assert cfg.auth_method == "basic"
        assert cfg.oauth2_client_id is None

    def test_from_dict_oauth2(self):
        data = {
            "chatbot_id": "test",
            "bot_token": "test:token",
            "auth_method": "oauth2",
            "oauth2_provider": "google",
            "oauth2_client_id": "my-client-id",
            "oauth2_client_secret": "my-secret",
            "oauth2_scopes": ["openid", "email"],
            "oauth2_redirect_uri": "https://example.com/callback",
        }
        cfg = TelegramAgentConfig.from_dict("TestBot", data)
        assert cfg.auth_method == "oauth2"
        assert cfg.oauth2_provider == "google"
        assert cfg.oauth2_client_id == "my-client-id"
        assert cfg.oauth2_client_secret == "my-secret"
        assert cfg.oauth2_scopes == ["openid", "email"]
        assert cfg.oauth2_redirect_uri == "https://example.com/callback"

    def test_from_dict_missing_oauth2_keys(self):
        """Missing OAuth2 keys should not crash — they're all Optional."""
        data = {
            "chatbot_id": "test",
            "bot_token": "test:token",
            "auth_method": "oauth2",
        }
        cfg = TelegramAgentConfig.from_dict("TestBot", data)
        assert cfg.auth_method == "oauth2"
        assert cfg.oauth2_provider == "google"

    def test_from_dict_backward_compat(self):
        """Legacy YAML without auth_method works unchanged."""
        data = {
            "chatbot_id": "test",
            "bot_token": "test:token",
            "auth_url": "https://nav.example.com/api/auth",
            "login_page_url": "https://static.example.com/login.html",
        }
        cfg = TelegramAgentConfig.from_dict("TestBot", data)
        assert cfg.auth_method == "basic"
        assert cfg.auth_url == "https://nav.example.com/api/auth"
        assert cfg.login_page_url == "https://static.example.com/login.html"


class TestValidate:
    """Verify validate() checks OAuth2 credentials."""

    def test_validate_basic_auth_no_oauth2_errors(self):
        bots = TelegramBotsConfig(agents={
            "TestBot": TelegramAgentConfig(
                name="TestBot",
                chatbot_id="test",
                bot_token="test:token",
                auth_method="basic",
            )
        })
        errors = bots.validate()
        assert not any("oauth2" in e.lower() for e in errors)

    def test_validate_oauth2_missing_client_id(self):
        bots = TelegramBotsConfig(agents={
            "TestBot": TelegramAgentConfig(
                name="TestBot",
                chatbot_id="test",
                bot_token="test:token",
                auth_method="oauth2",
            )
        })
        errors = bots.validate()
        assert any("oauth2_client_id" in e for e in errors)

    def test_validate_oauth2_missing_client_secret(self):
        bots = TelegramBotsConfig(agents={
            "TestBot": TelegramAgentConfig(
                name="TestBot",
                chatbot_id="test",
                bot_token="test:token",
                auth_method="oauth2",
                oauth2_client_id="some-id",
            )
        })
        errors = bots.validate()
        assert any("oauth2_client_secret" in e for e in errors)

    def test_validate_oauth2_valid(self):
        bots = TelegramBotsConfig(agents={
            "TestBot": TelegramAgentConfig(
                name="TestBot",
                chatbot_id="test",
                bot_token="test:token",
                auth_method="oauth2",
                oauth2_client_id="my-id",
                oauth2_client_secret="my-secret",
            )
        })
        errors = bots.validate()
        assert not any("oauth2" in e.lower() for e in errors)
