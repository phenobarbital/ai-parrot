"""Unit tests for GigSmartConfig."""

import pytest

from parrot_tools.interfaces.gigsmart.config import GigSmartConfig
from parrot_tools.interfaces.gigsmart.exceptions import GigSmartError


class TestGigSmartConfig:
    """Tests for GigSmartConfig instantiation and from_env loading."""

    def test_explicit_instantiation(self):
        """Direct construction with required fields works."""
        config = GigSmartConfig(client_id="my-id", client_secret="my-secret")
        assert config.client_id == "my-id"
        assert config.client_secret == "my-secret"
        assert config.environment == "production"

    def test_default_endpoint_url(self):
        """Default endpoint is the production GraphQL URL."""
        config = GigSmartConfig(client_id="id", client_secret="secret")
        assert config.endpoint_url == "https://api.gigsmart.com/graphql"

    def test_default_token_url(self):
        """Default token URL is the production OAuth token endpoint."""
        config = GigSmartConfig(client_id="id", client_secret="secret")
        assert config.token_url == "https://api.gigsmart.com/oauth/token"

    def test_default_timeout_and_concurrency(self):
        """Default request_timeout and max_concurrent_requests are sensible."""
        config = GigSmartConfig(client_id="id", client_secret="secret")
        assert config.request_timeout == 30.0
        assert config.max_concurrent_requests == 8

    def test_from_env(self, monkeypatch):
        """from_env() loads client_id and client_secret from environment."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "test-id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "test-secret")
        config = GigSmartConfig.from_env()
        assert config.client_id == "test-id"
        assert config.client_secret == "test-secret"
        assert config.environment == "production"

    def test_missing_client_id_raises(self, monkeypatch):
        """from_env() raises GigSmartError when GIGSMART_CLIENT_ID is absent."""
        monkeypatch.delenv("GIGSMART_CLIENT_ID", raising=False)
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        with pytest.raises(GigSmartError, match="GIGSMART_CLIENT_ID"):
            GigSmartConfig.from_env()

    def test_missing_client_secret_raises(self, monkeypatch):
        """from_env() raises GigSmartError when GIGSMART_CLIENT_SECRET is absent."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.delenv("GIGSMART_CLIENT_SECRET", raising=False)
        with pytest.raises(GigSmartError, match="GIGSMART_CLIENT_SECRET"):
            GigSmartConfig.from_env()

    def test_sandbox_environment(self, monkeypatch):
        """from_env() reads GIGSMART_ENV=sandbox correctly."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.setenv("GIGSMART_ENV", "sandbox")
        config = GigSmartConfig.from_env()
        assert config.environment == "sandbox"

    def test_custom_endpoint_url(self, monkeypatch):
        """from_env() respects GIGSMART_ENDPOINT_URL override."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.setenv("GIGSMART_ENDPOINT_URL", "https://sandbox.gigsmart.com/graphql")
        config = GigSmartConfig.from_env()
        assert config.endpoint_url == "https://sandbox.gigsmart.com/graphql"

    def test_log_pii_disabled_by_default(self, monkeypatch):
        """from_env() sets log_pii=False when GIGSMART_LOG_PII is unset."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.delenv("GIGSMART_LOG_PII", raising=False)
        config = GigSmartConfig.from_env()
        assert config.log_pii is False

    def test_log_pii_enabled(self, monkeypatch):
        """from_env() sets log_pii=True when GIGSMART_LOG_PII=1."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.setenv("GIGSMART_LOG_PII", "1")
        config = GigSmartConfig.from_env()
        assert config.log_pii is True

    def test_refresh_token_from_env(self, monkeypatch):
        """from_env() reads GIGSMART_REFRESH_TOKEN into refresh_token."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.setenv("GIGSMART_REFRESH_TOKEN", "refresh-abc")
        config = GigSmartConfig.from_env()
        assert config.refresh_token == "refresh-abc"

    def test_refresh_token_none_when_absent(self, monkeypatch):
        """from_env() sets refresh_token=None when env var is absent."""
        monkeypatch.setenv("GIGSMART_CLIENT_ID", "id")
        monkeypatch.setenv("GIGSMART_CLIENT_SECRET", "secret")
        monkeypatch.delenv("GIGSMART_REFRESH_TOKEN", raising=False)
        config = GigSmartConfig.from_env()
        assert config.refresh_token is None
