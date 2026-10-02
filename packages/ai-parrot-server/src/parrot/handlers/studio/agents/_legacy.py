"""Filesystem-mode (legacy) agent paths — the verbatim ``_legacy_*`` bodies, as a mixin."""

from __future__ import annotations

import contextlib
from pathlib import Path

from parrot.clients.factory import LLMFactory
from parrot.models.basic import ModelConfig
from parrot.registry.registry import BotConfig
from parrot.utils.naming import slugify_name
from pydantic import ValidationError


from .._base import is_valid_slug
from ..models import CreateAgentRequest


class _StudioAgentsLegacyMixin:
    """Legacy (registry/YAML) GET / POST / DELETE of ``StudioAgentsHandler``."""

    async def _legacy_get(self):
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

    async def _legacy_post(self):
        """Create a simple agent — registers into ``AgentRegistry``.

        With ``persist: true`` also writes a lossless ``agent:``-keyed
        YAML definition (``AgentRegistry.create_agent_definition``,
        FEAT-467 TASK-2509) under ``AGENTS_DIR/agents/<category>/``.
        """
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("agents", "astudio:agents:create")) is not None:
            return denied

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
            return self._error(f"Invalid request: {exc}", status=400, code="invalid_request")

        try:
            slug = slugify_name(create_request.name)
        except ValueError as exc:
            return self._error(str(exc), status=400, code="invalid_name")

        # SECURITY (adversarial-review fix): `category` becomes a path
        # segment in AGENTS_DIR/agents/<category>/ inside
        # create_agent_definition — an unvalidated "../../.." wrote the
        # YAML outside AGENTS_DIR entirely. Same slug rule as every other
        # Studio path segment.
        if not is_valid_slug(create_request.category):
            return self._error(
                f"Invalid category '{create_request.category}'; must match ^[a-z0-9_-]+$.",
                status=400,
                code="invalid_category",
            )

        existing = await self._check_duplicate(slug)
        if existing:
            return self._error(
                f"Agent '{slug}' already exists in {existing}.",
                status=409,
                code="duplicate",
            )

        manager = self._manager()
        if manager is None:
            return self._error("BotManager unavailable.", status=503, code="unavailable")

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

        # Adversarial-review fix: the requested `llm` was packed only into
        # bot_config.model, but a NON-persisted instance is built from
        # startup_config alone (BotMetadata.get_instance merges
        # startup_config into the constructor kwargs; bot_config.model is
        # never consulted on that path) — so the live instance silently
        # used the class default model. Thread the original
        # "provider:model" string as the `llm` constructor kwarg,
        # startup-side only (kept OUT of bot_config.config so the
        # persisted YAML stays lossless/unchanged).
        startup_kwargs = dict(config_dict)
        if create_request.llm:
            startup_kwargs["llm"] = create_request.llm

        registry = self._registry()
        try:
            registry.register(
                slug,
                bot_class,
                bot_config=bot_config,
                startup_config=startup_kwargs,
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
                file_path = registry.create_agent_definition(bot_config, category=create_request.category)
                persisted = True
                # Re-register FROM the freshly-written YAML so the live
                # BotMetadata.file_path/bot_config reflect the on-disk
                # definition of record — supersedes the class-based
                # registration above. Required for DELETE's file-safety
                # check (delete_factory_agent only ever unlinks
                # metadata.file_path; without this it would still point
                # at bot_class's own framework source file). Per-file
                # (adversarial-review fix): the directory scanner would
                # re-register fresh BotMetadata for every sibling YAML.
                registry.load_agent_definition_file(file_path)
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.error("Studio: failed to persist YAML for '%s': %s", slug, exc)

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
                slug,
                exc,
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

    async def _legacy_delete(self):
        """Delete a factory-origin YAML agent; DB agents are delegated."""
        # PBAC (adversarial-review fix: gate was defined but never called).
        if (denied := await self._pbac_gate("agents", "astudio:agents:delete")) is not None:
            return denied

        name = self.request.match_info.get("name")
        if not name:
            return self._error("Agent name is required.", status=400, code="missing_name")

        db_agent = await self._get_db_agent(name)
        if db_agent is not None:
            return self._error(
                f"Agent '{name}' is a database-origin agent; delete it via " "/api/v1/bots instead.",
                status=409,
                code="delegated",
            )

        registry = self._registry()
        if registry is None:
            return self._error("AgentRegistry unavailable.", status=503, code="unavailable")

        metadata = registry.get_metadata(name)
        if metadata is None:
            return self._error(f"Agent '{name}' not found.", status=404, code="not_found")

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
                # read from the package at call time: tests patch ``studio.agents.AGENTS_DIR``
                from parrot.handlers.studio import agents as _agents_pkg

                is_safe_to_delete = Path(file_path).resolve().is_relative_to(_agents_pkg.AGENTS_DIR.resolve())
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
