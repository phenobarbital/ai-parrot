"""Build a Studio agent instance from one storage snapshot (spec §2.7). Never registers anything."""

from __future__ import annotations

import asyncio
import logging
import shutil
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from parrot.bots.prompts.identity import IDENTITY_FILES
from parrot.models.basic import ToolConfig
from parrot.registry.registry import BotConfig
from parrot.tools.spec import AgentMCPServerSpec, ToolkitSpec

from ..handlers.studio.storage.models import StudioAgentSnapshot, StudioPartition, StudioToolingRefused
from ..handlers.studio.storage.services._common import (
    StudioClassAllowlist,
    StudioToolingGate,
    normalized_tooling_for,
)

if TYPE_CHECKING:
    from aiohttp import web

    from parrot.bots.abstract import AbstractBot
    from parrot.registry.registry import AgentRegistry

logger = logging.getLogger("Parrot.AgentStudio.Storage")


def _resolve_bot_class(name: str) -> type:
    """``parrot.bots`` first, then ``parrot.agents.<name>`` (the lookup ``BotManager.get_bot_class`` does)."""
    for module_name in ("parrot.bots", f"parrot.agents.{name.lower()}", "parrot.agents"):
        try:
            module = import_module(module_name)
        except ImportError:
            continue
        if hasattr(module, name):
            return getattr(module, name)
    raise ValueError(f"unknown bot_class {name!r}")


def _kb_dir_name(bot: "AbstractBot") -> str:
    """The directory name ``LocalKBMixin._get_agent_kb_directory`` derives from the instance (agent_id, else name)."""
    raw = getattr(bot, "agent_id", None) if hasattr(bot, "agent_id") else None
    return str(raw or bot.name).lower().replace(" ", "_")


class StudioAgentBuilder:
    """§2.7 build: gate → factory with the explicit constructor map → versioned asset dir → stamps → configure."""

    def __init__(self, registry: "AgentRegistry", runtime_dir: Path, tooling_gate: StudioToolingGate) -> None:
        self._registry, self._root, self._gate = registry, runtime_dir, tooling_gate

    @property
    def runtime_dir(self) -> Path:
        """Root of the versioned asset directories (``<root>/<agent_id>/v<version>``)."""
        return self._root

    async def build(
        self, snapshot: StudioAgentSnapshot, app: "web.Application", *, part: StudioPartition
    ) -> tuple["AbstractBot", Path]:
        """Build one instance; on failure clean the half-built bot once, remove its directory and raise.

        Raises:
            StudioToolingRefused: the tenant policy refuses the stored tooling (fails the build closed).
            AgentReloadError: any other failure (class refused/unknown, factory error, ``configure()`` error).
        """
        rec = snapshot.record
        self._gate.enforce(
            part, normalized_tooling_for(rec.definition, snapshot.tooling), agent_id=rec.agent_id, actor=None,
            phase="build",
        )
        directory = self._root / str(rec.agent_id) / f"v{rec.version}"
        shared = directory.exists()          # another entry (base/session) of this version already uses it
        bot: "AbstractBot | None" = None
        try:
            self._check_class(part, rec.definition.bot_class, app)
            bot_config, kwargs = self._constructor(snapshot)
            bot = await self._registry.create_agent_factory(bot_config)(**kwargs)
            self._write_assets(bot, snapshot, directory)
            self._stamp_and_bind(bot, snapshot, app, part, directory)
            await bot.configure(app)
        except BaseException as exc:
            await self._discard(bot, None if shared else directory, label=f"{rec.name}@v{rec.version}")
            if isinstance(exc, StudioToolingRefused) or not isinstance(exc, Exception):
                raise
            from .manager import AgentReloadError

            raise AgentReloadError(f"cannot build Studio agent {rec.name!r} v{rec.version}: {exc}") from exc
        return bot, directory

    # ---- steps ------------------------------------------------------------------------------------------------
    @staticmethod
    def _check_class(part: StudioPartition, bot_class: str, app: Any) -> None:
        """A tenant partition builds allowlisted classes only (a row written before the list was tightened is refused)."""
        if not StudioClassAllowlist.from_app(app).allows(part, bot_class):
            raise ValueError(f"bot_class {bot_class!r} is not allowed for this tenant")

    def _constructor(self, snapshot: StudioAgentSnapshot) -> tuple[BotConfig, dict[str, Any]]:
        """§2.7 map: each value reaches the constructor through exactly one channel.

        ``BotConfig.model`` is always ``None`` and ``config``/``startup_config`` stay empty: the factory overwrites
        ``llm``/``temperature``/``max_tokens`` from ``model`` and there is no startup-config bridge on a direct call.
        """
        rec, definition = snapshot.record, snapshot.record.definition
        bot_class = _resolve_bot_class(definition.bot_class)
        rows = sorted(snapshot.tooling, key=lambda r: (r.kind, r.position, r.slug))
        toolkits = [ToolkitSpec.model_validate({**r.config, "slug": r.slug, "secret_refs": dict(r.secret_refs),
                                                "vault_owner": r.vault_owner}) for r in rows if r.kind == "toolkit"]
        servers = [AgentMCPServerSpec.model_validate({**r.config, "name": r.slug, "secret_refs": dict(r.secret_refs),
                                                      "vault_owner": r.vault_owner}) for r in rows if r.kind == "mcp"]
        bot_config = BotConfig(
            name=rec.name, class_name=bot_class.__name__, module=bot_class.__module__, origin="factory",
            tools=ToolConfig(tools=[{"name": t} for t in definition.tools]), toolkits=toolkits,
            mcp_servers=[s.model_dump(mode="json") for s in servers], system_prompt=definition.system_prompt,
            model=None, config={}, startup_config={},
        )
        kwargs: dict[str, Any] = {**definition.config, "chatbot_id": str(rec.agent_id), "created_by": rec.owner}
        if definition.llm:
            kwargs["llm"] = definition.llm
        if definition.description is not None:
            kwargs["description"] = definition.description
        params = definition.model_params.model_dump(exclude_none=True)
        if params:
            kwargs["model_config"] = params
        kwargs.update(self._identity_kwargs(snapshot))
        return bot_config, kwargs

    @staticmethod
    def _identity_kwargs(snapshot: StudioAgentSnapshot) -> dict[str, str]:
        """``role.md`` … ``rationale.md`` identity assets → the five identity constructor kwargs."""
        wanted = {f"{field}.md": field for field in IDENTITY_FILES}
        return {
            wanted[a.name]: a.content.strip()
            for a in snapshot.assets
            if a.kind == "identity" and a.name in wanted and a.content and a.content.strip()
        }

    def _write_assets(self, bot: "AbstractBot", snapshot: StudioAgentSnapshot, directory: Path) -> None:
        """KB under ``<dir>/<kb-name>/kb``, skills under ``<dir>/<name>/skills``; ``bot._agents_dir = <dir>``."""
        targets = {"kb": directory / _kb_dir_name(bot) / "kb", "skills": directory / snapshot.record.name / "skills"}
        directory.mkdir(parents=True, exist_ok=True)
        for asset in snapshot.assets:
            if asset.kind not in targets or asset.content is None:
                continue
            target = (targets[asset.kind] / asset.name).resolve()
            if targets[asset.kind].resolve() not in target.parents:
                raise ValueError(f"asset path escapes its directory: {asset.kind}/{asset.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(asset.content, encoding="utf-8")
        bot._agents_dir = directory

    @staticmethod
    def _stamp_and_bind(
        bot: "AbstractBot", snapshot: StudioAgentSnapshot, app: Any, part: StudioPartition, directory: Path
    ) -> None:
        """Identity stamps, the tenant tooling policy binding (before ``configure()``) and the confirmation guard."""
        from parrot.tools.tooling_policy import ToolingSubject, get_tenant_tooling_policy

        rec = snapshot.record
        bot._studio_key = rec.key
        bot._studio_version = rec.version
        bot._studio_agent_id = rec.agent_id
        bot._tooling_ref = rec.tooling_ref
        bot._studio_visibility = rec.visibility   # carried into ``studio_scope.agent`` (C16)
        bot.bind_tooling_policy(
            get_tenant_tooling_policy(app),
            ToolingSubject(tenant=part.tenant, agent_id=rec.agent_id, actor=None, phase="build"),
            owner=rec.owner,
        )
        guard = app.get("studio_confirmation_guard")
        if guard is not None:
            bot.tool_manager.set_confirmation_guard(guard)

    async def _discard(self, bot: "AbstractBot | None", directory: Path | None, *, label: str) -> None:
        """Clean the half-built instance exactly once and remove the directory it created. Never raises."""
        if bot is not None:
            from .manager import cleanup_bot_instance

            await asyncio.shield(cleanup_bot_instance(bot, label=label))
        if directory is not None:
            await asyncio.to_thread(shutil.rmtree, directory, ignore_errors=True)
