"""Vault CRUD helpers — shared encrypted-credential storage for handlers.

Provides ``store``, ``retrieve``, and ``delete`` operations on the
``user_credentials`` DocumentDB collection using the same AES-GCM encryption
scheme as :class:`~parrot.handlers.credentials.CredentialsHandler`.

Any handler that needs to persist secrets in the Vault should import from here
rather than duplicating this logic.

Usage::

    from parrot.handlers.vault_utils import (
        store_vault_credential,
        retrieve_vault_credential,
        delete_vault_credential,
    )

    await store_vault_credential(user_id, "mcp_perplexity_agent-1", {"api_key": "sk-..."})
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from parrot.handlers.credentials_utils import decrypt_credential, encrypt_credential
from parrot.interfaces.documentdb import DocumentDb

try:
    from navigator_session.vault.config import get_active_key_id, load_master_keys
except ImportError:
    get_active_key_id = None  # type: ignore[assignment]
    load_master_keys = None   # type: ignore[assignment]


# DocumentDB collection for Vault credential storage (mirrors CredentialsHandler)
VAULT_CRED_COLLECTION: str = "user_credentials"


# ---------------------------------------------------------------------------
# Key loading
# ---------------------------------------------------------------------------


def load_vault_keys() -> tuple[int, bytes, dict[int, bytes]]:
    """Load vault master keys from the environment.

    Returns:
        Tuple of ``(active_key_id, active_master_key, all_master_keys)``.

    Raises:
        RuntimeError: If ``navigator_session.vault.config`` is unavailable.
    """
    if load_master_keys is None or get_active_key_id is None:
        raise RuntimeError(
            "navigator_session.vault.config is not available. "
            "Ensure navigator-session is installed."
        )
    master_keys = load_master_keys()
    active_key_id = get_active_key_id()
    active_key = master_keys[active_key_id]
    return active_key_id, active_key, master_keys


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
    """
    active_key_id, active_key, _ = load_vault_keys()
    encrypted = encrypt_credential(secret_params, active_key_id, active_key)
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
    """
    _, _, master_keys = load_vault_keys()

    async with DocumentDb() as db:
        doc = await db.read_one(
            VAULT_CRED_COLLECTION,
            {"user_id": user_id, "name": vault_name},
        )

    if doc is None:
        raise KeyError(
            f"Vault credential '{vault_name}' not found for user '{user_id}'"
        )

    return decrypt_credential(doc["credential"], master_keys)


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
