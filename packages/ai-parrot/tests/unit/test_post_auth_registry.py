"""Unit tests for the PostAuthProvider protocol and PostAuthRegistry
(FEAT-108 / TASK-757)."""
import logging

import pytest

from parrot.integrations.telegram.post_auth import (
    PostAuthProvider,
    PostAuthRegistry,
)


class FakeProvider:
    """Minimal provider implementation for testing."""

    provider_name = "fake"

    async def build_auth_url(self, session, config, callback_base_url):
        return "https://fake.example.com/auth"

    async def handle_result(self, data, session, primary_auth_data):
        return True


class OtherProvider:
    provider_name = "other"

    async def build_auth_url(self, session, config, callback_base_url):
        return "https://other.example.com/auth"

    async def handle_result(self, data, session, primary_auth_data):
        return True


class ProviderWithoutName:
    provider_name = ""

    async def build_auth_url(self, session, config, callback_base_url):
        return ""

    async def handle_result(self, data, session, primary_auth_data):
        return True


class TestPostAuthRegistry:
    """Tests for PostAuthRegistry register/get/lookup semantics."""

    def test_register_and_get(self):
        registry = PostAuthRegistry()
        provider = FakeProvider()
        registry.register(provider)
        assert registry.get("fake") is provider

    def test_get_unknown_returns_none(self):
        registry = PostAuthRegistry()
        assert registry.get("nonexistent") is None

    def test_providers_property(self):
        registry = PostAuthRegistry()
        registry.register(FakeProvider())
        assert "fake" in registry.providers

    def test_providers_is_list(self):
        registry = PostAuthRegistry()
        registry.register(FakeProvider())
        registry.register(OtherProvider())
        assert isinstance(registry.providers, list)
        assert set(registry.providers) == {"fake", "other"}

    def test_contains(self):
        registry = PostAuthRegistry()
        assert "fake" not in registry
        registry.register(FakeProvider())
        assert "fake" in registry
        assert "other" not in registry

    def test_len(self):
        registry = PostAuthRegistry()
        assert len(registry) == 0
        registry.register(FakeProvider())
        assert len(registry) == 1
        registry.register(OtherProvider())
        assert len(registry) == 2

    def test_register_missing_name_raises(self):
        registry = PostAuthRegistry()
        with pytest.raises(AttributeError, match="provider_name"):
            registry.register(ProviderWithoutName())

    def test_register_overwrite_logs_warning(self, caplog):
        registry = PostAuthRegistry()
        registry.register(FakeProvider())
        with caplog.at_level(
            logging.WARNING, logger="parrot.integrations.telegram.post_auth"
        ):
            registry.register(FakeProvider())
        assert any("overwriting" in rec.message for rec in caplog.records)


class TestPostAuthProviderProtocol:
    """Tests that @runtime_checkable Protocol accepts compliant classes."""

    def test_protocol_check_on_fake(self):
        provider = FakeProvider()
        assert isinstance(provider, PostAuthProvider)

    def test_protocol_check_on_non_provider(self):
        class NotAProvider:
            pass

        assert not isinstance(NotAProvider(), PostAuthProvider)
