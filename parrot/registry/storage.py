"""Redis-backed storage for BotConfig objects."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from redis.asyncio import Redis
from navconfig.logging import logging

from .registry import BotConfig
from ..conf import REDIS_SERVICES_URL
from ..models.basic import ModelConfig, ToolConfig

if TYPE_CHECKING:
    from .registry import AgentRegistry


class BotConfigStorage:
    """Redis-backed CRUD storage for BotConfig agent definitions."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        key_prefix: str = "parrot:agents",
    ) -> None:
        self.logger = logging.getLogger("Parrot.BotConfigStorage")
        self.redis_url = redis_url or REDIS_SERVICES_URL
        self.key_prefix = key_prefix
        self.redis: Redis = Redis.from_url(
            self.redis_url,
            decode_responses=True,
            encoding="utf-8",
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )

    # -- helpers -------------------------------------------------------------

    def _key(self, name: str) -> str:
        """Build the Redis key for a given agent name."""
        return f"{self.key_prefix}:{name}"

    def _serialize(self, config: BotConfig) -> str:
        """Serialize a BotConfig to a JSON string."""
        data = config.model_dump(mode="json")
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    def _deserialize(self, raw: str) -> BotConfig:
        """Deserialize a JSON string into a BotConfig."""
        data = json.loads(raw)
        # Rebuild nested Pydantic models when present
        if data.get("model") and isinstance(data["model"], dict):
            data["model"] = ModelConfig(**data["model"])
        if data.get("tools") and isinstance(data["tools"], dict):
            data["tools"] = ToolConfig(**data["tools"])
        return BotConfig(**data)

    # -- public API ----------------------------------------------------------

    async def list(self) -> List[BotConfig]:
        """Return all BotConfig objects stored in Redis."""
        configs: List[BotConfig] = []
        cursor: int = 0
        pattern = f"{self.key_prefix}:*"
        while True:
            cursor, keys = await self.redis.scan(
                cursor, match=pattern, count=100
            )
            for key in keys:
                raw = await self.redis.get(key)
                if raw is None:
                    continue
                try:
                    configs.append(self._deserialize(raw))
                except Exception as exc:
                    self.logger.error(
                        f"Failed to deserialize agent config from {key}: {exc}"
                    )
            if cursor == 0:
                break
        return configs

    async def get(self, name: str) -> Optional[BotConfig]:
        """Fetch a single BotConfig by agent name."""
        raw = await self.redis.get(self._key(name))
        if raw is None:
            return None
        return self._deserialize(raw)

    async def save(self, config: BotConfig) -> None:
        """Update an existing agent config in Redis.

        Raises KeyError if the agent does not already exist.
        """
        key = self._key(config.name)
        exists = await self.redis.exists(key)
        if not exists:
            raise KeyError(
                f"Agent '{config.name}' does not exist in Redis. "
                "Use insert() for new entries."
            )
        await self.redis.set(key, self._serialize(config))
        self.logger.info(f"Updated agent config in Redis: {config.name}")

    async def insert(
        self,
        config: BotConfig,
        registered_agents: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a new agent config into Redis.

        Args:
            config: The BotConfig to store.
            registered_agents: Optional mapping of already-registered agent
                names (e.g. ``AgentRegistry._registered_agents``) used to
                prevent duplicates.

        Raises:
            ValueError: If the agent is already registered or already in Redis.
        """
        if registered_agents and config.name in registered_agents:
            raise ValueError(
                f"Agent '{config.name}' is already registered in the "
                "AgentRegistry. Cannot insert duplicate."
            )
        key = self._key(config.name)
        # SET with NX — only set if key does not exist
        was_set = await self.redis.set(key, self._serialize(config), nx=True)
        if not was_set:
            raise ValueError(
                f"Agent '{config.name}' already exists in Redis."
            )
        self.logger.info(f"Inserted agent config into Redis: {config.name}")

    async def transfer(
        self,
        name: str,
        registry: "AgentRegistry",
        category: str = "general",
    ) -> Path:
        """Move a BotConfig from Redis to the filesystem as a YAML file.

        The entry is removed from Redis after a successful write.

        Args:
            name: Agent name to transfer.
            registry: AgentRegistry instance (used for ``create_agent_definition``).
            category: Subdirectory category for the YAML file.

        Returns:
            Path to the newly created YAML definition file.

        Raises:
            KeyError: If the agent does not exist in Redis.
        """
        config = await self.get(name)
        if config is None:
            raise KeyError(
                f"Agent '{name}' not found in Redis."
            )
        # Write YAML via the existing registry helper
        file_path = registry.create_agent_definition(config, category=category)
        # Remove from Redis only after successful file write
        await self.redis.delete(self._key(name))
        self.logger.info(
            f"Transferred agent '{name}' from Redis to {file_path}"
        )
        return file_path

    async def delete(self, name: str) -> bool:
        """Remove a BotConfig from Redis by name.

        Returns:
            True if the key was deleted, False if it did not exist.
        """
        result = await self.redis.delete(self._key(name))
        if result:
            self.logger.info(f"Deleted agent config from Redis: {name}")
        return result > 0

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        try:
            await self.redis.aclose()
        except Exception as exc:
            self.logger.error(f"Error closing Redis connection: {exc}")
