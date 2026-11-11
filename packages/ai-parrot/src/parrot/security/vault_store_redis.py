"""Vault credentials in Redis (FEAT-878)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_CREDENTIALS

logger = logging.getLogger("parrot.security.vault")


class RedisVaultCredentialStore:
    """Store encrypted ``user_credentials`` documents in Redis."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_CREDENTIALS)

    async def store(self, user_id: Any, vault_name: str, secret_params: dict[str, Any]) -> None:
        """Seal a credential, preserving its creation timestamp on rewrite."""
        from parrot.security.vault_utils import get_vault_keyring

        sealed = encrypt_credential(secret_params, credential_context(user_id, vault_name), get_vault_keyring())
        now = datetime.now(timezone.utc).isoformat()
        await self._docs.upsert(
            {"user_id": user_id, "name": vault_name},
            {"credential": sealed, "updated_at": now},
            on_insert={"created_at": now},
        )

    async def retrieve(self, user_id: Any, vault_name: str) -> dict[str, Any]:
        """Open a stored credential.

        Raises:
            KeyError: If the credential does not exist.
        """
        from parrot.security.vault_utils import get_vault_keyring

        document = await self._docs.get({"user_id": user_id, "name": vault_name})
        if document is None:
            raise KeyError(f"Vault credential '{vault_name}' not found for user '{user_id}'")
        return decrypt_credential(
            document["credential"], credential_context(user_id, vault_name), get_vault_keyring()
        )

    async def delete(self, user_id: Any, vault_name: str) -> None:
        """Delete a stored credential when present."""
        await self._docs.delete({"user_id": user_id, "name": vault_name})

    async def list_credentials(self, user_id: Any) -> dict[str, dict[str, Any]]:
        """Return decrypted credentials, skipping entries that cannot be opened."""
        from parrot.security.vault_utils import get_vault_keyring

        keyring = get_vault_keyring()
        credentials: dict[str, dict[str, Any]] = {}
        for document in await self._docs.find({"user_id": user_id}):
            name = document["name"]
            try:
                credentials[name] = decrypt_credential(
                    document["credential"], credential_context(user_id, name), keyring
                )
            except Exception as exc:  # noqa: BLE001 - one invalid credential must not hide valid entries
                logger.warning("Skipping undecryptable credential '%s': %s", name, type(exc).__name__)
        return credentials

    async def exists(self, user_id: Any, vault_name: str) -> bool:
        """Return whether the credential exists without decrypting it."""
        return await self._docs.exists({"user_id": user_id, "name": vault_name})
