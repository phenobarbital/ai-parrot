"""Vault credentials in Postgres (spec §2.10, M12). Same AAD as DocumentDB, so ciphertexts copy verbatim."""
from __future__ import annotations

import logging
from typing import Any

from parrot.security.credentials_utils import credential_context, decrypt_credential, encrypt_credential
from parrot.security.vault_utils import get_vault_keyring, set_vault_credential_store

from .repositories import _fetch_one

logger = logging.getLogger("Parrot.AgentStudio.Storage")

_GET_SQL = "SELECT credential FROM navigator.ai_user_credentials WHERE user_id = $1 AND name = $2"
_PUT_SQL = (
    "INSERT INTO navigator.ai_user_credentials (user_id, name, credential) VALUES ($1, $2, $3) "
    "ON CONFLICT (user_id, name) DO UPDATE SET credential = EXCLUDED.credential, updated_at = now() "
    "RETURNING name"
)
_DELETE_SQL = "DELETE FROM navigator.ai_user_credentials WHERE user_id = $1 AND name = $2 RETURNING name"


class PgVaultCredentialStore:
    """``store`` / ``retrieve`` / ``delete`` with the signatures of ``vault_utils`` over the host pool."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def store(self, user_id: Any, vault_name: str, secret_params: dict[str, Any]) -> None:
        """Seal and upsert; ``created_at`` survives a rewrite of the same ``(user_id, name)``."""
        sealed = encrypt_credential(secret_params, credential_context(user_id, vault_name), get_vault_keyring())
        async with self._pool.acquire() as conn:
            await _fetch_one(conn, _PUT_SQL, str(user_id), vault_name, sealed)

    async def retrieve(self, user_id: Any, vault_name: str) -> dict[str, Any]:
        """Open the credential. Raises ``KeyError`` when absent, like the DocumentDB path."""
        async with self._pool.acquire() as conn:
            row = await _fetch_one(conn, _GET_SQL, str(user_id), vault_name)
        if row is None:
            raise KeyError(f"Vault credential '{vault_name}' not found for user '{user_id}'")
        return decrypt_credential(row["credential"], credential_context(user_id, vault_name), get_vault_keyring())

    async def delete(self, user_id: Any, vault_name: str) -> None:
        """Hard-delete; absent is not an error."""
        async with self._pool.acquire() as conn:
            await _fetch_one(conn, _DELETE_SQL, str(user_id), vault_name)


_REGISTERED: "PgVaultCredentialStore | None" = None


def register_vault_store(store: "PgVaultCredentialStore | None") -> None:
    """Called by the server at startup when VAULT_STORE=postgres; read by core ``vault_utils``."""
    global _REGISTERED
    _REGISTERED = store
    set_vault_credential_store(store)


def get_vault_store(pool: Any) -> PgVaultCredentialStore:
    """The store over ``pool``, registered with core (reused while the pool is unchanged)."""
    store = _REGISTERED
    if store is None or store._pool is not pool:
        store = PgVaultCredentialStore(pool)
        register_vault_store(store)
    return store
