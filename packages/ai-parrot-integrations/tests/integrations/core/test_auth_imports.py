"""Tests for the core auth module imports (FEAT-225 / TASK-1467).

Verifies that PostAuthProvider, PostAuthRegistry, and OAuth2 primitives
are accessible from the new ``parrot.integrations.core.auth`` location.
"""
import importlib

import pytest


def test_post_auth_imports():
    """PostAuthProvider and PostAuthRegistry are importable from core.auth."""
    from parrot.integrations.core.auth.post_auth import PostAuthProvider, PostAuthRegistry

    assert PostAuthProvider is not None
    assert PostAuthRegistry is not None


def test_oauth2_providers_imports():
    """OAUTH2_PROVIDERS dict and get_provider are importable from core.auth."""
    from parrot.integrations.core.auth.oauth2_providers import OAUTH2_PROVIDERS, get_provider

    assert isinstance(OAUTH2_PROVIDERS, dict)
    assert callable(get_provider)


def test_reexport_from_init():
    """PostAuthProvider and PostAuthRegistry are re-exported from core.auth.__init__."""
    from parrot.integrations.core.auth import PostAuthProvider, PostAuthRegistry

    assert PostAuthProvider is not None
    assert PostAuthRegistry is not None


def test_oauth2_reexport_from_init():
    """OAuth2 primitives are re-exported from core.auth.__init__."""
    from parrot.integrations.core.auth import OAuth2ProviderConfig, OAUTH2_PROVIDERS, get_provider

    assert OAuth2ProviderConfig is not None
    assert isinstance(OAUTH2_PROVIDERS, dict)
    assert callable(get_provider)


def test_old_telegram_post_auth_path_removed():
    """The old telegram/post_auth.py module no longer exists."""
    with pytest.raises((ModuleNotFoundError, ImportError)):
        importlib.import_module("parrot.integrations.telegram.post_auth")


def test_old_telegram_oauth2_providers_path_removed():
    """The old telegram/oauth2_providers.py module no longer exists."""
    with pytest.raises((ModuleNotFoundError, ImportError)):
        importlib.import_module("parrot.integrations.telegram.oauth2_providers")


def test_post_auth_registry_registers_and_gets():
    """PostAuthRegistry can register and retrieve providers."""
    from parrot.integrations.core.auth.post_auth import PostAuthRegistry

    class FakeProvider:
        provider_name = "fake"

        async def build_auth_url(self, session, config, callback_base_url):
            return "https://fake.example.com/auth"

        async def handle_result(self, data, session, primary_auth_data):
            return True

    registry = PostAuthRegistry()
    provider = FakeProvider()
    registry.register(provider)
    assert registry.get("fake") is provider
    assert "fake" in registry
    assert len(registry) == 1


def test_oauth2_google_provider_config():
    """The Google OAuth2 provider is registered with correct endpoints."""
    from parrot.integrations.core.auth.oauth2_providers import OAUTH2_PROVIDERS, get_provider

    assert "google" in OAUTH2_PROVIDERS
    google = get_provider("google")
    assert "accounts.google.com" in google.authorization_url
    assert "oauth2.googleapis.com" in google.token_url


def test_oauth2_unknown_provider_raises():
    """get_provider raises ValueError for unknown provider names."""
    from parrot.integrations.core.auth.oauth2_providers import get_provider

    with pytest.raises(ValueError, match="Unknown OAuth2 provider"):
        get_provider("nonexistent_provider_xyz")
