"""FEAT-099 (TASK-080): BYOK keys are sealed bound to (user_id, provider)."""
from __future__ import annotations

import pytest
from navigator_session.vault import KeyRing, VaultIntegrityError
from parrot.security.credentials_utils import (
    decrypt_credential,
    encrypt_credential,
    llm_key_context,
)

MASTER_KEYS = {1: b"\x33" * 32}
USER = "user-42"


@pytest.fixture
def keyring():
    return KeyRing(MASTER_KEYS, 1)


def test_byok_key_bound_to_provider(keyring):
    """A key stored for one provider cannot be read as another provider's key."""
    stored = encrypt_credential({"api_key": "sk-openai"}, llm_key_context(USER, "openai"), keyring)
    assert decrypt_credential(stored, llm_key_context(USER, "openai"), keyring) == {
        "api_key": "sk-openai"
    }
    with pytest.raises(VaultIntegrityError):
        decrypt_credential(stored, llm_key_context(USER, "anthropic"), keyring)


def test_byok_key_bound_to_user(keyring):
    stored = encrypt_credential({"api_key": "sk-openai"}, llm_key_context(USER, "openai"), keyring)
    with pytest.raises(VaultIntegrityError):
        decrypt_credential(stored, llm_key_context("user-99", "openai"), keyring)


def test_byok_handler_uses_contexts():
    """The handler seals/opens with llm_key_context and the shared key ring."""
    import inspect

    from parrot.handlers.studio import byok

    source = inspect.getsource(byok)
    assert "_load_vault_keys" not in source and "load_master_keys" not in source
    assert source.count("llm_key_context(") >= 2
    assert "get_vault_keyring" in source
