"""Telegram /add_mcp configs in Redis (FEAT-878): ``TELEGRAM_MCP_STORE=redis`` (the default)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from parrot.userstore import RedisDocumentStore
from parrot.userstore.collections import TELEGRAM_USER_MCP_CONFIGS

from .mcp_persistence import TelegramMCPPublicParams, UserTelegramMCPConfig

logger = logging.getLogger(__name__)


class RedisTelegramMCPStore:
    """Same semantics as TelegramMCPPersistenceService on DocumentDB: soft delete, created_at on insert only."""

    def __init__(self, documents: RedisDocumentStore | None = None) -> None:
        self._docs = documents or RedisDocumentStore(TELEGRAM_USER_MCP_CONFIGS)

    async def save(
        self,
        user_id: str,
        name: str,
        params: TelegramMCPPublicParams,
        vault_credential_name: Optional[str],
    ) -> None:
        """Upsert one active Telegram MCP configuration."""
        now = datetime.now(timezone.utc).isoformat()
        await self._docs.upsert(
            {"user_id": user_id, "name": name},
            {
                "params": params.model_dump(),
                "vault_credential_name": vault_credential_name,
                "active": True,
                "updated_at": now,
            },
            on_insert={"created_at": now},
        )

    async def list(self, user_id: str) -> List[UserTelegramMCPConfig]:
        """Return all valid active configurations for a Telegram user."""
        docs = await self._docs.find({"user_id": user_id, "active": True})
        configs: List[UserTelegramMCPConfig] = []
        for doc in docs:
            try:
                raw_params = doc.get("params", {})
                if isinstance(raw_params, dict):
                    doc["params"] = TelegramMCPPublicParams(**raw_params)
                configs.append(UserTelegramMCPConfig(**doc))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Skipping malformed Telegram MCP config doc for user=%r: %s", user_id, type(exc).__name__
                )
        return configs

    async def read_one(self, user_id: str, name: str) -> Optional[UserTelegramMCPConfig]:
        """Return one active configuration, or ``None`` when absent or malformed."""
        doc = await self._docs.get({"user_id": user_id, "name": name})
        if doc is None or not doc.get("active"):
            return None
        try:
            raw_params = doc.get("params", {})
            if isinstance(raw_params, dict):
                doc["params"] = TelegramMCPPublicParams(**raw_params)
            return UserTelegramMCPConfig(**doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Malformed Telegram MCP config doc for user=%r name=%r: %s", user_id, name, type(exc).__name__
            )
            return None

    async def remove(self, user_id: str, name: str) -> tuple[bool, Optional[str]]:
        """Soft delete; returns ``(found, vault_credential_name)``."""
        existing = await self._docs.get({"user_id": user_id, "name": name})
        if existing is None:
            return False, None
        await self._docs.update(
            {"user_id": user_id, "name": name},
            {"active": False, "updated_at": datetime.now(timezone.utc).isoformat()},
        )
        return True, existing.get("vault_credential_name")
