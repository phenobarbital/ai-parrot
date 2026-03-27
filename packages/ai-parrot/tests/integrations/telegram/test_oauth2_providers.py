"""Tests for OAuth2 provider registry."""

import pytest

from parrot.integrations.telegram.oauth2_providers import (
    OAuth2ProviderConfig,
    OAUTH2_PROVIDERS,
    get_provider,
)


class TestOAuth2ProviderConfig:
    """Tests for the OAuth2ProviderConfig dataclass."""

    def test_google_provider_exists(self):
        """Google provider is registered in OAUTH2_PROVIDERS."""
        assert "google" in OAUTH2_PROVIDERS

    def test_google_provider_fields(self):
        """Google provider has correct OAuth2 endpoints and scopes."""
        google = OAUTH2_PROVIDERS["google"]
        assert isinstance(google, OAuth2ProviderConfig)
        assert google.name == "google"
        assert google.authorization_url == (
            "https://accounts.google.com/o/oauth2/v2/auth"
        )
        assert google.token_url == (
            "https://oauth2.googleapis.com/token"
        )
        assert google.userinfo_url == (
            "https://www.googleapis.com/oauth2/v3/userinfo"
        )
        assert google.default_scopes == ["openid", "email", "profile"]

    def test_provider_config_is_frozen(self):
        """OAuth2ProviderConfig instances are immutable."""
        google = OAUTH2_PROVIDERS["google"]
        with pytest.raises(AttributeError):
            google.name = "modified"


class TestGetProvider:
    """Tests for the get_provider lookup function."""

    def test_get_provider_google(self):
        """get_provider('google') returns the Google config."""
        provider = get_provider("google")
        assert provider.name == "google"
        assert provider.token_url == "https://oauth2.googleapis.com/token"

    def test_get_provider_case_insensitive(self):
        """get_provider is case-insensitive."""
        provider = get_provider("Google")
        assert provider.name == "google"

        provider_upper = get_provider("GOOGLE")
        assert provider_upper.name == "google"

    def test_get_provider_unknown_raises_value_error(self):
        """get_provider raises ValueError for unknown providers."""
        with pytest.raises(ValueError, match="Unknown OAuth2 provider 'unknown'"):
            get_provider("unknown")

    def test_get_provider_unknown_lists_available(self):
        """ValueError message includes available provider names."""
        with pytest.raises(ValueError, match="Available providers: google"):
            get_provider("nonexistent")

    def test_get_provider_returns_same_instance(self):
        """get_provider returns the same config object from the registry."""
        p1 = get_provider("google")
        p2 = get_provider("google")
        assert p1 is p2
