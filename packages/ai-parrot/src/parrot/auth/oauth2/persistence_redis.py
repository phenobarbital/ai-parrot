"""OAuth2 ``users_integrations`` persistence in Redis (FEAT-878)."""

from __future__ import annotations

import logging

from parrot.auth.oauth2.models import UsersIntegrationRow
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USERS_INTEGRATIONS

logger = logging.getLogger("parrot.auth.oauth2.persistence")


class RedisUsersIntegrationStore:
    """Redis twin of the four ``parrot.auth.oauth2.persistence`` functions."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USERS_INTEGRATIONS)

    async def upsert(self, row: UsersIntegrationRow) -> None:
        """Upsert an integration using its user and provider composite key."""
        key = {"user_id": row.user_id, "provider": row.provider}
        await self._docs.upsert(
            key,
            row.model_dump(mode="json", exclude={"user_id", "provider"}),
            on_insert=key,
        )

    async def get(self, user_id: str, provider: str) -> UsersIntegrationRow | None:
        """Return one integration, or ``None`` when it is absent."""
        document = await self._docs.get({"user_id": user_id, "provider": provider})
        return UsersIntegrationRow.model_validate(document) if document else None

    async def delete(self, user_id: str, provider: str) -> None:
        """Delete one integration, treating an absent record as a no-op."""
        await self._docs.delete({"user_id": user_id, "provider": provider})

    async def list(self, user_id: str) -> list[UsersIntegrationRow]:
        """Return valid integrations for a user, logging and skipping invalid documents."""
        rows: list[UsersIntegrationRow] = []
        for document in await self._docs.find({"user_id": user_id}):
            try:
                rows.append(UsersIntegrationRow.model_validate(document))
            except ValueError:
                logger.warning("Skipping invalid users_integration for user_id=%s", user_id)
        return rows
