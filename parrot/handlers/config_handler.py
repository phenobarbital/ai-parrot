"""REST API Handler for BotConfig Management.

Provides CRUD endpoints for managing agent configurations
via the AgentRegistry and BotConfigStorage (Redis).

Endpoints:
    GET    /api/v1/agents/config              — list all configs (optionally ?category=X)
    GET    /api/v1/agents/config/{agent_name} — get single config
    POST   /api/v1/agents/config/{agent_name} — update existing config
    PUT    /api/v1/agents/config              — insert new config (Redis)
    DELETE /api/v1/agents/config/{agent_name} — delete Redis-backed config
    PATCH  /api/v1/agents/config/{agent_name} — partial update of config fields
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import web
from navconfig.logging import logging
from navigator.views import BaseView

from ..registry import AgentRegistry, BotConfig, BotConfigStorage, BotMetadata
from ..models.basic import ModelConfig, ToolConfig


class BotConfigHandler(BaseView):
    """REST API Handler for BotConfig CRUD operations."""

    _logger_name: str = "Parrot.BotConfigHandler"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(self._logger_name)

    # -- helpers ---------------------------------------------------------------

    @property
    def registry(self) -> AgentRegistry:
        """Get AgentRegistry from the app."""
        return self.request.app["bot_manager"].registry

    @property
    def storage(self) -> BotConfigStorage:
        """Get BotConfigStorage from the app."""
        return self.request.app["bot_config_storage"]

    def _agent_name_from_request(self) -> Optional[str]:
        """Extract agent_name from URL path or query string."""
        name = self.request.match_info.get("agent_name")
        if not name:
            qs = self.query_parameters(self.request)
            name = qs.get("agent_name")
        return name or None

    @staticmethod
    def _metadata_to_summary(meta: BotMetadata) -> Dict[str, Any]:
        """Serialize BotMetadata to a lightweight summary dict."""
        return {
            "name": meta.name,
            "module_path": meta.module_path,
            "file_path": str(meta.file_path),
            "singleton": meta.singleton,
            "at_startup": meta.at_startup,
            "priority": meta.priority,
            "tags": sorted(meta.tags) if meta.tags else [],
        }

    @staticmethod
    def _config_to_dict(config: BotConfig) -> Dict[str, Any]:
        """Serialize a BotConfig to a JSON-safe dict."""
        return config.model_dump(mode="json")

    def _derive_category(self, meta: BotMetadata) -> Optional[str]:
        """Derive category from the YAML file path subdirectory."""
        try:
            parts = Path(meta.file_path).parts
            # Pattern: .../agents/agents/<category>/<name>.yaml
            if "agents" in parts:
                idx = len(parts) - 1
                # The category is the parent directory of the yaml file
                # within the agents tree.
                parent = parts[idx - 1] if idx > 0 else None
                if parent and parent != "agents":
                    return parent
        except Exception:
            pass
        return None

    # -- GET -------------------------------------------------------------------

    async def get(self) -> web.Response:
        """GET handler.

        - ``/config/{agent_name}`` → single agent config
        - ``/config`` → list all (optionally ``?category=X``)
        """
        agent_name = self._agent_name_from_request()
        qs = self.query_parameters(self.request)
        category = qs.get("category")

        if agent_name:
            return await self._get_one(agent_name)

        return await self._get_list(category=category)

    async def _get_one(self, name: str) -> web.Response:
        """Return a single agent's config by name."""
        # 1. Check runtime registry
        meta: Optional[BotMetadata] = self.registry._registered_agents.get(name)
        if meta:
            summary = self._metadata_to_summary(meta)
            summary["source"] = "registry"
            return self.json_response(summary)

        # 2. Check Redis storage
        config = await self.storage.get(name)
        if config:
            data = self._config_to_dict(config)
            data["source"] = "redis"
            return self.json_response(data)

        return self.error(
            response={"message": f"Agent '{name}' not found"},
            status=404,
        )

    async def _get_list(
        self, category: Optional[str] = None
    ) -> web.Response:
        """Return list of all agents, optionally filtered by category/tag."""
        agents = []

        # From registry (YAML + code-registered)
        for name, meta in self.registry._registered_agents.items():
            entry = self._metadata_to_summary(meta)
            entry["source"] = "registry"
            derived = self._derive_category(meta)
            if derived:
                entry["category"] = derived
            agents.append(entry)

        # From Redis storage
        try:
            redis_configs = await self.storage.list()
            for config in redis_configs:
                # Skip if already present from registry
                if any(a["name"] == config.name for a in agents):
                    continue
                entry = self._config_to_dict(config)
                entry["source"] = "redis"
                agents.append(entry)
        except Exception as exc:
            self.logger.warning(f"Failed to list Redis configs: {exc}")

        # Filter by category if requested
        if category:
            agents = [
                a for a in agents
                if category in a.get("tags", [])
                or a.get("category") == category
            ]

        return self.json_response({
            "agents": agents,
            "total": len(agents),
        })

    # -- POST (update) ---------------------------------------------------------

    async def post(self) -> web.Response:
        """Update an existing agent config.

        Body: full BotConfig JSON.  
        Query: ``?persist=file`` to write YAML instead of Redis.
        """
        agent_name = self._agent_name_from_request()
        if not agent_name:
            return self.error(
                response={"message": "agent_name is required in URL"},
                status=400,
            )

        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        # Ensure name consistency
        data["name"] = agent_name

        try:
            config = BotConfig(**data)
        except Exception as exc:
            return self.error(
                response={"message": f"Invalid BotConfig: {exc}"},
                status=400,
            )

        qs = self.query_parameters(self.request)
        persist = qs.get("persist", "redis")

        if persist == "file":
            category = qs.get("category", "general")
            try:
                file_path = self.registry.create_agent_definition(
                    config, category=category
                )
                return self.json_response({
                    "message": f"Agent '{agent_name}' saved to file",
                    "file_path": str(file_path),
                })
            except Exception as exc:
                return self.error(
                    response={"message": f"Failed to save to file: {exc}"},
                    status=500,
                )
        else:
            try:
                await self.storage.save(config)
                return self.json_response({
                    "message": f"Agent '{agent_name}' updated in Redis",
                })
            except KeyError:
                return self.error(
                    response={
                        "message": (
                            f"Agent '{agent_name}' does not exist in Redis. "
                            "Use PUT to insert a new agent."
                        )
                    },
                    status=404,
                )
            except Exception as exc:
                return self.error(
                    response={"message": f"Failed to update: {exc}"},
                    status=500,
                )

    # -- PUT (insert) ----------------------------------------------------------

    async def put(self) -> web.Response:
        """Insert a new agent config into Redis and register in runtime.

        Body: full BotConfig JSON.
        """
        try:
            data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        try:
            config = BotConfig(**data)
        except Exception as exc:
            return self.error(
                response={"message": f"Invalid BotConfig: {exc}"},
                status=400,
            )

        # Insert into Redis (checks duplicates against registry)
        try:
            await self.storage.insert(
                config,
                registered_agents=self.registry._registered_agents,
            )
        except ValueError as exc:
            return self.error(
                response={"message": str(exc)},
                status=409,
            )
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to insert: {exc}"},
                status=500,
            )

        # Register in runtime registry so it's immediately usable
        try:
            factory = self.registry.create_agent_factory(config)
            self.registry._registered_agents[config.name] = BotMetadata(
                name=config.name,
                factory=factory,
                module_path=config.module,
                file_path=Path("redis"),
                singleton=config.singleton,
                at_startup=config.at_startup,
                startup_config=config.config,
                tags=config.tags,
                priority=config.priority,
            )
        except Exception as exc:
            self.logger.warning(
                f"Agent '{config.name}' saved to Redis but runtime "
                f"registration failed: {exc}"
            )

        return self.json_response(
            {
                "message": f"Agent '{config.name}' created",
                "name": config.name,
            },
            status=201,
        )

    # -- DELETE ----------------------------------------------------------------

    async def delete(self) -> web.Response:
        """Delete a Redis-backed agent config.

        File-based configs cannot be deleted via this endpoint.
        """
        agent_name = self._agent_name_from_request()
        if not agent_name:
            return self.error(
                response={"message": "agent_name is required"},
                status=400,
            )

        # Safety: refuse to delete file-based agents
        meta = self.registry._registered_agents.get(agent_name)
        if meta and str(meta.file_path) != "redis":
            return self.error(
                response={
                    "message": (
                        f"Agent '{agent_name}' is file-based and cannot be "
                        "deleted via this endpoint."
                    )
                },
                status=403,
            )

        deleted = await self.storage.delete(agent_name)
        if not deleted:
            return self.error(
                response={"message": f"Agent '{agent_name}' not found in Redis"},
                status=404,
            )

        # Remove from runtime registry
        self.registry._registered_agents.pop(agent_name, None)

        return self.json_response({
            "message": f"Agent '{agent_name}' deleted",
        })

    # -- PATCH (partial update) ------------------------------------------------

    async def patch(self) -> web.Response:
        """Partially update fields on an existing agent config.

        Body: JSON with fields to merge (e.g. ``{"priority": 5}``).
        """
        agent_name = self._agent_name_from_request()
        if not agent_name:
            return self.error(
                response={"message": "agent_name is required in URL"},
                status=400,
            )

        try:
            patch_data = await self.request.json()
        except Exception:
            return self.error(
                response={"message": "Invalid JSON body"},
                status=400,
            )

        if not isinstance(patch_data, dict) or not patch_data:
            return self.error(
                response={"message": "Body must be a non-empty JSON object"},
                status=400,
            )

        # Fetch existing config from Redis first
        existing = await self.storage.get(agent_name)
        if not existing:
            return self.error(
                response={
                    "message": (
                        f"Agent '{agent_name}' not found in Redis. "
                        "PATCH only works on Redis-backed configs."
                    )
                },
                status=404,
            )

        # Merge patch data into existing config
        merged = existing.model_dump(mode="json")
        for key, value in patch_data.items():
            if key == "name":
                continue  # name is immutable
            if key in merged:
                # For nested models, merge dicts
                if isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                else:
                    merged[key] = value

        try:
            updated_config = BotConfig(**merged)
        except Exception as exc:
            return self.error(
                response={"message": f"Merged config is invalid: {exc}"},
                status=400,
            )

        # Persist
        try:
            # Use SET directly since we know it exists
            await self.storage.save(updated_config)
        except Exception as exc:
            return self.error(
                response={"message": f"Failed to save: {exc}"},
                status=500,
            )

        # Update runtime registry if registered
        meta = self.registry._registered_agents.get(agent_name)
        if meta:
            # Refresh the factory with updated config
            try:
                factory = self.registry.create_agent_factory(updated_config)
                self.registry._registered_agents[agent_name] = BotMetadata(
                    name=updated_config.name,
                    factory=factory,
                    module_path=updated_config.module,
                    file_path=meta.file_path,
                    singleton=updated_config.singleton,
                    at_startup=updated_config.at_startup,
                    startup_config=updated_config.config,
                    tags=updated_config.tags,
                    priority=updated_config.priority,
                )
            except Exception as exc:
                self.logger.warning(
                    f"Redis updated but runtime re-registration failed: {exc}"
                )

        return self.json_response({
            "message": f"Agent '{agent_name}' patched",
            "updated_fields": list(patch_data.keys()),
        })
