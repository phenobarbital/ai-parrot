"""BYOK keys in Postgres (spec §2.10, M11). Same AAD as DocumentDB, so ciphertexts copy verbatim."""
from __future__ import annotations

import logging
from typing import Any

from parrot.auth.broker import set_user_llm_key_store
from parrot.security.credentials_utils import decrypt_credential, encrypt_credential, llm_key_context
from parrot.security.vault_utils import get_vault_keyring

from .repositories import _fetch_all, _fetch_one
from .vault_targets import QUARANTINE_MARK

logger = logging.getLogger("Parrot.AgentStudio.Storage")

_GET_SQL = "SELECT api_key_enc FROM navigator.ai_user_llm_keys WHERE user_id = $1 AND provider = $2"
_PUT_SQL = (
    "INSERT INTO navigator.ai_user_llm_keys (user_id, provider, api_key_enc, key_id, masked) "
    "VALUES ($1, $2, $3, $4, $5) "
    "ON CONFLICT (user_id, provider) DO UPDATE SET api_key_enc = EXCLUDED.api_key_enc, "
    "key_id = EXCLUDED.key_id, masked = EXCLUDED.masked, updated_at = now() "
    "RETURNING provider"
)
_DELETE_SQL = "DELETE FROM navigator.ai_user_llm_keys WHERE user_id = $1 AND provider = $2 RETURNING provider"
# Vault quarantine renames a row's ``provider`` with this marker; such rows are not live keys.
_LIST_SQL = (
    "SELECT provider, masked, created_at FROM navigator.ai_user_llm_keys "
    "WHERE user_id = $1 AND position($2 in provider) = 0 ORDER BY provider"
)


class PgUserLLMKeyStore:
    """Per-user provider keys over the host pool. Keys are per user, never per tenant (spec Q4)."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def get(self, user_id: Any, provider: str) -> str | None:
        """Return the decrypted key, ``None`` when absent. Raises on a keyring or decrypt failure."""
        async with self._pool.acquire() as conn:
            row = await _fetch_one(conn, _GET_SQL, str(user_id), provider)
        if row is None:
            return None
        credential = decrypt_credential(row["api_key_enc"], llm_key_context(user_id, provider), get_vault_keyring())
        return credential.get("api_key")

    async def put(self, user_id: Any, provider: str, api_key: str) -> None:
        """Upsert the sealed key; ``created_at`` survives a rotation of the same (user, provider)."""
        from ..byok import _mask  # lazy: byok imports this module lazily too

        keyring = get_vault_keyring()
        sealed = encrypt_credential({"api_key": api_key}, llm_key_context(user_id, provider), keyring)
        async with self._pool.acquire() as conn:
            await _fetch_one(conn, _PUT_SQL, str(user_id), provider, sealed, keyring.active_key_id, _mask(api_key))

    async def delete(self, user_id: Any, provider: str) -> bool:
        """Remove the key; ``True`` when a row existed."""
        async with self._pool.acquire() as conn:
            return await _fetch_one(conn, _DELETE_SQL, str(user_id), provider) is not None

    async def list_masked(self, user_id: Any) -> list[dict[str, Any]]:
        """Masked previews (no decryption), in ``StudioKeysHandler.get`` item shape."""
        async with self._pool.acquire() as conn:
            rows = await _fetch_all(conn, _LIST_SQL, str(user_id), QUARANTINE_MARK)
        return [
            {"provider": r["provider"], "masked": r["masked"], "created_at": r["created_at"].isoformat()}
            for r in rows
        ]


_REGISTERED: "PgUserLLMKeyStore | None" = None
STUDIO_BYOK_STORE_APP_KEY = "studio_byok_store"


def register_byok_store(store: "PgUserLLMKeyStore | None") -> None:
    """Called by the server at startup when BYOK_STORE=postgres; read by the core resolver."""
    global _REGISTERED
    _REGISTERED = store
    set_user_llm_key_store(store)


def install_byok_store(app: Any, pool: Any) -> PgUserLLMKeyStore:
    """Startup: build the store over ``pool``, remember it on ``app`` and register it with the core resolver."""
    store = PgUserLLMKeyStore(pool)
    app[STUDIO_BYOK_STORE_APP_KEY] = store
    register_byok_store(store)
    return store


def release_byok_store(store: "PgUserLLMKeyStore | None") -> None:
    """Unregister ``store`` from the core resolver, but only while it is still the registered one."""
    if store is not None and _REGISTERED is store:
        register_byok_store(None)


def get_byok_store(app: Any) -> PgUserLLMKeyStore:
    """The store registered for ``app`` at startup (``ensure_studio_storage``); never creates one lazily."""
    store = app.get(STUDIO_BYOK_STORE_APP_KEY)
    if store is None:
        raise RuntimeError("BYOK_STORE=postgres but no Postgres BYOK store was registered at startup")
    return store
