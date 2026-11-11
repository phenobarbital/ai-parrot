"""Per-user toolkit overrides in Redis (FEAT-878): ``TOOLKIT_OVERRIDES_STORE=redis`` (the default)."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_TOOLKIT_CONFIGS

from .toolkit_persistence import UserToolkitOverride

logger = logging.getLogger(__name__)


def _validate(doc: dict) -> UserToolkitOverride | None:
    """Validate a stored document, returning ``None`` (with a warning) when malformed."""
    try:
        return UserToolkitOverride.model_validate(doc)
    except ValidationError as exc:
        logger.warning("Skipping malformed toolkit override (agent=%s): %s", doc.get("agent_id"), type(exc).__name__)
        return None


class RedisToolkitOverrideStore:
    """``ToolkitConfigService`` methods over Redis; key (user_id, agent_id, slug)."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_TOOLKIT_CONFIGS)

    async def save(self, override: UserToolkitOverride) -> None:
        """Upsert (full replace) an override."""
        await self._docs.put(override.model_dump(mode="json"))

    async def load(self, user_id: str, agent_id: str) -> list[UserToolkitOverride]:
        """Load the valid overrides of one user and agent."""
        docs = await self._docs.find({"user_id": user_id, "agent_id": agent_id})
        return [o for o in (_validate(d) for d in docs) if o is not None]

    async def remove(self, user_id: str, agent_id: str, slug: str) -> bool:
        """Delete an override and report whether it existed."""
        return await self._docs.delete({"user_id": user_id, "agent_id": agent_id, "slug": slug})

    async def purge_agent(self, agent_ref: str) -> list[UserToolkitOverride]:
        """Delete every user's override for ``agent_ref`` and return them."""
        deleted = await self._docs.delete_where({"agent_id": agent_ref})
        return [o for o in (_validate(d) for d in deleted) if o is not None]

    async def revision(self, user_id: str, agent_id: str) -> str:
        """Return the latest ``updated_at`` or an empty string."""
        return max((o.updated_at for o in await self.load(user_id, agent_id)), default="")
