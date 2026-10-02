"""Shared helpers of the agent-lifecycle views (``_StudioAgentsMixin``)."""

from __future__ import annotations

from typing import Any

from aiohttp import web
from asyncdb.exceptions import NoDataFound


from ...models import BotModel
from ..access import _legacy_record, _store_record
from ..models import StudioError
from ..storage.models import (
    StudioStorageUnavailable,
)


class _StudioAgentsMixin:
    """Shared helpers for the agent-lifecycle views in this module."""

    def _manager(self):
        """Return the ``BotManager`` instance, or ``None`` if unavailable."""
        return self.request.app.get("bot_manager")

    def _registry(self):
        """Return the ``AgentRegistry`` behind ``BotManager``, or ``None``."""
        manager = self._manager()
        return manager.registry if manager else None

    async def _get_db_agent(self, name: str) -> BotModel | None:
        """Query a single database-origin agent by name.

        Args:
            name: Agent name.

        Returns:
            The ``BotModel`` row, or ``None`` if absent or the database is
            unavailable.
        """
        db = self.request.app.get("database")
        if db is None:
            return None
        try:
            async with await db.acquire() as conn:
                BotModel.Meta.connection = conn
                try:
                    return await BotModel.get(name=name)
                except NoDataFound:
                    return None
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to query DB agent '%s': %s", name, exc)
            return None

    async def _get_all_db_agents(self) -> list[BotModel]:
        """Return every enabled database-origin agent."""
        db = self.request.app.get("database")
        if db is None:
            return []
        try:
            async with await db.acquire() as conn:
                BotModel.Meta.connection = conn
                agents = await BotModel.filter(enabled=True)
                return agents or []
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to list DB agents: %s", exc)
            return []

    async def _check_duplicate(self, name: str) -> str | None:
        """Return the source ('registry'/'database') if ``name`` is taken.

        Args:
            name: Candidate agent slug.

        Returns:
            ``"registry"``, ``"database"``, or ``None`` if the name is free.
        """
        registry = self._registry()
        if registry is not None and registry.has(name):
            return "registry"
        if await self._get_db_agent(name) is not None:
            return "database"
        return None

    @staticmethod
    def _registry_agent_owner(meta: Any) -> str | None:
        """Extract the ``created_by`` owner stamped in ``bot_config.config``.

        There is no ``owner`` column on ``BotMetadata`` — ownership is
        carried inside ``bot_config.config['created_by']`` (mirrors
        ``BotModel.created_by``; see TASK-2511/TASK-2512 Codebase
        Contract "Does NOT Exist").
        """
        bot_config = getattr(meta, "bot_config", None)
        if bot_config is None:
            return None
        config = getattr(bot_config, "config", None) or {}
        owner = config.get("created_by")
        return str(owner) if owner is not None else None

    def _registry_agent_to_dict(self, meta: Any) -> dict:
        """Serialize a registry ``BotMetadata`` for JSON response."""
        bot_config = getattr(meta, "bot_config", None)
        return {
            "name": meta.name,
            "source": "registry",
            "origin": getattr(bot_config, "origin", "repo") if bot_config else "repo",
            "owner": self._registry_agent_owner(meta),
            "enabled": getattr(bot_config, "enabled", True) if bot_config else True,
            "class_name": getattr(bot_config, "class_name", None),
            "module": getattr(bot_config, "module", meta.module_path),
            "file_path": str(meta.file_path) if meta.file_path else None,
            "tags": sorted(meta.tags) if meta.tags else [],
            "priority": meta.priority,
            "at_startup": meta.at_startup,
        }

    @staticmethod
    def _db_agent_to_dict(agent: BotModel) -> dict:
        """Serialize a database-origin ``BotModel`` for JSON response."""
        return {
            "name": agent.name,
            "source": "database",
            "origin": "database",
            "owner": str(agent.created_by) if agent.created_by is not None else None,
            "enabled": agent.enabled,
            "chatbot_id": str(agent.chatbot_id),
        }

    def _error(self, message: str, *, status: int, code: str | None = None):
        """Return a JSON error response shaped like :class:`StudioError`.

        ``BaseHandler.error()`` only maps a fixed status whitelist
        (400/401/403/404/406/412/428) and silently falls back to 400 for
        anything else (e.g. 409/422/503) — this task needs those exact
        codes, so it returns a plain ``json_response`` instead of relying
        on that helper.
        """
        return self.json_response(
            StudioError(message=message, code=code).model_dump(),
            status=status,
        )

    # -- database mode (FEAT-621 spec §2.8) ------------------------------

    async def _dispatch(self, legacy, database, gate=None):
        """Run ``database(storage, part)`` on the database backend, ``legacy()`` on the filesystem one.

        ``gate`` is the verb's PBAC check, run before any database-mode work (the legacy bodies gate themselves).
        A tenant partition on a non-database backend, or an unusable backend, is a 503 before any work; a bare
        app without resolved storage keeps the legacy behaviour.
        """
        storage = self.request.app.get("studio_storage")
        if storage is not None:
            try:
                part = await self._studio_partition()
                storage.require_for(part)
                if storage.backend != "filesystem":
                    if gate is not None and (denied := await gate()) is not None:
                        return denied
                    return await database(storage, part)
            except web.HTTPException:
                raise
            except Exception as exc:  # pylint: disable=broad-except
                return self._studio_error(exc)
        return await legacy()

    async def _patch_unavailable(self):
        """PATCH has no filesystem implementation (503 ``studio_storage_unavailable``)."""
        return self._studio_error(StudioStorageUnavailable("PATCH /agents/{name} needs the database backend"))

    @staticmethod
    def _studio_item(rec: Any) -> dict:
        """JSON item of a Studio agent (§2.9: the legacy keys plus the added ones)."""
        return {
            "name": rec.name,
            "source": "studio",
            "origin": "studio",
            "owner": rec.owner,
            "enabled": rec.status == "active",
            "agent_id": str(rec.agent_id),
            "tenant": rec.tenant,
            "version": rec.version,
            "updated_at": rec.updated_at.isoformat(),
            "visibility": rec.visibility,
            "allowed_groups": list(rec.allowed_groups),
            # the registry-item keys stay (§2.9 is additive-only): a Studio row has no module/file/startup order
            "class_name": rec.definition.bot_class,
            "module": None,
            "file_path": None,
            "tags": [],
            "priority": 0,
            "at_startup": False,
        }

    async def _studio_authorize(self, rec: Any, name: str, *, manage: bool):
        """404 when invisible, 403 when ``manage`` is required and denied; ``None`` when allowed."""
        access = await self._access()
        return await self._check_record_access(
            access, _store_record("agent", rec.agent_id, rec), "agent", name, manage=manage
        )

    @staticmethod
    def _legacy_view(access: Any, item: dict) -> dict:
        """A legacy item plus the additive visibility fields (``access: "global"``, FEAT-605 AC3/AC10)."""
        rec = _legacy_record("agent", item["name"], item["name"], item.get("owner"))
        return {**item, **access.visibility_fields(rec)}

    async def _legacy_items(self) -> list[dict]:
        """Legacy DB-origin plus registry agents (GLOBAL partition only)."""
        access = await self._access()
        items = [self._db_agent_to_dict(a) for a in await self._get_all_db_agents()]
        registry = self._registry()
        taken = {i["name"] for i in items}
        if registry is not None:
            items += [self._registry_agent_to_dict(m) for m in registry.list_agents() if m.name not in taken]
        return [self._legacy_view(access, i) for i in items]

    def _studio_item_for(self, access: Any, rec: Any) -> dict:
        """The Studio item with the visibility fields the caller's access decision yields (C14)."""
        item = self._studio_item(rec)
        item.update(access.visibility_fields(_store_record("agent", rec.agent_id, rec)))
        return item

    async def _studio_name_lookup(self, storage: Any, part: Any):
        """``(name, record)`` of the request's agent; the record is ``None`` when absent or no name was given."""
        name = self.request.match_info.get("name")
        rec = await storage.services.agents.get(part, name) if name else None
        return name, rec
