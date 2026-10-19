"""
SkillRegistryMixin for AbstractBot integration.

Provides automatic skill management integration:
- Skill tools exposed to agent
- Context injection of relevant skills
- Auto-extraction of skills from conversations
- File-based skill registry with eager loading
- Skill trigger middleware for /trigger patterns
- Directory-based skill discovery (FEAT-188)
- Static <available_skills> prompt layer injection (FEAT-188)
- On-demand SkillFileToolkit registration (FEAT-188)
"""

from __future__ import annotations
import inspect
import logging
from contextvars import Token
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING
from .models import SkillCategory, SkillDefinition, Skill
from .store import SkillRegistry, create_skill_registry
from .tenancy import (
    SkillView,
    TenantTreeReport,
    bind_skill_tenant,
    current_active_skill,
    current_skill_tenant,
    discover_tenant_dirs,
    reset_skill_tenant,
    set_active_skill,
    tenant_skills_dir,
    validate_tenant_id,
)
from .tools import create_skill_tools

if TYPE_CHECKING:
    from parrot.utils.helpers import RequestContext
    from .file_registry import SkillFileRegistry

GLOBAL_SKILLS_LAYER = "available_skills"
"""Prompt layer name of the ``<available_skills>`` block (global view / non-tenant mode)."""
TENANT_SKILLS_LAYER_PREFIX = "available_skills:"
"""Prompt layer name prefix of the per-tenant ``<available_skills>`` blocks (FEAT-707)."""


class SkillRegistryMixin:
    """Mixin to add skill registry capabilities to AbstractBot.

    Features:

    - Auto-configure skill registry
    - Expose skill tools to agent
    - Inject relevant skills into context
    - Auto-extract skills from conversations
    - File-based skill registry with eager loading
    - Skill trigger middleware for /trigger patterns
    - Directory discovery via :class:`~parrot.skills.loader.SkillsDirectoryLoader`
      when :attr:`skill_paths` is non-empty (FEAT-188).
    - Static ``<available_skills>`` XML layer injected into system prompt via
      :func:`~parrot.skills.prompt.render_skills_prompt_layer` when
      :attr:`inject_skills_into_prompt` is ``True`` (FEAT-188).
    - :class:`~parrot.skills.tools.SkillFileToolkit` registration exposing
      ``list_skill_commands`` / ``load_skill`` / ``read_skill_asset`` /
      ``save_learned_skill`` for skill discovery, on-demand body and asset
      retrieval (FEAT-188).

    Usage::

        class MyAgent(SkillRegistryMixin, AbstractBot):
            enable_skill_registry = True
            skill_paths = [Path(".agent/skills/")]
            inject_skills_into_prompt = True
    """

    # Configuration — existing
    enable_skill_registry: bool = True
    skill_registry_expose_tools: bool = True
    skill_registry_inject_context: bool = True
    skill_registry_auto_extract: bool = False  # Expensive, opt-in
    skill_registry_max_context_skills: int = 3
    skill_registry_max_context_tokens: int = 1500

    # Configuration — FEAT-188 directory discovery
    skill_paths: List[Path] = []
    """Filesystem paths to scan for skills at configure() time.
    Default is empty (opt-in). Recommended: ``[Path(".agent/skills/")]``."""

    inject_skills_into_prompt: bool = True
    """Inject an ``<available_skills>`` XML layer into the system prompt when
    ``skill_paths`` is non-empty and skills are discovered. Default ``True``."""

    skill_prompt_max_entries: Optional[int] = None
    """Truncation limit for the ``<available_skills>`` layer. ``None`` means
    include all discovered skills. Default ``None``."""

    # Runtime
    _skill_registry: Optional[SkillRegistry] = None
    _skill_file_registry: Optional["SkillFileRegistry"] = None

    @property
    def _active_skill(self) -> Optional[SkillDefinition]:
        """The ``/trigger``-activated skill for the current request (request-local, FEAT-707 S5)."""
        return current_active_skill()

    @_active_skill.setter
    def _active_skill(self, skill: Optional[SkillDefinition]) -> None:
        set_active_skill(skill)

    tenant_based: bool = False
    """Opt-in per-tenant skill trees under ``AGENTS_DIR/{agent_id}/tenants/{tenant}/skills/`` (FEAT-707)."""
    tenant_id: Optional[str] = None
    """Instance-level default tenant (lowest precedence). Class attribute or ``tenant_id=`` kwarg."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        tenant_based = kwargs.pop("tenant_based", None)
        tenant_id = kwargs.pop("tenant_id", None)
        super().__init__(*args, **kwargs)
        if tenant_based is not None:
            self.tenant_based = bool(tenant_based)
        default_tenant = tenant_id if tenant_id is not None else type(self).tenant_id
        if default_tenant is not None:
            self._tenant_id = validate_tenant_id(default_tenant)
        self._tenant_registries: Dict[str, "SkillFileRegistry"] = {}
        self._tenant_store_registries: Dict[str, SkillRegistry] = {}
        self._tenant_views: Dict[str, SkillView] = {}
        self._global_view: Optional[SkillView] = None
        self._known_tenants: set[str] = set()
        self._warned_tenants: set[str] = set()
        self._warned_flags: set[str] = set()

    def _skill_logger(self) -> logging.Logger:
        return getattr(self, "logger", None) or logging.getLogger(__name__)

    def _resolve_tenant(self, explicit: Optional[str] = None, ctx: Optional["RequestContext"] = None) -> Optional[str]:
        """Resolve the skill tenant: explicit, ctx.kwargs["tenant"], bound ContextVar, instance default.

        Raises:
            ValueError: the first non-empty candidate is not a valid tenant id.
        """
        ctx_tenant = None
        ctx_kwargs = getattr(ctx, "kwargs", None) if ctx is not None else None
        if isinstance(ctx_kwargs, dict):
            ctx_tenant = ctx_kwargs.get("tenant")
        candidates = (
            explicit,
            ctx_tenant,
            current_skill_tenant(),
            getattr(self, "_tenant_id", None) or type(self).tenant_id,
        )
        chosen = next((c for c in candidates if c is not None), None)
        if not self.tenant_based:
            if chosen and "ignored" not in self.__dict__.get("_warned_flags", set()):
                self.__dict__.setdefault("_warned_flags", set()).add("ignored")
                self._skill_logger().debug("tenant_based=False: ignoring skill tenant %r", chosen)
            return None
        if chosen is None:
            return None
        return validate_tenant_id(chosen)

    def known_tenants(self) -> frozenset[str]:
        """Tenants with a loaded skill tree."""
        return frozenset(self.__dict__.get("_known_tenants", ()))

    def current_skill_view(self, tenant: Optional[str] = None) -> Optional[SkillView]:
        """View for ``tenant`` (resolved when ``None``); global view for unresolved/unknown tenants."""
        global_view = self.__dict__.get("_global_view")
        resolved = self._resolve_tenant(tenant)
        logger = self._skill_logger()
        if resolved is None:
            logger.debug("No skill tenant resolved; using global skill view")
            return global_view
        view = self.__dict__.get("_tenant_views", {}).get(resolved)
        if view is not None:
            return view
        warned = self.__dict__.setdefault("_warned_tenants", set())
        if resolved not in warned:
            warned.add(resolved)
            logger.warning("Unknown skill tenant %r; falling back to global skills", resolved)
        return global_view

    def _layer_tenant(self) -> Optional[str]:
        """Current tenant for the tenant prompt-layer conditions.

        Same fallback as :meth:`current_skill_view`: the tenant bound for this
        ask()/ask_stream() call, else the instance default ``tenant_id`` — so a
        prompt built outside ask() (e.g. a direct ``create_system_prompt()``)
        shows the same skills the view resolves. Never raises: both sources
        were validated when they were set.
        """
        if not self.tenant_based:
            return None
        bound = current_skill_tenant()
        return bound if bound is not None else getattr(self, "_tenant_id", None)

    def _enter_skill_tenant(self, tenant: Optional[str], ctx: Optional["RequestContext"]) -> Optional[Token]:
        """Bind the resolved tenant for one ask()/ask_stream() call (called by BaseBot, TASK-4496)."""
        if not self.tenant_based:
            return None
        return bind_skill_tenant(self._resolve_tenant(tenant, ctx))

    def _exit_skill_tenant(self, token: Optional[Token]) -> None:
        """Undo :meth:`_enter_skill_tenant`."""
        if token is not None:
            reset_skill_tenant(token)

    async def _load_tenant_skill_trees(self, agent_root: Path) -> Dict[str, TenantTreeReport]:
        """Discover and load every ``tenants/<t>/skills`` tree into a registry + view; one INFO per tenant."""
        from .file_registry import SkillFileRegistry

        logger = self._skill_logger()
        self._tenant_registries.clear()
        self._tenant_views.clear()
        self._known_tenants.clear()
        reports: Dict[str, TenantTreeReport] = {}
        if self._skill_file_registry is None:
            return reports
        for tenant, skills_dir in discover_tenant_dirs(agent_root, logger).items():
            if (skills_dir / "learned").exists():
                logger.warning(
                    "Tenant %s has a learned/ directory (%s); it is ignored, learned skills are global",
                    tenant,
                    skills_dir / "learned",
                )
            reg = SkillFileRegistry(skills_dir=skills_dir, learned_dir=skills_dir / ".learned-disabled")
            await reg.load()
            view = SkillView(self._skill_file_registry, reg, tenant=tenant, logger=logger)
            self._tenant_registries[tenant] = reg
            self._tenant_views[tenant] = view
            self._known_tenants.add(tenant)
            report = view.report
            if report is not None:
                reports[tenant] = report
                logger.info(
                    "tenant=%s skills=%d shadowing=%s dropped=%s",
                    tenant,
                    report.loaded,
                    list(report.shadowing),
                    list(report.dropped),
                )
        return reports

    async def reload_tenant_skills(self, tenant: Optional[str] = None) -> Dict[str, TenantTreeReport]:
        """Rescan one (``tenant``) or all tenant trees and rebuild their views; then ``_after_tenant_reload``."""
        from .file_registry import SkillFileRegistry
        from .tenancy import tenant_skills_dir

        agents_dir = self._resolve_agents_dir()
        if self._skill_file_registry is None or not agents_dir:
            return {}
        agent_id = getattr(self, "name", None) or getattr(self, "agent_id", "default")
        agent_root = agents_dir / agent_id
        logger = self._skill_logger()
        if tenant is None:
            reports = await self._load_tenant_skill_trees(agent_root)
        else:
            validate_tenant_id(tenant)
            reports = {}
            skills_dir = tenant_skills_dir(agent_root, tenant)
            if skills_dir.is_dir():
                reg = SkillFileRegistry(skills_dir=skills_dir, learned_dir=skills_dir / ".learned-disabled")
                await reg.load()
                view = SkillView(self._skill_file_registry, reg, tenant=tenant, logger=logger)
                self._tenant_registries[tenant] = reg
                self._tenant_views[tenant] = view
                self._known_tenants.add(tenant)
                self._warned_tenants.discard(tenant)
                if view.report is not None:
                    reports[tenant] = view.report
            else:
                self._tenant_registries.pop(tenant, None)
                self._tenant_views.pop(tenant, None)
                self._known_tenants.discard(tenant)
        await self._after_tenant_reload(reports)
        return reports

    async def _after_tenant_reload(self, reports: Dict[str, TenantTreeReport]) -> None:
        """Refresh the skill views and the ``<available_skills>`` layers after a tenant (re)load.

        Layers of tenants that disappeared are removed by :meth:`_install_skill_prompt_layers`.
        """
        self._recompose_skill_views()
        self._install_skill_prompt_layers()
        if self.tenant_based:
            for tenant in set(self._tenant_store_registries) - self._known_tenants:
                registry = self._tenant_store_registries.pop(tenant)
                await registry.cleanup()
            await self._configure_tenant_store_registries()

    def _resolve_agents_dir(self) -> Optional[Path]:
        """Resolve the base AGENTS_DIR for skill persistence.

        Priority:
        1. Explicit ``self._agents_dir`` attribute (if set by the bot).
        2. ``parrot.conf.AGENTS_DIR`` as framework-wide default, matching the
           convention used for ``kb/``, ``prompts/``, ``queries/``, and
           ``documents/`` under ``AGENTS_DIR/{agent_id}/``.

        Returns:
            Resolved ``Path`` or ``None`` if neither is available.
        """
        agents_dir = getattr(self, "_agents_dir", None)
        if agents_dir is not None:
            return Path(agents_dir)
        try:
            from parrot.conf import AGENTS_DIR
        except ImportError:
            return None
        if AGENTS_DIR is None:
            return None
        return Path(AGENTS_DIR)

    async def _configure_skill_registry(self) -> None:
        """Configure skill registry during agent configure()."""
        if not self.enable_skill_registry:
            return

        if self._skill_registry is not None:
            return

        agent_id = getattr(self, "name", None) or getattr(self, "agent_id", "default")
        org_id = getattr(self, "org_id", "default")
        namespace = f"{org_id}/{agent_id}"

        # Determine persistence path
        persistence_path = None
        agents_dir = self._resolve_agents_dir()
        if agents_dir:
            persistence_path = agents_dir / agent_id / "skills"

        self._skill_registry = create_skill_registry(
            namespace=namespace,
            persistence_path=persistence_path,
            extraction_llm=getattr(self, "_llm", None),
        )

        await self._skill_registry.configure()

        # Add tools
        if self.skill_registry_expose_tools:
            await self._add_skill_tools()

        # Configure file-based skill registry
        await self._configure_skill_file_registry()

        if self.tenant_based:
            await self._configure_tenant_store_registries()

        if hasattr(self, "logger"):
            self.logger.info("SkillRegistry configured: %s", namespace)

    async def _configure_tenant_store_registries(self) -> None:
        """Configure one tenant registry per known tenant using the global embedding model."""
        if self._skill_registry is None:
            return

        agents_dir = self._resolve_agents_dir()
        if agents_dir is None:
            return

        agent_id = getattr(self, "name", None) or getattr(self, "agent_id", "default")
        org_id = getattr(self, "org_id", "default")
        agent_root = agents_dir / agent_id
        embedding_model = getattr(self._skill_registry, "_embedding_model", None)

        for tenant in sorted(self._known_tenants):
            if tenant in self._tenant_store_registries:
                continue
            registry = create_skill_registry(
                namespace=f"{org_id}/{agent_id}/{tenant}",
                persistence_path=tenant_skills_dir(agent_root, tenant),
                extraction_llm=getattr(self, "_llm", None),
            )
            await registry.configure(embedding_model=embedding_model)
            self._tenant_store_registries[tenant] = registry

    def _current_store_registry(self, tenant: Optional[str] = None) -> Optional[SkillRegistry]:
        """Return the resolved tenant store when known, otherwise the global store."""
        if not self.tenant_based:
            return self._skill_registry
        resolved = self._resolve_tenant(tenant)
        return self._tenant_store_registries.get(resolved, self._skill_registry)

    async def _configure_skill_file_registry(self) -> None:
        """Configure file-based skill registry and trigger middleware.

        Resolves ``AGENTS_DIR/{agent_id}/skills/`` and loads skills in both
        single-file (``{name}.md``) and composite (``{name}/SKILL.md``) layouts.
        Registers SkillTriggerMiddleware in the bot's prompt pipeline.

        When ``agents_dir`` is None the original agents-dir loading block is
        skipped but the FEAT-188 extensions (directory discovery, prompt layer
        injection, SkillFileToolkit registration) still run whenever
        ``skill_paths`` is non-empty.
        """
        from .file_registry import SkillFileRegistry
        from .middleware import create_skill_trigger_middleware

        if self._skill_file_registry is not None:
            return

        agent_id = getattr(self, "name", None) or getattr(self, "agent_id", "default")
        agents_dir = self._resolve_agents_dir()
        logger = getattr(self, "logger", logging.getLogger(__name__))

        # --- Original block: only runs when agents_dir is set ---
        if agents_dir:
            skills_dir = agents_dir / agent_id / "skills"
            learned_dir = skills_dir / "learned"

            # Create directories if they don't exist
            skills_dir.mkdir(parents=True, exist_ok=True)
            learned_dir.mkdir(parents=True, exist_ok=True)

            self._skill_file_registry = SkillFileRegistry(
                skills_dir=skills_dir,
                learned_dir=learned_dir,
            )
            await self._skill_file_registry.load()

            # Register trigger middleware in prompt pipeline.
            # FEAT-396 (TASK-2028): no wiring change needed here either —
            # like bots/search.py's competitor pipeline, whatever middleware
            # this appends to an existing `self._prompt_pipeline` keeps
            # applying through the unified INPUT `GuardrailPipeline` via the
            # always-registered `LegacyPipelineGuardrail` (see
            # `AbstractBot.__init__`), which resolves `self._prompt_pipeline`
            # dynamically rather than snapshotting it at construction time.
            prompt_pipeline = getattr(self, "_prompt_pipeline", None)
            if prompt_pipeline is not None:
                mw = create_skill_trigger_middleware(
                    registry=self._skill_file_registry,
                    bot=self,
                    **({"view_provider": self.current_skill_view} if self.tenant_based else {}),
                )
                prompt_pipeline.add(mw)

            n_skills = len(self._skill_file_registry.list_skills())
            logger.info(
                "SkillFileRegistry loaded: %d skills from %s",
                n_skills,
                skills_dir,
            )
            self._global_view = SkillView(self._skill_file_registry, logger=logger)
            if self.tenant_based:
                await self._load_tenant_skill_trees(agents_dir / agent_id)

        # --- FEAT-188 extensions: run regardless of agents_dir ---
        skill_paths = list(getattr(self, "skill_paths", []))
        if skill_paths:
            # Ensure a registry exists even when agents_dir is absent
            if self._skill_file_registry is None:
                import tempfile

                _tmp = Path(tempfile.mkdtemp(prefix="parrot_skills_"))
                self._skill_file_registry = SkillFileRegistry(
                    skills_dir=_tmp,
                    learned_dir=_tmp / "learned",
                )
                await self._skill_file_registry.load()

            from .loader import SkillsDirectoryLoader

            loader = SkillsDirectoryLoader(
                paths=skill_paths,
                logger=logger,
            )
            loaded = await loader.load_into(self._skill_file_registry)
            logger.info(
                "SkillsDirectoryLoader: loaded %d skills from %s",
                loaded,
                [str(p) for p in skill_paths],
            )

        if self._skill_file_registry is not None:
            # Rebuild so skill_paths skills are included in every view.
            self._global_view = SkillView(self._skill_file_registry, logger=logger)
            for tenant_view in self._tenant_views.values():
                tenant_view.compose()
            if self.tenant_based and not agents_dir:
                logger.warning("tenant_based=True but no agents_dir resolved; using global skills only")

        # --- FEAT-188 / FEAT-707: Prompt layer injection ---
        self._install_skill_prompt_layers()

        # --- FEAT-188: file-based skill tools registration ---
        # Register the SkillFileToolkit (list_skill_commands / load_skill /
        # read_skill_asset / save_learned_skill) whenever a file registry
        # exists — whether populated via the agents_dir convention, explicit
        # skill_paths, or still empty. An empty registry must still expose the
        # tools: save_learned_skill can hot-add skills mid-session and
        # list_skill_commands reads the live registry, so gating on a
        # non-empty registry at configure() time would hide them forever.
        if self._skill_file_registry is not None:
            from .tools import SkillFileToolkit

            toolkit = SkillFileToolkit(
                file_registry=self._skill_file_registry,
                learned_dir=self._skill_file_registry.learned_dir,
                **({"view_provider": self.current_skill_view} if self.tenant_based else {}),
            )
            skill_tools = toolkit.get_tools()
            tool_manager = getattr(self, "tool_manager", None)
            if tool_manager and hasattr(tool_manager, "register_tool"):
                for tool in skill_tools:
                    result = tool_manager.register_tool(tool)
                    if inspect.isawaitable(result):
                        await result
            elif hasattr(self, "_tools"):
                if isinstance(self._tools, list):
                    self._tools.extend(skill_tools)
                else:
                    self._tools = list(self._tools) + skill_tools
            logger.debug("SkillFileToolkit registered (%d tools)", len(skill_tools))

    def _install_skill_prompt_layers(self) -> None:
        """Install (replace-by-name) the ``<available_skills>`` layers for the global and tenant views.

        With ``tenant_based=False`` this installs exactly the single FEAT-188 layer
        (``render_skills_prompt_layer(registry, max_skills=...)``) when skills exist.

        With ``tenant_based=True`` it installs the global layer (rendered only while no
        known tenant is bound) and one layer per tenant view (rendered only while that
        tenant is bound), all REQUEST-phase and cacheable. Views with no skills get no
        layer, and layers of tenants that are no longer known are removed.
        """
        from .prompt import global_layer_condition, render_skills_prompt_layer, tenant_layer_condition
        from parrot.bots.prompts import RenderPhase

        prompt_builder = getattr(self, "_prompt_builder", None)
        if prompt_builder is None or self._skill_file_registry is None:
            return
        if not getattr(self, "inject_skills_into_prompt", True):
            return
        max_entries = getattr(self, "skill_prompt_max_entries", None)
        logger = self._skill_logger()

        if not self.tenant_based:
            if self._skill_file_registry.list_skills():
                prompt_builder.add(render_skills_prompt_layer(self._skill_file_registry, max_skills=max_entries))
                logger.debug(
                    "Skills prompt layer injected (%d entries)",
                    len(self._skill_file_registry.list_skills()),
                )
            return

        # Live set: the conditions must observe later tenant (re)loads, so never copy it.
        known_tenants = self.__dict__.setdefault("_known_tenants", set())
        global_view = self.__dict__.get("_global_view")
        desired: Dict[str, Any] = {}
        if global_view is not None and global_view.list_skills():
            desired[GLOBAL_SKILLS_LAYER] = render_skills_prompt_layer(
                global_view,
                max_skills=max_entries,
                phase=RenderPhase.REQUEST,
                condition=global_layer_condition(known_tenants, self._layer_tenant),
                cacheable=True,
            )
        for tenant, view in self.__dict__.get("_tenant_views", {}).items():
            if not view.list_skills():
                continue
            name = f"{TENANT_SKILLS_LAYER_PREFIX}{tenant}"
            desired[name] = render_skills_prompt_layer(
                view,
                max_skills=max_entries,
                name=name,
                phase=RenderPhase.REQUEST,
                condition=tenant_layer_condition(tenant, self._layer_tenant),
                cacheable=True,
            )

        # Drop previously installed skill layers that are no longer desired.
        for name in list(prompt_builder.layer_names):
            if name == GLOBAL_SKILLS_LAYER or name.startswith(TENANT_SKILLS_LAYER_PREFIX):
                if name not in desired:
                    prompt_builder.remove(name)
        for layer in desired.values():
            prompt_builder.add(layer)

    def _recompose_skill_views(self) -> None:
        """Recompute the global and every tenant view after a global registry change (learned skills)."""
        global_view = self.__dict__.get("_global_view")
        if global_view is not None:
            global_view.compose()
        for view in self.__dict__.get("_tenant_views", {}).values():
            view.compose()

    async def save_learned_skill(
        self,
        name: str,
        content: str,
        description: str,
        triggers: List[str],
        category: str = "general",
    ) -> Optional[SkillDefinition]:
        """Save a learned skill as a .md file and hot-add to the registry.

        Writes a markdown file with YAML frontmatter to the learned skills
        directory and makes it immediately available in the current session.

        Args:
            name: Skill name (used as filename).
            description: Short description of the skill.
            content: Skill instruction body (markdown).
            triggers: Trigger commands, e.g. ['/resumen'].
            category: Skill category.

        Returns:
            The created SkillDefinition, or None if the save failed.
        """
        if not self._skill_file_registry:
            return None

        from .parsers import parse_skill_file

        logger = getattr(self, "logger", logging.getLogger(__name__))

        # Check name collision
        for existing in self._skill_file_registry.list_skills():
            if existing.name == name:
                logger.error("Skill name '%s' already exists — cannot save", name)
                return None

        # Resolve learned directory
        learned_dir = self._skill_file_registry.learned_dir
        learned_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize filename
        safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
        file_path = learned_dir / f"{safe_name}.md"

        # Build YAML frontmatter
        triggers_yaml = "\n".join(f"  - {t}" for t in triggers)
        md_content = f"""---
name: {name}
description: {description}
triggers:
{triggers_yaml}
source: learned
category: {category}
---

{content}
"""
        # Write file
        file_path.write_text(md_content)

        # Validate via parser
        try:
            skill = parse_skill_file(file_path)
        except Exception as exc:
            logger.error("Failed to validate learned skill '%s': %s", name, exc)
            file_path.unlink(missing_ok=True)
            return None

        # Hot-add to registry
        self._skill_file_registry.add(skill)
        self._recompose_skill_views()
        self._install_skill_prompt_layers()
        logger.info("Learned skill '%s' saved and hot-added", name)
        return skill

    async def _add_skill_tools(self) -> None:
        """Add skill tools to agent.

        ``ToolManager.register_tool`` is synchronous in the current
        framework, so we call it directly. For forward compatibility with a
        hypothetical async variant we ``await`` the result only when it is
        awaitable.
        """
        if not self._skill_registry:
            return

        agent_id = getattr(self, "name", "agent")
        tools = create_skill_tools(
            registry=self._skill_registry,
            agent_id=agent_id,
            include_write_tools=True,
            **({"registry_provider": self._current_store_registry} if self.tenant_based else {}),
        )

        tool_manager = getattr(self, "tool_manager", None)
        if tool_manager and hasattr(tool_manager, "register_tool"):
            for tool in tools:
                result = tool_manager.register_tool(tool)
                if inspect.isawaitable(result):
                    await result
        elif hasattr(self, "_tools"):
            self._tools = getattr(self, "_tools", []) + tools

    async def get_skill_context(
        self,
        query: str,
        max_skills: Optional[int] = None,
        max_tokens: Optional[int] = None,
        tenant: Optional[str] = None,
    ) -> str:
        """
        Get relevant skills for context injection.

        Returns formatted Markdown for system prompt.
        """
        if not self._skill_registry or not self.skill_registry_inject_context:
            return ""

        registry = self._current_store_registry(tenant)
        if registry is None:
            return ""
        context = await registry.get_relevant_skills(
            query=query,
            max_skills=max_skills or self.skill_registry_max_context_skills,
            max_tokens=max_tokens or self.skill_registry_max_context_tokens,
        )
        if registry is not self._skill_registry and not context.strip():
            return await self._skill_registry.get_relevant_skills(
                query=query,
                max_skills=max_skills or self.skill_registry_max_context_skills,
                max_tokens=max_tokens or self.skill_registry_max_context_tokens,
            )
        return context

    async def document_skill(
        self,
        name: str,
        content: str,
        description: str = "",
        category: str = "general",
        tags: Optional[List[str]] = None,
        triggers: Optional[List[str]] = None,
        tenant: Optional[str] = None,
    ) -> Optional[Skill]:
        """
        Programmatically document a skill.

        Returns created Skill or None.
        """
        if not self._skill_registry:
            return None

        agent_id = getattr(self, "name", "agent")
        registry = self._current_store_registry(tenant)
        if registry is None:
            return None
        skill, _ = await registry.upload_skill(
            name=name,
            content=content,
            agent_id=agent_id,
            description=description,
            category=category,
            tags=tags or [],
            triggers=triggers or [],
        )
        return skill

    async def extract_skills_from_conversation(
        self,
        conversation: str,
        context: Optional[str] = None,
    ) -> Optional[Skill]:
        """
        Use LLM to extract skills from conversation.

        Should be called selectively (expensive).
        """
        if not self._skill_registry or not self.skill_registry_auto_extract:
            return None

        agent_id = getattr(self, "name", "agent")
        result = await self._skill_registry.extract_skill_from_conversation(
            conversation=conversation,
            agent_id=agent_id,
            context=context,
        )

        return result[0] if result else None

    async def search_skills(
        self,
        query: str,
        category: Optional[str] = None,
        max_results: int = 5,
        tenant: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search for relevant skills."""
        if not self._skill_registry:
            return []

        cat = SkillCategory(category) if category else None
        global_results = await self._skill_registry.search_skills(
            query=query,
            category=cat,
            max_results=max_results,
        )

        registry = self._current_store_registry(tenant)
        if registry is self._skill_registry:
            results = [(result, self._skill_registry.namespace) for result in global_results]
        else:
            tenant_results = await registry.search_skills(
                query=query,
                category=cat,
                max_results=max_results,
            )
            by_name = {
                result.skill.metadata.name: (result, self._skill_registry.namespace) for result in global_results
            }
            by_name.update({result.skill.metadata.name: (result, registry.namespace) for result in tenant_results})
            results = sorted(by_name.values(), key=lambda item: item[0].relevance_score, reverse=True)[:max_results]

        return [
            {
                "skill_id": r.skill.skill_id,
                "name": r.skill.metadata.name,
                "description": r.skill.metadata.description,
                "content": r.content,
                "relevance": r.relevance_score,
                "namespace": namespace,
            }
            for r, namespace in results
        ]

    async def _cleanup_skill_registry(self) -> None:
        """Cleanup skill registry."""
        for registry in self._tenant_store_registries.values():
            await registry.cleanup()
        self._tenant_store_registries.clear()
        if self._skill_registry:
            await self._skill_registry.cleanup()
            self._skill_registry = None


class SkillRegistryHooks:
    """Hook functions for skill registry integration."""

    @staticmethod
    async def pre_ask_hook(agent: SkillRegistryMixin, query: str, **kwargs) -> Dict[str, Any]:
        """Get relevant skills before ask()."""
        context = await agent.get_skill_context(query)
        return {"skill_context": context}

    @staticmethod
    async def post_ask_hook(agent: SkillRegistryMixin, query: str, response: Any, **kwargs) -> None:
        """Optionally extract skills after ask()."""
        if not agent.skill_registry_auto_extract:
            return

        conversation = f"User: {query}\nAssistant: {response}"
        await agent.extract_skills_from_conversation(conversation)
