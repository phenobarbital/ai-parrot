"""MCP Persistence Service — DocumentDB CRUD for user MCP server configs.

Provides save, load, and soft-delete operations for
:class:`~parrot.mcp.registry.UserMCPServerConfig` documents, scoped by
``(user_id, agent_id)``.

The ``user_mcp_configs`` collection is created implicitly on the first write.
Secret values are **never** stored here — they live in the Vault.  The
``vault_credential_name`` field in each document points to the relevant Vault
entry.

Usage::

    service = MCPPersistenceService()
    await service.save_user_mcp_config(config)
    configs = await service.load_user_mcp_configs(user_id, agent_id)
    removed = await service.remove_user_mcp_config(user_id, agent_id, "perplexity")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from navconfig.logging import logging

from parrot.interfaces.documentdb import DocumentDb
from parrot.mcp.registry import UserMCPServerConfig


# Collection name used for all MCP config documents.
COLLECTION: str = "user_mcp_configs"

logger = logging.getLogger(__name__)


class MCPPersistenceService:
    """Handles saving and loading user MCP server configurations in DocumentDB.

    All documents are scoped by the compound key ``(user_id, agent_id,
    server_name)``.  Deactivation is a soft-delete that sets ``active=False``
    so the configuration can be re-activated in the future without data loss.

    Methods:
        save_user_mcp_config: Upsert a config document.
        load_user_mcp_configs: Retrieve all active configs for a user/agent.
        remove_user_mcp_config: Soft-delete a config (sets active=False).
    """

    async def save_user_mcp_config(self, config: UserMCPServerConfig) -> None:
        """Upsert a user MCP server configuration in DocumentDB.

        If a document with the same ``(user_id, agent_id, server_name)`` already
        exists it is updated; otherwise a new document is inserted.  The
        ``created_at`` timestamp is set only on first insert; ``updated_at`` is
        refreshed on every save.

        Args:
            config: The :class:`~parrot.mcp.registry.UserMCPServerConfig` to
                persist.  The ``params`` dict must **not** contain any secret
                values — those belong in the Vault.
        """
        now = datetime.now(timezone.utc).isoformat()
        query = {
            "user_id": config.user_id,
            "agent_id": config.agent_id,
            "server_name": config.server_name,
        }

        update_data = {
            "$set": {
                "params": config.params,
                "vault_credential_name": config.vault_credential_name,
                "active": config.active,
                "updated_at": now,
            },
            "$setOnInsert": {
                "user_id": config.user_id,
                "agent_id": config.agent_id,
                "server_name": config.server_name,
                "created_at": now,
            },
        }

        async with DocumentDb() as db:
            await db.update_one(COLLECTION, query, update_data, upsert=True)

        logger.info(
            "Upserted MCP config for server='%s' user='%s' agent='%s'",
            config.server_name,
            config.user_id,
            config.agent_id,
        )

    async def load_user_mcp_configs(
        self,
        user_id: str,
        agent_id: str,
    ) -> List[UserMCPServerConfig]:
        """Load all active MCP server configs for a given user and agent.

        Inactive configs (``active=False``) are excluded from the results.

        Args:
            user_id: Owner user identifier.
            agent_id: Agent identifier to scope the query.

        Returns:
            List of :class:`~parrot.mcp.registry.UserMCPServerConfig` instances.
            Returns an empty list if none are found.
        """
        query = {
            "user_id": user_id,
            "agent_id": agent_id,
            "active": True,
        }

        async with DocumentDb() as db:
            docs = await db.read(COLLECTION, query)

        configs: List[UserMCPServerConfig] = []
        for doc in docs:
            # Strip internal DocumentDB fields that aren't in the model
            doc.pop("_id", None)
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

    async def remove_user_mcp_config(
        self,
        user_id: str,
        agent_id: str,
        server_name: str,
    ) -> bool:
        """Soft-delete a user MCP server configuration.

        Sets ``active=False`` on the document rather than hard-deleting it,
        so the configuration can be re-activated later.

        Args:
            user_id: Owner user identifier.
            agent_id: Agent identifier.
            server_name: Registry slug of the server to deactivate.

        Returns:
            ``True`` if a matching document was found and deactivated.
            ``False`` if no document with the given compound key exists.
        """
        query = {
            "user_id": user_id,
            "agent_id": agent_id,
            "server_name": server_name,
        }

        async with DocumentDb() as db:
            existing = await db.read_one(COLLECTION, query)

            if existing is None:
                logger.debug(
                    "remove_user_mcp_config: no config found for "
                    "server='%s' user='%s' agent='%s'",
                    server_name,
                    user_id,
                    agent_id,
                )
                return False

            now = datetime.now(timezone.utc).isoformat()
            update_data = {
                "$set": {
                    "active": False,
                    "updated_at": now,
                }
            }
            # Reuse the same connection — no second round-trip needed
            await db.update_one(COLLECTION, query, update_data)

        logger.info(
            "Soft-deleted MCP config for server='%s' user='%s' agent='%s'",
            server_name,
            user_id,
            agent_id,
        )
        return True
