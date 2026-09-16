"""Credential encryption helpers — envelope v2 (FEAT-099).

Credentials are sealed with the navigator-session vault kernel and bound
(AEAD associated data) to the document they live in::

    user_credentials   purpose="parrot-credential"  (user_id, name, field="credential")
    user_llm_keys      purpose="parrot-llm-key"     (user_id, provider, field="api_key")

A ciphertext copied to another user, credential name or provider therefore
fails to decrypt instead of silently opening.

The stored representation stays a base64 ASCII string, so DocumentDB string
fields are unchanged.

Security Note:
    Never log credentials, ciphertext or key material.
"""
from __future__ import annotations

import base64
from typing import Any, Optional

import orjson
from navigator_session.vault import KeyRing, VaultContext, open_sealed, seal

CREDENTIAL_PURPOSE = "parrot-credential"
LLM_KEY_PURPOSE = "parrot-llm-key"

CREDENTIAL_FIELD = "credential"
LLM_KEY_FIELD = "api_key"


def normalize_user_id(user_id: Any) -> Any:
    """Canonical ``user_id`` for credential contexts.

    Session user ids reach these helpers as ``int`` or ``str``; digit-only
    strings are normalized to ``int`` so the same document opens regardless of
    the caller. Runtime and the migration target must use this function.

    Raises:
        ValueError: If ``user_id`` is empty, a bool, or of another type.
    """
    if isinstance(user_id, bool):
        raise ValueError("user_id must not be a bool")
    if isinstance(user_id, int):
        return user_id
    if isinstance(user_id, str) and user_id.strip():
        value = user_id.strip()
        return int(value) if value.isdigit() else value
    raise ValueError("user_id is required for vault credentials")


def credential_context(user_id: Any, name: str) -> VaultContext:
    """Context of ``user_credentials.credential`` for ``(user_id, name)``."""
    if not name:
        raise ValueError("credential name is required")
    return VaultContext(
        purpose=CREDENTIAL_PURPOSE,
        layer="db",
        fields=(
            ("user_id", normalize_user_id(user_id)),
            ("name", str(name)),
            ("field", CREDENTIAL_FIELD),
        ),
    )


def llm_key_context(user_id: Any, provider: str) -> VaultContext:
    """Context of ``user_llm_keys.api_key`` for ``(user_id, provider)``."""
    if not provider:
        raise ValueError("provider is required")
    return VaultContext(
        purpose=LLM_KEY_PURPOSE,
        layer="db",
        fields=(
            ("user_id", normalize_user_id(user_id)),
            ("provider", str(provider)),
            ("field", LLM_KEY_FIELD),
        ),
    )


def encrypt_credential(
    credential: dict,
    context: VaultContext,
    keyring: KeyRing,
    *,
    key_id: Optional[int] = None,
) -> str:
    """Encrypt a credential dict for DocumentDB storage.

    Args:
        credential: Dict of secret values (e.g. asyncdb connection params or
            ``{"api_key": "sk-..."}``). All unicode values round-trip.
        context: Context binding the ciphertext to its document and field
            (see :func:`credential_context` / :func:`llm_key_context`).
        keyring: Vault key ring; new ciphertexts use its active key.
        key_id: Optional master key version override (rotation/migration).

    Returns:
        Base64-encoded (ASCII) sealed envelope, ready for DocumentDB.
    """
    plaintext: bytes = orjson.dumps(credential)
    blob = seal(plaintext, context, keyring, key_id=key_id)
    return base64.b64encode(blob).decode("ascii")


def decrypt_credential(
    encrypted: str,
    context: VaultContext,
    keyring: KeyRing,
) -> dict:
    """Decrypt a credential string stored by :func:`encrypt_credential`.

    Args:
        encrypted: Base64-encoded sealed envelope.
        context: Expected context of the document and field.
        keyring: Vault key ring holding the referenced key version.

    Returns:
        Original credential dict.

    Raises:
        navigator_session.vault.VaultCryptoError: Tampered ciphertext, wrong
            document/field, unknown key version or legacy (v1) format.
        binascii.Error: If ``encrypted`` is not valid base64.
    """
    blob = base64.b64decode(encrypted)
    return orjson.loads(open_sealed(blob, context, keyring))


def reseal_credential(
    encrypted: str,
    old_context: VaultContext,
    new_context: VaultContext,
    keyring: KeyRing,
) -> str:
    """Re-seal a credential for a new context (rename of name/provider).

    Args:
        encrypted: Currently stored ciphertext.
        old_context: Context it was sealed with.
        new_context: Context of the new document identity.
        keyring: Vault key ring.

    Returns:
        Base64-encoded ciphertext bound to ``new_context``.
    """
    return encrypt_credential(
        decrypt_credential(encrypted, old_context, keyring), new_context, keyring
    )
