"""Studio agent lifecycle endpoints (FEAT-467 TASK-2512).

Implements the core agent CRUD of the Studio API (spec §3 Module 4):

    POST   /api/v1/astudio/agents               — create a simple agent
    GET    /api/v1/astudio/agents                — list (registry + DB, merged)
    GET    /api/v1/astudio/agents/{name}          — single agent
    POST   /api/v1/astudio/agents/{name}/reload   — hot reload (TASK-2510)
    DELETE /api/v1/astudio/agents/{name}          — delete (factory-origin only)

Reuses the proven patterns of ``ChatbotHandler`` (``handlers/bots.py``) —
slugify/duplicate-check discipline, server-set ``created_by``, merged
registry+DB listing — WITHOUT touching ``bots.py`` itself (spec §7 "bots.py
untouched" regression-isolation constraint).
"""
from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from asyncdb.exceptions import NoDataFound
from navigator_auth.decorators import is_authenticated, user_session
from parrot.clients.factory import LLMFactory
from parrot.conf import AGENTS_DIR
from parrot.models.basic import ModelConfig
from parrot.registry.registry import BotConfig
from parrot.utils.naming import slugify_name
from pydantic import ValidationError

from parrot.manager.manager import AgentNotFoundError, AgentReloadError

from ..models import BotModel
from ._base import StudioBaseView
from .models import CreateAgentRequest, StudioError


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


@is_authenticated()
@user_session()
class StudioAgentsHandler(_StudioAgentsMixin, StudioBaseView):
    """``/api/v1/astudio/agents`` and ``/api/v1/astudio/agents/{name}``.

    GET (list/single), POST (create), DELETE (factory-origin only).
    """

    # -- GET ---------------------------------------------------------

    async def get(self):
        """List all agents, or return a single agent by name."""
        name = self.request.match_info.get("name")
        if name:
            return await self._get_one(name)
        return await self._get_all()

    async def _get_one(self, name: str):
        db_agent = await self._get_db_agent(name)
        if db_agent is not None:
            return self.json_response(self._db_agent_to_dict(db_agent))
        registry = self._registry()
        if registry is not None:
            meta = registry.get_metadata(name)
            if meta is not None:
                return self.json_response(self._registry_agent_to_dict(meta))
        return self._error(f"Agent '{name}' not found.", status=404, code="not_found")

    async def _get_all(self):
        agents: list[dict] = []
        seen: set = set()
        for db_agent in await self._get_all_db_agents():
            agents.append(self._db_agent_to_dict(db_agent))
            seen.add(db_agent.name)
        registry = self._registry()
        if registry is not None:
            for meta in registry.list_agents():
                if meta.name in seen:
                    continue
                agents.append(self._registry_agent_to_dict(meta))
        return self.json_response({"agents": agents, "count": len(agents)})

    # -- POST (create) -------------------------------------------------

    async def post(self):
        """Create a simple agent — registers into ``AgentRegistry``.

        With ``persist: true`` also writes a lossless ``agent:``-keyed
        YAML definition (``AgentRegistry.create_agent_definition``,
        FEAT-467 TASK-2509) under ``AGENTS_DIR/agents/<category>/``.
        """
        if self.request.match_info.get("name"):
            return self._error(
                "Use POST /astudio/agents (no name in the URL) to create, "
                "or POST /astudio/agents/{name}/reload to reload.",
                status=400,
                code="invalid_route",
            )

        try:
            payload = await self.request.json()
        except Exception:  # pylint: disable=broad-except
            return self._error("Invalid JSON body.", status=400, code="invalid_json")

        try:
            create_request = CreateAgentRequest(**(payload or {}))
        except ValidationError as exc:
            return self._error(
                f"Invalid request: {exc}", status=400, code="invalid_request"
            )

        try:
            slug = slugify_name(create_request.name)
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_name")

        existing = await self._check_duplicate(slug)
        if existing:
            return self._error(
                f"Agent '{slug}' already exists in {existing}.",
                status=409,
                code="duplicate",
            )

        manager = self._manager()
        if manager is None:
            return self._error(
                "BotManager unavailable.", status=503, code="unavailable"
            )

        bot_class = manager.get_bot_class(create_request.bot_class)
        if bot_class is None:
            return self._error(
                f"Unknown bot_class '{create_request.bot_class}'.",
                status=400,
                code="invalid_bot_class",
            )

        user = await self._get_user()

        config_dict = dict(create_request.config)
        if create_request.description:
            config_dict["description"] = create_request.description
        # Ownership is server-set from the session — NEVER client-supplied.
        config_dict["created_by"] = user.user_id

        model_config = None
        if create_request.llm:
            provider, model = LLMFactory.parse_llm_string(create_request.llm)
            model_config = ModelConfig(provider=provider, model=model or "")

        bot_config = BotConfig(
            name=slug,
            class_name=bot_class.__name__,
            module=bot_class.__module__,
            origin="factory",
            config=config_dict,
            model=model_config,
        )

        registry = self._registry()
        try:
            registry.register(
                slug,
                bot_class,
                bot_config=bot_config,
                startup_config=config_dict,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error("Studio: failed to register agent '%s': %s", slug, exc)
            return self._error(
                f"Failed to register agent: {exc}",
                status=500,
                code="register_failed",
            )

        persisted = False
        file_path = None
        if create_request.persist:
            try:
                file_path = registry.create_agent_definition(
                    bot_config, category=create_request.category
                )
                persisted = True
                # Re-register FROM the freshly-written YAML so the live
                # BotMetadata.file_path/bot_config reflect the on-disk
                # definition of record — supersedes the class-based
                # registration above. Required for DELETE's file-safety
                # check (delete_factory_agent only ever unlinks
                # metadata.file_path; without this it would still point
                # at bot_class's own framework source file).
                registry.load_agent_definitions(file_path.parent)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error(
                    "Studio: failed to persist YAML for '%s': %s", slug, exc
                )

        # Best-effort live instantiation (non-fatal — mirrors
        # handlers/bots.py `_put_registry`'s identical "best-effort
        # BotManager registration" convention).
        try:
            bot_instance = await registry.get_instance(slug)
            if bot_instance is not None:
                if not getattr(bot_instance, "is_configured", False):
                    await bot_instance.configure(self.request.app)
                manager.add_bot(bot_instance)
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.warning(
                "Studio: agent '%s' registered but instantiation failed: %s",
                slug, exc,
            )

        return self.json_response(
            {
                "name": slug,
                "persisted": persisted,
                "source": "registry",
                "file_path": str(file_path) if file_path else None,
            },
            status=201,
        )

    # -- DELETE ----------------------------------------------------------

    async def delete(self):
        """Delete a factory-origin YAML agent; DB agents are delegated."""
        name = self.request.match_info.get("name")
        if not name:
            return self._error(
                "Agent name is required.", status=400, code="missing_name"
            )

        db_agent = await self._get_db_agent(name)
        if db_agent is not None:
            return self._error(
                f"Agent '{name}' is a database-origin agent; delete it via "
                "/api/v1/bots instead.",
                status=409,
                code="delegated",
            )

        registry = self._registry()
        if registry is None:
            return self._error(
                "AgentRegistry unavailable.", status=503, code="unavailable"
            )

        metadata = registry.get_metadata(name)
        if metadata is None:
            return self._error(
                f"Agent '{name}' not found.", status=404, code="not_found"
            )

        user = await self._get_user()
        owner = self._registry_agent_owner(metadata)
        self._require_owner(owner, user)  # raises web.HTTPForbidden on denial

        # Safety: AgentRegistry.delete_factory_agent() unconditionally
        # unlinks metadata.file_path once bot_config.origin == "factory" —
        # for an agent created via POST /astudio/agents WITHOUT
        # persist=true, AgentRegistry.register() still resolves
        # file_path via inspect.getmodule(bot_class), i.e. the
        # bot_class's own FRAMEWORK/PLUGIN SOURCE FILE (never a
        # throwaway YAML). Deleting such an agent must NOT risk
        # unlinking real source code — refuse unless the on-disk
        # definition actually lives under AGENTS_DIR (where
        # create_agent_definition writes persisted YAMLs).
        file_path = getattr(metadata, "file_path", None)
        is_safe_to_delete = False
        if file_path:
            try:
                is_safe_to_delete = Path(file_path).resolve().is_relative_to(
                    AGENTS_DIR.resolve()
                )
            except (OSError, ValueError):
                is_safe_to_delete = False
        if not is_safe_to_delete:
            return self._error(
                f"Agent '{name}' has no deletable on-disk YAML definition "
                "(it was created without persist=true). Unregister it "
                "programmatically, or recreate it with persist=true.",
                status=409,
                code="no_definition",
            )

        deleted, reason = registry.delete_factory_agent(name)
        if not deleted:
            return self._error(reason, status=409, code="delete_refused")

        manager = self._manager()
        if manager is not None:
            with contextlib.suppress(KeyError):
                manager.remove_bot(name)

        return self.json_response({"name": name, "deleted": True})


@is_authenticated()
@user_session()
class StudioAgentReloadHandler(_StudioAgentsMixin, StudioBaseView):
    """``POST /api/v1/astudio/agents/{name}/reload`` — hot-swap an agent.

    Delegates to ``BotManager.reload_agent`` (FEAT-467 TASK-2510); this
    handler only maps the typed errors it raises to HTTP status codes.
    """

    async def post(self):
        name = self.request.match_info.get("name")
        if not name:
            return self._error(
                "Agent name is required.", status=400, code="missing_name"
            )

        manager = self._manager()
        if manager is None:
            return self._error(
                "BotManager unavailable.", status=503, code="unavailable"
            )

        try:
            result = await manager.reload_agent(name)
        except AgentNotFoundError as exc:
            return self._error(str(exc), status=404, code="not_found")
        except AgentReloadError as exc:
            return self._error(str(exc), status=422, code="reload_failed")
        except Exception as exc:  # pylint: disable=broad-except
            self.logger.error(
                "Studio: reload of agent '%s' failed unexpectedly: %s",
                name, exc, exc_info=True,
            )
            return self._error(
                "Internal server error.", status=500, code="internal_error"
            )

        return self.json_response(result.model_dump(), status=200)
