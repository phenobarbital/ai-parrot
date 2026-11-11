"""BYOK LLM keys in Redis (FEAT-878). Same AAD as DocumentDB/Postgres."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from parrot.security.credentials_utils import decrypt_credential, encrypt_credential, llm_key_context
from parrot.security.vault_utils import get_vault_keyring
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_LLM_KEYS


def mask_api_key(api_key: str) -> str:
    """Return a safe preview containing at most three leading and four trailing characters."""
    if len(api_key) <= 7:
        return "*" * len(api_key)
    return f"{api_key[:3]}…{api_key[-4:]}"


class RedisUserLLMKeyStore:
    """Store sealed per-user LLM keys as Redis documents."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_LLM_KEYS)

    async def get(self, user_id: Any, provider: str) -> str | None:
        """Return the decrypted key, or ``None`` when the key is absent."""
        doc = await self._docs.get({"user_id": user_id, "provider": provider})
        if doc is None:
            return None
        return decrypt_credential(
            doc["api_key"], llm_key_context(user_id, provider), get_vault_keyring()
        ).get("api_key")

    async def put(self, user_id: Any, provider: str, api_key: str) -> None:
        """Seal and upsert a key, retaining ``created_at`` on rotation."""
        now = datetime.now(timezone.utc)
        keyring = get_vault_keyring()
        sealed = encrypt_credential({"api_key": api_key}, llm_key_context(user_id, provider), keyring)
        await self._docs.upsert(
            {"user_id": user_id, "provider": provider},
            {
                "api_key": sealed,
                "key_id": keyring.active_key_id,
                "masked": mask_api_key(api_key),
                "updated_at": now,
            },
            on_insert={"created_at": now},
        )

    async def delete(self, user_id: Any, provider: str) -> bool:
        """Remove a key and report whether it existed."""
        return await self._docs.delete({"user_id": user_id, "provider": provider})

    async def list_masked(self, user_id: Any) -> list[dict[str, Any]]:
        """Return provider previews sorted by provider without exposing key material."""
        documents = await self._docs.find({"user_id": user_id})
        items: list[dict[str, Any]] = []
        for document in documents:
            masked = document.get("masked")
            if masked is None:
                try:
                    credential = decrypt_credential(
                        document["api_key"],
                        llm_key_context(user_id, document["provider"]),
                        get_vault_keyring(),
                    )
                    masked = mask_api_key(credential.get("api_key", ""))
                except Exception:
                    masked = "****"
            created_at = document.get("created_at")
            if isinstance(created_at, datetime):
                created_at = created_at.isoformat()
            items.append(
                {
                    "provider": document["provider"],
                    "masked": masked,
                    "created_at": created_at,
                }
            )
        return sorted(items, key=lambda item: item["provider"])
