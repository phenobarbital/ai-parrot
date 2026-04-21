"""Telegram MCP Persistence Service — DocumentDB CRUD for /add_mcp configs.

Stores the *non-secret* subset of each ``/add_mcp`` JSON payload in the
``telegram_user_mcp_configs`` DocumentDB collection, scoped by
``(user_id, name)``.  Secret fields (``token``, ``api_key``, ``username``,
``password``) are **never** stored here — they live in the Vault.  The
``vault_credential_name`` field in each document points to the relevant Vault
entry.

This module is Telegram-scoped and intentionally separate from
:mod:`parrot.handlers.mcp_persistence` which handles catalog-activated MCP
servers (``UserMCPServerConfig`` / ``user_mcp_configs`` collection).

Usage::

    svc = TelegramMCPPersistenceService()
    await svc.save(user_id, name, public_params, vault_name)
    configs = await svc.list(user_id)
    removed = await svc.remove(user_id, name)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import logging

from pydantic import BaseModel, Field

from parrot.interfaces.documentdb import DocumentDb


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TelegramMCPPublicParams(BaseModel):
    """Non-secret subset of an /add_mcp payload safe to persist in DocumentDB.

    Attributes:
        name: Server name (the command's JSON ``name``).
        url: HTTP(S) endpoint of the MCP server.
        transport: MCP transport protocol (default ``"http"``).
        description: Optional human-readable description.
        auth_scheme: Authentication scheme used (``"none"`` | ``"bearer"`` |
            ``"api_key"`` | ``"basic"``).
        api_key_header: Custom header name for ``api_key`` scheme only.
        use_bearer_prefix: Whether to add the ``Bearer `` prefix for
            ``api_key`` scheme.
        headers: Extra HTTP headers sent with every MCP request.
        allowed_tools: Whitelist of tool names; ``None`` means all tools.
        blocked_tools: Blacklist of tool names; ``None`` means none blocked.
    """

    name: str = Field(..., min_length=1, max_length=64, pattern=r'^[a-zA-Z0-9_-]+$')
    url: str
    transport: str = "http"
    description: Optional[str] = None
    auth_scheme: str = "none"  # "none" | "bearer" | "api_key" | "basic"
    api_key_header: Optional[str] = None  # api_key scheme only
    use_bearer_prefix: Optional[bool] = None  # api_key scheme only
    headers: Dict[str, str] = Field(default_factory=dict)
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None


class UserTelegramMCPConfig(BaseModel):
    """Persisted non-secret config for a /add_mcp HTTP server.

    Attributes:
        user_id: Telegram user identifier in ``tg:<telegram_id>`` format.
        name: Server name (the command's JSON ``name``).
        params: Non-secret connection parameters.
        vault_credential_name: Vault key name (``"tg_mcp_{name}"``) when
            secrets are present; ``None`` for ``auth_scheme=none``.
        active: ``False`` after a soft-delete via :meth:`TelegramMCPPersistenceService.remove`.
        created_at: ISO-8601 UTC timestamp of first insert.
        updated_at: ISO-8601 UTC timestamp of last upsert.
    """

    user_id: str
    name: str
    params: TelegramMCPPublicParams
    vault_credential_name: Optional[str] = None
    active: bool = True
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class TelegramMCPPersistenceService:
    """CRUD for the ``telegram_user_mcp_configs`` DocumentDB collection.

    All documents are scoped by the compound key ``(user_id, name)``.
    Deactivation is a soft-delete (``active=False``) so configurations can
    be re-activated in the future without data loss.

    Mirrors the pattern of :class:`~parrot.handlers.mcp_persistence.MCPPersistenceService`
    but is dedicated to the Telegram ``/add_mcp`` free-form flow.

    Methods:
        save: Upsert a config document.
        list: Retrieve all active configs for a user.
        read_one: Retrieve a single active config by name.
        remove: Soft-delete a config (sets ``active=False``).
    """

    COLLECTION: str = "telegram_user_mcp_configs"

    async def save(
        self,
        user_id: str,
        name: str,
        params: TelegramMCPPublicParams,
        vault_credential_name: Optional[str],
    ) -> None:
        """Upsert a Telegram MCP server configuration in DocumentDB.

        If a document with the same ``(user_id, name)`` already exists it is
        updated; otherwise a new document is inserted.  The ``created_at``
        timestamp is set only on first insert; ``updated_at`` is refreshed on
        every save.

        Args:
            user_id: Telegram user identifier (``tg:<telegram_id>``).
            name: Server name (must match ``params.name``).
            params: Non-secret :class:`TelegramMCPPublicParams` to persist.
            vault_credential_name: Vault credential key for this server, or
                ``None`` when no secrets are stored (``auth_scheme=none``).
        """
        now = datetime.now(timezone.utc).isoformat()
        query = {"user_id": user_id, "name": name}
        update_data = {
            "$set": {
                "params": params.model_dump(),
                "vault_credential_name": vault_credential_name,
                "active": True,
                "updated_at": now,
            },
            "$setOnInsert": {
                "user_id": user_id,
                "name": name,
                "created_at": now,
            },
        }

        async with DocumentDb() as db:
            await db.update_one(self.COLLECTION, query, update_data, upsert=True)

        logger.info(
            "Upserted Telegram MCP config name=%r user=%r",
            name,
            user_id,
        )

    async def list(self, user_id: str) -> List[UserTelegramMCPConfig]:
        """Load all active MCP server configs for a given Telegram user.

        Inactive configs (``active=False``) are excluded from the results.

        Args:
            user_id: Telegram user identifier.

        Returns:
            List of :class:`UserTelegramMCPConfig` instances.  Returns an
            empty list if none are found.
        """
        query = {"user_id": user_id, "active": True}

        async with DocumentDb() as db:
            docs = await db.read(self.COLLECTION, query)

        configs: List[UserTelegramMCPConfig] = []
        for doc in docs:
            doc.pop("_id", None)
            try:
                # params may be stored as a nested dict — parse it properly
                raw_params = doc.get("params", {})
                if isinstance(raw_params, dict):
                    doc["params"] = TelegramMCPPublicParams(**raw_params)
                configs.append(UserTelegramMCPConfig(**doc))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed Telegram MCP config doc for user=%r: %s",
                    user_id,
                    exc,
                )

        return configs

    async def read_one(
        self, user_id: str, name: str
    ) -> Optional[UserTelegramMCPConfig]:
        """Retrieve a single active Telegram MCP config by name.

        Args:
            user_id: Telegram user identifier.
            name: Server name to look up.

        Returns:
            :class:`UserTelegramMCPConfig` instance, or ``None`` if not found
            or if the matching doc is inactive.
        """
        query = {"user_id": user_id, "name": name, "active": True}

        async with DocumentDb() as db:
            doc = await db.read_one(self.COLLECTION, query)

        if doc is None:
            return None

        doc.pop("_id", None)
        try:
            raw_params = doc.get("params", {})
            if isinstance(raw_params, dict):
                doc["params"] = TelegramMCPPublicParams(**raw_params)
            return UserTelegramMCPConfig(**doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Malformed Telegram MCP config doc for user=%r name=%r: %s",
                user_id,
                name,
                exc,
            )
            return None

    async def remove(self, user_id: str, name: str) -> tuple[bool, Optional[str]]:
        """Soft-delete a Telegram MCP server configuration.

        Sets ``active=False`` on the document rather than hard-deleting it.

        Args:
            user_id: Telegram user identifier.
            name: Server name to deactivate.

        Returns:
            Tuple of ``(found, vault_credential_name)``.
            ``found`` is ``True`` if a matching document was found and deactivated,
            ``False`` if no document with the given compound key exists.
            ``vault_credential_name`` is the Vault key of the deleted document, or
            ``None`` if the document was not found or had no Vault entry.
        """
        query = {"user_id": user_id, "name": name}

        async with DocumentDb() as db:
            existing = await db.read_one(self.COLLECTION, query)

            if existing is None:
                logger.debug(
                    "remove: no Telegram MCP config found for name=%r user=%r",
                    name,
                    user_id,
                )
                return False, None

            vault_cred_name: Optional[str] = existing.get("vault_credential_name")
            now = datetime.now(timezone.utc).isoformat()
            update_data = {
                "$set": {
                    "active": False,
                    "updated_at": now,
                }
            }
            await db.update_one(self.COLLECTION, query, update_data)

        logger.info(
            "Soft-deleted Telegram MCP config name=%r user=%r",
            name,
            user_id,
        )
        return True, vault_cred_name
