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


class ToolkitConfigService:
    """CRUD over ``user_toolkit_configs`` keyed ``(user_id, agent_id, slug)``."""

    async def save(self, override: UserToolkitOverride) -> None:
        """Upsert an override using its user, agent, and toolkit slug."""
        query = {"user_id": override.user_id, "agent_id": override.agent_id, "slug": override.slug}
        async with DocumentDb() as db:
            await db.update_one(COLLECTION, query, {"$set": override.model_dump()}, upsert=True)

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        """Load valid overrides belonging to one user and agent."""
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
        query = {"user_id": user_id, "agent_id": agent_id, "slug": slug}
        async with DocumentDb() as db:
            existing = await db.read_one(COLLECTION, query)
            if existing is None:
                return False
            await db.delete(COLLECTION, query)
        return True

    async def revision(self, user_id: str, agent_id: str) -> str:
        """Return the latest override timestamp, or an empty string when none exist."""
        overrides = await self.load(user_id, agent_id)
        return max((override.updated_at for override in overrides), default="")
