"""Unit tests for parrot.integrations.oauth2.registry."""
from __future__ import annotations

from typing import Any, List, Optional

import pytest

from parrot.integrations.oauth2.registry import (
    OAuth2Provider,
    OAuth2ProviderRegistry,
    register_oauth2_provider,
)


class FakeProvider(OAuth2Provider):
    """Minimal concrete provider for testing."""

    provider_id = "fake"
    display_name = "Fake"
    icon = None
    default_scopes: List[str] = []
    pbac_action_namespace = "integration"

    @property
    def manager(self) -> Any:
        return None

    def toolkit_factory(self, credential_resolver: Any) -> Any:
        return None


class AnotherFakeProvider(OAuth2Provider):
    """Second fake provider for multi-provider tests."""

    provider_id = "another"
    display_name = "Another"
    icon = "mdi:star"
    default_scopes: List[str] = ["scope:read"]
    pbac_action_namespace = "integration"

    @property
    def manager(self) -> Any:
        return None

    def toolkit_factory(self, credential_resolver: Any) -> Any:
        return None


class TestOAuth2ProviderRegistry:
    """Tests for OAuth2ProviderRegistry."""

    @pytest.fixture(autouse=True)
    def reset_registry(self) -> None:
        """Reset the singleton before and after each test."""
        OAuth2ProviderRegistry._reset()
        yield
        OAuth2ProviderRegistry._reset()

    def test_singleton(self) -> None:
        """Two calls to OAuth2ProviderRegistry() return the same instance."""
        r1 = OAuth2ProviderRegistry()
        r2 = OAuth2ProviderRegistry()
        assert r1 is r2

    def test_register_and_get(self) -> None:
        """Registering a provider then getting it returns the same instance."""
        reg = OAuth2ProviderRegistry()
        provider = FakeProvider()
        reg.register(provider)
        assert reg.get("fake") is provider

    def test_get_nonexistent_returns_none(self) -> None:
        """Getting an unregistered provider returns None."""
        reg = OAuth2ProviderRegistry()
        assert reg.get("nonexistent") is None

    def test_duplicate_register_overwrites(self) -> None:
        """Registering the same provider_id twice keeps the last one."""
        reg = OAuth2ProviderRegistry()
        p1 = FakeProvider()
        p2 = FakeProvider()
        reg.register(p1)
        reg.register(p2)
        assert reg.get("fake") is p2

    def test_all_returns_all_providers(self) -> None:
        """all() returns all registered providers."""
        reg = OAuth2ProviderRegistry()
        reg.register(FakeProvider())
        assert len(reg.all()) == 1

    def test_all_returns_multiple_providers(self) -> None:
        """all() returns all when multiple providers are registered."""
        reg = OAuth2ProviderRegistry()
        reg.register(FakeProvider())
        reg.register(AnotherFakeProvider())
        providers = reg.all()
        assert len(providers) == 2
        provider_ids = {p.provider_id for p in providers}
        assert provider_ids == {"fake", "another"}

    def test_all_empty_when_no_providers(self) -> None:
        """all() returns empty list when no providers registered."""
        reg = OAuth2ProviderRegistry()
        assert reg.all() == []

    def test_reset_clears_providers(self) -> None:
        """_reset() resets the singleton — subsequent call creates fresh instance."""
        reg = OAuth2ProviderRegistry()
        reg.register(FakeProvider())
        OAuth2ProviderRegistry._reset()
        new_reg = OAuth2ProviderRegistry()
        assert new_reg.get("fake") is None
        assert new_reg.all() == []


class TestRegisterOAuth2Provider:
    """Tests for the module-level register_oauth2_provider() helper."""

    @pytest.fixture(autouse=True)
    def reset_registry(self) -> None:
        OAuth2ProviderRegistry._reset()
        yield
        OAuth2ProviderRegistry._reset()

    def test_register_helper(self) -> None:
        """register_oauth2_provider() adds to the global registry."""
        provider = FakeProvider()
        register_oauth2_provider(provider)
        assert OAuth2ProviderRegistry().get("fake") is provider
