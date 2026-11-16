"""Per-user MCP server configs in Redis (FEAT-878): ``MCP_CONFIGS_STORE=redis`` (the default)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from parrot.mcp.registry import UserMCPServerConfig
from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import USER_MCP_CONFIGS

logger = logging.getLogger(__name__)


class RedisMCPConfigStore:
    """Same semantics as MCPPersistenceService on DocumentDB: soft delete, created_at on insert only."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(USER_MCP_CONFIGS)

    async def save(self, config: UserMCPServerConfig) -> None:
        """Upsert a configuration while preserving its original creation time."""
        now = datetime.now(timezone.utc).isoformat()
        key = {"user_id": config.user_id, "agent_id": config.agent_id, "server_name": config.server_name}
        await self._docs.upsert(
            key,
            {
                "params": config.params,
                "vault_credential_name": config.vault_credential_name,
                "active": config.active,
                "updated_at": now,
            },
            on_insert={"created_at": now},
        )

    async def load(self, user_id: str, agent_id: str) -> list[UserMCPServerConfig]:
        """Load active configs only, skipping malformed documents with a warning."""
        docs = await self._docs.find({"user_id": user_id, "agent_id": agent_id, "active": True})
        configs: list[UserMCPServerConfig] = []
        for doc in docs:
            try:
                configs.append(UserMCPServerConfig(**doc))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed MCP config doc for user='%s' agent='%s': %s",
                    user_id,
                    agent_id,
                    exc,
                )
        return configs

    async def remove(self, user_id: str, agent_id: str, server_name: str) -> bool:
        """Soft delete a configuration, returning ``False`` when it is absent."""
        now = datetime.now(timezone.utc).isoformat()
        return await self._docs.update(
            {"user_id": user_id, "agent_id": agent_id, "server_name": server_name},
            {"active": False, "updated_at": now},
        )
