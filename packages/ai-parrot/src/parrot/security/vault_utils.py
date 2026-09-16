"""Vault CRUD helpers — shared encrypted-credential storage for handlers.

Provides ``store``, ``retrieve``, and ``delete`` operations on the
``user_credentials`` DocumentDB collection using the same AES-GCM encryption
scheme as :class:`~parrot.handlers.credentials.CredentialsHandler`.

Any handler that needs to persist secrets in the Vault should import from here
rather than duplicating this logic.

Usage::

    from parrot.security.vault_utils import (
        store_vault_credential,
        retrieve_vault_credential,
        delete_vault_credential,
    )

    await store_vault_credential(user_id, "mcp_perplexity_agent-1", {"api_key": "sk-..."})
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from parrot.security.credentials_utils import (
    credential_context,
    decrypt_credential,
    encrypt_credential,
)
from parrot.interfaces.documentdb import DocumentDb

try:
    from navigator_session.vault import KeyRing
except ImportError:  # pragma: no cover - navigator-session not installed
    KeyRing = None  # type: ignore[assignment]

_KEYRING: Any = None


# DocumentDB collection for Vault credential storage (mirrors CredentialsHandler)
VAULT_CRED_COLLECTION: str = "user_credentials"


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------


def get_vault_keyring() -> Any:
    """Return the process-wide vault :class:`KeyRing` (built on first use).

    Returns:
        KeyRing built from ``VAULT_MASTER_KEY_v{N}`` / ``VAULT_ACTIVE_KEY_ID``.

    Raises:
        RuntimeError: If navigator-session vault crypto is unavailable or the
            keys are not configured.
    """
    global _KEYRING  # pylint: disable=global-statement
    if _KEYRING is None:
        if KeyRing is None:
            raise RuntimeError(
                "navigator_session.vault is not available. "
                "Ensure navigator-session is installed."
            )
        try:
            _KEYRING = KeyRing.from_env()
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError(f"Vault keys are not configured: {exc}") from exc
    return _KEYRING


def reset_vault_keyring() -> None:
    """Drop the cached key ring (tests, key reconfiguration)."""
    global _KEYRING  # pylint: disable=global-statement
    _KEYRING = None


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


async def store_vault_credential(
    user_id: str,
    vault_name: str,
    secret_params: Dict[str, Any],
) -> None:
    """Encrypt and upsert secret parameters in the Vault.

    Stores the credential under the compound key ``(user_id, vault_name)``
    in the ``user_credentials`` collection.  If a document with that key
    already exists it is updated; otherwise a new document is inserted.

    Args:
        user_id: Owner's user identifier.
        vault_name: Deterministic credential name (e.g. ``"mcp_perplexity_agent-1"``).
        secret_params: Dict of secret values to encrypt (e.g. ``{"api_key": "sk-..."}``)

    Raises:
        RuntimeError: If vault keys are unavailable.
        navigator_session.vault.VaultCryptoError: If the stored credential
            does not belong to ``(user_id, vault_name)`` or fails integrity.
    """
    keyring = get_vault_keyring()
    encrypted = encrypt_credential(
        secret_params, credential_context(user_id, vault_name), keyring
    )
    now_str = datetime.now(timezone.utc).isoformat()

    async with DocumentDb() as db:
        existing = await db.read_one(
            VAULT_CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )
        if existing is None:
            await db.write(
                VAULT_CRED_COLLECTION,
                {
                    "user_id": user_id,
                    "name": vault_name,
                    "credential": encrypted,
                    "created_at": now_str,
                    "updated_at": now_str,
                },
            )
        else:
            await db.update_one(
                VAULT_CRED_COLLECTION,
                {"user_id": user_id, "name": vault_name},
                {"$set": {"credential": encrypted, "updated_at": now_str}},
            )


async def retrieve_vault_credential(
    user_id: str,
    vault_name: str,
) -> Dict[str, Any]:
    """Decrypt and return a secret credential from the Vault.

    Args:
        user_id: Owner's user identifier.
        vault_name: Vault credential name.

    Returns:
        Decrypted dict of secret parameters.

    Raises:
        KeyError: If the credential is not found in the Vault.
        RuntimeError: If vault keys are unavailable.
        navigator_session.vault.VaultCryptoError: If the stored credential
            does not belong to ``(user_id, vault_name)`` or fails integrity.
    """
    keyring = get_vault_keyring()

    async with DocumentDb() as db:
        doc = await db.read_one(
            VAULT_CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )

    if doc is None:
        raise KeyError(
            f"Vault credential '{vault_name}' not found for user '{user_id}'"
        )

    return decrypt_credential(
        doc["credential"], credential_context(user_id, vault_name), keyring
    )


async def delete_vault_credential(user_id: str, vault_name: str) -> None:
    """Hard-delete a Vault credential from DocumentDB.

    Args:
        user_id: Owner's user identifier.
        vault_name: Vault credential name to remove.
    """
    async with DocumentDb() as db:
        await db.delete(
            VAULT_CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )


# ---------------------------------------------------------------------------
# OAuth2 helpers
# ---------------------------------------------------------------------------


def oauth2_vault_name(provider_id: str, channel: str, user_id: str) -> str:
    """Build the deterministic Vault credential name for an OAuth2 token.

    Mirrors :data:`parrot.auth.oauth2_base._VAULT_NAME_TEMPLATE` so the
    namespace stays consistent across writers and readers.
    """
    return f"oauth2_{provider_id}_{channel}_{user_id}"
