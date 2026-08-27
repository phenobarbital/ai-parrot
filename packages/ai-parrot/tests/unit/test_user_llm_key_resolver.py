"""Unit tests for ``_UserLLMKeyResolver`` (FEAT-467 TASK-2516 — BYOK).

Fakes ``navigator_session.vault.config.load_master_keys`` and
``parrot.interfaces.documentdb.DocumentDb`` at their SOURCE modules —
``_UserLLMKeyResolver.resolve()`` does local ``from X import Y`` imports
inside the method body, which re-resolve ``X.Y`` fresh on every call, so
patching the source module's attribute (not a re-exported name) is both
necessary and sufficient.
"""
from __future__ import annotations

from typing import ClassVar

import parrot.interfaces.documentdb as documentdb_module
import pytest
from parrot.auth.broker import CredentialResolverFactory, _UserLLMKeyResolver
from parrot.security.credentials_utils import encrypt_credential

MASTER_KEY_ID = 1
MASTER_KEY = b"0" * 32  # deterministic 32-byte AES key for tests
MASTER_KEYS = {MASTER_KEY_ID: MASTER_KEY}


class _FakeDocumentDb:
    """In-memory stand-in for ``parrot.interfaces.documentdb.DocumentDb``."""

    docs: ClassVar[list] = []  # populated per-test via the class itself (simple + explicit)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def read_one(self, collection_name, query):
        for doc in self.docs:
            if doc.get("_collection") != collection_name:
                continue
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None


@pytest.fixture(autouse=True)
def patch_vault_keys(monkeypatch):
    """Stand in for navigator_session.vault.config.load_master_keys."""
    try:
        import navigator_session.vault.config as vault_config_module
    except ImportError:
        pytest.skip("navigator_session.vault not installed")
    monkeypatch.setattr(vault_config_module, "load_master_keys", lambda: MASTER_KEYS)


@pytest.fixture
def fake_db(monkeypatch):
    _FakeDocumentDb.docs = []
    monkeypatch.setattr(documentdb_module, "DocumentDb", _FakeDocumentDb)
    return _FakeDocumentDb


def _seed_stored_key(user_id: str, provider: str, api_key: str) -> None:
    encrypted = encrypt_credential({"api_key": api_key}, MASTER_KEY_ID, MASTER_KEY)
    _FakeDocumentDb.docs.append({
        "_collection": "user_llm_keys",
        "user_id": user_id,
        "provider": provider,
        "api_key": encrypted,
    })


class TestUserLLMKeyResolver:
    @pytest.mark.asyncio
    async def test_resolves_stored_key(self, fake_db):
        _seed_stored_key("user-1", "anthropic", "sk-ant-secret-value")

        resolver = _UserLLMKeyResolver()
        result = await resolver.resolve("anthropic", "user-1")

        assert result == "sk-ant-secret-value"

    @pytest.mark.asyncio
    async def test_provider_normalized_lowercase(self, fake_db):
        _seed_stored_key("user-1", "anthropic", "sk-ant-secret-value")

        resolver = _UserLLMKeyResolver()
        result = await resolver.resolve("ANTHROPIC", "user-1")

        assert result == "sk-ant-secret-value"

    @pytest.mark.asyncio
    async def test_absent_key_returns_none(self, fake_db):
        resolver = _UserLLMKeyResolver()
        result = await resolver.resolve("anthropic", "no-such-user")
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_user_does_not_leak_another_users_key(self, fake_db):
        _seed_stored_key("user-1", "anthropic", "sk-ant-secret-value")

        resolver = _UserLLMKeyResolver()
        result = await resolver.resolve("anthropic", "user-2")

        assert result is None

    @pytest.mark.asyncio
    async def test_vault_unavailable_returns_none(self, fake_db, monkeypatch):
        import navigator_session.vault.config as vault_config_module

        def _raise():
            raise RuntimeError("vault keys not configured")

        monkeypatch.setattr(vault_config_module, "load_master_keys", _raise)
        _seed_stored_key("user-1", "anthropic", "sk-ant-secret-value")

        resolver = _UserLLMKeyResolver()
        result = await resolver.resolve("anthropic", "user-1")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_auth_url_returns_empty_string(self):
        resolver = _UserLLMKeyResolver()
        assert await resolver.get_auth_url("anthropic", "user-1") == ""


class TestCredentialResolverFactoryBuildsUserLLMKeyResolver:
    def test_build_user_llm_key_resolver_returns_resolver_instance(self):
        factory = CredentialResolverFactory()
        resolver = factory.build_user_llm_key_resolver()
        assert isinstance(resolver, _UserLLMKeyResolver)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
