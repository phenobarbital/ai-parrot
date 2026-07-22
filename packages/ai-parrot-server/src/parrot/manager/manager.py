"""
Chatbot Manager.

Tool for instanciate, managing and interacting with Chatbot through APIs.
"""
from typing import Any, Dict, Type, Optional, Tuple, List, TYPE_CHECKING
from importlib import import_module
import contextlib
import time
import asyncio
import copy
from aiohttp import web
from datamodel.exceptions import ValidationError  # pylint: disable=E0611 # noqa
# Navigator:
from navconfig.logging import logging
# FEAT-153: PBAC agent-access enforcement
from ..auth.agent_guard import enforce_agent_access, AgentAccessDenied  # noqa: F401
from asyncdb.exceptions import NoDataFound
# FEAT-133: reranker + parent-searcher factories
from ..rerankers.factory import create_reranker
from ..stores.parents.factory import create_parent_searcher
from ..exceptions import ConfigError
from ..bots.abstract import AbstractBot
from ..bots.basic import BasicBot
from ..bots.chatbot import Chatbot
from ..bots.agent import BasicAgent
from ..handlers.chat import ChatHandler, BotHandler
from ..handlers.agent import AgentTalk
from ..handlers.integrations import IntegrationsHandler
from ..handlers.infographic import InfographicTalk
from ..handlers.agents.data import DataAnalystHandler
from ..handlers.agents.factory import AgentFactoryHandler
from ..handlers.print_pdf import PrintPDFHandler
from ..handlers.datasets import DatasetManagerHandler
from ..handlers.infographic_recipes import RecipeHandler
from ..handlers.database import (
    DatabaseDriversHandler,
    DatabaseFormatsHandler,
    DatabaseIntentsHandler,
    DatabaseRolesHandler,
    DatabaseSchemasHandler,
)
from ..handlers.chat_interaction import ChatInteractionHandler
from ..storage import (
    ChatStorage,
    ArtifactStore,
    build_conversation_backend,
    build_overflow_store,
)
from ..handlers import ChatbotHandler
from ..handlers.config_handler import BotConfigHandler
from ..handlers.testing_handler import BotConfigTestHandler
from ..handlers.dashboard_handler import (
    DashboardHandler,
    DashboardTabHandler,
    _ensure_dashboard_indexes,
)
from ..handlers.models import BotModel, UserBotModel
# Per-user bot HTTP handler (PUT/PATCH/GET/DELETE)
from ..handlers.agents.users import UserAgentHandler
# FEAT-149: Ephemeral user agent handler + tool catalog
from ..handlers.agents.ephemeral import EphemeralUserAgentHandler
from ..handlers.tools_catalog import ToolCatalogHandler
from ..handlers.prompt import PromptTunerHandler
from ..handlers.stream import StreamHandler
from ..handlers.knowledge import AgentKnowledgeHandler
from ..registry import agent_registry, AgentRegistry, BotConfigStorage
# Crew:
from ..bots.flows.crew import AgentCrew
from ..models.crew_definition import CrewDefinition
from ..handlers.crew.handler import CrewHandler
from ..handlers.crew.execution_handler import CrewExecutionHandler
from ..handlers.crew.execution_history_handler import CrewExecutionHistoryHandler
from ..handlers.crew.tool_catalog import CrewToolCatalogHandler
from ..handlers.crew.special_nodes import CrewSpecialNodeCatalogHandler
from ..handlers.crew.redis_persistence import CrewRedis
from ..openapi.config import setup_swagger
from ..conf import (
    BOT_CLEANUP_TIMEOUT,
    ENABLE_CREWS,
    ENABLE_DATABASE_BOTS,
    ENABLE_DASHBOARDS,
    ENABLE_STRUCTURED_OUTPUT_TRANSPORT,
    ENABLE_REGISTRY_BOTS,
    ENABLE_SWAGGER,
    REDIS_URL,
)
# Credentials handler
from ..handlers.credentials import setup_credentials_routes
# MCP helper handler (discovery, activation, management)
from ..handlers.mcp_helper import setup_mcp_helper_routes
# FEAT-146: Web HITL response endpoint + bootstrap
from ..handlers.web_hitl import HITLResponseHandler, setup_web_hitl
# Telegram integration
# Integrations (Telegram, MS Teams) — imported lazily inside on_startup
# because IntegrationBotManager pulls aiogram (~1.5s); we only need it
# when the app starts serving traffic.
if TYPE_CHECKING:
    from parrot.integrations import IntegrationBotManager


class BotManager:
    """BotManager.

    Manage Bots/Agents and interact with them through via aiohttp App.
    Deploy and manage chatbots and agents using a RESTful API.

    """
    app: web.Application = None

    def __init__(
        self,
        enable_database_bots: bool = ENABLE_DATABASE_BOTS,
        enable_crews: bool = ENABLE_CREWS,
        enable_registry_bots: bool = ENABLE_REGISTRY_BOTS,
        enable_swagger_api: bool = ENABLE_SWAGGER,
    ) -> None:
        """Initialize BotManager.

        Args:
            enable_database_bots: When True, load bots from the database via
                ``_load_database_bots()``. Defaults to ``ENABLE_DATABASE_BOTS``
                (False unless overridden in config/env).
            enable_crews: When True, initialize ``CrewRedis`` and call
                ``load_crews()`` during startup. Defaults to ``ENABLE_CREWS``.
            enable_registry_bots: When True, run the full ``AgentRegistry``
                pipeline (load_modules, discover_config_agents,
                load_agent_definitions, instantiate_startup_agents). Defaults
                to ``ENABLE_REGISTRY_BOTS`` (True).
            enable_swagger_api: When True, register the OpenAPI/Swagger routes
                via ``setup_swagger()``. Defaults to ``ENABLE_SWAGGER``.
        """
        self.app = None
        self._bots: Dict[str, AbstractBot] = {}
        self._botdef: Dict[str, Type] = {}  # Store class definitions for each bot
        self._bot_expiration: Dict[str, float] = {}  # Track expiration timestamps for temporary bots
        self._cleanup_task: Optional[asyncio.Task] = None  # Background cleanup task
        self._cleaned_up: set[str] = set()  # Idempotency guard for _safe_cleanup
        self.logger = logging.getLogger(
            name='Parrot.Manager'
        )
        self.registry: AgentRegistry = agent_registry
        self._crews: Dict[str, Tuple[AgentCrew, CrewDefinition]] = {}
        # Store flags as instance attributes
        self.enable_database_bots: bool = enable_database_bots
        self.enable_crews: bool = enable_crews
        self.enable_registry_bots: bool = enable_registry_bots
        self.enable_swagger_api: bool = enable_swagger_api
        # Initialize Redis persistence for crews — keyed off instance attr
        self.crew_redis = CrewRedis() if self.enable_crews else None
        # Integration manager
        self._integration_manager: Optional["IntegrationBotManager"] = None
        # Shared Redis client published at app['redis'] during setup(). True
        # when BotManager created it (and must close it during on_cleanup);
        # False when another component had already set app['redis'] and
        # BotManager is merely consuming it.
        self._redis_owned: bool = False

    @staticmethod
    def _normalize_tenant(tenant: Optional[str]) -> str:
        return tenant or "global"

    def _get_crew_key(self, tenant: str, name: str) -> str:
        return f"{tenant}:{name}"

    def _split_crew_key(self, key: str) -> Tuple[str, str]:
        """
        Split a crew cache key into (tenant, name).

        Legacy or malformed keys may not contain a tenant prefix
        separated by ":", in which case we assume the global tenant
        and treat the whole key as the name.
        """
        if ":" not in key:
            # Handle legacy or malformed keys gracefully instead of raising ValueError
            self.logger.warning(
                "Malformed or legacy crew key without tenant prefix: %r. "
                "Assuming global tenant.",
                key,
            )
            return self._normalize_tenant(None), key

        tenant, name = key.split(":", 1)
        # Normalize empty or falsy tenant values to the default
        tenant = tenant or self._normalize_tenant(None)
        return tenant, name

    def get_bot_class(self, bot_name: str) -> Optional[Type]:
        """
        Get bot class by name, searching in:
        1. parrot.bots (core bots)
        2. parrot.agents (plugin agents)

        Args:
            bot_name: Name of the bot/agent class

        Returns:
            Bot class if found, None otherwise
        """
        if not bot_name:
            self.logger.warning(
                "Empty bot_name provided to get_bot_class, defaulting to 'BasicAgent'"
            )
            bot_name = "BasicAgent"

        # First, try to import from core bots
        with contextlib.suppress(ImportError, AttributeError):
            module = import_module("parrot.bots")
            if hasattr(module, bot_name):
                return getattr(module, bot_name)

        # Second, try to import from plugin agents
        with contextlib.suppress(ImportError, AttributeError):
            agent_module_name = f"parrot.agents.{bot_name.lower()}"
            module = import_module(agent_module_name)
            if hasattr(module, bot_name):
                return getattr(module, bot_name)

        # Third, try direct import from parrot.agents package
        # (in case the agent is defined in plugins/agents/__init__.py)
        with contextlib.suppress(ImportError, AttributeError):
            module = import_module("parrot.agents")
            if hasattr(module, bot_name):
                return getattr(module, bot_name)

        self.logger.warning(
            f"Warning: Bot class '{bot_name}' not found in parrot.bots or parrot.agents"
        )
        return None

    def _resolve_database_bot_class(self, bot_model: Any) -> Type[AbstractBot]:
        """Resolve a DB bot class, falling back to the DB model default."""
        bot_name = getattr(bot_model, "name", "<unnamed>")
        bot_class_name = getattr(bot_model, "bot_class", None)

        if not isinstance(bot_class_name, str) or not bot_class_name.strip():
            self.logger.warning(
                "Database bot %r has empty bot_class; using default %s.",
                bot_name,
                BasicBot.__name__,
            )
            return BasicBot

        bot_class_name = bot_class_name.strip()
        bot_class = self.get_bot_class(bot_class_name)
        if bot_class is None or not callable(bot_class):
            self.logger.error(
                "Database bot %r configured bot_class %r could not be resolved; "
                "using default %s.",
                bot_name,
                bot_class_name,
                BasicBot.__name__,
            )
            return BasicBot

        return bot_class

    def _normalize_database_bot_permissions(self, bot_model: Any) -> dict:
        """Return DB bot permissions in the canonical policy wrapper shape."""
        bot_name = getattr(bot_model, "name", "<unnamed>")
        permissions = getattr(bot_model, "permissions", None)

        if permissions is None:
            return {}
        if not isinstance(permissions, dict):
            self.logger.warning(
                "Bot %r has non-dict 'permissions' JSON (%s); ignoring it.",
                bot_name,
                type(permissions).__name__,
            )
            return {}
        if permissions and "permissions" not in permissions:
            self.logger.warning(
                "Bot %r has legacy 'permissions' JSON without canonical "
                "'permissions' key; ignoring keys %r.",
                bot_name,
                list(permissions.keys()),
            )
            return {}
        return permissions

    def get_or_create_bot(self, bot_name: str, **kwargs):
        """
        Get existing bot or create new one from class name.

        Args:
            bot_name: Name of the bot/agent class
            **kwargs: Arguments to pass to bot constructor

        Returns:
            Bot instance
        """
        # Check if already instantiated
        if bot_name in self._bots:
            return self._bots[bot_name]

        # Get the class and instantiate
        bot_class = self.get_bot_class(bot_name)
        if bot_class is None:
            raise ValueError(f"Bot class '{bot_name}' not found")

        return self.create_bot(class_name=bot_class, name=bot_name, **kwargs)

    def _log_final_state(self) -> None:
        """Log the final state of bot loading."""
        registry_info = self.registry.get_registration_info()
        self.logger.notice("=== Bot Loading Complete ===")
        self.logger.notice("Registered agents: %s", registry_info['total_registered'])
        # self.logger.info("Startup agents: %s", startup_info['total_startup_agents'])
        self.logger.notice("Active bots: %s", len(self._bots))

    async def _process_startup_results(self, startup_results: Dict[str, Any]) -> None:
        """Process startup instantiation results."""
        for agent_name, result in startup_results.items():
            self.logger.debug(
                "Agent startup result: %s -> %s", agent_name, result
            )
            if result["status"] == "success":
                if instance := result.get("instance"):
                    self._bots[agent_name] = instance
                    self.logger.info(
                        f"Added startup agent to active bots: {agent_name}"
                    )
            else:
                self.logger.error(
                    f"Startup agent {agent_name} failed: {result['error']}"
                )

    async def load_bots(self, app: web.Application) -> None:
        """Load and register all bots using the registry and optional database.

        Args:
            app: The aiohttp Application instance passed during startup.
        """
        self.logger.info("Starting bot loading with global registry")

        if self.enable_registry_bots:
            # Step 0: Wire app reference into registry for PBAC policy registration
            # Must be called BEFORE load_modules() so that decorator-registered
            # agents can register policies during import.
            self.registry.setup(app)

            # Step 1: Import modules to trigger decorator registration
            await self.registry.load_modules()

            # Step 2: Register config-based agents
            config_count = self.registry.discover_config_agents()
            self.logger.info(
                f"Registered {config_count} agents from config"
            )

            # Step 2b: Load YAML agent definitions from agents/agents/
            definitions_dir = self.registry.agents_dir / "agents"
            if definitions_dir.is_dir():
                def_count = self.registry.load_agent_definitions(definitions_dir)
                self.logger.info(
                    f"Loaded {def_count} agents from YAML definitions"
                )

            # Step 3: Instantiate startup agents
            startup_results = await self.registry.instantiate_startup_agents(app)
            await self._process_startup_results(startup_results)
        else:
            self.logger.info(
                "AgentRegistry loading skipped (enable_registry_bots=False)"
            )

        # Step 4: Load database bots
        if self.enable_database_bots:
            await self._load_database_bots(app)
        else:
            self.logger.debug(
                "Database bot loading skipped (enable_database_bots=False)"
            )

        # Step 5: Report final state
        self._log_final_state()

    async def _load_database_bots(self, app: web.Application) -> None:
        """Load bots from database."""
        try:
            # Import here to avoid circular imports
            from ..handlers.models import BotModel  # pylint: disable=import-outside-toplevel # noqa
            db = app['database']
            async with await db.acquire() as conn:
                BotModel.Meta.connection = conn
                try:
                    all_bots = await BotModel.filter(enabled=True)
                except Exception as e:
                    self.logger.error(
                        f"Failed to load bots from DB: {e}"
                    )
                    return

            for bot_model in all_bots:
                self.logger.notice(
                    f"Loading bot '{bot_model.name}' (mode: {bot_model.operation_mode})..."
                )
                if bot_model.name in self._bots:
                    self.logger.debug(
                        f"Bot {bot_model.name} already active, skipping"
                    )
                    continue
                try:
                    # Use the factory function from models.py or create bot directly
                    class_name = self._resolve_database_bot_class(bot_model)
                    bot_permissions = self._normalize_database_bot_permissions(bot_model)

                    # FEAT-133 Step 1: Build reranker BEFORE bot construction.
                    # Reranker has no dependency on the store — can be resolved now.
                    try:
                        reranker = create_reranker(
                            bot_model.reranker_config,
                            bot_llm_client=None,  # patched post-construction if type=llm
                        )
                    except ConfigError as exc:
                        self.logger.error(
                            "Bot '%s': invalid reranker_config: %s",
                            bot_model.name,
                            exc,
                        )
                        raise

                    # Prompt preset: optional, declared in ai_bots.prompt_config.
                    # Mutations (remove/add/customize) are applied post-init,
                    # before configure(), to mirror the YAML registry flow.
                    prompt_config_dict = bot_model.prompt_config or {}
                    has_prompt_mutations = any(
                        prompt_config_dict.get(key)
                        for key in ("remove", "add", "customize")
                    )
                    prompt_preset_name = (
                        prompt_config_dict.get("preset")
                        or ("default" if has_prompt_mutations else None)
                    )

                    bot_instance = class_name(
                        chatbot_id=bot_model.chatbot_id,
                        name=bot_model.name,
                        description=bot_model.description,
                        prompt_preset=prompt_preset_name,
                        # LLM configuration: ``model_config`` (JSONB) is the
                        # canonical source for model/temperature/max_tokens/
                        # top_k/top_p. AbstractBot resolves them from there.
                        use_llm=bot_model.llm,
                        model_config=bot_model.model_config,
                        # Bot personality
                        role=bot_model.role,
                        goal=bot_model.goal,
                        backstory=bot_model.backstory,
                        rationale=bot_model.rationale,
                        capabilities=bot_model.capabilities,
                        # Prompt configuration
                        system_prompt=bot_model.system_prompt_template,
                        human_prompt=bot_model.human_prompt_template,
                        pre_instructions=bot_model.pre_instructions,
                        # Vector store configuration — embedding model is
                        # carried inside ``vector_store_config['embedding_model']``.
                        use_vectorstore=bot_model.use_vector,
                        vector_store_config=bot_model.vector_store_config,
                        context_search_limit=bot_model.context_search_limit,
                        context_score_threshold=bot_model.context_score_threshold,
                        # Tool and agent configuration
                        tools_enabled=bot_model.tools_enabled,
                        auto_tool_detection=bot_model.auto_tool_detection,
                        tool_threshold=bot_model.tool_threshold,
                        available_tools=bot_model.tools,
                        operation_mode=bot_model.operation_mode,
                        # Memory configuration
                        memory_type=bot_model.memory_type,
                        memory_config=bot_model.memory_config,
                        max_context_turns=bot_model.max_context_turns,
                        use_conversation_history=bot_model.use_conversation_history,
                        # Security and permissions
                        permissions=bot_permissions,
                        # Metadata
                        language=bot_model.language,
                        disclaimer=bot_model.disclaimer,
                        # FEAT-133: reranker + expand_to_parent injected at construction.
                        # parent_searcher injected AFTER configure() (needs bot.store).
                        reranker=reranker,
                        expand_to_parent=bool(
                            bot_model.parent_searcher_config.get("expand_to_parent", False)
                        ),
                    )
                    # Set the model ID reference
                    bot_instance.model_id = bot_model.chatbot_id

                    # Apply prompt-layer mutations BEFORE configure() so
                    # newly-added layers also resolve their CONFIGURE-phase
                    # variables in the same pass.
                    self._apply_prompt_config(bot_instance, prompt_config_dict)

                    await bot_instance.configure(app)

                    # FEAT-133 Step 2: Patch LLM reranker client now that
                    # bot.llm_client is available (option a from spec §3 Module 5).
                    from ..rerankers.llm import LLMReranker  # noqa: PLC0415
                    if isinstance(reranker, LLMReranker) and reranker.client is None:
                        reranker.client = getattr(bot_instance, 'llm_client', None)

                    # FEAT-133 Step 3: Build parent_searcher AFTER configure()
                    # because InTableParentSearcher requires bot.store.
                    try:
                        parent_searcher = create_parent_searcher(
                            bot_model.parent_searcher_config,
                            store=bot_instance.store,
                        )
                    except ConfigError as exc:
                        self.logger.error(
                            "Bot '%s': invalid parent_searcher_config: %s",
                            bot_model.name,
                            exc,
                        )
                        raise

                    if parent_searcher is not None:
                        bot_instance.parent_searcher = parent_searcher

                    # FEAT-133: Operational visibility log.
                    self.logger.info(
                        "Bot '%s': reranker=%s, parent_searcher=%s",
                        bot_model.name,
                        type(reranker).__name__ if reranker else None,
                        type(parent_searcher).__name__ if parent_searcher else None,
                    )

                    # FEAT-153: Register DB-declared permissions into the evaluator
                    # BEFORE adding the bot so a concurrent get_bot cannot resolve
                    # the bot before its policies are loaded.
                    try:
                        n_policies = self.registry.register_db_bot_policies(
                            bot_model.name,
                            bot_permissions,
                        )
                        if n_policies:
                            self.logger.info(
                                "Bot %r: registered %d DB-declared policy rule(s).",
                                bot_model.name, n_policies,
                            )
                    except ValueError as exc:
                        self.logger.warning(
                            "Bot %r has malformed 'permissions' JSON: %s. "
                            "Skipping this bot.",
                            bot_model.name, exc,
                        )
                        continue  # skip — do NOT add to self._bots

                    self.add_bot(bot_instance)
                    self.logger.info(
                        f"Successfully loaded bot '{bot_model.name}' "
                        f"with {len(bot_model.tools) if bot_model.tools else 0} tools"
                    )
                except ConfigError:
                    # ConfigError already logged above — re-raise so the bot is
                    # NOT silently registered without its configured features.
                    raise
                except ValidationError as e:
                    self.logger.error(
                        f"Invalid configuration for bot '{bot_model.name}': {e}"
                    )
                except Exception as e:
                    self.logger.error(
                        "Failed to load database bot %s: %s",
                        bot_model.name,
                        e,
                        exc_info=True,
                    )
            self.logger.info(
                f":: Bots loaded successfully. Total active bots: {len(self._bots)}"
            )
        except Exception as e:
            self.logger.error(
                f"Database bot loading failed: {str(e)}"
            )

    @staticmethod
    def _apply_prompt_config(bot: AbstractBot, prompt_config: dict) -> None:
        """Apply remove/add/customize mutations to ``bot._prompt_builder``.

        The builder itself is constructed by ``AbstractBot.__init__`` from the
        ``prompt_preset`` kwarg, so this helper only handles the post-init
        mutations. Mirrors the YAML path in
        ``parrot.registry.BotRegistry._apply_prompt_config`` for the
        DB-loaded-bots flow.

        Args:
            bot: The bot instance whose ``_prompt_builder`` is mutated in place.
            prompt_config: Dict with keys ``remove``, ``add``, ``customize``
                (``preset`` is consumed at construction time, not here).

        No-op if ``prompt_config`` is empty or the bot has no
        ``_prompt_builder``.
        """
        if not prompt_config:
            return
        builder = getattr(bot, "_prompt_builder", None)
        has_prompt_mutations = any(
            prompt_config.get(key)
            for key in ("remove", "add", "customize")
        )
        if builder is None and has_prompt_mutations:
            from ..bots.prompts.presets import get_preset
            builder = get_preset(prompt_config.get("preset") or "default")
            bot._prompt_builder = builder
        if builder is None:
            return

        from ..bots.prompts.layers import PromptLayer, LayerPriority, RenderPhase
        from ..bots.prompts.domain_layers import get_domain_layer

        for layer_name in prompt_config.get("remove", []):
            builder.remove(layer_name)

        for item in prompt_config.get("add", []):
            if isinstance(item, str):
                builder.add(get_domain_layer(item))
            elif isinstance(item, dict):
                phase_str = item.get("phase", "configure")
                phase = (
                    RenderPhase.CONFIGURE
                    if phase_str == "configure"
                    else RenderPhase.REQUEST
                )
                builder.add(
                    PromptLayer(
                        name=item["name"],
                        priority=item.get("priority", LayerPriority.CUSTOM),
                        phase=phase,
                        template=item.get("template", ""),
                    )
                )

        for layer_name, overrides in prompt_config.get("customize", {}).items():
            existing = builder.get(layer_name)
            if existing is None:
                continue
            builder.replace(
                layer_name,
                PromptLayer(
                    name=existing.name,
                    priority=existing.priority,
                    phase=existing.phase,
                    template=overrides.get("template", existing.template),
                    condition=existing.condition,
                    required_vars=existing.required_vars,
                ),
            )

    def create_bot(self, class_name: Any = None, name: str = None, **kwargs) -> AbstractBot:
        """Create a Bot and add it to the manager."""
        if class_name is None:
            class_name = Chatbot
        chatbot = class_name(**kwargs)
        chatbot.name = name
        return chatbot

    def add_bot(self, bot: AbstractBot) -> None:
        """Add a Bot to the manager."""
        self._bots[bot.name] = bot
        # Store the class definition for future instance creation
        self._botdef[bot.name] = bot.__class__

    async def get_bot(
        self,
        name: str,
        new: bool = False,
        session_id: str = "",
        request: Optional[web.Request] = None,
        **kwargs
    ) -> AbstractBot:
        """Get a Bot by name.

        Args:
            name: Name of the bot to get.
            new: If True, create a new instance instead of returning existing one.
            session_id: Session identifier for creating unique temporary instances.
            request: Optional aiohttp request.  When provided, the caller's subject
                is checked against any PBAC policies registered for this bot via
                FEAT-153 ``enforce_agent_access``.  ``None`` means programmatic
                invocation — no PBAC check is performed (HTTP-scoped enforcement).
            **kwargs: Additional arguments to pass to bot constructor when new=True.

        Returns:
            Bot instance (existing or newly created).

        Raises:
            AgentAccessDenied: When ``request`` is provided and the caller's
                subject does not match the bot's PBAC policies.
        """
        # Handle new instance creation
        if new:
            # FEAT-153: Enforce PBAC on the base name BEFORE constructing the new
            # instance.  Checking after construction causes a resource leak: the bot
            # ends up registered in self._bots for up to 1 hour even though the
            # caller was denied access.  AgentAccessDenied propagates to the caller.
            await enforce_agent_access(self.registry.evaluator, name, request)

            # Get the class definition for this bot
            cls = self._botdef.get(name, BasicAgent)

            # Create unique name to avoid duplicates
            new_name = f"{name}_{session_id}" if session_id else f"{name}_{int(time.time())}"

            # Prepare configuration to inherit from base bot
            base_bot = self._bots.get(name)
            bot_kwargs = kwargs.copy()

            if base_bot:
                # 1. Inherit LLM Configuration if not explicitly provided
                if 'use_llm' not in bot_kwargs and hasattr(base_bot, '_llm_raw'):
                    bot_kwargs['use_llm'] = base_bot._llm_raw

                if 'model' not in bot_kwargs and hasattr(base_bot, '_llm_model'):
                    bot_kwargs['model'] = base_bot._llm_model

                # 2. Clone Tools
                if 'tools' not in bot_kwargs and hasattr(base_bot, 'tool_manager'):
                    try:
                        # Deep copy tools to ensure isolation
                        base_tools = base_bot.tool_manager.get_all_tools()
                        new_tools = []
                        for tool in base_tools:
                            try:
                                # Attempt deep copy
                                new_tool = copy.deepcopy(tool)
                                new_tools.append(new_tool)
                            except Exception as e:
                                self.logger.warning(
                                    f"Failed to copy tool {tool.name}, sharing instance. Error: {e}"
                                )
                                # Fallback to shared instance
                                new_tools.append(tool)
                        bot_kwargs['tools'] = new_tools
                    except Exception as e:
                        self.logger.error("Error cloning tools from %s: %s", name, e)

                # 3. Clone Vector Store Configuration
                if 'vector_store_config' not in bot_kwargs and hasattr(base_bot, '_vector_store'):
                    try:
                        if base_bot._vector_store:
                            bot_kwargs['vector_store_config'] = copy.deepcopy(base_bot._vector_store)
                    except Exception as e:
                        self.logger.warning("Failed to copy vector store config: %s", e)
                        bot_kwargs['vector_store_config'] = base_bot._vector_store

                if 'use_vectorstore' not in bot_kwargs and hasattr(base_bot, '_use_vector'):
                    bot_kwargs['use_vectorstore'] = getattr(base_bot, '_use_vector', False)

            # Create new instance with merged configuration
            bot = cls(name=new_name, **bot_kwargs)

            # Configure the bot
            await bot.configure(self.app)

            # Add to bots dictionary
            self._bots[new_name] = bot

            # Set expiration time (1 hour from now)
            self._bot_expiration[new_name] = time.time() + 3600

            self.logger.info(
                f"Created new temporary bot instance '{new_name}' from '{name}' "
                f"(expires in 1 hour)"
            )

            return bot

        # Existing behavior for getting/creating bots
        if name not in self._bots:
            self.logger.warning(
                f"Bot '{name}' not in _bots. Available: {list(self._bots.keys())}"
            )
        if name in self._bots:
            _bot = self._bots[name]
            if not getattr(_bot, 'is_configured', False):
                self.logger.warning("Bot '%s' found in _bots and is not configured.", name)
                await _bot.configure(self.app)
            # FEAT-153: Enforce PBAC before returning. AgentAccessDenied propagates.
            await enforce_agent_access(self.registry.evaluator, name, request)
            return self._bots[name]
        if self.registry.has(name):
            bot_instance = None
            try:
                # Get instance (returns singleton if at_startup=True)
                bot_instance = await self.registry.get_instance(name)
                if bot_instance:
                    # Only configure if NOT already configured
                    if not getattr(bot_instance, 'is_configured', False):
                        self.logger.info("Configuring bot %s on demand.", name)
                        await bot_instance.configure(self.app)
                    self.add_bot(bot_instance)
            except Exception as e:
                self.logger.error(
                    f"Failed to get bot instance from registry: {e}"
                )
            if bot_instance:
                # FEAT-153: Enforce PBAC OUTSIDE the try/except above so that
                # AgentAccessDenied is NOT swallowed as "Failed to get bot instance".
                await enforce_agent_access(self.registry.evaluator, name, request)
                return bot_instance
        return None

    def remove_bot(self, name: str) -> None:
        """Remove a Bot by name."""
        del self._bots[name]
        # Clean up expiration tracking if it exists (but keep class definition)
        self._bot_expiration.pop(name, None)

    # ------------------------------------------------------------------
    # User-defined bots (per-user, session-cached)
    # ------------------------------------------------------------------

    USER_BOTS_SESSION_KEY = "_user_bots"

    async def _fetch_user_bot_model(
        self,
        user_id: int,
        chatbot_id: str,
    ) -> Optional[UserBotModel]:
        """Load a single ``UserBotModel`` row scoped to ``(user_id, chatbot_id)``."""
        db = self.app["database"]
        async with await db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            try:
                return await UserBotModel.get(
                    user_id=user_id, chatbot_id=chatbot_id
                )
            except NoDataFound:
                return None

    async def _build_user_bot_instance(
        self,
        bot_model: UserBotModel,
    ) -> AbstractBot:
        """Instantiate and ``configure()`` a bot from a ``UserBotModel`` row."""
        kwargs = bot_model.to_bot_kwargs()
        # User bots always use BasicBot — they don't carry a bot_class column.
        bot = BasicBot(**kwargs)
        bot.model_id = bot_model.chatbot_id
        # Apply prompt-layer mutations declared in prompt_config (mirrors system bots).
        prompt_config_dict = bot_model.prompt_config or {}
        with contextlib.suppress(Exception):
            self._apply_prompt_config(bot, prompt_config_dict)
        await bot.configure(self.app)
        return bot

    async def get_user_bot(
        self,
        request: web.Request,
        chatbot_id: Any,
    ) -> Optional[AbstractBot]:
        """Resolve a user-defined bot via session cache → DB load → instantiate.

        Order of resolution:
          1. Look in ``request.session[USER_BOTS_SESSION_KEY][chatbot_id]``.
          2. On miss, query ``navigator.users_bots`` constrained by
             ``(user_id, chatbot_id)`` from the authenticated session.
          3. Build the bot instance, cache it on the session, return it.

        Returns ``None`` when the user is not authenticated or no row matches.
        """
        try:
            from navigator_session import get_session  # noqa: PLC0415
        except ImportError:
            return None

        try:
            session = request.session or await get_session(request)
        except AttributeError:
            session = await get_session(request)
        if session is None:
            return None
        user_id = session.get("user_id")
        if not user_id:
            return None

        cache = session.setdefault(self.USER_BOTS_SESSION_KEY, {})
        cid = str(chatbot_id)
        cached = cache.get(cid)
        if cached is not None:
            return cached

        bot_model = await self._fetch_user_bot_model(user_id, cid)
        if bot_model is None:
            return None
        try:
            bot = await self._build_user_bot_instance(bot_model)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Failed to build user bot %s for user %s: %s",
                cid,
                user_id,
                exc,
                exc_info=True,
            )
            return None
        cache[cid] = bot
        return bot

    @classmethod
    def invalidate_user_bot(cls, session: Any, chatbot_id: Any) -> None:
        """Drop a user-bot from the session cache (used after PATCH/DELETE)."""
        if session is None:
            return
        cache = session.get(cls.USER_BOTS_SESSION_KEY)
        if not cache:
            return
        cache.pop(str(chatbot_id), None)

    def get_bots(self) -> Dict[str, AbstractBot]:
        """Get all Bots declared on Manager."""
        return self._bots

    async def create_agent(self, class_name: Any = None, name: str = None, **kwargs) -> AbstractBot:
        if class_name is None:
            class_name = BasicAgent
        return class_name(name=name, **kwargs)

    def add_agent(self, agent: AbstractBot) -> None:
        """Add a Agent to the manager."""
        self._bots[str(agent.chatbot_id)] = agent

    def remove_agent(self, agent: AbstractBot) -> None:
        """Remove a Bot by name."""
        del self._bots[str(agent.chatbot_id)]

    # ------------------------------------------------------------------
    # Ephemeral user-bot lifecycle (FEAT-149)
    # ------------------------------------------------------------------

    @property
    def _ephemeral_registry(self):
        """Lazy-initialised EphemeralRegistry singleton on this manager instance."""
        try:
            return self.__ephemeral_registry  # type: ignore[attr-defined]
        except AttributeError:
            from ..manager.ephemeral import EphemeralRegistry  # noqa: PLC0415
            self.__ephemeral_registry = EphemeralRegistry()
            return self.__ephemeral_registry

    async def create_ephemeral_user_bot(
        self,
        user_id: Optional[int] = None,
        config: Optional[Dict[str, Any]] = None,
        uploaded_paths: Optional[List[dict]] = None,
        *,
        owner_id: Optional[str] = None,
        owner_kind: str = "user",
        ttl_seconds: int = 86400,
    ):
        """Create an ephemeral (in-memory-only) user bot and schedule warm-up.

        No row is written to ``navigator.users_bots``. The bot lives only in
        ``self._bots`` until it is either promoted (``promote_user_bot``) or
        discarded (``discard_ephemeral_user_bot`` / TTL expiry).

        Accepts typed ownership: pass either the legacy ``user_id: int`` (for
        human-owned bots, backward compat) or ``owner_id: str`` +
        ``owner_kind`` (for agent-owned sub-bots — FEAT-208).

        Args:
            user_id: Owning human user ID (legacy path; HTTP handler uses this).
            config: Dict matching the UserBotModel field names (plain values;
                ``mcp_config_plain`` / ``tools_config_plain`` are the raw lists).
            uploaded_paths: List of document dicts from ``_ingest_uploads``
                (``[{name, path, url, size, ...}]``).
            owner_id: Canonical owner string ID (new path — FEAT-208). Use for
                agent-owned sub-bots (e.g. ``"agent:parent-123"``).
            owner_kind: ``"user"`` (default) or ``"agent"``.  Ignored when
                ``user_id`` is provided (normalised automatically).
            ttl_seconds: Seconds until this ephemeral bot expires.  Defaults to
                86400 (24 h).

        Returns:
            EphemeralAgentStatus with ``phase="creating"`` and the new
            ``chatbot_id``.

        Raises:
            ValueError: On invalid config, missing owner, or instantiation failure.
        """
        import uuid as _uuid  # noqa: PLC0415
        from datetime import datetime, timedelta  # noqa: PLC0415
        from ..manager.ephemeral import EphemeralAgentStatus, _warm_up  # noqa: PLC0415

        # --- Normalize ownership -------------------------------------------------
        # Legacy path: user_id provided → convert to owner_id/owner_kind.
        if owner_id is None and user_id is not None:
            owner_id = str(user_id)
            owner_kind = "user"
        elif owner_id is None:
            raise ValueError(
                "create_ephemeral_user_bot: either 'user_id' or 'owner_id' is required."
            )

        config = config or {}
        uploaded_paths = uploaded_paths or []

        # For UserBotModel (requires user_id: int for field validation):
        # Use int(owner_id) for user-owned bots; use 0 as a placeholder for
        # agent-owned ephemeral bots (never written to DB).
        if owner_kind == "user":
            try:
                model_user_id = int(owner_id)
            except (ValueError, TypeError):
                model_user_id = 0
        else:
            model_user_id = 0  # placeholder; agent-owned bots are never persisted

        # Build UserBotModel in memory — no DB write.
        chatbot_id = _uuid.uuid4()
        try:
            plain = {k: v for k, v in config.items()
                     if k not in ("mcp_config", "tools_config",
                                  "mcp_config_plain", "tools_config_plain")}
            model = UserBotModel(
                chatbot_id=chatbot_id,
                user_id=model_user_id,
                documents=list(uploaded_paths),
                **plain,
            )
            mcp_cfg = config.get("mcp_config_plain") or config.get("mcp_config")
            tools_cfg = config.get("tools_config_plain") or config.get("tools_config")
            if mcp_cfg is not None:
                model.set_mcp_config(mcp_cfg)
            if tools_cfg is not None:
                model.set_tools_config(tools_cfg)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "create_ephemeral_user_bot: failed to build UserBotModel "
                "for owner %s: %s",
                owner_id, exc, exc_info=True,
            )
            raise ValueError(f"Invalid ephemeral bot configuration: {exc}") from exc

        # Instantiate bot (without configure — warm-up handles that).
        try:
            kwargs = model.to_bot_kwargs()
            bot = BasicBot(**kwargs)
            bot.model_id = model.chatbot_id
            prompt_config_dict = model.prompt_config or {}
            with contextlib.suppress(Exception):
                self._apply_prompt_config(bot, prompt_config_dict)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "create_ephemeral_user_bot: failed to instantiate bot for "
                "owner %s: %s",
                owner_id, exc, exc_info=True,
            )
            raise ValueError(f"Could not instantiate ephemeral bot: {exc}") from exc

        # Register in BotManager._bots (keyed by chatbot_id string).
        self.add_agent(bot)

        # Create EphemeralAgentStatus with rag_mode derived from vector_config.
        # FIX-13: replace deprecated datetime.utcnow()
        from datetime import timezone as _tz  # noqa: PLC0415
        now = datetime.now(_tz.utc).replace(tzinfo=None)
        rag_mode = None
        vector_config = config.get("vector_config") or {}
        if isinstance(vector_config, dict):
            rag_mode = vector_config.get("rag_mode")

        status = EphemeralAgentStatus(
            chatbot_id=str(chatbot_id),
            owner_id=owner_id,
            owner_kind=owner_kind,
            phase="creating",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            rag_mode=rag_mode,
        )
        await self._ephemeral_registry.register(status)  # FIX-1: async register

        # Fire-and-forget warm-up (completes async in background).
        if self.app is not None:
            # FIX-12: pass remove_bot_callback so _warm_up can clean up on failure
            asyncio.create_task(_warm_up(
                bot, status, self.app,
                remove_bot_callback=lambda cid: self._bots.pop(cid, None),
            ))
        else:
            # No app context yet (test / standalone scenario) — mark ready immediately.
            status.phase = "ready"

        self.logger.info(
            "create_ephemeral_user_bot: created ephemeral bot %s for owner %s (kind=%s)",
            chatbot_id,
            owner_id,
            owner_kind,
        )
        return status

    async def save_user_bot(
        self,
        model: "UserBotModel",
    ) -> "UserBotModel":
        """INSERT a ``UserBotModel`` row into ``navigator.users_bots``.

        This is the user-bot analogue of :meth:`save_agent`, which writes
        ``navigator.ai_bots`` via ``BotModel``.  Do NOT use ``save_agent``
        for user bots — the tables are different.

        Used by :meth:`promote_user_bot` and reusable for any flow that needs
        to persist a ``UserBotModel`` from within BotManager.

        Args:
            model: A fully-populated ``UserBotModel`` instance (encrypted blobs
                already set via ``set_mcp_config`` / ``set_tools_config``).

        Returns:
            The same ``model`` after it has been persisted to DB.

        Raises:
            RuntimeError: If ``self.app`` is not set (no DB available).
        """
        if self.app is None:
            raise RuntimeError(
                "save_user_bot: BotManager has no app context (DB unavailable)."
            )
        db = self.app["database"]
        async with await db.acquire() as conn:
            UserBotModel.Meta.connection = conn
            await model.insert()
        self.logger.info(
            "save_user_bot: inserted UserBotModel chatbot_id=%s for user %s",
            model.chatbot_id,
            model.user_id,
        )
        return model

    async def promote_user_bot(
        self,
        chatbot_id: str,
        user_id: int,
    ) -> "UserBotModel":
        """Promote an ephemeral bot to a persisted ``navigator.users_bots`` row.

        Verifies the bot is in ``phase="ready"``, writes the DB row via
        :meth:`save_user_bot`, removes the ephemeral registry entry, and
        optionally dumps the FAISS index to S3 if ``rag_mode == "vector"``.

        Args:
            chatbot_id: Canonical UUID string of the bot to promote.
            user_id: Owning user ID (ownership check).

        Returns:
            The persisted ``UserBotModel``.

        Raises:
            ValueError: If the bot is not found, not owned by ``user_id``,
                already promoted, or not in ``phase="ready"``.
        """
        import uuid as _uuid  # noqa: PLC0415

        status = self._ephemeral_registry.get(chatbot_id, user_id)
        if status is None:
            raise ValueError(
                f"promote_user_bot: no ephemeral bot {chatbot_id!r} for user {user_id} "
                "(already promoted or never created)."
            )
        if status.phase != "ready":
            raise ValueError(
                f"promote_user_bot: bot {chatbot_id!r} is in phase={status.phase!r}, "
                "must be 'ready' to promote (409)."
            )

        # Fetch the in-memory bot instance.
        bot = self._bots.get(chatbot_id)
        if bot is None:
            raise ValueError(
                f"promote_user_bot: bot {chatbot_id!r} not found in active bots."
            )

        # Build the UserBotModel from the bot's state for DB persistence.
        # FIX-10: dynamically derive the field set from UserBotModel.model_fields
        # rather than maintaining a hardcoded list.
        try:
            _model_fields = set(UserBotModel.model_fields.keys()) - {
                "chatbot_id", "user_id", "created_at", "updated_at",
                "mcp_config", "tools_config",  # handled separately below
            }
            field_values = {}
            for field_name in _model_fields:
                val = getattr(bot, field_name, None)
                if val is not None:
                    field_values[field_name] = val
            model = UserBotModel(
                chatbot_id=_uuid.UUID(chatbot_id),
                user_id=user_id,
                **field_values,
            )
            # Preserve encrypted blobs from the bot instance.
            if getattr(bot, "mcp_config", None) is not None:
                model.mcp_config = bot.mcp_config  # already encrypted
            if getattr(bot, "tools_config", None) is not None:
                model.tools_config = bot.tools_config  # already encrypted

            # If vector mode: dump FAISS to S3 and store path.
            faiss_store = getattr(bot, "_ephemeral_faiss_store", None)
            if faiss_store is not None and status.rag_mode == "vector":
                try:
                    from ...tools.filemanager import FileManagerToolkit  # noqa: PLC0415
                    import os as _os  # noqa: PLC0415
                    bucket = _os.environ.get("S3_BUCKET") or _os.environ.get("AWS_S3_BUCKET")
                    if bucket:
                        fm = FileManagerToolkit(manager_type="s3", bucket=bucket)
                    else:
                        fm = FileManagerToolkit(manager_type="fs")
                    s3_path = await faiss_store.dump_to_s3(chatbot_id, fm)
                    vc = dict(model.vector_config or {})
                    vc["faiss_persist_path"] = s3_path
                    model.vector_config = vc
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "promote_user_bot: FAISS dump failed for %s: %s",
                        chatbot_id, exc,
                    )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                f"promote_user_bot: failed to build UserBotModel for {chatbot_id!r}: {exc}"
            ) from exc

        # Persist to DB via save_user_bot.
        await self.save_user_bot(model)

        # Remove from ephemeral registry (bot remains accessible in _bots via normal path).
        await self._ephemeral_registry.remove(chatbot_id)  # FIX-1: async remove

        self.logger.info(
            "promote_user_bot: promoted ephemeral bot %s for user %s",
            chatbot_id,
            user_id,
        )
        return model

    def get_ephemeral_status(
        self,
        chatbot_id: str,
        user_id: Optional[int] = None,
        *,
        owner_id: Optional[str] = None,
    ):
        """Return the ``EphemeralAgentStatus`` for *chatbot_id* owned by the given owner.

        Accepts either the legacy ``user_id: int`` (backward compat) or the new
        ``owner_id: str`` keyword argument (FEAT-208 agent-owner path).

        Args:
            chatbot_id: Canonical UUID string.
            user_id: Owning human user ID (legacy positional path).
            owner_id: Canonical owner string ID (new keyword path).

        Returns:
            The ``EphemeralAgentStatus`` or ``None`` if not found / wrong owner.

        Raises:
            ValueError: If neither ``user_id`` nor ``owner_id`` is provided.
        """
        if owner_id is None and user_id is not None:
            owner_id = str(user_id)
        elif owner_id is None:
            raise ValueError(
                "get_ephemeral_status: either 'user_id' or 'owner_id' is required."
            )
        return self._ephemeral_registry.get(chatbot_id, owner_id=owner_id)

    async def discard_ephemeral_user_bot(
        self,
        chatbot_id: str,
        user_id: Optional[int] = None,
        *,
        owner_id: Optional[str] = None,
    ) -> bool:
        """Remove an ephemeral bot from memory and clean up its resources.

        Accepts either the legacy ``user_id: int`` (backward compat) or the new
        ``owner_id: str`` keyword argument (FEAT-208 agent-owner path).

        Args:
            chatbot_id: Canonical UUID string.
            user_id: Owning human user ID (legacy positional path; ownership check).
            owner_id: Canonical owner string ID (new keyword path; ownership check).

        Returns:
            ``True`` if the bot was found and removed, ``False`` otherwise.

        Raises:
            ValueError: If neither ``user_id`` nor ``owner_id`` is provided.
        """
        if owner_id is None and user_id is not None:
            owner_id = str(user_id)
        elif owner_id is None:
            raise ValueError(
                "discard_ephemeral_user_bot: either 'user_id' or 'owner_id' is required."
            )
        status = self._ephemeral_registry.get(chatbot_id, owner_id=owner_id)
        if status is None:
            return False
        await self._ephemeral_registry.remove(chatbot_id)  # FIX-1: async remove
        self._bots.pop(chatbot_id, None)
        self.logger.info(
            "discard_ephemeral_user_bot: discarded %s for owner %s",
            chatbot_id,
            owner_id,
        )
        return True

    async def save_agent(self, name: str, **kwargs) -> None:
        """Save a Agent to the DB."""
        self.logger.info("Saving Agent %s into DB ...", name)
        db = self.app['database']
        async with await db.acquire() as conn:
            BotModel.Meta.connection = conn
            try:
                try:
                    bot = await BotModel.get(name=name)
                except NoDataFound:
                    bot = None
                if bot:
                    self.logger.info("Bot %s already exists.", name)
                    for key, val in kwargs.items():
                        bot.set(key, val)
                    await bot.update()
                    self.logger.info("Bot %s updated.", name)
                else:
                    self.logger.info("Bot %s not found. Creating new one.", name)
                    # Create a new Bot
                    new_bot = BotModel(
                        name=name,
                        **kwargs
                    )
                    await new_bot.insert()
                self.logger.info("Bot %s saved into DB.", name)
                return True
            except Exception as e:
                self.logger.error(
                    f"Failed to Create new Bot {name} from DB: {e}"
                )
                return None

    def get_app(self) -> web.Application:
        """Get the app."""
        if self.app is None:
            raise RuntimeError("App is not set.")
        return self.app

    def _register_shared_redis(self) -> None:
        """Publish a shared ``app['redis']`` client, idempotently.

        Called from :meth:`setup`. If ``app['redis']`` is already populated
        (tests, custom bootstraps, explicit user wiring), keep it untouched
        and mark BotManager as not owning it. Otherwise, build a lazy
        ``redis.asyncio`` client from :data:`parrot.conf.REDIS_URL` and
        register an ``on_cleanup`` hook that closes it on shutdown.

        ``redis.asyncio.from_url`` does not open a connection until the
        first command is issued, so the call is safe in a synchronous
        setup path.
        """
        existing = self.app.get('redis')
        if existing is not None:
            self._redis_owned = False
            self.logger.info(
                "BotManager: app['redis'] already set by another "
                "component — reusing it (owned=False)."
            )
            return

        import redis.asyncio as aioredis
        self.app['redis'] = aioredis.from_url(
            REDIS_URL, decode_responses=True,
        )
        self._redis_owned = True
        self.app.on_cleanup.append(self._cleanup_shared_redis)
        self.logger.info(
            "BotManager: registered shared Redis client at "
            "app['redis'] (owned=True, url=%s).",
            REDIS_URL,
        )

    async def _cleanup_all_bots(self, app: web.Application) -> None:
        """aiohttp on_cleanup callback: clean every registered bot concurrently.

        Iterates ``self._bots`` and awaits each bot's ``cleanup()`` via
        :meth:`_safe_cleanup`, which enforces :data:`~parrot.conf.BOT_CLEANUP_TIMEOUT`
        and isolates failures so one misbehaving bot cannot block the rest.
        Logs a summary line at INFO level when done.
        """
        if not self._bots:
            self.logger.debug("BotManager: no bots to clean up")
            return

        self.logger.info(
            "BotManager: cleaning up %d bot(s) (timeout=%ds)",
            len(self._bots),
            BOT_CLEANUP_TIMEOUT,
        )
        results = await asyncio.gather(
            *(self._safe_cleanup(name, bot) for name, bot in self._bots.items()),
            return_exceptions=False,
        )
        failed = sum(1 for ok in results if not ok)
        ok_count = len(results) - failed
        self.logger.info(
            "BotManager: bot cleanup complete — %d ok, %d failed",
            ok_count,
            failed,
        )

    async def _safe_cleanup(self, name: str, bot: AbstractBot) -> bool:
        """Run ``bot.cleanup()`` with timeout and exception isolation.

        Returns ``True`` on success, ``False`` on timeout or exception.
        Never raises — the gather in :meth:`_cleanup_all_bots` must always
        complete.  Maintains an idempotency guard (``self._cleaned_up``) so
        bots used as async context managers are not cleaned up twice.

        Args:
            name: The bot's registered name (key in ``self._bots``).
            bot: The bot instance whose ``cleanup()`` will be awaited.

        Returns:
            ``True`` if cleanup completed successfully, ``False`` otherwise.
        """
        if name in self._cleaned_up:
            self.logger.debug("BotManager: bot '%s' already cleaned up", name)
            return True
        try:
            await asyncio.wait_for(bot.cleanup(), timeout=BOT_CLEANUP_TIMEOUT)
        except asyncio.TimeoutError:
            self.logger.warning(
                "BotManager: cleanup of bot '%s' timed out after %ds",
                name,
                BOT_CLEANUP_TIMEOUT,
            )
            return False
        except Exception:  # noqa: BLE001 — teardown must not raise
            self.logger.exception(
                "BotManager: cleanup of bot '%s' raised an unexpected exception",
                name,
            )
            return False
        self._cleaned_up.add(name)
        return True

    async def _cleanup_shared_redis(self, app: web.Application) -> None:
        """aiohttp cleanup hook: close the shared Redis when we own it."""
        if not self._redis_owned:
            return
        client = app.pop('redis', None)
        if client is None:
            return
        close = getattr(client, 'aclose', None) or client.close
        result = close()
        if hasattr(result, '__await__'):
            await result

    def _register_voice_routes(self, router) -> bool:
        """Register the AgentVoiceTalk voice route under the optional guard.

        Imports the voice handler defensively: ``AgentVoiceTalk`` reaches the
        ``ai-parrot-integrations[voice]`` stack via lazy imports, so the import
        here usually succeeds even without the extra. The ``ImportError`` guard
        is defence-in-depth — a broken/absent voice stack logs a warning and
        skips the route instead of crashing server boot.

        Args:
            router: The aiohttp ``UrlDispatcher`` to register the route on.

        Returns:
            ``True`` if the voice route was registered, ``False`` if it was
            skipped because the voice stack could not be imported.
        """
        try:
            from ..handlers.agent_voice import AgentVoiceTalk
        except ImportError as exc:
            self.logger.warning(
                "Voice endpoints disabled (%s); install "
                "'ai-parrot-integrations[voice]' to enable "
                "POST /api/v1/agents/voice/{agent_id}.",
                exc,
            )
            return False
        router.add_view(
            '/api/v1/agents/voice/{agent_id}',
            AgentVoiceTalk,
        )
        return True

    def _register_transcribe_route(self, router) -> bool:
        """Register the transcribe-only STT endpoint (FEAT-249 Mode B — TASK-1608).

        Mounts ``AgentTranscribeOnly`` at
        ``POST /api/v1/agents/transcribe/{agent_id}`` under the same
        lazy-import guard as ``_register_voice_routes``.  When the voice extra is
        absent, a warning is logged and the route is skipped — server boot is
        unaffected.

        Args:
            router: The aiohttp ``UrlDispatcher`` to register the route on.

        Returns:
            ``True`` if the route was registered, ``False`` if skipped.
        """
        try:
            from ..handlers.agent_voice import AgentTranscribeOnly
        except ImportError as exc:
            self.logger.warning(
                "Transcribe endpoint disabled (%s); install "
                "'ai-parrot-integrations[voice]' to enable "
                "POST /api/v1/agents/transcribe/{agent_id}.",
                exc,
            )
            return False
        router.add_view(
            '/api/v1/agents/transcribe/{agent_id}',
            AgentTranscribeOnly,
        )
        self.logger.info("Transcribe-only route registered at /api/v1/agents/transcribe/{agent_id} (Mode B).")
        return True

    def _register_voice_chat_routes(self, app: web.Application) -> bool:
        """Register the Gemini Live + LITE avatar WebSocket route (FEAT-245 Mode D).

        Mounts ``VoiceChatHandler`` at ``/ws/voice`` under a lazy-import guard so
        a server without ``ai-parrot-integrations[voice]`` or Gemini credentials
        still boots — the route is simply skipped with a warning.

        Args:
            app: The aiohttp Application.

        Returns:
            ``True`` if the route was registered, ``False`` otherwise.
        """
        try:
            from parrot.voice.handler import VoiceChatHandler
        except ImportError as exc:
            self.logger.warning(
                "VoiceChatHandler (/ws/voice) disabled (%s); install "
                "'ai-parrot-integrations[voice]' to enable Mode D (Gemini Live).",
                exc,
            )
            return False

        handler = VoiceChatHandler()
        handler.setup_routes(app, include_health=False, include_static=False)
        self.logger.info("VoiceChatHandler registered at /ws/voice (Mode D).")
        return True

    def _register_avatar_routes(self, router) -> bool:
        """Register the avatar session start/stop routes (FEAT-242 Phase A).

        Delegates to ``parrot.handlers.avatar.register_avatar_routes`` which
        guards on the optional ``ai-parrot-integrations[liveavatar]`` extra and
        serves the routes through the authenticated ``AvatarSessionView``.  Also
        registers a shutdown hook to tear down any lingering avatar sessions.

        Args:
            router: The aiohttp ``UrlDispatcher`` to register routes on.

        Returns:
            ``True`` if the avatar routes were registered, ``False`` otherwise.
        """
        try:
            from ..handlers.avatar import (
                close_all_avatar_sessions,
                register_avatar_routes,
            )
        except ImportError as exc:
            self.logger.warning(
                "Avatar endpoints disabled (%s); install "
                "'ai-parrot-integrations[liveavatar]' to enable "
                "POST /api/v1/agents/avatar/{agent_id}/start.",
                exc,
            )
            return False
        registered = register_avatar_routes(router)
        if registered and self.app is not None:
            self.app.on_cleanup.append(close_all_avatar_sessions)
            # Shared avatar voice provider (chat→avatar "mouth"). Cheap to
            # construct — the heavy Supertonic ONNX load is deferred to the
            # first avatar turn. Stored on the app so AgentTalk can synthesize
            # the streamed reply into PCM for the active avatar session.
            try:
                import os as _os  # noqa: PLC0415

                from parrot.integrations.liveavatar import AvatarVoiceProvider

                self.app["avatar_voice_provider"] = AvatarVoiceProvider(
                    voice=_os.environ.get("LIVEAVATAR_VOICE") or None,
                    language=_os.environ.get("LIVEAVATAR_LANGUAGE") or None,
                )
                self.logger.info(
                    "Avatar voice provider registered (Supertonic loads lazily)."
                )
            except ImportError as exc:  # voice-supertonic extra missing
                self.logger.warning(
                    "Avatar voice provider unavailable (%s); the avatar will "
                    "appear but stay silent. Install "
                    "'ai-parrot-integrations[liveavatar,voice-supertonic]'.",
                    exc,
                )
        return registered

    def _register_fullmode_avatar_routes(self, router) -> bool:
        """Register the FULL mode avatar REST endpoints (FEAT-248).

        Delegates to ``parrot.handlers.avatar_fullmode.register_fullmode_routes``
        which guards on the optional ``ai-parrot-integrations[liveavatar]`` extra
        and registers start/stop/list/transcript routes.  Also registers a shutdown
        hook to tear down any lingering FULL mode sessions.

        Args:
            router: The aiohttp ``UrlDispatcher`` to register routes on.

        Returns:
            ``True`` if the FULL mode routes were registered, ``False`` otherwise.
        """
        try:
            from ..handlers.avatar_fullmode import (
                close_all_fullmode_sessions,
                register_fullmode_routes,
            )
        except ImportError as exc:
            self.logger.warning(
                "FULL mode avatar endpoints disabled (%s); install "
                "'ai-parrot-integrations[liveavatar]' to enable "
                "POST /api/v1/avatar/fullmode/{agent_id}/start.",
                exc,
            )
            return False
        registered = register_fullmode_routes(router)
        if registered and self.app is not None:
            self.app.on_cleanup.append(close_all_fullmode_sessions)
        return registered

    def _setup_structured_output_transport(self) -> None:
        """Wire the Redis structured-output transport subscriber when enabled (FEAT-249).

        Opt-in via ``ENABLE_STRUCTURED_OUTPUT_TRANSPORT``. The subscriber's own
        ``on_startup`` defers reading ``app['user_socket_manager']``, so registering
        it here (before that key is populated) is safe.
        """
        if not ENABLE_STRUCTURED_OUTPUT_TRANSPORT:
            return
        from ..handlers.liveavatar_output import (
            configure_liveavatar_output_subscriber,
        )

        configure_liveavatar_output_subscriber(self.app)

    def setup(self, app: web.Application) -> web.Application:
        self.app = None
        if app:
            self.app = app if isinstance(app, web.Application) else app.get_app()
        # register signals for startup and shutdown
        self.app.on_startup.append(self.on_startup)
        self.app.on_shutdown.append(self.on_shutdown)
        # Register per-bot cleanup BEFORE shared-Redis cleanup so bots can
        # still use app['redis'] inside their own cleanup() coroutines.
        self.app.on_cleanup.append(self._cleanup_all_bots)
        # Publish a shared Redis client so every ai-parrot component that
        # expects ``app['redis']`` (navigator-auth refresh-token rotation,
        # FEAT-108 VaultTokenSync, Jira OAuth state, etc.) finds one. If a
        # prior component already set the key, respect it.
        self._register_shared_redis()
        # Add Manager to main Application:
        self.app['bot_manager'] = self
        # Register OAuth2 providers after startup (FEAT-144)
        # Uses a deferred callback so app["jira_oauth_manager"] is available.
        self.app.on_startup.append(self._register_oauth2_providers)
        ## Configure Routes
        router = self.app.router
        # Chat Information Router
        router.add_view(
            '/api/v1/chats',
            ChatHandler
        )
        router.add_view(
            '/api/v1/chat/{chatbot_name}',
            ChatHandler
        )
        router.add_view(
            '/api/v1/chat/{chatbot_name}/{method_name}',
            ChatHandler
        )
        # Talk with agents:
        router.add_view(
            '/api/v1/agents/chat/{agent_id}',
            AgentTalk
        )
        router.add_view(
            '/api/v1/agents/chat/{agent_id}/{method_name}',
            AgentTalk
        )
        # Agent knowledge index (PageIndex / GraphIndex) management.
        # Literal action sub-route ({action}: search|ask) MUST be registered
        # before the bare {agent_id} route so aiohttp resolves /search and /ask
        # before matching them as agent IDs.
        router.add_view(
            '/api/v1/agents/knowledge/{agent_id}/{action}',
            AgentKnowledgeHandler
        )
        router.add_view(
            '/api/v1/agents/knowledge/{agent_id}',
            AgentKnowledgeHandler
        )
        # FEAT-146: HITL response endpoint (agent-driven human-in-the-loop)
        router.add_view(
            '/api/v1/agents/hitl/respond',
            HITLResponseHandler
        )
        # FEAT-146: Bootstrap web HITL stack (idempotent).
        # Deferred to on_startup so that app['user_socket_manager'] is
        # guaranteed to be populated before setup_web_hitl runs.
        async def _hitl_deferred_startup(app: web.Application) -> None:
            await setup_web_hitl(app)

        self.app.on_startup.append(_hitl_deferred_startup)
        # FEAT-249: Redis structured-output transport subscriber (opt-in).
        self._setup_structured_output_transport()
        # OAuth2 Integrations routes (FEAT-144)
        router.add_view(
            '/api/v1/agents/integrations/{agent_id}',
            IntegrationsHandler,
        )
        router.add_view(
            '/api/v1/agents/integrations/{agent_id}/{provider}/connect',
            IntegrationsHandler,
        )
        router.add_view(
            '/api/v1/agents/integrations/{agent_id}/{provider}/enable',
            IntegrationsHandler,
        )
        router.add_view(
            '/api/v1/agents/integrations/{agent_id}/{provider}',
            IntegrationsHandler,
        )
        # User-defined bots: PUT/PATCH/GET/DELETE
        router.add_view(
            '/api/v1/user_agents',
            UserAgentHandler
        )
        router.add_view(
            '/api/v1/user_agents/{chatbot_id}',
            UserAgentHandler
        )
        # FEAT-149: Ephemeral user agents (POST/GET status/PUT promote/DELETE)
        # The status sub-route MUST be registered before the bare {chatbot_id}
        # route so aiohttp resolves /…/{id}/status correctly.
        router.add_view(
            '/api/v1/agents/user',
            EphemeralUserAgentHandler,
        )
        router.add_view(
            '/api/v1/agents/user/{chatbot_id}/status',
            EphemeralUserAgentHandler,
        )
        router.add_view(
            '/api/v1/agents/user/{chatbot_id}',
            EphemeralUserAgentHandler,
        )
        # FEAT-149: Tool catalog — read-only TOOL_REGISTRY surface
        router.add_view(
            '/api/v1/tools/catalog',
            ToolCatalogHandler,
        )
        # Prompt fine-tuning console (in-memory system-prompt editing).
        # Literal action sub-routes MUST precede the bare {agent_name} route so
        # aiohttp resolves /suggest, /test and /save before the catch-all.
        router.add_view(
            '/api/v1/agents/prompt/{agent_name}/suggest',
            PromptTunerHandler,
        )
        router.add_view(
            '/api/v1/agents/prompt/{agent_name}/test',
            PromptTunerHandler,
        )
        router.add_view(
            '/api/v1/agents/prompt/{agent_name}/save',
            PromptTunerHandler,
        )
        router.add_view(
            '/api/v1/agents/prompt/{agent_name}',
            PromptTunerHandler,
        )
        # Data Analyst creation route:
        router.add_view(
            '/api/v1/agents/analyst',
            DataAnalystHandler
        )
        # AgentFactory: meta-agent that drafts and registers new agents
        # from a natural-language description (RAG / tool-agent / clone).
        router.add_view(
            '/api/v1/agents/factory',
            AgentFactoryHandler
        )
        # InfographicTalk routes (FEAT-095) — literal resource routes MUST
        # come before the {agent_id} catch-all so aiohttp resolves
        # /templates and /themes before matching them as agent IDs.
        router.add_view(
            '/api/v1/agents/infographic/{resource:templates}',
            InfographicTalk,
        )
        router.add_view(
            '/api/v1/agents/infographic/{resource:templates}/{template_name}',
            InfographicTalk,
        )
        router.add_view(
            '/api/v1/agents/infographic/{resource:themes}',
            InfographicTalk,
        )
        router.add_view(
            '/api/v1/agents/infographic/{resource:themes}/{theme_name}',
            InfographicTalk,
        )
        router.add_view(
            '/api/v1/agents/infographic/{agent_id}',
            InfographicTalk,
        )
        # AgentVoiceTalk route (FEAT-231) — voice I/O adapter around the text
        # path. Registered under the optional-integration guard: the handler
        # reaches the voice stack (ai-parrot-integrations[voice]) via lazy
        # imports, so a missing stack must degrade gracefully, never crash boot.
        self._register_voice_routes(router)
        # Mode B: transcribe-only STT endpoint (FEAT-249 TASK-1608). Allows the
        # FULL-mode frontend to obtain a transcript from ai-parrot's internal STT
        # without invoking the agent. Registered under the same optional guard.
        self._register_transcribe_route(router)
        # Mode D: Gemini Live + LITE avatar WebSocket (FEAT-245/FEAT-249). Mounted
        # under the optional-integration guard; missing [voice] logs a warning.
        self._register_voice_chat_routes(self.app)
        # Avatar session routes (FEAT-242 Phase A) — start/stop the LiveAvatar
        # session. Registered under the optional-integration guard like voice:
        # a missing ai-parrot-integrations[liveavatar] extra logs a warning and
        # skips the routes instead of crashing boot.
        self._register_avatar_routes(router)
        # FULL mode avatar routes (FEAT-248) — LiveAvatar-managed STT/TTS/lip-sync.
        # Registered under the same optional-integration guard; a missing stack
        # logs a warning instead of crashing boot.
        self._register_fullmode_avatar_routes(router)
        # Dataset Manager for agents:
        router.add_view(
            '/api/v1/agents/datasets/{agent_id}',
            DatasetManagerHandler
        )
        router.add_view(
            '/api/v1/agents/datasets/{agent_id}/{dataset_id}',
            DatasetManagerHandler
        )
        # Infographic Recipes (FEAT-324): CRUD + on-demand replay. Unlike
        # DatasetManagerHandler, the recipe store/runner have no per-request
        # cloning path — configure them via
        # ``parrot.handlers.infographic_recipes.register_recipe_routes(app,
        # recipe_store=..., dataset_manager=...)`` at startup; until then the
        # handler returns a clear 500 ("recipe_store is not configured").
        router.add_view(
            '/api/v1/infographic_recipes',
            RecipeHandler
        )
        router.add_view(
            '/api/v1/infographic_recipes/{name}',
            RecipeHandler
        )
        router.add_view(
            '/api/v1/infographic_recipes/{name}/run',
            RecipeHandler
        )
        # Database Agent metadata:
        router.add_view(
            '/api/v1/agents/database/roles',
            DatabaseRolesHandler
        )
        router.add_view(
            '/api/v1/agents/database/formats',
            DatabaseFormatsHandler
        )
        router.add_view(
            '/api/v1/agents/database/intents',
            DatabaseIntentsHandler
        )
        router.add_view(
            '/api/v1/agents/database/drivers',
            DatabaseDriversHandler
        )
        router.add_view(
            '/api/v1/agents/database/schemas',
            DatabaseSchemasHandler
        )
        router.add_view(
            '/api/v1/agents/database/schemas/{name}',
            DatabaseSchemasHandler
        )
        # Utility endpoints
        # Print-to-PDF (FEAT-097)
        router.add_view(
            '/api/v1/utilities/print2pdf',
            PrintPDFHandler
        )
        # ChatBot Manager
        ChatbotHandler.configure(self.app, '/api/v1/bots')
        # Bot Handler
        router.add_view(
            '/api/v1/chatbots',
            BotHandler
        )
        router.add_view(
            '/api/v1/chatbots/{name}',
            BotHandler
        )
        # Streaming Handler:
        st = StreamHandler()
        st.configure_routes(self.app)
        # FEAT-244: publish the StreamHandler so the LiveAvatar output subscriber
        # can use it as a fan-out sink for structured-output delivery.
        # Must be set HERE (before on_startup hooks run) so the subscriber's
        # _start hook finds it when it reads app['stream_handler'].
        self.app['stream_handler'] = st
        # Crew Configuration
        if ENABLE_CREWS:
            router.add_view('/api/v1/crew/tools', CrewToolCatalogHandler)
            # Must register BEFORE CrewHandler.configure — its '{id:.*}'
            # catch-all route would otherwise shadow this path.
            router.add_view(
                '/api/v1/crew/special_nodes', CrewSpecialNodeCatalogHandler
            )
            # Execution-history API (list/detail/replay/schedule/delete).
            # Must register BEFORE CrewHandler.configure — its '{id:.*}'
            # catch-all would otherwise shadow '/api/v1/crew/executions' and
            # resolve 'executions' as a crew id.
            CrewExecutionHistoryHandler.configure(
                self.app, '/api/v1/crew/executions'
            )
            CrewHandler.configure(self.app, '/api/v1/crew')
            CrewExecutionHandler.configure(self.app, '/api/v1/crews')
        # Agent Config CRUD
        router.add_view(
            '/api/v1/agents/config',
            BotConfigHandler
        )
        router.add_view(
            '/api/v1/agents/config/{agent_name}',
            BotConfigHandler
        )
        # Agent Testing (session-based)
        router.add_view(
            '/api/v1/agents/test/{agent_name}',
            BotConfigTestHandler
        )
        # Chat Interaction Persistence
        router.add_view(
            '/api/v1/chat/interactions',
            ChatInteractionHandler
        )
        router.add_view(
            '/api/v1/chat/interactions/{session_id}',
            ChatInteractionHandler
        )
        # Dashboard Persistence
        if ENABLE_DASHBOARDS:
            router.add_view(
                '/api/v1/dashboards',
                DashboardHandler
            )
            router.add_view(
                '/api/v1/dashboards/{dashboard_id}',
                DashboardHandler
            )
            router.add_view(
                '/api/v1/dashboards/{dashboard_id}/tabs',
                DashboardTabHandler
            )
            router.add_view(
                '/api/v1/dashboards/{dashboard_id}/tabs/{tab_id}',
                DashboardTabHandler
            )
        # User credential management routes
        setup_credentials_routes(self.app)
        # MCP helper routes (discovery, activation, management)
        setup_mcp_helper_routes(self.app)
        if self.enable_swagger_api:
            self.logger.info("Setting up OpenAPI documentation...")
            setup_swagger(self.app)
            self.logger.info("""
✅ OpenAPI Documentation configured successfully!

Available documentation UIs:
- Swagger UI:  http://localhost:5000/api/docs
- ReDoc:       http://localhost:5000/api/docs/redoc
- RapiDoc:     http://localhost:5000/api/docs/rapidoc
- OpenAPI Spec: http://localhost:5000/api/docs/swagger.json
            """)
        return self.app

    async def _cleanup_expired_bots(self) -> None:
        """Background task to cleanup expired temporary bot instances.

        Runs every 5 minutes to check for and remove bot instances that have
        exceeded their expiration time (typically 1 hour after creation).
        """
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                current_time = time.time()

                # Find all expired bots
                expired = [
                    name for name, expiry in self._bot_expiration.items()
                    if current_time > expiry
                ]

                # Remove expired bots
                for name in expired:
                    try:
                        self.logger.info("Removing expired bot instance: %s", name)
                        self.remove_bot(name)
                        del self._bot_expiration[name]
                    except Exception as e:
                        self.logger.error(
                            f"Error removing expired bot '{name}': {e}"
                        )
                        # Remove from expiration tracking even if removal failed
                        self._bot_expiration.pop(name, None)

                if expired:
                    self.logger.info(
                        f"Cleaned up {len(expired)} expired bot instance(s). "
                        f"Active bots: {len(self._bots)}, "
                        f"Tracked expirations: {len(self._bot_expiration)}"
                    )

                # Sweep expired ephemeral bots (FEAT-149).
                # FIX-8: removed outer bare except — the lazy _ephemeral_registry
                # property never raises, so it is safe to call unconditionally.
                # FIX-1: await the async remove()
                expired_ephemerals = self._ephemeral_registry.get_expired()
                for cid in expired_ephemerals:
                    try:
                        await self._ephemeral_registry.remove(cid)
                        self._bots.pop(cid, None)
                        self.logger.info(
                            "Swept expired ephemeral bot: %s", cid
                        )
                    except Exception as sweep_exc:  # noqa: BLE001
                        self.logger.error(
                            "Error sweeping ephemeral bot %s: %s",
                            cid, sweep_exc,
                        )

            except asyncio.CancelledError:
                self.logger.info("Cleanup task cancelled")
                raise
            except Exception as e:
                self.logger.error(
                    f"Error in cleanup task: {e}",
                    exc_info=True
                )
                # Continue running even if there's an error

    async def _register_oauth2_providers(self, app: web.Application) -> None:
        """Register OAuth2 providers with the global registry (FEAT-144).

        Called as an ``on_startup`` callback so that ``app["jira_oauth_manager"]``
        is guaranteed to be available before registration.
        """
        try:
            from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
            from parrot.auth.oauth2.registry import register_oauth2_provider

            jira_manager = app.get("jira_oauth_manager")
            if jira_manager is not None:
                register_oauth2_provider(JiraOAuth2Provider(manager=jira_manager))
                self.logger.info(
                    "Registered JiraOAuth2Provider with the global OAuth2ProviderRegistry"
                )
            else:
                self.logger.warning(
                    "app['jira_oauth_manager'] is not set — "
                    "JiraOAuth2Provider not registered.  "
                    "Ensure JiraOAuthManager.setup(app) is called before startup."
                )
        except Exception:  # noqa: BLE001
            self.logger.exception(
                "Failed to register OAuth2 providers — integrations endpoints "
                "will return empty provider lists."
            )

    async def on_startup(self, app: web.Application) -> None:
        """On startup."""
        # Initialize the ArtifactStore (FEAT-103) BEFORE loading bots.
        # at_startup agents configure() during load_bots and may register
        # toolkits (e.g. InfographicToolkit) that require app['artifact_store'];
        # request-time handlers (agent, infographic, artifacts) read it too.
        try:
            backend = await build_conversation_backend()
            await backend.initialize()
            overflow = build_overflow_store()
            app['artifact_store'] = ArtifactStore(
                dynamodb=backend,
                s3_overflow=overflow,
            )
            self.logger.info("ArtifactStore initialized and published to app['artifact_store']")
        except Exception as exc:
            self.logger.warning("ArtifactStore initialization failed: %s", exc)
        # Bootstrap the web HITL stack BEFORE loading bots so the process-wide
        # HumanInteractionManager exists when at_startup agents run configure()
        # (e.g. ExpenseApprovalAgent wires its escalation policy there). This
        # call is idempotent: the deferred _hitl_deferred_startup on_startup
        # hook still runs later to attach the "web" channel once
        # app['user_socket_manager'] is populated.
        try:
            await setup_web_hitl(app)
        except Exception as exc:
            self.logger.warning("Early setup_web_hitl failed: %s", exc)
        # configure all pre-configured chatbots:
        await self.load_bots(app)
        # Initialize BotConfigStorage and attach to app
        if self.enable_registry_bots:
            app['bot_config_storage'] = BotConfigStorage()
        # Load crews from Redis
        if self.enable_crews:
            await self.load_crews()
        # Start background cleanup task for expired bots
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_bots())
        self.logger.info("Started background cleanup task for temporary bot instances")
        # Initialize ChatStorage (Redis + DocumentDB)
        chat_storage = ChatStorage()
        try:
            await chat_storage.initialize()
            self.logger.info("ChatStorage initialized (Redis + DocumentDB)")
        except Exception as exc:
            self.logger.warning("ChatStorage initialization failed: %s", exc)
        # Initialize Dashboard indexes
        if ENABLE_DASHBOARDS:
            await _ensure_dashboard_indexes(app)
        app['chat_storage'] = chat_storage
        # Start Integration bots (deferred aiogram import — see top of file).
        # ai-parrot-integrations is an optional satellite distribution: a
        # server install may omit it (or a per-channel SDK may be missing).
        # Treat integrations as optional and degrade gracefully instead of
        # failing startup — on_shutdown already guards on the None manager.
        try:
            from parrot.integrations import IntegrationBotManager
        except ImportError as exc:
            self.logger.warning(
                "Integration bots disabled: %s "
                "(install 'ai-parrot-integrations[all]' to enable them).",
                exc,
            )
            self._integration_manager = None
        else:
            self._integration_manager = IntegrationBotManager(self)
            await self._integration_manager.startup()

    async def on_shutdown(self, app: web.Application) -> None:
        """On shutdown."""
        # Cancel background cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self.logger.info("Stopped background cleanup task")
        # Stop Integration bots
        if self._integration_manager:
            await self._integration_manager.shutdown()
        # Close ChatStorage
        chat_storage = app.get('chat_storage')
        if chat_storage:
            await chat_storage.close()
            self.logger.info("ChatStorage closed")
        # Close ArtifactStore backend
        artifact_store = app.get('artifact_store')
        if artifact_store is not None:
            backend = getattr(artifact_store, '_db', None)
            if backend is not None and hasattr(backend, 'close'):
                try:
                    await backend.close()
                    self.logger.info("ArtifactStore backend closed")
                except Exception as exc:
                    self.logger.warning("ArtifactStore backend close failed: %s", exc)

    async def add_crew(
        self,
        name: str,
        crew: AgentCrew,
        crew_def: CrewDefinition
    ) -> None:
        """
        Register a crew in the manager and persist to Redis.

        Args:
            name: Unique name for the crew
            crew: AgentCrew instance
            crew_def: Crew definition containing metadata

        Raises:
            ValueError: If crew with same name already exists
        """
        tenant = self._normalize_tenant(crew_def.tenant)
        crew_key = self._get_crew_key(tenant, name)
        if crew_key in self._crews:
            raise ValueError(f"Crew '{name}' already exists")

        # Add to memory
        self._crews[crew_key] = (crew, crew_def)

        # Persist to Redis (only when Redis-backed persistence is enabled)
        if self.crew_redis is None:
            self.logger.debug(
                "Crew persistence disabled (ENABLE_CREWS is False); "
                "crew '%s' registered in memory only",
                name,
            )
            return

        try:
            await self.crew_redis.save_crew(crew_def)
            self.logger.info(
                f"Registered crew '{name}' with {len(crew.agents)} agents "
                f"in {crew_def.execution_mode.value} mode and saved to Redis"
            )
        except Exception as e:
            self.logger.error("Failed to save crew '%s' to Redis: %s", name, e)
            # Don't fail the operation if Redis fails, crew is still in memory
            self.logger.info(
                f"Crew '{name}' registered in memory only (Redis persistence failed)"
            )

    async def get_crew(
        self,
        identifier: str,
        as_new: bool = False,
        tenant: Optional[str] = None
    ) -> Optional[Tuple[AgentCrew, CrewDefinition]]:
        """
        Get a crew by name or ID. Loads from Redis if not in memory.

        Args:
            identifier: Crew name or crew_id
            as_new: If True, creates a new instance (default False)
            tenant: Tenant identifier

        Returns:
            Tuple of (AgentCrew, CrewDefinition) if found, None otherwise
        """
        crew_def = None
        cached_crew = None
        tenant = self._normalize_tenant(tenant)
        crew_key = self._get_crew_key(tenant, identifier)

        # 1. Resolve Crew Definition from Memory
        if crew_key in self._crews:
            cached_crew, crew_def = self._crews[crew_key]
        else:
            # Check by crew_id in memory
            for _, (c, cd) in self._crews.items():
                if cd.crew_id == identifier and cd.tenant == tenant:
                    cached_crew, crew_def = c, cd
                    break

        # 2. If valid definition found in memory
        if crew_def:
            if as_new:
                # Create fresh instance from definition
                try:
                    new_crew = await self._create_crew_from_definition(crew_def)
                    return (new_crew, crew_def)
                except Exception as e:
                    self.logger.error(
                        f"Failed to create new crew instance: {e}"
                    )
                    return (None, None)
            else:
                return (cached_crew, crew_def)

        # 3. If not in memory, try Redis (when persistence is enabled)
        if self.crew_redis is None:
            return (None, None)

        try:
            # Try to load by name first
            crew_def = await self.crew_redis.load_crew(identifier, tenant)
            # If not found by name, try by ID
            if not crew_def:
                crew_def = await self.crew_redis.load_crew_by_id(identifier, tenant)

            if crew_def:
                # We found it in Redis!
                # We need to instantiate it to cache it (so we have definition for next time)
                base_crew = await self._create_crew_from_definition(crew_def)

                # Update Cache
                cache_key = self._get_crew_key(crew_def.tenant, crew_def.name)
                self._crews[cache_key] = (base_crew, crew_def)

                self.logger.info(
                    f"Loaded crew '{crew_def.name}' from Redis "
                    f"(ID: {crew_def.crew_id})"
                )

                if as_new:
                    return (await self._create_crew_from_definition(crew_def), crew_def)
                else:
                    return (base_crew, crew_def)

        except Exception as e:
            self.logger.error(
                f"Error loading crew '{identifier}' from Redis: {e}"
            )
            return (None, None)

        return (None, None)

    def list_crews(
        self,
        tenant: Optional[str] = None
    ) -> Dict[str, Tuple[AgentCrew, CrewDefinition]]:
        """
        List all registered crews.

        Returns:
            Dictionary mapping crew names to (AgentCrew, CrewDefinition) tuples
        """
        if tenant is None:
            return self._crews.copy()
        tenant = self._normalize_tenant(tenant)
        return {
            crew_def.name: (crew, crew_def)
            for _, (crew, crew_def) in self._crews.items()
            if crew_def.tenant == tenant
        }

    async def remove_crew(
        self,
        identifier: str,
        tenant: Optional[str] = None
    ) -> bool:
        """
        Remove a crew from the manager and Redis.

        Args:
            identifier: Crew name or crew_id
            tenant: Tenant identifier

        Returns:
            True if removed, False if not found
        """
        crew_name = None
        crew_def = None
        tenant = self._normalize_tenant(tenant)

        # Try by name first
        crew_key = self._get_crew_key(tenant, identifier)
        if crew_key in self._crews:
            crew_name = identifier
            _, crew_def = self._crews[crew_key]
            del self._crews[crew_key]
        else:
            # Try by crew_id
            for key, (_, def_) in list(self._crews.items()):
                if def_.crew_id == identifier and def_.tenant == tenant:
                    crew_name = def_.name
                    crew_def = def_
                    del self._crews[key]
                    break

        if crew_name and crew_def:
            # Remove from Redis (when persistence is enabled)
            if self.crew_redis is None:
                self.logger.debug(
                    "Crew persistence disabled; crew '%s' removed from memory only",
                    crew_name,
                )
                return True
            try:
                await self.crew_redis.delete_crew(crew_def.name, crew_def.tenant)
                self.logger.info(
                    f"Removed crew '{crew_name}' (ID: {crew_def.crew_id}) "
                    f"from memory and Redis"
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to delete crew '{crew_name}' from Redis: {e}"
                )
                self.logger.info(
                    f"Crew '{crew_name}' removed from memory only"
                )
            return True

        return False

    def update_crew(
        self,
        identifier: str,
        crew: AgentCrew,
        crew_def: CrewDefinition
    ) -> bool:
        """
        Update an existing crew.

        Args:
            identifier: Crew name or crew_id
            crew: Updated AgentCrew instance
            crew_def: Updated crew definition

        Returns:
            True if updated, False if not found
        """
        crew_key = self._get_crew_key(crew_def.tenant, identifier)
        if crew_key in self._crews:
            self._crews[crew_key] = (crew, crew_def)
            self.logger.info("Updated crew '%s'", identifier)
            return True

        for key, (_, def_) in self._crews.items():
            if def_.crew_id == identifier and def_.tenant == crew_def.tenant:
                self._crews[key] = (crew, crew_def)
                self.logger.info("Updated crew '%s'", def_.name)
                return True

        return False

    async def load_crews(self) -> None:
        """
        Load all crews from Redis on startup.

        This method is called during application startup to restore
        all previously saved crews from Redis into memory.
        """
        if self.crew_redis is None:
            self.logger.debug(
                "Crew persistence disabled (ENABLE_CREWS is False); "
                "skipping crew loading from Redis"
            )
            return
        try:
            # Check Redis connection
            if not await self.crew_redis.ping():
                self.logger.warning("Redis connection failed, skipping crew loading")
                return

            # Get all crew definitions from Redis
            crew_defs = await self.crew_redis.get_all_crews()

            if not crew_defs:
                self.logger.info("No crews found in Redis")
                return

            self.logger.info("Loading %s crews from Redis...", len(crew_defs))

            loaded_count = 0
            for crew_def in crew_defs:
                try:
                    # Reconstruct the crew from definition
                    crew = await self._create_crew_from_definition(crew_def)

                    # Add to memory (without saving back to Redis)
                    crew_key = self._get_crew_key(crew_def.tenant, crew_def.name)
                    self._crews[crew_key] = (crew, crew_def)

                    loaded_count += 1
                    self.logger.info(
                        f"Loaded crew '{crew_def.name}' with {len(crew_def.agents)} agents "
                        f"in {crew_def.execution_mode.value} mode"
                    )
                except Exception as e:
                    self.logger.error(
                        f"Failed to load crew '{crew_def.name}': {e}",
                        exc_info=True
                    )

            self.logger.info(
                f":: Crews loaded successfully. Total active crews: {loaded_count}"
            )
        except Exception as e:
            self.logger.error(
                f"Failed to load crews from Redis: {e}",
                exc_info=True
            )

    async def sync_crews(self) -> None:
        """
        Synchronize in-memory crews with Redis.

        This handles:
        1. Loading new crews added by other workers
        2. Removing crews deleted by other workers
        """
        if self.crew_redis is None:
            # Redis-backed persistence disabled; nothing to sync (in-memory only)
            return
        try:
            # Get all crew names from Redis
            remote_entries = await self.crew_redis.list_all_crews()
            remote_names = {
                self._get_crew_key(entry["tenant"], entry["name"])
                for entry in remote_entries
            }
            local_names = set(self._crews.keys())

            # Identify additions and removals
            added = remote_names - local_names
            removed = local_names - remote_names

            if not added and not removed:
                return

            self.logger.debug(
                f"Syncing crews: {len(added)} to add, {len(removed)} to remove"
            )

            # Handle additions
            for key in added:
                try:
                    tenant, name = self._split_crew_key(key)
                    crew_def = await self.crew_redis.load_crew(name, tenant)
                    if crew_def:
                        crew = await self._create_crew_from_definition(crew_def)
                        self._crews[key] = (crew, crew_def)
                        self.logger.info("Synced new crew '%s' from Redis", name)
                except Exception as e:
                    # Provide more specific diagnostics, especially for malformed keys.
                    if isinstance(e, ValueError):
                        self.logger.error(
                            f"Failed to sync crew: invalid key format {key!r}: {e}"
                        )
                    else:
                        self.logger.error(
                            f"Failed to sync crew for key {key!r}: {e}",
                            exc_info=True,
                        )

            # Handle removals
            for key in removed:
                self._crews.pop(key, None)
                self.logger.info("Synced removal of crew '%s'", key)

        except Exception as e:
            self.logger.error("Error syncing crews: %s", e, exc_info=True)

    async def _create_crew_from_definition(
        self,
        crew_def: CrewDefinition
    ) -> AgentCrew:
        """Create an AgentCrew from a CrewDefinition.

        Delegates to ``AgentCrew.from_definition()``, passing
        ``self.get_bot_class`` as ``class_resolver``. Shared tool
        resolution is not available in this context (no tool registry on
        BotManager); ``from_definition`` handles the ``tool_resolver=None``
        default by skipping shared tool resolution.

        Args:
            crew_def: Crew definition.

        Returns:
            AgentCrew instance.
        """
        return AgentCrew.from_definition(
            crew_def,
            class_resolver=self.get_bot_class,
        )

    def get_crew_stats(self) -> Dict[str, Any]:
        """
        Get statistics about registered crews.

        Returns:
            Dictionary with crew statistics
        """
        stats = {
            'total_crews': len(self._crews),
            'crews_by_mode': {
                'sequential': 0,
                'parallel': 0,
                'flow': 0
            },
            'total_agents': 0,
            'crews': []
        }

        for name, (crew, crew_def) in self._crews.items():
            mode = crew_def.execution_mode.value
            stats['crews_by_mode'][mode] = stats['crews_by_mode'].get(mode, 0) + 1
            stats['total_agents'] += len(crew.agents)

            stats['crews'].append({
                'name': crew_def.name,
                'tenant': crew_def.tenant,
                'crew_id': crew_def.crew_id,
                'mode': mode,
                'agent_count': len(crew.agents)
            })

        return stats
