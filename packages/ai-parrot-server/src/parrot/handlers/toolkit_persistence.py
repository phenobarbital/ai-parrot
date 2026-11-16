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


_REDIS_OVERRIDES: Any = None


def _active_override_store() -> Any:
    """Return the store to use, or ``None`` for DocumentDB.

    Registered store wins; otherwise ``TOOLKIT_OVERRIDES_STORE`` decides: ``redis`` -> module-level
    ``RedisToolkitOverrideStore``, ``documentdb`` -> ``None``, ``postgres`` with nothing registered ->
    ``RuntimeError`` (fail closed).
    """
    global _REDIS_OVERRIDES  # pylint: disable=global-statement
    if _PG_OVERRIDES is not None:
        return _PG_OVERRIDES
    from parrot.userstore import resolve_store_backend

    backend = resolve_store_backend("TOOLKIT_OVERRIDES_STORE")
    if backend == "documentdb":
        return None
    if backend == "postgres":
        raise RuntimeError("TOOLKIT_OVERRIDES_STORE=postgres but no Postgres override store is registered")
    if _REDIS_OVERRIDES is None:
        from .toolkit_persistence_redis import RedisToolkitOverrideStore

        _REDIS_OVERRIDES = RedisToolkitOverrideStore()
    return _REDIS_OVERRIDES


class ToolkitConfigService:
    """CRUD over ``user_toolkit_configs`` keyed ``(user_id, agent_id, slug)``."""

    async def save(self, override: UserToolkitOverride) -> None:
        """Upsert an override using its user, agent, and toolkit slug."""
        store = _active_override_store()
        if store is not None:
            return await store.save(override)
        query = {"user_id": override.user_id, "agent_id": override.agent_id, "slug": override.slug}
        async with DocumentDb() as db:
            await db.update_one(COLLECTION, query, {"$set": override.model_dump()}, upsert=True)

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        """Load valid overrides belonging to one user and agent."""
        store = _active_override_store()
        if store is not None:
            return await store.load(user_id, agent_id)
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
        store = _active_override_store()
        if store is not None:
            return await store.remove(user_id, agent_id, slug)
        query = {"user_id": user_id, "agent_id": agent_id, "slug": slug}
        async with DocumentDb() as db:
            existing = await db.read_one(COLLECTION, query)
            if existing is None:
                return False
            await db.delete(COLLECTION, query)
        return True

    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
        """Delete every user's override documents for ``agent_ref`` and return them (spec §2.5c clean-up)."""
        store = _active_override_store()
        if store is not None:
            return await store.purge_agent(agent_ref)
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
        store = _active_override_store()
        if store is not None:
            return await store.revision(user_id, agent_id)
        overrides = await self.load(user_id, agent_id)
        return max((override.updated_at for override in overrides), default="")
