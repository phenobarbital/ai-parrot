"""
Integration Bot Manager.

Manages lifecycle of bots (Telegram, MS Teams, WhatsApp) exposing AI-Parrot agents.
Loads configuration from {ENV_DIR}/integrations_bots.yaml (or telegram_bots.yaml fallback).
"""
# ``annotations`` future-import keeps every annotation a string, so the
# aiogram symbols (``Bot``/``Dispatcher``) referenced in instance-attribute
# and method annotations are never evaluated at import time. Combined with the
# lazy imports inside ``_start_telegram_bot``, this lets ``IntegrationBotManager``
# be imported without the optional ``aiogram`` (Telegram) dependency installed.
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import yaml
from aiohttp import web

from navconfig import BASE_DIR
from navconfig.logging import logging
from parrot.conf import AGENTS_DIR, REDIS_URL
from parrot.human import (
    HumanInteractionManager,
    set_default_human_manager,
)
from .models import (
    IntegrationBotConfig,
    TelegramAgentConfig,
    MSTeamsAgentConfig,
    WhatsAppAgentConfig,
    SlackAgentConfig,
    MSAgentSDKConfig,
    MSAgentIntegrationConfig,
    A2AAgentConfig,
)
if TYPE_CHECKING:
    from aiogram import Bot, Dispatcher
    from .telegram.wrapper import TelegramAgentWrapper
    from .msteams.wrapper import MSTeamsAgentWrapper
    from .whatsapp.wrapper import WhatsAppAgentWrapper
    from .slack.wrapper import SlackAgentWrapper
    from .msagentsdk.wrapper import MSAgentSDKWrapper
    from parrot.manager import BotManager
    from parrot.bots.abstract import AbstractBot


ENV_DIR = BASE_DIR.joinpath('env')


async def handle_a2a_directory(request: web.Request) -> web.Response:
    """GET /a2a/directory — returns JSON array of all registered AgentCards.

    Lists only agents declared with ``kind: a2a`` (including the automatic
    A2A companion surface of ``kind: msagent`` bots); other integration
    kinds (telegram/slack/etc.) never register into
    ``app["a2a_discovery_registry"]``.
    """
    registry: Dict[str, Any] = request.app.get("a2a_discovery_registry", {})
    cards = [card.to_dict() for card in registry.values()]
    return web.json_response(cards)


class IntegrationBotManager:
    """
    Manages bot integrations for exposed agents.

    Supports:
    - Telegram
    - MS Teams
    - WhatsApp
    - MS Agent SDK
    """

    def __init__(self, bot_manager: 'BotManager'):
        self.bot_manager = bot_manager
        self.logger = logging.getLogger("IntegrationBotManager")

        # Active bots
        self.telegram_bots: Dict[str, Tuple[Bot, Dispatcher, 'TelegramAgentWrapper']] = {}
        self.msteams_bots: Dict[str, 'MSTeamsAgentWrapper'] = {}
        self.whatsapp_bots: Dict[str, 'WhatsAppAgentWrapper'] = {}
        self.slack_bots: Dict[str, 'SlackAgentWrapper'] = {}
        self.msagentsdk_bots: Dict[str, 'MSAgentSDKWrapper'] = {}
        self.a2a_bots: Dict[str, Any] = {}
        self.msagent_bots: Dict[str, Any] = {}

        # Dedicated aiohttp.web.AppRunner instances for A2A agents started
        # with a per-agent ``port`` (i.e. NOT mounted on the shared app).
        self._a2a_runners: List[web.AppRunner] = []

        # Matrix crew transport (FEAT-044)
        self.matrix_crew: Optional[object] = None  # MatrixCrewTransport

        self._polling_tasks: List[asyncio.Task] = []
        self._config: Optional[IntegrationBotConfig] = None

        # Human-in-the-Loop: one shared manager, one channel per Telegram bot.
        # The manager is created lazily when the first integration needs it.
        self.human_manager: Optional[HumanInteractionManager] = None
        self._human_redis = None

    def _get_config_path(self) -> Path:
        """Get path to integrations_bots.yaml (preferred) or telegram_bots.yaml."""
        p = ENV_DIR / "integrations_bots.yaml"
        if p.exists():
            return p
        return ENV_DIR / "telegram_bots.yaml"

    async def load_config(self) -> Optional[IntegrationBotConfig]:
        """Load configuration."""
        config_path = self._get_config_path()
        
        if not config_path.exists():
            self.logger.debug("No integration config found.")
            return None
            
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                
            if not data:
                return None
                
            # Use the unified config parser
            config = IntegrationBotConfig.from_dict(data)
            
            errors = config.validate()
            if errors:
                for error in errors:
                    self.logger.error("Config Error: %s", error)
                return None
                
            self._config = config
            return config
            
        except Exception as e:
            self.logger.error("Error loading integration config: %s", e, exc_info=True)
            return None

    async def _get_agent(self, chatbot_id: str, system_prompt_override: Optional[str] = None) -> Optional['AbstractBot']:
        """Get agent instance from BotManager."""
        agent = await self.bot_manager.get_bot(chatbot_id)
        if not agent:
            self.logger.error("Agent '%s' not found.", chatbot_id)
            return None
            
        if system_prompt_override and hasattr(agent, 'system_prompt'):
            agent.system_prompt = system_prompt_override
            
        return agent

    async def startup(self, extra_config: Optional[dict] = None) -> None:
        """Start all configured bots.

        Args:
            extra_config: Optional dict with additional integration keys.
                Supports ``"matrix_crew"`` → path to YAML config file for
                ``MatrixCrewTransport`` (FEAT-044).
        """
        self.logger.info("Starting Integration Manager...")

        # Matrix crew transport (FEAT-044)
        if extra_config and "matrix_crew" in extra_config:
            await self._start_matrix_crew(extra_config["matrix_crew"])

        config = await self.load_config()
        if not config:
            return

        for name, agent_config in config.agents.items():
            try:
                if isinstance(agent_config, TelegramAgentConfig):
                    await self._start_telegram_bot(name, agent_config)
                elif isinstance(agent_config, MSTeamsAgentConfig):
                    await self._start_msteams_bot(name, agent_config)
                elif isinstance(agent_config, WhatsAppAgentConfig):
                    await self._start_whatsapp_bot(name, agent_config)
                elif isinstance(agent_config, SlackAgentConfig):
                    await self._start_slack_bot(name, agent_config)
                elif isinstance(agent_config, MSAgentSDKConfig):
                    await self._start_msagentsdk_bot(name, agent_config)
                elif isinstance(agent_config, A2AAgentConfig):
                    await self._start_a2a_bot(name, agent_config)
                elif isinstance(agent_config, MSAgentIntegrationConfig):
                    await self._start_msagent_bot(name, agent_config)
            except Exception as e:
                self.logger.error("Failed to start bot %s: %s", name, e, exc_info=True)

    async def _ensure_human_manager(self) -> HumanInteractionManager:
        """Lazily create the shared HumanInteractionManager + its Redis client."""
        if self.human_manager is None:
            import redis.asyncio as aioredis

            self._human_redis = aioredis.from_url(
                REDIS_URL, decode_responses=True
            )
            self.human_manager = HumanInteractionManager(
                redis_url=REDIS_URL,
            )
            # Expose it as the process-wide default so tools constructed
            # before integration startup can resolve the manager lazily.
            set_default_human_manager(self.human_manager)
        return self.human_manager

    async def _start_telegram_bot(self, name: str, config: TelegramAgentConfig):
        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
        if not agent:
            return

        # Lazy aiogram + Telegram HITL imports: keep the optional Telegram
        # dependency out of the import path for non-Telegram deployments.
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from parrot.human import TelegramHumanChannel

        bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
        dp = Dispatcher()
        from .telegram.wrapper import TelegramAgentWrapper
        # Resolve the aiohttp app so the wrapper can pull shared services
        # (``jira_oauth_manager``, ``authdb``/``database``, ``redis``) for
        # the FEAT-108 combined auth flow and /connect_jira. If the bot
        # manager was never attached to an aiohttp app, degrade gracefully.
        try:
            app = self.bot_manager.get_app()
        except RuntimeError:
            app = None
        wrapper = TelegramAgentWrapper(agent, bot, config, app=app)

        # Publish the Telegram command menu (setMyCommands + chat menu button)
        # so platform/agent commands (e.g. /connect_jira from JiraSpecialist)
        # appear in Telegram Desktop and mobile autocomplete.  The wrapper is
        # fully constructed here, so _platform_commands (Jira/Office365/MCP)
        # is already populated and flows into the published menu automatically.
        # Wrapped defensively: a menu failure must never abort bot startup.
        # Parity with TelegramBotManager._start_bot (FEAT-220).
        if config.register_menu:
            try:
                await wrapper.register_command_menu()
            except Exception:
                self.logger.warning(
                    "Failed to register Telegram command menu for '%s'",
                    name,
                    exc_info=True,
                )

        # HITL channel: shares the aiogram Bot. MUST be included BEFORE the
        # wrapper router so HITL replies (free_text / button callbacks) are
        # claimed first; otherwise the wrapper re-feeds the reply into the
        # agent loop and ask_human spirals infinitely.
        human_manager = await self._ensure_human_manager()
        human_channel = TelegramHumanChannel(
            bot=bot,
            redis=self._human_redis,
            voice_config=config.voice_config,
        )
        human_manager.register_channel(name, human_channel)
        await human_channel.register_response_handler(
            human_manager.receive_response
        )
        await human_channel.register_cancel_handler(
            human_manager.cancel_pending
        )
        dp.include_router(human_channel.router)
        dp.include_router(wrapper.router)

        # Expose manager + channel key on the agent so tools can find them
        if agent is not None:
            setattr(agent, "_human_manager", human_manager)
            setattr(agent, "_human_channel_key", name)

        self.telegram_bots[name] = (bot, dp, wrapper)

        task = asyncio.create_task(
            self._run_polling(name, dp, bot),
            name=f"telegram_polling_{name}"
        )
        self._polling_tasks.append(task)
        self.logger.info(
            "Started Telegram bot '%s' (HITL channel registered as '%s')", name, name
        )

    async def _run_polling(self, name: str, dp: Dispatcher, bot: Bot):
        try:
            await dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query"],
                handle_signals=False,
                close_bot_session=True
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error("Polling error for %s: %s", name, e)

    async def _start_msteams_bot(self, name: str, config: MSTeamsAgentConfig):
        agent = await self._get_agent(config.chatbot_id)
        if not agent:
            return

        # Wire JiraOAuthManager if Jira OAuth is configured (FEAT-225).
        app = self.bot_manager.get_app()
        jira_oauth_manager = None
        if getattr(config, "jira_client_id", None):
            existing = app.get("jira_oauth_manager")
            if existing is not None:
                jira_oauth_manager = existing
                self.logger.info(
                    "MS Teams bot '%s': reusing existing JiraOAuthManager from app",
                    name,
                )
            else:
                try:
                    from parrot.auth.jira_oauth import JiraOAuthManager

                    jira_oauth_manager = JiraOAuthManager(
                        client_id=config.jira_client_id,
                        client_secret=config.jira_client_secret,
                        redirect_uri=config.jira_redirect_uri,
                        app=app,
                    )
                    self.logger.info(
                        "MS Teams bot '%s': initialized JiraOAuthManager", name
                    )
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "MS Teams bot '%s': failed to initialize JiraOAuthManager: %s",
                        name,
                        exc,
                    )

        # Initialize Wrapper (which registers the route)
        from .msteams.wrapper import MSTeamsAgentWrapper
        wrapper = MSTeamsAgentWrapper(
            agent=agent,
            config=config,
            app=app,
            forms_directory=config.forms_directory or AGENTS_DIR / "forms",
            oauth_manager=jira_oauth_manager,
        )
        self.msteams_bots[name] = wrapper
        self.logger.info("Started MS Teams bot '%s'", name)

    async def _start_whatsapp_bot(self, name: str, config: WhatsAppAgentConfig):
        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
        if not agent:
            return

        # Initialize Wrapper (which registers the webhook routes)
        from .whatsapp.wrapper import WhatsAppAgentWrapper
        wrapper = WhatsAppAgentWrapper(
            agent=agent,
            config=config,
            app=self.bot_manager.get_app(),
        )
        self.whatsapp_bots[name] = wrapper
        self.logger.info("Started WhatsApp bot '%s'", name)


    async def _start_msagentsdk_bot(self, name: str, config: MSAgentSDKConfig) -> None:
        """Start a Microsoft 365 Agents SDK bot.

        Resolves the parrot agent from BotManager, creates an
        ``MSAgentSDKWrapper`` (which registers the HTTP route on the
        aiohttp app), and stores the wrapper in ``msagentsdk_bots``.

        Args:
            name: Agent name as declared in the YAML config.
            config: ``MSAgentSDKConfig`` for this bot.
        """
        agent = await self._get_agent(
            config.chatbot_id,
            config.system_prompt_override,
        )
        if not agent:
            return

        from .msagentsdk.wrapper import MSAgentSDKWrapper

        wrapper = MSAgentSDKWrapper(
            agent=agent,
            config=config,
            app=self.bot_manager.get_app(),
        )
        self.msagentsdk_bots[name] = wrapper
        self.logger.info("Started MS Agent SDK bot '%s'", name)

    # A2A endpoint sub-paths registered by ``A2AServer.setup()`` under an
    # agent's ``base_path`` (``{base_path}/message/*``, ``{base_path}/tasks/*``,
    # ``{base_path}/rpc``). Used to scope the security middleware to ONLY the
    # authenticated routes of the agent it belongs to — see ``_wire_a2a_security``.
    _A2A_PROTECTED_SEGMENTS: Tuple[str, ...] = ("message", "tasks", "rpc")

    def _wire_a2a_security(
        self, app: web.Application, config: Any, base_path: str
    ) -> None:
        """Build and attach a path-scoped ``A2ASecurityMiddleware`` for an A2A agent.

        Wires whichever authenticators correspond to the security fields set
        on *config* (JWT, mTLS, API key / HMAC via the in-memory credential
        provider) and appends the resulting middleware to *app*.

        The middleware is **scoped to this agent's own routes** (those under
        ``base_path`` — ``/message/*``, ``/tasks/*``, ``/rpc``). aiohttp
        middlewares are application-global, so an unscoped
        ``A2ASecurityMiddleware`` on the *shared* app would authenticate every
        other integration's routes too (Telegram/Slack/MSTeams/WhatsApp
        webhooks, the public ``/a2a/directory`` listing, and any other A2A
        agent mounted at a deeper ``base_path``), locking them out with 401s
        the moment one A2A agent enables auth. The scope wrapper only delegates
        to the real middleware for requests that target this agent's endpoints;
        everything else passes straight through.

        Shared by ``_start_a2a_bot()`` (``A2AAgentConfig``, TASK-1709) and the
        A2A companion surface in ``_start_msagent_bot()``
        (``MSAgentIntegrationConfig``, TASK-1710) — the latter only carries
        ``jwt_secret``/``api_key``, not the full mTLS/HMAC/basic-auth/policy
        surface, so every field is read via ``getattr(..., None)`` rather
        than direct attribute access.

        Args:
            app: The aiohttp application the A2A agent is mounted on.
            config: ``A2AAgentConfig`` or ``MSAgentIntegrationConfig``
                carrying the security fields.
            base_path: The agent's route prefix (e.g. ``/a2a`` or
                ``/a2a/<name>``); the middleware only guards paths under it.
        """
        from parrot.a2a.security import (
            A2ASecurityMiddleware,
            SecurityPolicy,
            JWTAuthenticator,
            MTLSAuthenticator,
            InMemoryCredentialProvider,
        )

        jwt_secret = getattr(config, "jwt_secret", None)
        mtls_ca_cert = getattr(config, "mtls_ca_cert", None)
        api_key = getattr(config, "api_key", None)
        hmac_secret = getattr(config, "hmac_secret", None)
        basic_credentials = getattr(config, "basic_credentials", None)
        security_policy = getattr(config, "security_policy", None)

        jwt_authenticator = None
        if jwt_secret:
            jwt_authenticator = JWTAuthenticator(secret_key=jwt_secret)

        mtls_authenticator = None
        if mtls_ca_cert:
            mtls_authenticator = MTLSAuthenticator(ca_cert_path=mtls_ca_cert)

        credential_provider = None
        if api_key or hmac_secret or basic_credentials:
            credential_provider = InMemoryCredentialProvider()

        policy_kwargs = dict(security_policy or {})
        default_policy = SecurityPolicy(**policy_kwargs)

        # Populate the credential provider with the configured secrets so
        # that inbound requests carrying x-api-key / HMAC / basic-auth
        # can actually be validated. Without this the provider stays empty
        # and every API-key check returns None → 401.
        # register_agent() is async but only does dict ops — populate
        # the internal dicts directly to avoid event-loop nesting.
        if credential_provider is not None:
            agent_name = getattr(config, "name", None) or "a2a-agent"
            agent_data: Dict[str, Any] = {
                "permissions": [],
                "roles": [],
                "scopes": [],
                "metadata": {},
            }
            credential_provider._agents[agent_name] = agent_data
            if api_key:
                agent_data["api_key"] = api_key
                credential_provider._api_keys[api_key] = agent_name
            if hmac_secret:
                agent_data["hmac_secret"] = hmac_secret
                credential_provider._hmac_secrets[agent_name] = hmac_secret

        middleware = A2ASecurityMiddleware(
            jwt_authenticator=jwt_authenticator,
            mtls_authenticator=mtls_authenticator,
            credential_provider=credential_provider,
            default_policy=default_policy,
        )

        # Only guard THIS agent's authenticated endpoints. Matching on the
        # exact endpoint sub-paths (rather than a bare ``base_path`` prefix)
        # keeps agents isolated even when their base paths nest — e.g. agent 1
        # at ``/a2a`` must NOT catch agent 2's ``/a2a/<name>/...`` routes, and
        # the public ``/a2a/directory`` listing must stay unauthenticated.
        protected_prefixes = tuple(
            f"{base_path}/{segment}" for segment in self._A2A_PROTECTED_SEGMENTS
        )
        inner_middleware = middleware.middleware

        @web.middleware
        async def scoped_a2a_security(request: web.Request, handler):
            if request.path.startswith(protected_prefixes):
                return await inner_middleware(request, handler)
            return await handler(request)

        app.middlewares.append(scoped_a2a_security)
        self.logger.info(
            "Wired scoped A2ASecurityMiddleware for agent config '%s' "
            "(guarding paths under %s)",
            config.name,
            base_path,
        )

    def _parse_credential_configs(
        self, raw_configs: List[Dict[str, Any]], bot_name: str
    ) -> List[Any]:
        """Parse raw credential dicts into ``ProviderCredentialConfig`` objects.

        Each entry is validated independently: a malformed dict is skipped with
        a warning rather than aborting the whole bot startup. This mirrors the
        ``CredentialBroker.from_config(strict=False)`` contract — invalid
        credential configs are skipped, not fatal — which an eager
        ``[ProviderCredentialConfig(**c) for c in ...]`` comprehension would
        otherwise defeat by raising before ``from_config`` ever runs.

        Args:
            raw_configs: Inline credential dicts from the YAML config.
            bot_name: Bot name, for log context.

        Returns:
            The successfully parsed ``ProviderCredentialConfig`` list (possibly
            shorter than the input when entries are skipped).
        """
        from parrot.auth.credentials import ProviderCredentialConfig

        parsed: List[Any] = []
        for entry in raw_configs:
            try:
                parsed.append(ProviderCredentialConfig(**entry))
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Bot '%s': skipping invalid credential config %r: %s",
                    bot_name,
                    entry,
                    exc,
                )
        return parsed

    async def _start_a2a_bot(self, name: str, config: A2AAgentConfig) -> None:
        """Start an agent as an A2A (Agent-to-Agent protocol) service.

        Resolves the parrot agent from BotManager, optionally builds a
        ``CredentialBroker`` from the inline ``credentials`` list, wraps the
        agent with ``A2AServer``, mounts it on the shared aiohttp app (or a
        dedicated ``TCPSite`` when ``config.port`` is set), registers its
        ``AgentCard`` in the in-process discovery registry, and wires
        ``A2ASecurityMiddleware`` when any security field is configured.

        Args:
            name: Agent name as declared in the YAML config.
            config: ``A2AAgentConfig`` for this bot.
        """
        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
        if not agent:
            return

        try:
            from parrot.a2a.server import A2AServer
        except ImportError:
            self.logger.warning(
                "Cannot start A2A bot '%s': ai-parrot-server is not installed.",
                name,
            )
            return

        # Build credential broker if enabled. Parse defensively so a single
        # malformed credential dict is skipped (not fatal) — consistent with
        # ``CredentialBroker.from_config(strict=False)``.
        broker = None
        if config.enable_credential_broker and config.credentials:
            from parrot.auth.broker import CredentialBroker

            configs = self._parse_credential_configs(config.credentials, name)
            broker = CredentialBroker.from_config(configs, strict=False)

        app = self.bot_manager.get_app()

        # Init discovery registry (shared across all A2A + msagent-companion bots)
        app.setdefault("a2a_discovery_registry", {})

        # Register the discovery listing route once on the shared app,
        # regardless of whether THIS agent is mounted there or on a
        # dedicated port — /a2a/directory always lives on the shared app.
        if not app.get("a2a_directory_registered"):
            app.router.add_get("/a2a/directory", handle_a2a_directory)
            app["a2a_directory_registered"] = True

        # Avoid base_path collisions when multiple A2A agents share the app:
        # only the first agent may keep the default "/a2a" path.
        used_base_paths: set = app.setdefault("a2a_base_paths", set())
        base_path = config.base_path
        if base_path in used_base_paths:
            base_path = f"{config.base_path}/{name.lower()}"
        used_base_paths.add(base_path)

        # Dynamically exclude this agent's A2A surface from the
        # navigator auth/ABAC middleware chain — A2A endpoints use their
        # own security (A2ASecurityMiddleware), not the session-based
        # ABAC chain. Covers any base_path, including non-default values
        # and collision-avoidance suffixes.
        from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY  # noqa: E402
        exclude_list: list = app.setdefault(AUTH_EXCLUDE_LIST_KEY, [])
        for pattern in (base_path, f"{base_path}/*"):
            if pattern not in exclude_list:
                exclude_list.append(pattern)

        a2a_server = A2AServer(
            agent=agent,
            base_path=base_path,
            tags=config.tags,
            broker=broker,
            output_mode=getattr(config, "output_mode", "text"),
        )

        has_security = bool(
            config.jwt_secret or config.api_key or config.mtls_ca_cert
            or config.hmac_secret or config.basic_credentials
        )

        if config.port:
            # Dedicated port: mount on a standalone sub-application. Security
            # middleware and routes MUST be registered before ``runner.setup()``
            # — aiohttp freezes the app's middlewares/router at that point.
            # This app hosts only this agent, so it always owns its own
            # ``/.well-known/agent.json`` card route.
            target_app = web.Application()
            target_app["a2a_discovery_registry"] = app["a2a_discovery_registry"]
            if has_security:
                self._wire_a2a_security(target_app, config, base_path)
            a2a_server.setup(target_app, url=config.url, register_well_known=True)
            runner = web.AppRunner(target_app)
            await runner.setup()
            try:
                site = web.TCPSite(runner, "0.0.0.0", config.port)
                await site.start()
                self._a2a_runners.append(runner)
            except OSError as exc:
                self.logger.error(
                    "Failed to start dedicated A2A port %s for bot '%s': %s",
                    config.port,
                    name,
                    exc,
                )
                await runner.cleanup()
                return
        else:
            # Shared app: this runs from the aiohttp ``on_startup`` signal
            # (via IntegrationBotManager.startup()), before the app is
            # frozen, so middleware/router mutation here is safe.
            #
            # ``/.well-known/agent.json`` is a single fixed route per app: only
            # the FIRST A2A agent registers it (its card is what the endpoint
            # serves); later agents rely on ``/a2a/directory`` for discovery
            # (spec §"Known Risks"). Registering it more than once would leave
            # a redundant, unreachable second route on the shared router.
            target_app = app
            if has_security:
                self._wire_a2a_security(target_app, config, base_path)
            register_well_known = not app.get("a2a_well_known_registered", False)
            a2a_server.setup(
                target_app,
                url=config.url,
                register_well_known=register_well_known,
            )
            app["a2a_well_known_registered"] = True

        # Register in discovery registry
        card = a2a_server.get_agent_card()
        app["a2a_discovery_registry"][name] = card

        self.a2a_bots[name] = a2a_server
        self.logger.info("Started A2A bot '%s' at %s", name, base_path)

    async def _setup_o365_oauth(self, app: web.Application, manager: Any) -> None:
        """Wire an ``O365OAuthManager`` into *app*, tolerating a frozen ``on_startup``.

        ``O365OAuthManager.setup()`` (inherited from ``AbstractOAuth2Manager``)
        appends itself to ``app.on_startup`` to resolve its Redis client
        lazily. ``_start_msagent_bot()`` runs from the shared app's OWN
        ``on_startup`` dispatch (``IntegrationBotManager.startup()`` is
        invoked from ``BotManagerServer.on_startup``), and aiohttp freezes
        ``app.on_startup`` before dispatching it — so ``setup()``'s
        ``app.on_startup.append()`` would raise ``RuntimeError: Cannot modify
        frozen list`` in that context.

        This method distinguishes that expected timing case (detected up-front
        via ``app.on_startup.frozen``) from a genuine conflict — a *different*
        ``O365OAuthManager`` instance already bound to the same app slot — which
        it refuses rather than silently clobbering. During ``on_startup``
        dispatch only ``on_startup`` itself is frozen; ``app.router`` and
        ``app.on_cleanup`` remain mutable, so the callback route and cleanup
        hook can still be registered while the Redis client is resolved
        immediately.

        Args:
            app: The aiohttp application to wire the manager into.
            manager: An ``O365OAuthManager`` constructed with ``app=app``.

        Raises:
            RuntimeError: If the app slot is already bound to a *different*
                ``O365OAuthManager`` instance (conflicting O365 app
                registrations across bots).
        """
        slot = f"oauth2_manager_{manager.provider_id}"
        existing = app.get(slot)
        if existing is not None and existing is not manager:
            raise RuntimeError(
                f"app['{slot}'] is already bound to a different "
                "O365OAuthManager instance; multiple MSAgent bots must share a "
                "single O365 app registration rather than each registering "
                "their own."
            )

        if not app.on_startup.frozen:
            # Normal path: on_startup has not been dispatched yet, so the
            # manager's own setup() can append its startup hook safely.
            manager.setup()
            return

        # Frozen on_startup path: replicate setup()'s side effects without
        # touching the frozen on_startup signal, and resolve Redis immediately.
        from parrot.auth.oauth2_routes import setup_oauth2_routes

        app[slot] = manager
        setup_oauth2_routes(app, manager.provider_id, manager._callback_path)
        manager._setup_done = True
        if not app.on_cleanup.frozen:
            app.on_cleanup.append(manager._on_cleanup)
        await manager._on_startup(app)

    async def _start_msagent_bot(self, name: str, config: MSAgentIntegrationConfig) -> None:
        """Start a full-featured MS Agent SDK bot with broker + A2A companion.

        Resolves the parrot agent from BotManager, converts *config* to the
        inner ``MSAgentSDKConfig`` via ``to_msagentsdk_config()``, optionally
        builds a ``CredentialBroker`` from the inline ``credentials`` list
        and an O365 OAuth2 SSO manager when ``o365_client_id`` is set,
        constructs the ``MSAgentSDKWrapper`` (which registers its HTTP
        route(s) on construction), and always mounts a companion A2A surface
        sharing the same broker (registered in the discovery registry).

        Args:
            name: Agent name as declared in the YAML config.
            config: ``MSAgentIntegrationConfig`` for this bot.
        """
        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override)
        if not agent:
            return

        sdk_config = config.to_msagentsdk_config()

        # Build credential broker if enabled. Parse defensively so a single
        # malformed credential dict is skipped (not fatal) — consistent with
        # ``CredentialBroker.from_config(strict=False)``.
        broker = None
        if config.enable_credential_broker and config.credentials:
            from parrot.auth.broker import CredentialBroker

            configs = self._parse_credential_configs(config.credentials, name)
            broker = CredentialBroker.from_config(configs, strict=False)

        app = self.bot_manager.get_app()

        # O365 OAuth2 SSO infrastructure (optional). One O365 app registration
        # is shared per aiohttp app (single callback route). If another bot
        # already wired an O365 manager, reuse it rather than constructing a
        # second one that would clobber the first bot's slot/route.
        if config.o365_client_id and config.o365_client_secret:
            from parrot.auth.o365_oauth import O365OAuthManager

            o365_slot = f"oauth2_manager_{O365OAuthManager.provider_id}"
            if app.get(o365_slot) is not None:
                self.logger.info(
                    "MSAgent bot '%s': reusing existing O365OAuthManager from app",
                    name,
                )
            else:
                o365_manager = O365OAuthManager(
                    client_id=config.o365_client_id,
                    client_secret=config.o365_client_secret,
                    redirect_uri=config.redirect_uri,
                    tenant_id=config.o365_tenant_id or "common",
                    app=app,
                )
                await self._setup_o365_oauth(app, o365_manager)

        # Create MS Agent SDK wrapper (constructor registers the HTTP
        # route(s) synchronously — no separate async setup() call).
        from .msagentsdk.wrapper import MSAgentSDKWrapper

        wrapper = MSAgentSDKWrapper(
            agent=agent,
            config=sdk_config,
            app=app,
            broker=broker,
        )
        self.msagent_bots[name] = wrapper

        # Companion A2A surface (always-on per spec)
        try:
            from parrot.a2a.server import A2AServer

            app.setdefault("a2a_discovery_registry", {})
            if not app.get("a2a_directory_registered"):
                app.router.add_get("/a2a/directory", handle_a2a_directory)
                app["a2a_directory_registered"] = True

            companion_path = f"/a2a/{name.lower()}"

            # Exclude this companion's A2A surface from the navigator
            # auth/ABAC chain — same rationale as _start_a2a_bot().
            from navigator_auth.conf import AUTH_EXCLUDE_LIST_KEY  # noqa: E402
            exclude_list: list = app.setdefault(AUTH_EXCLUDE_LIST_KEY, [])
            for pattern in (companion_path, f"{companion_path}/*"):
                if pattern not in exclude_list:
                    exclude_list.append(pattern)

            # Wire security when ANY auth field is configured — not just
            # ``jwt_secret``. ``MSAgentIntegrationConfig`` carries ``jwt_secret``
            # and ``api_key``; gating on ``jwt_secret`` alone would leave an
            # ``api_key``-only companion surface unauthenticated.
            companion_has_security = bool(config.jwt_secret or config.api_key)
            if companion_has_security:
                self._wire_a2a_security(app, config, companion_path)

            a2a_server = A2AServer(
                agent=agent,
                base_path=companion_path,
                tags=config.tags,
                broker=broker,
                output_mode=getattr(config, "output_mode", "text"),
            )
            # Register the single ``/.well-known/agent.json`` route only if no
            # earlier A2A agent (or companion) already claimed it on this app.
            register_well_known = not app.get("a2a_well_known_registered", False)
            a2a_server.setup(
                app, url=config.url, register_well_known=register_well_known
            )
            app["a2a_well_known_registered"] = True
            card = a2a_server.get_agent_card()
            app["a2a_discovery_registry"][name] = card
            self.a2a_bots[name] = a2a_server
        except ImportError:
            self.logger.warning(
                "ai-parrot-server not installed — A2A companion skipped for '%s'",
                name,
            )

        self.logger.info("Started MSAgent bot '%s'", name)

    async def _start_slack_bot(self, name: str, config: SlackAgentConfig):
        # Suppress the verbose DEBUG/INFO output from the slack_sdk internals
        # (heartbeats, raw WebSocket frames, HTTP request dumps, etc.)
        logging.getLogger("slack_sdk").setLevel(logging.WARNING)

        agent = await self._get_agent(config.chatbot_id, config.system_prompt_override if hasattr(config, "system_prompt_override") else None)
        if not agent:
            return

        # Wire JiraOAuthManager if Jira OAuth is configured (FEAT-225).
        # Reuse an existing manager on the app if one was already set up by
        # another integration (same Atlassian app registration, single callback).
        app = self.bot_manager.get_app()
        jira_oauth_manager = None
        if getattr(config, "jira_client_id", None):
            existing = app.get("jira_oauth_manager")
            if existing is not None:
                jira_oauth_manager = existing
                self.logger.info(
                    "Slack bot '%s': reusing existing JiraOAuthManager from app", name
                )
            else:
                try:
                    from parrot.auth.jira_oauth import JiraOAuthManager

                    jira_oauth_manager = JiraOAuthManager(
                        client_id=config.jira_client_id,
                        client_secret=config.jira_client_secret,
                        redirect_uri=config.jira_redirect_uri,
                        app=app,
                    )
                    self.logger.info(
                        "Slack bot '%s': initialized JiraOAuthManager", name
                    )
                except Exception as exc:  # noqa: BLE001
                    self.logger.warning(
                        "Slack bot '%s': failed to initialize JiraOAuthManager: %s",
                        name,
                        exc,
                    )

        from .slack.wrapper import SlackAgentWrapper
        wrapper = SlackAgentWrapper(
            agent=agent,
            config=config,
            app=app,
            oauth_manager=jira_oauth_manager,
        )
        self.slack_bots[name] = wrapper

        # Start the wrapper's background cleanup
        await wrapper.start()

        # Check connection mode
        if config.connection_mode == "socket":
            from .slack.socket_handler import SlackSocketHandler

            handler = SlackSocketHandler(wrapper)
            wrapper._socket_handler = handler
            task = asyncio.create_task(
                handler.start(),
                name=f"slack_socket_{name}",
            )
            self._polling_tasks.append(task)
            self.logger.info("Started Slack bot '%s' (Socket Mode)", name)
        else:
            self.logger.info("Started Slack bot '%s' (Webhook Mode)", name)
    async def _start_matrix_crew(self, config_path: str) -> None:
        """Start a Matrix multi-agent crew from a YAML config file.

        Args:
            config_path: Path to the YAML crew configuration file.
        """
        try:
            from .matrix.crew import MatrixCrewTransport

            transport = MatrixCrewTransport.from_yaml(config_path)
            await transport.start()
            self.matrix_crew = transport
            self.logger.info("✅ Started Matrix crew transport from %s", config_path)
        except Exception as exc:
            self.logger.error(
                "Failed to start Matrix crew transport: %s", exc, exc_info=True
            )

    async def shutdown(self) -> None:
        """Shutdown bots."""
        self.logger.info("Shutting down Integration Manager...")
        
        # First, cancel all polling tasks to stop the polling loops
        for task in self._polling_tasks:
            if not task.done():
                task.cancel()
        
        # Wait for all polling tasks to complete (with timeout)
        if self._polling_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._polling_tasks, return_exceptions=True),
                    timeout=5.0
                )
                self.logger.info("All polling tasks cancelled successfully")
            except asyncio.TimeoutError:
                self.logger.warning("Timeout waiting for polling tasks to cancel")
            except Exception as e:
                self.logger.error("Error while cancelling polling tasks: %s", e)
        
        # Now close bot sessions
        for name, (bot, dp, _) in self.telegram_bots.items():
            try:
                self.logger.debug("Closing session for bot '%s'", name)
                await bot.session.close()
            except Exception as e:
                self.logger.error("Error closing bot session for '%s': %s", name, e)

        # Stop MS Agent SDK bots
        for name, wrapper in self.msagentsdk_bots.items():
            try:
                self.logger.debug("Stopping MS Agent SDK bot '%s'", name)
                await wrapper.stop()
            except Exception as e:
                self.logger.error("Error stopping MS Agent SDK bot '%s': %s", name, e)

        # Stop MSAgent bots (full-featured surface + A2A companion)
        for name, wrapper in self.msagent_bots.items():
            try:
                self.logger.debug("Stopping MSAgent bot '%s'", name)
                await wrapper.stop()
            except Exception as e:
                self.logger.error("Error stopping MSAgent bot '%s': %s", name, e)

        # Stop Slack bots (including Socket Mode handlers)
        for name, wrapper in self.slack_bots.items():
            try:
                self.logger.debug("Stopping Slack bot '%s'", name)
                # Stop Socket Mode handler if present
                if hasattr(wrapper, "_socket_handler") and wrapper._socket_handler:
                    await wrapper._socket_handler.stop()
                # Stop the wrapper
                await wrapper.stop()
            except Exception as e:
                self.logger.error("Error stopping Slack bot '%s': %s", name, e)
        
        # Stop dedicated-port A2A runners (shared-app A2A bots are torn down
        # with the shared app itself and need no explicit cleanup here).
        for runner in self._a2a_runners:
            try:
                self.logger.debug("Stopping dedicated A2A runner")
                await runner.cleanup()
            except Exception as e:
                self.logger.error("Error stopping A2A runner: %s", e)

        # Stop Matrix crew transport (FEAT-044)
        if self.matrix_crew is not None:
            try:
                await self.matrix_crew.stop()
                self.logger.info("Matrix crew transport stopped")
            except Exception as exc:
                self.logger.error(
                    "Error stopping Matrix crew transport: %s", exc
                )
            self.matrix_crew = None

        # Close HITL manager (cancels pending futures + closes its Redis)
        if self.human_manager is not None:
            try:
                await self.human_manager.close()
            except Exception as exc:
                self.logger.warning("Error closing HumanInteractionManager: %s", exc)
            self.human_manager = None
            set_default_human_manager(None)
        if self._human_redis is not None:
            try:
                await self._human_redis.close()
            except Exception as exc:
                self.logger.warning("Error closing HITL Redis client: %s", exc)
            self._human_redis = None

        # Clear data structures
        self.telegram_bots.clear()
        self.msteams_bots.clear()
        self.whatsapp_bots.clear()
        self.slack_bots.clear()
        self.msagentsdk_bots.clear()
        self.a2a_bots.clear()
        self.msagent_bots.clear()
        self._a2a_runners.clear()
        self._polling_tasks.clear()

        self.logger.info("Integration Manager shutdown complete")
