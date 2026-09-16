"""FEAT-099 (TASK-080): MCP restore skips credentials that fail integrity checks."""
from __future__ import annotations

import inspect

import pytest
from navigator_session.vault import KeyRing, VaultIntegrityError
from parrot.security.credentials_utils import (
    credential_context,
    decrypt_credential,
    encrypt_credential,
)

MASTER_KEYS = {1: b"\x44" * 32}


@pytest.fixture
def keyring():
    return KeyRing(MASTER_KEYS, 1)


def test_restored_credential_is_bound_to_user_and_name(keyring):
    """A credential copied from another user's document no longer opens."""
    stored = encrypt_credential(
        {"api_key": "sk-mcp"}, credential_context(1, "mcp_perplexity_agent-1"), keyring
    )
    assert decrypt_credential(
        stored, credential_context(1, "mcp_perplexity_agent-1"), keyring
    ) == {"api_key": "sk-mcp"}
    with pytest.raises(VaultIntegrityError):
        decrypt_credential(stored, credential_context(2, "mcp_perplexity_agent-1"), keyring)
    with pytest.raises(VaultIntegrityError):
        decrypt_credential(stored, credential_context(1, "mcp_other_agent-1"), keyring)


def test_restore_path_uses_context_and_skips_on_failure():
    """The MCP restore loop passes a context and keeps its skip-on-error behaviour."""
    from parrot.handlers import agent

    source = inspect.getsource(agent)
    assert "load_master_keys" not in source
    assert "get_vault_keyring()" in source
    assert "credential_context(user_id, config.vault_credential_name)" in source
    # the decrypt call stays inside the try/except that logs and continues
    restore = source[source.index("MCP restore: vault unavailable"):]
    decrypt_at = restore.index("_decrypt_credential(")
    assert "failed to decrypt Vault credential" in restore[decrypt_at:decrypt_at + 1500]
    assert "continue" in restore[decrypt_at:decrypt_at + 1500]
