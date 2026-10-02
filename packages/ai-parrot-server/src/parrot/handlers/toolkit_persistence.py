"""Per-user toolkit overrides (FEAT-593) — DocumentDB ``user_toolkit_configs``."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from parrot.interfaces.documentdb import DocumentDb

logger = logging.getLogger(__name__)
COLLECTION: str = "user_toolkit_configs"


class UserToolkitOverride(BaseModel):
    """One user's override of one toolkit on one agent (non-secret params + vault refs)."""

    user_id: str
    agent_id: str
    slug: str
    params: dict[str, Any] = Field(default_factory=dict)
    secret_refs: dict[str, str] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


_PURGE_MAX_PASSES = 50
_PG_OVERRIDES: Any = None


def set_toolkit_override_store(store: Any) -> None:
    """Register the Postgres store (``TOOLKIT_OVERRIDES_STORE=postgres``); ``None`` restores DocumentDB."""
    global _PG_OVERRIDES  # pylint: disable=global-statement
    _PG_OVERRIDES = store


class ToolkitConfigService:
    """CRUD over ``user_toolkit_configs`` keyed ``(user_id, agent_id, slug)``."""

    async def save(self, override: UserToolkitOverride) -> None:
        """Upsert an override using its user, agent, and toolkit slug."""
        if _PG_OVERRIDES is not None:
            return await _PG_OVERRIDES.save(override)
        query = {"user_id": override.user_id, "agent_id": override.agent_id, "slug": override.slug}
        async with DocumentDb() as db:
            await db.update_one(COLLECTION, query, {"$set": override.model_dump()}, upsert=True)

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        """Load valid overrides belonging to one user and agent."""
        if _PG_OVERRIDES is not None:
            return await _PG_OVERRIDES.load(user_id, agent_id)
        async with DocumentDb() as db:
            docs = await db.read(COLLECTION, {"user_id": user_id, "agent_id": agent_id})

        overrides: list[UserToolkitOverride] = []
        for doc in docs:
            doc.pop("_id", None)
            try:
                overrides.append(UserToolkitOverride.model_validate(doc))
            except ValidationError as exc:
                logger.warning(
                    "Skipping malformed toolkit override for user='%s' agent='%s': %s", user_id, agent_id, exc
                )
        return overrides

    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:
        """Delete an override and report whether it existed."""
        if _PG_OVERRIDES is not None:
            return await _PG_OVERRIDES.remove(user_id, agent_id, slug)
        query = {"user_id": user_id, "agent_id": agent_id, "slug": slug}
        async with DocumentDb() as db:
            existing = await db.read_one(COLLECTION, query)
            if existing is None:
                return False
            await db.delete(COLLECTION, query)
        return True

    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
        """Delete every user's override documents for ``agent_ref`` and return them (spec §2.5c clean-up)."""
        if _PG_OVERRIDES is not None:
            return await _PG_OVERRIDES.purge_agent(agent_ref)
        query = {"agent_id": agent_ref}
        docs: list[dict] = []
        async with DocumentDb() as db:
            # Delete exactly the documents that were read, and re-read until none is left, so an override written
            # concurrently is either purged (and returned for vault clean-up) or survives untouched — never lost.
            for _ in range(_PURGE_MAX_PASSES):
                batch = await db.read(COLLECTION, query)
                if not batch:
                    break
                docs.extend(batch)
                ids = [doc["_id"] for doc in batch if "_id" in doc]
                if not ids:
                    await db.delete_many(COLLECTION, query)
                    break
                await db.delete_many(COLLECTION, {**query, "_id": {"$in": ids}})
        purged: list[UserToolkitOverride] = []
        for doc in docs or []:
            doc.pop("_id", None)
            try:
                purged.append(UserToolkitOverride.model_validate(doc))
            except ValidationError as exc:
                logger.warning("Purged malformed toolkit override for agent='%s': %s", agent_ref, exc)
        return purged

    async def revision(self, user_id: str, agent_id: str) -> str:
        """Return the latest override timestamp, or an empty string when none exist."""
        if _PG_OVERRIDES is not None:
            return await _PG_OVERRIDES.revision(user_id, agent_id)
        overrides = await self.load(user_id, agent_id)
        return max((override.updated_at for override in overrides), default="")
