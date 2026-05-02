"""Transparent AES-GCM encryption helpers for postgres TEXT columns.

Used by :class:`UserBotModel` to seal/unseal ``mcp_config`` and ``tools_config``
blobs which may contain credentials. Reuses the same vault key system as
:mod:`parrot.handlers.credentials_utils` so existing master keys cover this
table without further configuration.

Plaintext shape is JSON-serialisable (typically a list of dicts).
Ciphertext is the base64 string returned by :func:`encrypt_credential`.
"""
from __future__ import annotations

from typing import Any, Optional

from parrot.handlers.credentials_utils import (
    decrypt_credential,
    encrypt_credential,
)
from parrot.handlers.vault_utils import load_vault_keys


def seal(value: Any) -> Optional[str]:
    """Encrypt a JSON-serialisable value to a base64 ciphertext string.

    Returns ``None`` for empty / falsy values so the column stays NULL.
    Raises :class:`RuntimeError` if the vault keys are not configured.
    """
    if value in (None, [], {}, ""):
        return None
    active_key_id, active_key, _ = load_vault_keys()
    payload = value if isinstance(value, dict) else {"__list__": value}
    return encrypt_credential(payload, active_key_id, active_key)


def unseal(blob: Optional[str]) -> Any:
    """Decrypt a base64 ciphertext string back to its original value.

    Returns ``None`` if ``blob`` is empty / NULL.
    """
    if not blob:
        return None
    _, _, all_keys = load_vault_keys()
    plaintext = decrypt_credential(blob, all_keys)
    if isinstance(plaintext, dict) and set(plaintext.keys()) == {"__list__"}:
        return plaintext["__list__"]
    return plaintext
