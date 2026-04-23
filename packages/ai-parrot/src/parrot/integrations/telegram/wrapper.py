"""
Telegram Agent Wrapper.

Connects Telegram messages to AI-Parrot agents with per-chat conversation memory.
Supports:
- Direct messages (private chats)
- Group messages with @mentions
- Group commands (/ask)
- Channel posts (optional)
"""
from typing import Dict, Any, List, Optional, Tuple, TYPE_CHECKING, Callable
from pathlib import Path
import asyncio
import contextlib
import tempfile
import re
import json
import secrets
import markdown2
from aiogram import Bot, Router, F
from aiogram.enums import ChatAction, ChatType
from aiogram.types import (
    Message, ContentType, FSInputFile, BotCommand,
    ReplyKeyboardRemove,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandStart, Command
from parrot.integrations.core.state import IntegrationStateManager
from navconfig.logging import logging
from .callbacks import (
    CallbackRegistry,
    CallbackContext,
    CallbackResult
)
from .combined_callback import COMBINED_CALLBACK_PATH
from .context import telegram_chat_scope
from .models import TelegramAgentConfig
from .auth import (
    TelegramUserSession,
    AbstractAuthStrategy,
    BasicAuthStrategy,
    OAuth2AuthStrategy,
    AzureAuthStrategy,
    CompositeAuthStrategy,
)
from .filters import BotMentionedFilter
from .post_auth import PostAuthRegistry
from .utils import extract_query_from_mention
from ..parser import parse_response, ParsedResponse
from ...auth.context import UserContext
from ...models.outputs import OutputMode

if TYPE_CHECKING:
    from aiohttp import web
    from ...bots.abstract import AbstractBot
    from ...memory import ConversationMemory
    from ...voice.transcriber import VoiceTranscriber


class TelegramAgentWrapper:
    """
    Wraps an Agent/AgentCrew/AgentFlow for Telegram integration.

    Manages:
    - Per-chat conversation memory
    - Message routing from Telegram to agent
    - Response formatting for Telegram
    - File/image handling

    Attributes:
        agent: The AI-Parrot agent instance
        bot: The aiogram Bot instance
        config: Telegram configuration for this agent
        router: aiogram Router with registered handlers
        conversations: Per-chat conversation memories
    """

    def __init__(
        self,
        agent: 'AbstractBot',
        bot: Bot,
        config: TelegramAgentConfig,
        agent_commands: list = None,
        *,
        app: Optional["web.Application"] = None,
    ):
        self.agent = agent
        self.bot = bot
        self.config = config
        # aiohttp application carrying shared services
        # (``jira_oauth_manager``, ``authdb``/``database``, ``redis``).
        # Optional so non-aiohttp callers keep working; FEAT-108 combined
        # flow and /connect_jira require it to be set.
        self.app = app
        self.router = Router()
        self.conversations: Dict[int, 'ConversationMemory'] = {}
        self.logger = logging.getLogger(f"TelegramWrapper.{config.name}")

        # Agent-declared commands (from @telegram_command decorator)
        self._agent_commands: list = agent_commands or []
        # Per-user session cache (keyed by Telegram user ID)
        self._user_sessions: Dict[int, TelegramUserSession] = {}

        # Serializes ``self.agent.tool_manager`` swap in singleton_agent mode.
        # Concurrent Telegram messages would otherwise race on the shared
        # agent's tool_manager attribute (user A's swap visible to user B).
        # Only acquired when ``config.singleton_agent`` is True; the
        # per-user-agent mode does not need it because each user has its
        # own agent instance.
        self._agent_lock: asyncio.Lock = asyncio.Lock()

        # FEAT-120: Per-chat message ID → text snippet cache for O(1) reply lookup.
        # Structure: {chat_id: {message_id: text_snippet[:200]}}
        # Each chat is capped at 100 entries (FIFO eviction).
        self._message_id_cache: Dict[int, Dict[int, str]] = {}

        # ─── FEAT-108 / FEAT-109: Secondary auth providers ───
        # Built BEFORE the auth strategy so AzureAuthStrategy can receive
        # the registry at construction time (Approach A, TASK-778).
        # Populated from config.post_auth_actions; empty if not configured.
        # Missing services degrade gracefully (combined flow is disabled).
        self._post_auth_registry: PostAuthRegistry = PostAuthRegistry()
        self._init_post_auth_providers()

        # Auth strategy (Composite, Azure, OAuth2, or Basic, depending on config)
        # FEAT-109: extracted to _build_auth_strategy; routes to CompositeAuthStrategy
        # when auth_methods lists >= 2 entries.
        self._auth_strategy = self._build_auth_strategy(config)

        # ─── NEW: Callback infrastructure ───
        self._callback_registry = CallbackRegistry()
        self._state_manager = IntegrationStateManager()
        
        # We need the orchestrator if this is a managed environment
        discovered = self._callback_registry.discover_from_agent(self.agent)
        if discovered:
            self.logger.info(
                f"Discovered {discovered} callback handler(s): "
                f"{', '.join(self._callback_registry.prefixes)}"
            )
        # Give the agent a back-reference to the wrapper (for proactive messaging)
        if hasattr(self.agent, 'set_wrapper'):
            self.agent.set_wrapper(self)

        # Voice transcriber (lazy — created on first voice message)
        self._transcriber: Optional["VoiceTranscriber"] = None

        # Register message handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register aiogram message handlers on the router."""
        # /start command (works in both private and group chats)
        self.router.message.register(
            self.handle_start,
            CommandStart()
        )

        # /help command — briefing with available options
        self.router.message.register(
            self.handle_help,
            Command("help")
        )

        # /whoami — agent name and description
        self.router.message.register(
            self.handle_whoami,
            Command("whoami")
        )

        # /commands — list all registered commands
        self.router.message.register(
            self.handle_commands,
            Command("commands")
        )

        # /clear command to reset conversation
        self.router.message.register(
            self.handle_clear,
            Command("clear")
        )

        # /skill <name> [args] — invoke a tool by name
        self.router.message.register(
            self.handle_skill,
            Command("skill")
        )

        # /function <method> [key=val ...] — invoke agent method with kwargs
        self.router.message.register(
            self.handle_function,
            Command("function")
        )

        # /question <text> — pure LLM query without tools
        self.router.message.register(
            self.handle_question,
            Command("question")
        )

        # /call command to invoke agent methods (backward compat)
        self.router.message.register(
            self.handle_call,
            Command("call")
        )

        # /login — authenticate via configured strategy (if enabled)
        if self.config.enable_login and self._auth_strategy:
            self.router.message.register(
                self.handle_login,
                Command("login")
            )
            self.router.message.register(
                self.handle_logout,
                Command("logout")
            )
            # Handle WebApp data returned from login page
            self.router.message.register(
                self.handle_web_app_data,
                F.web_app_data,
            )

        # Register Jira OAuth 2.0 (3LO) commands when a manager is wired in.
        self._register_jira_commands()
        self._register_office365_commands()

        # Register /add_mcp, /list_mcp, /remove_mcp so users can attach
        # their own HTTP MCP server (e.g. Fireflies.ai) to their session.
        self._register_mcp_commands()

        # Register custom commands from config YAML
        for cmd_name, method_name in self.config.commands.items():
            self._register_custom_command(cmd_name, method_name)

        # Register agent-declared commands (@telegram_command decorator)
        self._register_agent_commands()

        # ─── Group/Channel Handlers (must be before generic text handler) ───

        # /ask command in groups (e.g., "/ask what is Python?" or "/ask@botname query")
        if self.config.enable_group_commands:
            self.router.message.register(
                self.handle_group_ask,
                Command("ask"),
                F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
            )

        # @mention in group messages
        if self.config.enable_group_mentions:
            self.router.message.register(
                self.handle_group_mention,
                BotMentionedFilter(),
                F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})
            )

        # Channel post handlers (if enabled)
        if self.config.enable_channel_posts:
            self.router.channel_post.register(
                self.handle_channel_mention,
                BotMentionedFilter()
            )

        # ─── Private Chat Handlers ───

        # Private chat text messages
        self.router.message.register(
            self.handle_message,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.TEXT
        )

        # Photo messages (private only for now)
        self.router.message.register(
            self.handle_photo,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.PHOTO
        )

        # Document messages (private only for now)
        self.router.message.register(
            self.handle_document,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.DOCUMENT
        )

        # Voice notes (private only — microphone recordings)
        self.router.message.register(
            self.handle_voice,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.VOICE
        )

        # Audio files (private only — forwarded audio)
        self.router.message.register(
            self.handle_voice,
            F.chat.type == ChatType.PRIVATE,
            F.content_type == ContentType.AUDIO
        )

        # ─── NEW: Callback Query Handler ───
        if self._callback_registry:
            self.router.callback_query.register(
                self._handle_callback_query
            )
            self.logger.info(
                f"Registered callback_query handler for prefixes: "
                f"{self._callback_registry.prefixes}"
            )

    def _register_custom_command(self, cmd_name: str, method_name: str) -> None:
        """Register a custom command that calls an agent method."""
        async def custom_handler(message: Message) -> None:
            await self._execute_agent_method(message, method_name, message.text or "")

        self.router.message.register(
            custom_handler,
            Command(cmd_name)
        )
        self.logger.info(f"Registered custom command /{cmd_name} -> {method_name}()")

    def _register_jira_commands(self) -> None:
        """Wire ``/connect_jira``, ``/disconnect_jira`` and ``/jira_status``.

        The Jira OAuth manager is resolved from ``app['jira_oauth_manager']``
        when OAuth 2.0 (3LO) is enabled for this agent. When the aiohttp app
        was not passed to the wrapper, or the key is absent, the commands are
        simply not registered — legacy deployments are unaffected.
        """
        oauth_manager = (
            self.app.get("jira_oauth_manager") if self.app is not None else None
        )
        if oauth_manager is None:
            return
        from .jira_commands import register_jira_commands

        # Closure over ``self._user_sessions`` so /disconnect_jira clears the
        # Jira identity from the in-memory session, preventing
        # ``_enrich_question`` from keeping the stale ``<jira>`` block in
        # the prompt after revocation.
        def _clear_jira_session(telegram_id: int) -> None:
            session = self._user_sessions.get(telegram_id)
            if session is not None:
                session.clear_jira_auth()
                self.logger.info(
                    "Cleared in-memory Jira identity for tg:%s after "
                    "/disconnect_jira", telegram_id,
                )

        register_jira_commands(
            self.router, oauth_manager, session_clearer=_clear_jira_session
        )
        self.logger.info(
            "Registered Jira OAuth commands: /connect_jira, "
            "/disconnect_jira, /jira_status",
        )

        # Expose a stamper so the OAuth callback route can surface the
        # connected Jira identity on the user's TelegramUserSession the
        # moment Atlassian redirects back — without this, the session
        # only carries the primary /login email and the LLM/tools see
        # the wrong identity on "my tickets".
        if self.app is not None and "telegram_jira_session_stamper" not in self.app:
            def _stamp(telegram_user_id: str, token_set: Any) -> None:
                try:
                    tg_id = int(telegram_user_id)
                except (TypeError, ValueError):
                    self.logger.warning(
                        "Ignoring Jira session stamp: non-integer telegram_user_id=%r",
                        telegram_user_id,
                    )
                    return
                session = self._user_sessions.get(tg_id)
                if session is None:
                    # First contact via OAuth callback — create the shell;
                    # it will be enriched by the next Telegram message.
                    session = TelegramUserSession(telegram_id=tg_id)
                    self._user_sessions[tg_id] = session
                session.set_jira_authenticated(
                    account_id=getattr(token_set, "account_id", "") or "",
                    email=getattr(token_set, "email", None),
                    display_name=getattr(token_set, "display_name", None),
                    cloud_id=getattr(token_set, "cloud_id", None),
                )
                self.logger.info(
                    "Stamped Jira identity on tg:%s (account=%s email=%s)",
                    tg_id,
                    getattr(token_set, "account_id", None),
                    getattr(token_set, "email", None),
                )

            self.app["telegram_jira_session_stamper"] = _stamp

    def _register_office365_commands(self) -> None:
        """Wire Office365 delegated auth commands.

        Commands mirror Jira command ergonomics but source credentials from
        the existing Telegram OAuth2 login session.
        """
        methods = set(getattr(self.config, "auth_methods", []) or [])
        if "oauth2" not in methods:
            return

        from .office365_commands import register_office365_commands

        def _session_provider(telegram_id: int) -> TelegramUserSession:
            session = self._user_sessions.get(telegram_id)
            if session is None:
                session = TelegramUserSession(telegram_id=telegram_id)
                self._user_sessions[telegram_id] = session
            return session

        register_office365_commands(self.router, _session_provider)
        self.logger.info(
            "Registered Office365 commands: /connect_office365, "
            "/disconnect_office365, /office365_status",
        )

    def _register_mcp_commands(self) -> None:
        """Wire ``/add_mcp``, ``/list_mcp`` and ``/remove_mcp``.

        Per-user MCP servers live on the user's isolated ``ToolManager``
        clone built by ``_initialize_user_context``. The handler module
        only needs (a) a resolver to fetch that per-user ToolManager on
        demand and (b) the Redis client for persistence across restarts.
        When Redis is absent the commands degrade gracefully — servers
        still work for the current session but are not saved.
        """
        from .mcp_commands import register_mcp_commands

        async def _resolver(message: Message) -> Optional[Any]:
            session = self._get_user_session(message)
            # Build per-user state on demand so users can issue /add_mcp
            # immediately after /login even if they haven't spoken to the
            # agent yet.
            if not session.post_login_ran:
                await self._initialize_user_context(session, message=message)
            return self._get_user_tool_manager(session)

        register_mcp_commands(self.router, _resolver)
        self.logger.info(
            "Registered MCP commands: /add_mcp, /list_mcp, /remove_mcp "
            "(vault-backed credentials)",
        )

    def _get_user_tool_manager(
        self, session: TelegramUserSession
    ) -> Optional[Any]:
        """Return the ToolManager the user should mutate for MCP commands.

        In ``singleton_agent`` mode this is ``session.tool_manager`` (the
        clone). In full-clone mode it is the per-user agent's own
        ToolManager. ``None`` when neither is populated yet (init skipped
        or failed).
        """
        if self.config.singleton_agent:
            return session.tool_manager
        if session.user_agent is not None:
            return getattr(session.user_agent, "tool_manager", None)
        return None

    # ──────────────────────────────────────────────────────────────────
    # FEAT-108 — Post-authentication providers (combined flow)
    # ──────────────────────────────────────────────────────────────────

    def _init_post_auth_providers(self) -> None:
        """Populate :pyattr:`_post_auth_registry` from the config.

        Reads ``config.post_auth_actions`` and, for each supported provider,
        instantiates the concrete provider together with its service
        dependencies resolved from the aiohttp application:

        * ``app['jira_oauth_manager']`` — the Jira OAuth manager
        * ``app['authdb']`` (preferred) or ``app['database']`` — DB pool
        * ``app['redis']`` — async Redis client

        Missing dependencies result in the provider being skipped with a
        warning; the standard BasicAuth flow still works unchanged.
        """
        actions = getattr(self.config, "post_auth_actions", None) or []
        if not actions:
            return

        if self.app is None:
            self.logger.warning(
                "post_auth_actions configured but aiohttp app not provided "
                "to TelegramAgentWrapper; combined flow disabled."
            )
            return

        jira_oauth = self.app.get("jira_oauth_manager")
        db_pool = self.app.get("authdb") or self.app.get("database")
        redis_client = self.app.get("redis")

        for action in actions:
            if action.provider == "jira":
                if jira_oauth is None:
                    self.logger.warning(
                        "post_auth_actions includes 'jira' but "
                        "app['jira_oauth_manager'] is not set; skipping."
                    )
                    continue
                if db_pool is None or redis_client is None:
                    self.logger.warning(
                        "post_auth_actions includes 'jira' but "
                        "app['authdb']/app['database'] or app['redis'] "
                        "is not set; combined flow will be disabled."
                    )
                    continue
                # Local imports avoid import cycles and keep the heavy
                # service modules out of the hot path for bots that don't
                # use the combined flow.
                from parrot.integrations.telegram.post_auth_jira import (
                    JiraPostAuthProvider,
                )
                from parrot.services.identity_mapping import (
                    IdentityMappingService,
                )
                from parrot.services.vault_token_sync import VaultTokenSync

                identity_service = IdentityMappingService(db_pool)
                vault_sync = VaultTokenSync(db_pool, redis_client)
                provider = JiraPostAuthProvider(
                    oauth_manager=jira_oauth,
                    identity_service=identity_service,
                    vault_sync=vault_sync,
                )
                self._post_auth_registry.register(provider)
                self.logger.info(
                    "Registered PostAuthProvider 'jira' "
                    "(required=%s)",
                    action.required,
                )
            else:
                self.logger.warning(
                    "post_auth_actions references unknown provider '%s'; "
                    "skipping.",
                    action.provider,
                )

    def _is_combined_payload(self, data: Dict[str, Any]) -> bool:
        """Return True if ``data`` contains any configured secondary auth key."""
        actions = getattr(self.config, "post_auth_actions", None) or []
        return any(
            action.provider in data
            and isinstance(data.get(action.provider), dict)
            for action in actions
        )

    async def _build_next_auth_url(
        self,
        session: TelegramUserSession,
    ) -> Tuple[Optional[str], bool]:
        """Build the redirect URL for the first configured post-auth provider.

        Returns:
            ``(next_auth_url, required)``. Returns ``(None, False)`` if the
            provider has no registered instance or URL construction fails.
        """
        actions = getattr(self.config, "post_auth_actions", None) or []
        for action in actions:
            provider = self._post_auth_registry.get(action.provider)
            if provider is None:
                continue
            try:
                callback_base = getattr(
                    self.config, "public_base_url", ""
                )
                url = await provider.build_auth_url(
                    session=session,
                    config=self.config,
                    callback_base_url=callback_base,
                )
                return url, action.required
            except Exception:  # noqa: BLE001
                self.logger.exception(
                    "Failed to build next_auth_url for provider '%s'",
                    action.provider,
                )
                return None, action.required
        return None, False

    # ------------------------------------------------------------------
    # FEAT-109: Auth strategy selection (extracted from __init__)
    # ------------------------------------------------------------------

    def _build_auth_strategy(
        self, config: "TelegramAgentConfig"
    ) -> Optional[AbstractAuthStrategy]:
        """Build and return the appropriate auth strategy for this agent.

        Routes based on the normalized ``config.auth_methods`` list:
        - 0 methods → ``None`` (authentication disabled).
        - 1 method  → the corresponding single-method strategy.
        - 2+ methods → ``CompositeAuthStrategy`` wrapping all valid members.

        Member strategies that are missing required config (e.g. ``azure``
        without ``azure_auth_url``) are skipped with a logged warning rather
        than raising.

        Args:
            config: TelegramAgentConfig with ``auth_methods`` already
                normalized by ``__post_init__`` (TASK-780).

        Returns:
            An ``AbstractAuthStrategy`` instance, or ``None`` if no methods
            are configured or all listed methods lack required config.
        """
        methods = list(getattr(config, "auth_methods", None) or [])
        if not methods:
            return None

        if len(methods) == 1:
            return self._build_single_strategy(methods[0], config)

        # Multi-method: build each member and wrap in Composite.
        strategies = {}
        for m in methods:
            strat = self._build_single_strategy(m, config)
            if strat is not None:
                strategies[m] = strat

        if not strategies:
            self.logger.warning(
                "Agent '%s': auth_methods listed but no valid strategy built; "
                "authentication disabled.",
                getattr(config, "name", "?"),
            )
            return None

        if len(strategies) == 1:
            # Only one survived config validation — no need for Composite.
            return next(iter(strategies.values()))

        return CompositeAuthStrategy(
            strategies=strategies,
            login_page_url=getattr(config, "login_page_url", None) or "",
        )

    def _build_single_strategy(
        self, method: str, config: "TelegramAgentConfig"
    ) -> Optional[AbstractAuthStrategy]:
        """Build a single-method auth strategy instance.

        Args:
            method: One of ``"basic"``, ``"azure"``, ``"oauth2"``.
            config: TelegramAgentConfig.

        Returns:
            The strategy instance, or ``None`` if required config is absent.
        """
        if method == "basic" and config.auth_url:
            # BasicAuthStrategy does NOT receive the post_auth_registry here.
            # It participates in the combined-auth flow via the wrapper's
            # _handle_combined_auth path, not via constructor injection.
            # AzureAuthStrategy uses Approach A (registry injected at
            # construction) because it drives the chain itself after JWT decode.
            return BasicAuthStrategy(config.auth_url, config.login_page_url)

        if method == "azure" and config.azure_auth_url:
            return AzureAuthStrategy(
                auth_url=config.auth_url or config.azure_auth_url,
                azure_auth_url=config.azure_auth_url,
                login_page_url=config.login_page_url,
                # Approach A (TASK-778): inject registry so Azure runs the chain
                # after successful JWT decode without wrapper involvement.
                post_auth_registry=self._post_auth_registry,
            )

        if method == "oauth2" and config.oauth2_client_id:
            return OAuth2AuthStrategy(config)

        self.logger.warning(
            "Agent '%s': auth_method '%s' listed but required config missing; "
            "skipping.",
            getattr(config, "name", "?"),
            method,
        )
        return None

    def _register_agent_commands(self) -> None:
        """Register commands declared via @telegram_command on the agent."""
        for cmd_info in self._agent_commands:
            cmd_name = cmd_info["command"]
            method = cmd_info["method"]
            parse_mode = cmd_info.get("parse_mode", "raw")

            async def agent_cmd_handler(
                message: Message,
                _method=method,
                _parse_mode=parse_mode,
            ) -> None:
                chat_id = message.chat.id
                if not self._is_authorized(chat_id):
                    await message.answer("⛔ You are not authorized to use this bot.")
                    return
                text = (message.text or "").split(maxsplit=1)
                raw_args = text[1] if len(text) > 1 else ""
                typing_task = asyncio.create_task(self._typing_indicator(chat_id))
                try:
                    if _parse_mode == "keyword":
                        kwargs = self._parse_kwargs(raw_args)
                        result = await _method(**kwargs) if asyncio.iscoroutinefunction(_method) else _method(**kwargs)
                    elif _parse_mode == "positional":
                        args = raw_args.split() if raw_args else []
                        result = await _method(*args) if asyncio.iscoroutinefunction(_method) else _method(*args)
                    else:  # raw
                        result = await _method(raw_args) if asyncio.iscoroutinefunction(_method) else _method(raw_args)
                    typing_task.cancel()
                    parsed = self._parse_response(result)
                    await self._send_parsed_response(message, parsed)
                except Exception as e:
                    typing_task.cancel()
                    self.logger.error(f"Error in agent command /{cmd_name}: {e}", exc_info=True)
                    await message.answer(f"❌ Error: {str(e)[:200]}")
                finally:
                    typing_task.cancel()

            self.router.message.register(agent_cmd_handler, Command(cmd_name))
            self.logger.info(
                f"Registered agent command /{cmd_name} -> {cmd_info['method_name']}()"
            )

    # Telegram Bot API constraints for BotCommand entries.
    # A single invalid entry makes the whole `setMyCommands` call 400, which
    # silently wipes the menu for every user, so we normalize aggressively.
    _CMD_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")
    _CMD_DESC_MAX = 256

    @classmethod
    def _sanitize_command_name(cls, raw: Any) -> Optional[str]:
        """Normalize a command name to Telegram's ``^[a-z0-9_]{1,32}$``.

        Lowercases, replaces hyphens and whitespace with underscores, drops
        anything else, and truncates to 32 chars. Returns ``None`` when the
        result is empty (caller should drop that command).
        """
        if not isinstance(raw, str):
            return None
        s = raw.strip().lower().lstrip("/")
        s = re.sub(r"[\s-]+", "_", s)
        s = re.sub(r"[^a-z0-9_]", "", s)
        s = s[:32]
        return s if s else None

    @classmethod
    def _sanitize_command_description(cls, raw: Any, fallback: str) -> str:
        """Collapse whitespace and enforce Telegram's 1..256 char window.

        Telegram rejects descriptions containing newlines or exceeding 256
        characters. Docstrings (the default for ``@telegram_command``) almost
        always contain newlines and leading indentation, which is why this
        silently killed the entire menu for agents that used the decorator.
        """
        text = "" if raw is None else str(raw)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            text = fallback
        return text[: cls._CMD_DESC_MAX]

    def _make_bot_command(
        self, command: Any, description: Any, *, fallback_desc: str
    ) -> Optional[BotCommand]:
        """Build a validated ``BotCommand`` or return ``None`` with a warning.

        Returning ``None`` for a single bad entry lets the caller skip it
        rather than losing the whole menu to a 400 from Telegram.
        """
        name = self._sanitize_command_name(command)
        if name is None:
            self.logger.warning(
                "Dropping Telegram command with invalid name %r", command
            )
            return None
        if not self._CMD_NAME_RE.match(name):
            self.logger.warning(
                "Dropping Telegram command %r: name %r violates Telegram rules",
                command, name,
            )
            return None
        desc = self._sanitize_command_description(description, fallback_desc)
        return BotCommand(command=name, description=desc)

    def get_bot_commands(self) -> list:
        """Build list of ``BotCommand`` for Telegram ``setMyCommands`` API.

        Every entry is sanitized and duplicates are dropped so a single bad
        definition (e.g. a docstring-derived description with newlines, or a
        YAML command name with uppercase letters) cannot wipe out the entire
        menu for this bot.
        """
        raw_entries: list[tuple[str, str]] = [
            ("start", "Start conversation"),
            ("help", "Show help and available options"),
            ("whoami", "Agent name and description"),
            ("commands", "List all available commands"),
            ("clear", "Reset conversation memory"),
            ("skill", "Call a tool by name"),
            ("function", "Call an agent method"),
            ("question", "Ask the LLM directly (no tools)"),
        ]
        # Authentication commands (when enabled)
        if self.config.enable_login and self._auth_strategy:
            methods = getattr(self.config, "auth_methods", [])
            if len(methods) > 1:
                login_desc = "Sign in"
            elif "oauth2" in methods:
                provider = getattr(self.config, "oauth2_provider", "oauth2") or "oauth2"
                login_desc = f"Sign in with {provider.capitalize()}"
            elif "azure" in methods:
                login_desc = "Sign in with Azure"
            else:
                login_desc = "Sign in with Navigator"
            raw_entries.append(("login", login_desc))
            raw_entries.append(("logout", "Sign out"))
            if "oauth2" in methods:
                raw_entries.append(
                    ("connect_office365", "Connect Office365 delegated access")
                )
                raw_entries.append(
                    ("disconnect_office365", "Disconnect Office365 access")
                )
                raw_entries.append(
                    ("office365_status", "Show Office365 connection status")
                )
        # Custom commands from YAML config
        for cmd_name, method_name in self.config.commands.items():
            raw_entries.append((cmd_name, f"Calls {method_name}()"))
        # Agent-declared commands from decorator
        for cmd_info in self._agent_commands:
            raw_entries.append(
                (
                    cmd_info.get("command", ""),
                    cmd_info.get("description", "")
                    or f"Calls {cmd_info.get('method_name', 'agent method')}()",
                )
            )

        commands: list[BotCommand] = []
        seen: set[str] = set()
        for raw_name, raw_desc in raw_entries:
            fallback = f"/{raw_name}" if isinstance(raw_name, str) and raw_name else "Command"
            bc = self._make_bot_command(raw_name, raw_desc, fallback_desc=fallback)
            if bc is None:
                continue
            if bc.command in seen:
                # Later definitions shadow earlier ones in the wrapper itself
                # (decorator can override a YAML mapping), but Telegram rejects
                # duplicates in a single call, so we dedupe by keeping the
                # first occurrence and warn on the collision.
                self.logger.warning(
                    "Duplicate Telegram command /%s — keeping first definition",
                    bc.command,
                )
                continue
            seen.add(bc.command)
            commands.append(bc)
        return commands

    @staticmethod
    def _parse_kwargs(text: str) -> dict:
        """Parse 'key=val key2=val2' or 'arg1 arg2' into kwargs/args dict."""
        if not text.strip():
            return {}
        # Support both space and comma separators
        parts = [p.strip() for p in text.replace(",", " ").split() if p.strip()]
        kwargs: dict = {}
        positional_idx = 0
        for part in parts:
            if "=" in part:
                key, _, val = part.partition("=")
                kwargs[key.strip()] = val.strip()
            else:
                kwargs[f"arg{positional_idx}"] = part
                positional_idx += 1
        return kwargs

    def _is_authorized(self, chat_id: int) -> bool:
        """Check if chat is authorized to use this bot."""
        if self.config.allowed_chat_ids is None:
            return True
        return chat_id in self.config.allowed_chat_ids

    def _get_or_create_memory(self, chat_id: int) -> 'ConversationMemory':
        """Get or create conversation memory for a chat."""
        if chat_id not in self.conversations:
            # Use in-memory conversation storage per chat
            from ...memory import InMemoryConversation
            self.conversations[chat_id] = InMemoryConversation()
        return self.conversations[chat_id]

    def _get_user_session(self, message: Message) -> TelegramUserSession:
        """Get or create a user session from a Telegram message."""
        tg_user = message.from_user
        tg_id = tg_user.id if tg_user else 0
        if tg_id not in self._user_sessions:
            self._user_sessions[tg_id] = TelegramUserSession(
                telegram_id=tg_id,
                telegram_username=tg_user.username if tg_user else None,
                telegram_first_name=tg_user.first_name if tg_user else None,
                telegram_last_name=tg_user.last_name if tg_user else None,
            )
        return self._user_sessions[tg_id]

    @staticmethod
    def _enrich_question(
        question: str, session: TelegramUserSession
    ) -> str:
        """Attach user identity context to a question as structured metadata.

        The identity is wrapped in an ``<user_context>`` XML tag so the LLM
        reads it as metadata, not as a user utterance. The previous format
        (``-- I am -- name: X, telegram: @Y``) matched the role-impersonation
        pattern that prompt-injection classifiers flag on every message.

        When the user has connected Jira via ``/connect_jira``, the Jira
        identity is surfaced in a sibling ``<jira>`` block so the LLM
        understands that tickets / assignments belong to the connected
        Atlassian account, not the primary Navigator login.
        """
        parts = []
        name = session.display_name
        if name:
            parts.append(f'<name>{name}</name>')
        if session.nav_email:
            parts.append(f'<email>{session.nav_email}</email>')
        elif session.telegram_username:
            parts.append(f'<telegram>@{session.telegram_username}</telegram>')

        jira_parts = []
        if session.jira_account_id:
            jira_parts.append(
                f'<account_id>{session.jira_account_id}</account_id>'
            )
        if session.jira_email:
            jira_parts.append(f'<email>{session.jira_email}</email>')
        if session.jira_display_name:
            jira_parts.append(
                f'<display_name>{session.jira_display_name}</display_name>'
            )

        if not parts and not jira_parts:
            return question
        identity = "".join(parts)
        jira_block = (
            f'<jira>{"".join(jira_parts)}</jira>' if jira_parts else ""
        )
        return (
            f"{question}\n\n"
            f'<user_context source="telegram">{identity}{jira_block}</user_context>'
        )

    # ─── FEAT-120: Message ID cache helpers ──────────────────────────────

    def _cache_message_id(self, chat_id: int, message_id: int, text: str) -> None:
        """Store a message_id → text snippet in the per-chat cache.

        Enforces a per-chat limit of 100 entries with FIFO eviction so the
        cache does not grow without bound for long-running bots.

        Args:
            chat_id: Telegram chat identifier.
            message_id: The message's Telegram message_id.
            text: The message text or description (truncated to 200 chars).
        """
        if chat_id not in self._message_id_cache:
            self._message_id_cache[chat_id] = {}
        cache = self._message_id_cache[chat_id]
        cache[message_id] = (text or "")[:200]
        # Evict oldest entry when over limit (dict preserves insertion order, Python 3.7+)
        if len(cache) > 100:
            oldest_key = next(iter(cache))
            del cache[oldest_key]

    async def _store_telegram_metadata(
        self,
        memory: Any,
        user_id: str,
        session_id: str,
        user_message_id: int,
        bot_message_id: int,
    ) -> None:
        """Inject Telegram message IDs into the latest ConversationTurn metadata.

        Retrieves the most recent turn from conversation memory and writes
        ``telegram_message_id`` and ``telegram_bot_message_id`` into its
        ``metadata`` dict.  Handles gracefully: missing history, empty turns,
        or memory backends that don't persist mutations in-place (Redis).

        Args:
            memory: ConversationMemory instance for this chat.
            user_id: The user's identifier string.
            session_id: The conversation session identifier.
            user_message_id: The Telegram message_id of the user's message.
            bot_message_id: The Telegram message_id of the bot's response.
        """
        try:
            history = await memory.get_history(user_id, session_id)
            if history and history.turns:
                last_turn = history.turns[-1]
                last_turn.metadata['telegram_message_id'] = user_message_id
                last_turn.metadata['telegram_bot_message_id'] = bot_message_id
        except Exception:
            self.logger.debug(
                "Could not store Telegram message IDs in turn metadata",
                exc_info=True,
            )

    def _extract_reply_context(self, message: Message) -> str:
        """Extract reply-to message content and wrap in XML for context injection.

        When a user replies to a specific message, this method builds a
        ``<reply_context>text</reply_context>\\n`` XML block containing the
        original message text.  This block should be prepended to the user's
        question BEFORE calling ``_enrich_question`` so the LLM sees it as
        metadata before the ``<user_context>`` block.

        Args:
            message: The incoming aiogram Message that may contain a
                ``reply_to_message`` reference.

        Returns:
            A ``"<reply_context>…</reply_context>\\n"`` string, or ``""`` if:
            - ``config.enable_reply_context`` is False
            - The message is not a reply (``reply_to_message`` is None)
        """
        if not self.config.enable_reply_context:
            return ""
        reply = message.reply_to_message
        if reply is None:
            return ""

        chat_id = message.chat.id
        reply_id = reply.message_id

        # Fast path: check in-memory cache first
        cached = self._message_id_cache.get(chat_id, {}).get(reply_id)
        if cached:
            original_text = cached
        elif reply.text:
            original_text = reply.text
        elif reply.caption:
            original_text = reply.caption
        elif reply.voice:
            original_text = "[Voice message]"
        elif reply.document:
            fname = reply.document.file_name or "unknown"
            original_text = f"[Document: {fname}]"
        else:
            original_text = "[Media message]"

        # Truncate to 200 chars
        if len(original_text) > 200:
            original_text = original_text[:197] + "..."

        return f"<reply_context>{original_text}</reply_context>\n"

    @staticmethod
    def _build_permission_context(session: TelegramUserSession) -> Any:
        """Construct a ``PermissionContext`` scoped to this Telegram user.

        The context carries ``channel="telegram"`` and the telegram_id as
        the session ``user_id`` so ``JiraToolkit._pre_execute`` can look up
        the per-user OAuth2 3LO token in Redis (key
        ``jira:oauth:telegram:<telegram_id>``). Without this the toolkit
        has no way to identify the caller and falls back to guessing from
        the LLM-provided email, which is the wrong identity when a user
        runs ``/login`` with a corporate email but ``/connect_jira`` with
        a personal Atlassian account.

        Imported lazily to keep the Telegram wrapper importable without
        ``parrot.auth.permission`` on the path (older deployments).
        """
        try:
            from parrot.auth.permission import PermissionContext, UserSession
        except ImportError:
            return None
        user_session = UserSession(
            user_id=str(session.telegram_id),
            tenant_id="default",
            roles=frozenset(),
        )
        extra: Dict[str, Any] = {
            "telegram_id": session.telegram_id,
        }
        if session.nav_user_id:
            extra["nav_user_id"] = session.nav_user_id
        if session.jira_account_id:
            extra["jira_account_id"] = session.jira_account_id
        if session.o365_access_token:
            extra["o365_access_token"] = session.o365_access_token
        if session.o365_id_token:
            extra["o365_id_token"] = session.o365_id_token
        if session.o365_provider:
            extra["o365_provider"] = session.o365_provider
        return PermissionContext(
            session=user_session,
            channel="telegram",
            extra=extra,
        )

    def _build_user_context(self, session: TelegramUserSession) -> UserContext:
        """Build an agnostic :class:`UserContext` from a Telegram session.

        Keeps the per-user initialization hook (``post_login``) and
        factory (``clone_for_user``) decoupled from the Telegram-specific
        session object so the same agent code works under any wrapper.
        """
        metadata: Dict[str, Any] = {
            "telegram_id": session.telegram_id,
        }
        if session.telegram_username:
            metadata["telegram_username"] = session.telegram_username
        if session.nav_user_id:
            metadata["nav_user_id"] = session.nav_user_id
        if session.jira_account_id:
            metadata["jira_account_id"] = session.jira_account_id
        if session.jira_cloud_id:
            metadata["jira_cloud_id"] = session.jira_cloud_id
        return UserContext(
            channel="telegram",
            user_id=session.user_id,
            display_name=session.display_name,
            email=session.nav_email or session.jira_email,
            session_id=session.session_id,
            metadata=metadata,
        )

    async def _initialize_user_context(
        self,
        session: TelegramUserSession,
        message: Optional[Message] = None,
    ) -> None:
        """Eagerly build per-user agent/tool state and run ``post_login``.

        Runs once per user (guarded by ``session.post_login_ran``). Called
        from the auth success paths so any delay from the agent's
        ``post_login`` hook (e.g. priming a Jira client) is absorbed at
        login time rather than blocking the user's first question.

        In ``singleton_agent=True`` mode this clones the shared agent's
        ``ToolManager`` into ``session.tool_manager``.
        In ``singleton_agent=False`` mode it calls
        ``self.agent.clone_for_user(user_context)`` and stores the
        resulting agent on ``session.user_agent``.

        A typing indicator is shown if ``message`` is provided so the
        user sees activity while initialization runs.
        """
        if session.post_login_ran:
            return

        user_context = self._build_user_context(session)
        typing_task: Optional[asyncio.Task] = None
        chat_id = message.chat.id if message else None
        if chat_id is not None:
            typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            if self.config.singleton_agent:
                # Per-user ToolManager clone off the shared agent.
                base_tm = getattr(self.agent, "tool_manager", None)
                if base_tm is not None and hasattr(base_tm, "clone"):
                    session.tool_manager = base_tm.clone()
                else:
                    self.logger.warning(
                        "Agent %r has no cloneable tool_manager; falling back "
                        "to the shared instance (credentials may leak across "
                        "users).",
                        getattr(self.agent, "name", self.agent.__class__.__name__),
                    )
                target_agent = self.agent
            else:
                # Full per-user agent instance.
                session.user_agent = await self.agent.clone_for_user(user_context)
                target_agent = session.user_agent

            # Run the user-initialization hook against the correct agent
            # so any toolkit binding happens on the per-user surface.
            try:
                await target_agent.post_login(user_context)
            except NotImplementedError:
                # Default no-op contract — nothing to do.
                pass
            except Exception:  # noqa: BLE001
                self.logger.exception(
                    "post_login hook raised for user %s; continuing with "
                    "best-effort isolation.",
                    session.user_id,
                )

            # Rehydrate any MCP servers the user had previously attached
            # via /add_mcp so a process restart or a fresh conversation
            # doesn't require re-issuing the command. Failures are logged
            # per-server inside the helper — initialization must not be
            # aborted just because one stored server is unreachable.
            user_tm = self._get_user_tool_manager(session)
            if user_tm is not None:
                try:
                    from .mcp_commands import rehydrate_user_mcp_servers
                    count = await rehydrate_user_mcp_servers(
                        user_tm, f"tg:{session.telegram_id}"
                    )
                    if count:
                        self.logger.info(
                            "Rehydrated %d MCP server(s) for tg:%s",
                            count,
                            session.telegram_id,
                        )
                except Exception:  # noqa: BLE001
                    self.logger.exception(
                        "MCP rehydration failed for tg:%s (continuing)",
                        session.telegram_id,
                    )

            session.post_login_ran = True
        finally:
            if typing_task is not None:
                typing_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await typing_task

    async def _invoke_agent(
        self,
        session: TelegramUserSession,
        question: str,
        *,
        memory: Any,
        output_mode: OutputMode = OutputMode.TELEGRAM,
        message: Optional[Message] = None,
        attachments: Optional[List[str]] = None,
    ) -> Any:
        """Call ``agent.ask`` with per-user ToolManager/agent isolation.

        In ``singleton_agent=True`` the shared agent's ``tool_manager``
        is temporarily swapped to the user's clone under
        ``self._agent_lock`` (concurrent messages for this wrapper
        serialize). In ``singleton_agent=False`` the per-user agent is
        invoked directly — no swap, no lock.

        The permission_context and enriched question are built here so
        the two call sites (private DM and group mention) stay in sync.

        Args:
            session: The current user's Telegram session.
            question: The user's message text (may include reply context prefix).
            memory: Conversation memory for this chat.
            output_mode: Controls response formatting.
            message: The raw aiogram Message (optional, for context).
            attachments: Optional list of local file paths to forward to
                ``agent.ask()`` so downstream tools can access the files.
        """
        if attachments:
            self.logger.debug(
                "Chat %s: _invoke_agent received attachments: %s",
                session.telegram_id, attachments,
            )

        agent, user_tm = await self._resolve_agent_for_request(
            session, message=message
        )
        permission_context = self._build_permission_context(session)
        enriched = self._enrich_question(question, session)

        if self.config.singleton_agent and user_tm is not None:
            async with self._agent_lock:
                original_tm = agent.tool_manager
                original_enable_tools = agent.enable_tools
                agent.tool_manager = user_tm
                if user_tm.tool_count() > 0:
                    agent.enable_tools = True
                with contextlib.suppress(Exception):
                    agent.sync_tools()
                try:
                    if attachments:
                        self.logger.debug(
                            "Chat %s: forwarding attachments to agent.ask (singleton): %s",
                            session.telegram_id, attachments,
                        )
                    return await agent.ask(
                        enriched,
                        user_id=session.user_id,
                        session_id=session.session_id,
                        memory=memory,
                        output_mode=output_mode,
                        permission_context=permission_context,
                        attachments=attachments,
                    )
                finally:
                    agent.tool_manager = original_tm
                    agent.enable_tools = original_enable_tools
                    with contextlib.suppress(Exception):
                        agent.sync_tools()

        # Per-user agent mode (or singleton fallback with no cloneable TM):
        # no shared mutation, so no lock required.
        if attachments:
            self.logger.debug(
                "Chat %s: forwarding attachments to agent.ask (per-user): %s",
                session.telegram_id, attachments,
            )
        return await agent.ask(
            enriched,
            user_id=session.user_id,
            session_id=session.session_id,
            memory=memory,
            output_mode=output_mode,
            permission_context=permission_context,
            attachments=attachments,
        )

    async def _resolve_agent_for_request(
        self,
        session: TelegramUserSession,
        message: Optional[Message] = None,
    ) -> Tuple["AbstractBot", Optional[Any]]:
        """Return the (agent, per-user ToolManager) tuple for this call.

        Lazily runs ``_initialize_user_context`` if the user authenticated
        but the eager hook did not fire (defensive — e.g., users who were
        already authenticated before this change rolled out).

        Returns:
            ``(agent, tool_manager)`` where ``tool_manager`` is the
            cloned per-user manager in singleton mode (the caller must
            swap it in before ``agent.ask``) or ``None`` in full-clone
            mode (``agent`` is already user-scoped).
        """
        if not session.post_login_ran:
            await self._initialize_user_context(session, message=message)

        if self.config.singleton_agent:
            return self.agent, session.tool_manager
        return (session.user_agent or self.agent), None

    async def _check_authentication(self, message: Message) -> bool:
        """
        Check if user is authenticated if force_authentication is enabled.

        Returns:
            True if authenticated or auth not forced.
            False if not authenticated and auth is forced.
        """
        if not self.config.force_authentication:
            return True

        session = self._get_user_session(message)
        if session.authenticated:
            return True

        await message.answer("⛔ You must sign in with /login to talk to me.")
        return False

    async def handle_start(self, message: Message) -> None:
        """Handle /start command with welcome message."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        # Clear any existing conversation
        if chat_id in self.conversations:
            del self.conversations[chat_id]

        welcome = self.config.welcome_message or (
            f"👋 Hello! I'm {self.config.name}, your AI assistant.\n\n"
            f"Send me a message and I'll help you out!\n"
            f"Use /clear to reset our conversation."
        )
        await message.answer(welcome)

    async def handle_clear(self, message: Message) -> None:
        """Handle /clear command to reset conversation memory."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if chat_id in self.conversations:
            del self.conversations[chat_id]

        await message.answer("🔄 Conversation cleared. Starting fresh!")

    async def handle_help(self, message: Message) -> None:
        """Handle /help command — briefing description with available options."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        agent_desc = getattr(self.agent, 'description', '') or ''
        help_text = (
            f"📚 *{self.config.name}*\n"
        )
        if agent_desc:
            help_text += f"{agent_desc}\n"
        help_text += (
            "\n*Built-in Commands:*\n"
            "/start - Start conversation\n"
            "/help - Show this help message\n"
            "/whoami - Agent name and description\n"
            "/commands - List all available commands\n"
            "/clear - Reset conversation memory\n"
            "/skill <name> [args] - Call a tool by name\n"
            "/function <method> [key=val ...] - Call agent method\n"
            "/question <text> - Ask the LLM directly (no tools)\n"
            "/call <method> [args] - Call agent method (legacy)\n"
        )

        # Add custom commands if any
        if self.config.commands:
            help_text += "\n*Custom Commands:*\n"
            for cmd_name, method_name in self.config.commands.items():
                help_text += f"/{cmd_name} - Calls {method_name}()\n"

        # Agent-declared commands
        if self._agent_commands:
            help_text += "\n*Agent Commands:*\n"
            for cmd_info in self._agent_commands:
                help_text += f"/{cmd_info['command']} - {cmd_info['description']}\n"

        help_text += (
            "\nSend any message directly for a conversation with the agent."
        )

        await self._send_safe_message(message, help_text)

    def _get_callable_methods(self) -> list:
        """Get list of public callable methods on the agent."""
        methods = []
        for name in dir(self.agent):
            if name.startswith('_'):
                continue
            attr = getattr(self.agent, name, None)
            if callable(attr) and asyncio.iscoroutinefunction(attr):
                methods.append(name)
        return sorted(methods)

    async def handle_call(self, message: Message) -> None:
        """Handle /call command to invoke an agent method."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        # Parse command: /call method_name arg1 arg2 ...
        text = message.text or ""
        parts = text.split(maxsplit=2)  # ["/call", "method", "args..."]

        if len(parts) < 2:
            await message.answer(
                "Usage: /call <method_name> [arguments]\n\n"
                "Example: /call custom_report Q4 2024"
            )
            return

        method_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        await self._execute_agent_method(message, method_name, args_text)

    async def handle_whoami(self, message: Message) -> None:
        """Handle /whoami — returns agent name and description."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        agent_name = getattr(self.agent, 'name', self.config.name)
        agent_desc = getattr(self.agent, 'description', '') or 'No description available.'
        agent_id = getattr(self.agent, 'agent_id', '') or ''
        model = getattr(self.agent, 'model', '') or ''

        text = f"🤖 *{agent_name}*\n"
        if agent_id:
            text += f"ID: `{agent_id}`\n"
        text += f"\n{agent_desc}\n"
        if model:
            text += f"\nModel: `{model}`\n"

        # Tools count
        if hasattr(self.agent, 'get_tools_count'):
            text += f"Tools: {self.agent.get_tools_count()}\n"

        # User identity
        session = self._get_user_session(message)
        text += "\n👤 *Your Identity:*\n"
        text += f"Name: {session.display_name}\n"
        text += f"User ID: `{session.user_id}`\n"
        if session.authenticated:
            text += "Status: ✅ Authenticated\n"
        elif self._auth_strategy:
            text += "Status: 🔓 Not authenticated (use /login)\n"

        await self._send_safe_message(message, text)

    async def handle_commands(self, message: Message) -> None:
        """Handle /commands — list all registered commands and functions."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = f"📋 *{self.config.name} — Commands*\n\n"

        # Built-in commands
        text += "*Built-in:*\n"
        for bc in self.get_bot_commands():
            text += f"/{bc.command} - {bc.description}\n"

        # Available tools (for /skill)
        if hasattr(self.agent, 'get_available_tools'):
            tools = self.agent.get_available_tools()
            if tools:
                text += f"\n*Tools (/skill):* {len(tools)} available\n"
                for tool_name in tools[:15]:
                    text += f"• `{tool_name}`\n"
                if len(tools) > 15:
                    text += f"... and {len(tools) - 15} more\n"

        # Callable methods (for /function)
        callable_methods = self._get_callable_methods()
        if callable_methods:
            text += f"\n*Methods (/function):* {len(callable_methods)} available\n"
            for method in callable_methods[:15]:
                text += f"• `{method}`\n"
            if len(callable_methods) > 15:
                text += f"... and {len(callable_methods) - 15} more\n"

        await self._send_safe_message(message, text)

    async def handle_skill(self, message: Message) -> None:
        """Handle /skill <name> [args] — invoke a tool by name."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = message.text or ""
        parts = text.split(maxsplit=2)  # ["/skill", "tool_name", "args..."]

        if len(parts) < 2:
            # Show available tools
            tools = []
            if hasattr(self.agent, 'get_available_tools'):
                tools = self.agent.get_available_tools()
            usage = "Usage: /skill <tool_name> [arguments]\n\n"
            if tools:
                usage += "Available tools:\n"
                for t in tools[:20]:
                    usage += f"• `{t}`\n"
                if len(tools) > 20:
                    usage += f"... and {len(tools) - 20} more\n"
            else:
                usage += "No tools registered on this agent.\n"
            await message.answer(usage, parse_mode=None)
            return

        tool_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        # Check tool exists
        if not hasattr(self.agent, 'tool_manager') or not self.agent.tool_manager:
            await message.answer("❌ No tool manager available on this agent.")
            return

        tool = self.agent.tool_manager.get_tool(tool_name)
        if not tool:
            await message.answer(
                f"❌ Tool `{tool_name}` not found.\n"
                f"Use /skill without arguments to see available tools."
            )
            return

        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            self.logger.info(f"Chat {chat_id}: Calling tool {tool_name}({args_text})")
            # Use agent.ask to let the LLM invoke the tool properly
            question = f"Use the tool `{tool_name}` with the following input: {args_text}" if args_text else f"Use the tool `{tool_name}`"
            with telegram_chat_scope(chat_id):
                response = await self.agent.ask(
                    question,
                    output_mode=OutputMode.TELEGRAM,
                )
            typing_task.cancel()
            parsed = self._parse_response(response)
            await self._send_parsed_response(
                message, parsed,
                prefix=f"🔧 *{tool_name}* result:\n\n"
            )
        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error calling tool {tool_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error calling tool `{tool_name}`: {str(e)[:200]}")
        finally:
            typing_task.cancel()

    async def handle_function(self, message: Message) -> None:
        """Handle /function <method> [key=val ...] — invoke agent method with kwargs."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = message.text or ""
        parts = text.split(maxsplit=2)  # ["/function", "method", "key=val ..."]

        if len(parts) < 2:
            await message.answer(
                "Usage: /function <method_name> [key=val ...]\n\n"
                "Examples:\n"
                "/function create_ticket summary=Bug description=Crash\n"
                "/function search_all_tickets\n\n"
                "Use /commands to see available methods."
            )
            return

        method_name = parts[1]
        args_text = parts[2] if len(parts) > 2 else ""

        # Check if method exists
        if not hasattr(self.agent, method_name):
            await message.answer(f"❌ Method `{method_name}` not found on agent.")
            return

        method = getattr(self.agent, method_name)
        if not callable(method):
            await message.answer(f"❌ `{method_name}` is not callable.")
            return

        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            self.logger.info(f"Chat {chat_id}: /function {method_name}({args_text})")

            kwargs = self._parse_kwargs(args_text)

            if asyncio.iscoroutinefunction(method):
                result = await method(**kwargs) if kwargs else await method()
            else:
                result = method(**kwargs) if kwargs else method()

            typing_task.cancel()
            parsed = self._parse_response(result)
            await self._send_parsed_response(
                message, parsed,
                prefix=f"✅ *{method_name}* result:\n\n"
            )
        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error in /function {method_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error calling {method_name}: {str(e)[:200]}")
        finally:
            typing_task.cancel()

    async def handle_question(self, message: Message) -> None:
        """Handle /question <text> — pure LLM query without tools."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        text = message.text or ""
        parts = text.split(maxsplit=1)
        question = parts[1] if len(parts) > 1 else ""

        if not question:
            await message.answer(
                "Usage: /question <your question>\n\n"
                "Sends your question directly to the LLM (no tool usage)."
            )
            return

        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        try:
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)
            self.logger.info(f"Chat {chat_id}: /question {question[:50]}...")

            with telegram_chat_scope(chat_id):
                response = await self.agent.ask(
                    self._enrich_question(question, session),
                    user_id=session.user_id,
                    session_id=session.session_id,
                    memory=memory,
                    output_mode=OutputMode.TELEGRAM,
                    use_tools=False,
                )

            typing_task.cancel()
            parsed = self._parse_response(response)
            await self._send_parsed_response(message, parsed)
        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error in /question: {e}", exc_info=True)
            await message.answer(
                "❌ Sorry, I encountered an error. Please try again."
            )
        finally:
            typing_task.cancel()

    async def handle_login(self, message: Message) -> None:
        """Handle /login — show login WebApp button via configured strategy."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        session = self._get_user_session(message)
        if session.authenticated:
            await message.answer(
                f"✅ Already authenticated as *{session.display_name}* "
                f"(`{session.nav_user_id}`).\n\n"
                "Use /logout to sign out.",
                parse_mode="Markdown"
            )
            return

        if not self._auth_strategy:
            await message.answer("❌ Authentication is not configured for this bot.")
            return

        # Generate CSRF state and delegate keyboard to strategy
        state = secrets.token_urlsafe(32)

        # FEAT-108 / FEAT-109: If post_auth_actions are configured AND the
        # strategy supports the chain, build the secondary auth URL so the
        # login page can redirect to it after primary auth succeeds.
        # Previously gated on isinstance(BasicAuthStrategy); now uses the
        # declarative capability flag introduced by TASK-777.
        kwargs: Dict[str, Any] = {}
        if (
            getattr(self._auth_strategy, "supports_post_auth_chain", False)
            and len(self._post_auth_registry) > 0
        ):
            session = self._get_user_session(message)
            next_url, required = await self._build_next_auth_url(session)
            if next_url:
                kwargs["next_auth_url"] = next_url
                kwargs["next_auth_required"] = required

        try:
            keyboard = await self._auth_strategy.build_login_keyboard(
                self.config, state, **kwargs
            )
        except ValueError as exc:
            await message.answer(f"❌ Login configuration error: {exc}")
            return

        # Compose prompt text based on the active auth method(s).
        # Use auth_methods (FEAT-109 list) rather than the legacy singleton
        # so that composite deployments get an appropriate message.
        methods = getattr(self.config, "auth_methods", [])
        if len(methods) > 1:
            prompt_text = (
                "🔐 *Sign In*\n\n"
                "Tap the button below and choose how you'd like to authenticate."
            )
        elif "azure" in methods:
            prompt_text = (
                "\U0001f510 *Azure SSO*\n\n"
                "Tap the button below to sign in with your organization's Azure account."
            )
        elif "oauth2" in methods:
            provider = getattr(self.config, "oauth2_provider", "oauth2") or "oauth2"
            provider = provider.capitalize()
            prompt_text = (
                f"🔐 *{provider} Authentication*\n\n"
                f"Tap the button below to sign in with {provider}."
            )
        else:
            prompt_text = (
                "🔐 *Navigator Authentication*\n\n"
                "Tap the button below to sign in with your Navigator credentials."
            )

        await message.answer(
            prompt_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    async def handle_logout(self, message: Message) -> None:
        """Handle /logout — clear authentication state."""
        chat_id = message.chat.id
        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        session = self._get_user_session(message)
        if not session.authenticated:
            await message.answer("ℹ️ You are not currently authenticated.")
            return

        old_name = session.display_name
        session.clear_auth()
        await message.answer(
            f"👋 Logged out. Was authenticated as *{old_name}*.\n"
            "Your Telegram ID will be used for identification.",
            parse_mode="Markdown"
        )

    async def handle_web_app_data(self, message: Message) -> None:
        """Handle data returned from the login WebApp.

        Delegates to the configured auth strategy to process the callback.
        When the payload includes keys matching configured
        ``post_auth_actions`` providers (FEAT-108), BasicAuth is processed
        first and then each secondary auth provider runs via
        :pyattr:`_post_auth_registry`.
        """
        if not message.web_app_data or not message.from_user:
            return

        if not self._auth_strategy:
            return

        try:
            data = json.loads(message.web_app_data.data)
        except (json.JSONDecodeError, TypeError):
            await message.answer("❌ Invalid login response data.")
            return

        session = self._get_user_session(message)

        # FEAT-108: combined auth flow — dispatch to secondary providers.
        # CompositeAuthStrategy handles method routing internally via
        # handle_callback; the combined-auth path was designed for single-
        # method BasicAuth and cannot correctly reconstruct basic_data when
        # a composite is active (it strips auth_method before delegating).
        if self._is_combined_payload(data) and not isinstance(
            self._auth_strategy, CompositeAuthStrategy
        ):
            await self._handle_combined_auth(message, data, session)
            return

        # Standard (single-step) auth flow.
        success = await self._auth_strategy.handle_callback(data, session)

        if success:
            await message.answer(
                f"✅ Authenticated as *{session.display_name}* "
                f"(`{session.nav_user_id}`).\n\n"
                "Your identity will be used for all interactions.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
            # Eagerly build per-user agent/tool state so the first
            # question does not pay the post_login cost. A typing
            # indicator covers any noticeable delay.
            await self._initialize_user_context(session, message=message)
        else:
            await message.answer("❌ Login failed. Please try again with /login.")

    async def _handle_combined_auth(
        self,
        message: Message,
        data: Dict[str, Any],
        session: TelegramUserSession,
    ) -> None:
        """Process a combined BasicAuth + secondary auth payload (FEAT-108).

        The payload is expected to contain one or more provider keys
        (e.g., ``"jira": {"code", "state"}``) and optionally a
        ``"basic_auth"`` sub-dict carrying the primary auth result from
        the login page. When ``basic_auth`` is absent we fall back to
        treating the top-level keys as BasicAuth (matches the
        single-step contract for backward safety).

        Rollback semantics:
          * Primary BasicAuth failure → hard failure, no secondary runs.
          * Secondary failure + ``required=True`` → ``session.clear_auth``
            and error message.
          * Secondary failure + ``required=False`` → partial success
            message; BasicAuth session persists.
        """
        basic_data = data.get("basic_auth") or {
            k: v for k, v in data.items()
            if k not in {action.provider
                         for action in self.config.post_auth_actions}
        }
        basic_ok = await self._auth_strategy.handle_callback(
            basic_data, session
        )
        if not basic_ok:
            await message.answer(
                "❌ Login failed. Please try again with /login."
            )
            return

        failures_required: list[str] = []
        failures_optional: list[str] = []

        for action in self.config.post_auth_actions:
            payload = data.get(action.provider)
            if not isinstance(payload, dict):
                # Provider data absent from this submission — skip silently.
                continue
            provider = self._post_auth_registry.get(action.provider)
            if provider is None:
                self.logger.warning(
                    "Combined auth: no provider registered for '%s'; "
                    "skipping.",
                    action.provider,
                )
                if action.required:
                    failures_required.append(action.provider)
                continue
            try:
                ok = await provider.handle_result(
                    data=payload,
                    session=session,
                    primary_auth_data=basic_data,
                )
            except Exception:  # noqa: BLE001
                self.logger.exception(
                    "Combined auth: provider '%s' raised",
                    action.provider,
                )
                ok = False
            if not ok:
                if action.required:
                    failures_required.append(action.provider)
                else:
                    failures_optional.append(action.provider)

        # Required failure → rollback the primary session.
        if failures_required:
            session.clear_auth()
            providers_str = ", ".join(failures_required)
            await message.answer(
                "❌ Login requires authorization for "
                f"*{providers_str}*. Please try again with /login.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        # Partial success (optional provider failed).
        if failures_optional:
            providers_str = ", ".join(failures_optional)
            await message.answer(
                f"✅ Authenticated as *{session.display_name}*.\n"
                f"⚠️ Could not connect: {providers_str}. "
                "Use `/connect_jira` (or equivalent) to retry.",
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(),
            )
            await self._initialize_user_context(session, message=message)
            return

        # Full success.
        linked = ", ".join(
            action.provider for action in self.config.post_auth_actions
            if action.provider in data
        )
        await message.answer(
            f"✅ Authenticated as *{session.display_name}*.\n"
            f"🔗 Connected: {linked}.",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        await self._initialize_user_context(session, message=message)

    async def _execute_agent_method(
        self,
        message: Message,
        method_name: str,
        args_text: str
    ) -> None:
        """Execute an agent method and send the result."""
        chat_id = message.chat.id

        # Check if method exists
        if not hasattr(self.agent, method_name):
            await message.answer(f"❌ Method '{method_name}' not found on agent.")
            return

        method = getattr(self.agent, method_name)
        if not callable(method):
            await message.answer(f"❌ '{method_name}' is not callable.")
            return

        # Start typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            self.logger.info(f"Chat {chat_id}: Calling {method_name}({args_text})")

            # Parse arguments (simple space-separated for now)
            args = args_text.split() if args_text else []

            # Call the method
            if asyncio.iscoroutinefunction(method):
                if args:
                    result = await method(*args)
                else:
                    result = await method()
            else:
                if args:
                    result = method(*args)
                else:
                    result = method()

            # Stop typing
            typing_task.cancel()

            # Format and send result using parsed response
            parsed = self._parse_response(result)
            await self._send_parsed_response(
                message, 
                parsed, 
                prefix=f"✅ *{method_name}* result:\n\n"
            )

        except Exception as e:
            typing_task.cancel()
            self.logger.error(f"Error calling {method_name}: {e}", exc_info=True)
            await message.answer(f"❌ Error calling {method_name}: {str(e)[:200]}")
        finally:
            typing_task.cancel()

    async def _typing_indicator(self, chat_id: int) -> None:
        """Background task that sends typing indicator every 4 seconds."""
        try:
            while True:
                await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass

    async def handle_message(self, message: Message) -> None:
        """
        Process incoming text message and send agent response.

        Steps:
        1. Check authorization
        2. Get/create conversation memory for this chat
        3. Call agent.ask() with the message
        4. Send response back to Telegram
        """
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        user_text = message.text
        if not user_text:
            return

        # Start continuous typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            # Check for suspended session first
            suspended_state = await self._state_manager.get_suspended_session(
                integration_id="telegram",
                chat_id=str(chat_id),
                user_id=str(message.from_user.id) if message.from_user else "unknown"
            )

            # Get conversation memory and user session
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            if suspended_state:
                session_id = suspended_state.get("session_id")
                agent_name = suspended_state.get("agent_name")
                
                # We have a suspended session, override session ID
                self.logger.info(
                    f"Chat {chat_id}: Found suspended session {session_id} for agent {agent_name}. Resuming..."
                )
                session.session_id = session_id

                from parrot.core.orchestrator.autonomous import AutonomousOrchestrator
                
                # Create a lightweight orchestrator or use existing one if possible
                # We'll instantiate one just for this resume operation. 
                # Ideally, this should use the central orchestrator, but typically methods are stateless enough.
                orchestrator = AutonomousOrchestrator(
                    bot_manager=getattr(self.bot, "manager", None),
                    agent_registry=getattr(self.agent, "registry", None) 
                )
                
                # We pass the message text to resume_agent
                result = await orchestrator.resume_agent(
                    session_id=session_id,
                    user_input=user_text,
                    state=suspended_state
                )
                
                # Clear state if successful so we don't trap the user forever
                if result.success:
                     await self._state_manager.clear_suspended_state(
                         integration_id="telegram",
                         chat_id=str(chat_id),
                         user_id=str(message.from_user.id) if message.from_user else "unknown"
                     )
                     
                parsed = self._parse_response(result.result)
                typing_task.cancel()
                await self._send_parsed_response(message, parsed)
                return

            # Call the agent
            self.logger.info(
                f"Chat {chat_id} (user {session.user_id}): "
                f"Processing message: {user_text[:50]}..."
            )

            # FEAT-120: cache user message ID for reply context lookup
            self._cache_message_id(chat_id, message.message_id, user_text)

            # FEAT-120: prepend reply context before calling agent
            reply_ctx = self._extract_reply_context(message)
            if reply_ctx:
                user_text = reply_ctx + user_text

            with telegram_chat_scope(chat_id):
                response = await self._invoke_agent(
                    session,
                    user_text,
                    memory=memory,
                    output_mode=OutputMode.TELEGRAM,
                    message=message,
                )

            # Parse and extract response content
            parsed = self._parse_response(response)

            # Stop typing indicator before sending response
            typing_task.cancel()

            # Send parsed response (handles text, images, documents, tables, code)
            sent = await self._send_parsed_response(message, parsed)

            # FEAT-120: cache bot message ID and persist metadata
            bot_msg_id = sent.message_id if sent else 0
            self._cache_message_id(chat_id, bot_msg_id, str(parsed)[:200])
            await self._store_telegram_metadata(
                memory, session.user_id, session.session_id,
                message.message_id, bot_msg_id,
            )

        except Exception as e:
            from parrot.core.exceptions import HumanInteractionInterrupt

            if isinstance(e, HumanInteractionInterrupt):
                # Agent requested human input — send prompt and suspend
                typing_task.cancel()
                prompt_text = str(e)
                self.logger.info(
                    f"Chat {chat_id}: Agent requested handoff. Prompt: {prompt_text[:80]}..."
                )
                await message.answer(prompt_text)
                user_id_str = str(message.from_user.id) if message.from_user else "unknown"
                await self._state_manager.set_suspended_state(
                    integration_id="telegram",
                    chat_id=str(chat_id),
                    user_id=user_id_str,
                    session_id=getattr(e, "session_id", session.session_id),
                    agent_name=getattr(self.agent, "name", "unknown"),
                )
            else:
                self.logger.error(f"Error processing message: {e}", exc_info=True)
                await message.answer(
                    "❌ Sorry, I encountered an error processing your request. "
                    "Please try again."
                )
        finally:
            # Ensure typing indicator is stopped
            typing_task.cancel()

    # ─── Group/Channel Message Handlers ──────────────────────────────────

    async def handle_group_ask(self, message: Message) -> None:
        """
        Handle /ask command in group chats.

        Usage:
            /ask what is Python?
            /ask@botname explain machine learning

        Strips the /ask command and processes the remaining query.
        """
        await self._process_group_query(message)

    async def handle_group_mention(self, message: Message) -> None:
        """
        Handle @mention in group chats.

        Usage:
            @botname what is AI?
            Hey @botname tell me about Python

        Responds when the bot is explicitly mentioned.
        """
        await self._process_group_query(message)

    async def handle_channel_mention(self, message: Message) -> None:
        """
        Handle @mention in channel posts.

        Note: Channel posts don't have a from_user by default.
        The bot must be an admin of the channel.
        """
        await self._process_group_query(message, is_channel=True)

    async def _process_group_query(
        self,
        message: Message,
        is_channel: bool = False
    ) -> None:
        """
        Process a group/channel query and send the response.

        Args:
            message: The incoming Telegram message
            is_channel: True if this is a channel post (no from_user)
        """
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.reply("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        # Extract the actual query (strips @mention and /command)
        query = await extract_query_from_mention(message, self.bot)

        if not query:
            if is_channel:
                return  # Silent skip for empty channel mentions
            await message.reply(
                "You mentioned me but didn't ask anything! "
                "Try: @me your question here"
            )
            return

        # Start typing indicator
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))

        try:
            # Check for suspended session first
            suspended_state = await self._state_manager.get_suspended_session(
                integration_id="telegram",
                chat_id=str(chat_id),
                user_id=str(message.from_user.id) if message.from_user else "unknown"
            )

            # Get conversation memory and user session
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            if suspended_state:
                session_id = suspended_state.get("session_id")
                agent_name = suspended_state.get("agent_name")
                
                # We have a suspended session, override session ID
                self.logger.info(
                    f"Chat {chat_id}: Found suspended session {session_id} for agent {agent_name}. Resuming..."
                )
                session.session_id = session_id

                from parrot.core.orchestrator.autonomous import AutonomousOrchestrator
                orchestrator = AutonomousOrchestrator(
                    bot_manager=getattr(self.bot, "manager", None),
                    agent_registry=getattr(self.agent, "registry", None) 
                )
                
                result = await orchestrator.resume_agent(
                    session_id=session_id,
                    user_input=query,
                    state=suspended_state
                )
                
                if result.success:
                     await self._state_manager.clear_suspended_state(
                         integration_id="telegram",
                         chat_id=str(chat_id),
                         user_id=str(message.from_user.id) if message.from_user else "unknown"
                     )
                     
                parsed = self._parse_response(result.result)
                typing_task.cancel()
                await self._send_parsed_response(message, parsed)
                return
                
            self.logger.info(
                f"Chat {chat_id} (user {session.user_id}): "
                f"Processing group query: {query[:50]}..."
            )

            # Call the agent
            with telegram_chat_scope(chat_id):
                response = await self._invoke_agent(
                    session,
                    query,
                    memory=memory,
                    output_mode=OutputMode.TELEGRAM,
                    message=message,
                )

            # Parse response
            parsed = self._parse_response(response)

            # Stop typing before sending
            typing_task.cancel()

            # Send response (reply in thread if configured)
            await self._send_group_response(message, parsed)

        except Exception as e:
            from parrot.core.exceptions import HumanInteractionInterrupt

            if isinstance(e, HumanInteractionInterrupt):
                typing_task.cancel()
                prompt_text = str(e)
                self.logger.info(
                    f"Chat {chat_id}: Agent requested handoff in group. Prompt: {prompt_text[:80]}..."
                )
                await message.reply(prompt_text)
                user_id_str = str(message.from_user.id) if message.from_user else "unknown"
                await self._state_manager.set_suspended_state(
                    integration_id="telegram",
                    chat_id=str(chat_id),
                    user_id=user_id_str,
                    session_id=getattr(e, "session_id", session.session_id),
                    agent_name=getattr(self.agent, "name", "unknown"),
                )
            else:
                typing_task.cancel()
                self.logger.error(f"Error processing group query: {e}", exc_info=True)
                await message.reply(
                    "❌ Sorry, I encountered an error processing your request."
                )
        finally:
            typing_task.cancel()

    async def _send_group_response(
        self,
        message: Message,
        parsed: ParsedResponse
    ) -> None:
        """
        Send response to a group message.

        Uses reply (thread) mode if configured, otherwise sends directly.
        """
        if self.config.reply_in_thread:
            # Reply to the original message (creates/continues thread)
            await self._send_parsed_response_reply(message, parsed)
        else:
            # Send as regular message
            await self._send_parsed_response(message, parsed)

    async def _send_parsed_response_reply(
        self,
        message: Message,
        parsed: ParsedResponse,
        prefix: str = ""
    ) -> None:
        """Send parsed response as a reply to the original message."""
        # Build the text response
        text_parts = []

        if prefix:
            text_parts.append(prefix)

        if parsed.text:
            text_to_add = parsed.text
            if self.config.use_html:
                # Convert Markdown to HTML
                text_to_add = self._markdown_to_html(text_to_add)
            else:
                # Convert Headers to Bold for Legacy Markdown
                text_to_add = self._convert_headers_to_bold(text_to_add)
            text_parts.append(text_to_add)

        # Add code block if present
        if parsed.has_code:
            lang = parsed.code_language or ""
            if self.config.use_html:
                code_block = f"<pre><code class=\"language-{lang}\">\n{parsed.code}\n</code></pre>"
            else:
                code_block = f"```{lang}\n{parsed.code}\n```"
            text_parts.append(code_block)

        # Add table if present (as markdown)
        if parsed.has_table and parsed.table_markdown:
            if self.config.use_html:
                 # Tables are tricky in Telegram HTML. Best to use <pre> block for alignment.
                 text_parts.append(f"<pre>\n{parsed.table_markdown}\n</pre>")
            else:
                text_parts.append(f"```\n{parsed.table_markdown}\n```")

        # Send the text message as reply
        full_text = "\n\n".join(text_parts)
        
        parse_mode = "HTML" if self.config.use_html else "Markdown"
        
        
        if full_text.strip():
            await self._send_long_reply(message, full_text, parse_mode=parse_mode)

        # Send attachments (images, documents, media, charts)
        # These are sent as separate messages but still in reply context
        await self._send_attachments(message.chat.id, parsed)

    async def _send_long_reply(
        self,
        message: Message,
        text: str,
        max_length: int = 4096,
        parse_mode: str = "Markdown",
    ) -> None:
        """Send a long message as reply, splitting if necessary."""
        if not text:
            text = "..."

        # Split into chunks if needed
        if len(text) <= max_length:
            chunks = [text]
        else:
            chunks = []
            current = ""
            for line in text.split('\n'):
                if len(current) + len(line) + 1 > max_length:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current += ('\n' if current else '') + line
            if current:
                chunks.append(current)

        # First chunk as reply, rest as regular messages
        for i, chunk in enumerate(chunks):
            if i == 0:
                await self._send_safe_reply(message, chunk, parse_mode=parse_mode)
            else:
                await self._send_safe_message(message, chunk, parse_mode=parse_mode)
            await asyncio.sleep(0.3)  # Rate limiting

    async def _send_safe_reply(
        self,
        message: Message,
        text: str,
        parse_mode: Optional[str] = None
    ) -> None:
        """Send a reply with retry logic for markdown errors."""
        async def _reply(txt, mode):
            await message.reply(txt, parse_mode=mode)
            
        await self._try_send_message(_reply, text, parse_mode)

    async def _send_safe_message(
        self,
        message: Message,
        text: str,
        parse_mode: Optional[str] = None
    ) -> Optional[Message]:
        """Send a message with retry logic for markdown errors.

        Returns:
            The sent Message object, or None if sending failed.
        """
        sent: Optional[Message] = None

        async def _answer(txt, mode):
            nonlocal sent
            sent = await message.answer(txt, parse_mode=mode)

        await self._try_send_message(_answer, text, parse_mode)
        return sent

    async def _try_send_message(
        self,
        send_func: Callable,
        text: str,
        parse_mode: Optional[str] = None
    ) -> None:
        """
        Attempt to send a message with error handling and plaintext fallback.

        On a Telegram 'can't parse entities' error the formatted text is
        stripped of all Markdown/HTML and re-sent as plain text.  LLM output
        frequently contains unbalanced `*`, `` ` `` or `_` characters that
        Telegram's legacy Markdown parser cannot recover from, so we do not
        attempt to re-send with the same parse_mode.
        """
        safe_text = (text or "...")[:4096]

        try:
            await send_func(safe_text, parse_mode)
            return

        except Exception as e:
            is_parse_error = (
                "can't parse entities" in str(e)
                or "Bad Request" in str(e)
            )

            if is_parse_error and parse_mode:
                # Strip all markup and deliver as plain text.
                plain = self._strip_markdown(safe_text)
                self.logger.info(
                    f"Telegram parse error (mode={parse_mode}), "
                    f"falling back to plain text. Error: {e}"
                )
                try:
                    await send_func(plain, None)
                    return
                except Exception as fallback_e:
                    self.logger.error(
                        f"Plain-text fallback also failed: {fallback_e}",
                        exc_info=True,
                    )
            else:
                self.logger.warning(
                    f"Failed to send message (mode={parse_mode}): {e}"
                )
                # Non-parse error: still try bare plaintext as last resort.
                try:
                    await send_func(safe_text, None)
                except Exception as fallback_e:
                    self.logger.error(
                        f"Final fallback failed: {fallback_e}",
                        exc_info=True,
                    )

    async def _send_attachments(
        self,
        chat_id: int,
        parsed: ParsedResponse
    ) -> None:
        """Send attachments (images, documents, media, charts) to a chat."""
        # Send charts
        if hasattr(parsed, 'charts') and parsed.charts:
            for chart in parsed.charts:
                try:
                    image_path = chart.path

                    # SVG not supported by Telegram - convert to PNG
                    if chart.format.lower() == "svg" or image_path.suffix.lower() == '.svg':
                        self.logger.info(f"Converting SVG chart to PNG: {chart.path.name}")
                        image_path = await self._convert_svg_to_png(chart.path)

                    caption = f"📊 {chart.title}"
                    if chart.chart_type and chart.chart_type != "unknown":
                        caption += f" ({chart.chart_type.replace('_', ' ').title()})"

                    if image_path.exists():
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=FSInputFile(image_path),
                            caption=caption[:200]
                        )
                        await asyncio.sleep(0.3)
                except Exception as e:
                    self.logger.error(f"Failed to send chart '{chart.title}': {e}")

        # Send images
        for image_path in parsed.images:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(image_path),
                    caption=image_path.name[:200] if len(parsed.images) > 1 else None
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.error(f"Failed to send image {image_path}: {e}")

        # Send documents
        for doc_path in parsed.documents:
            try:
                await self.bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(doc_path),
                    caption=doc_path.name[:200]
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.error(f"Failed to send document {doc_path}: {e}")

        # Send media (videos, audio)
        for media_path in parsed.media:
            try:
                suffix = media_path.suffix.lower()
                if suffix in ('.mp4', '.avi', '.mov', '.webm', '.mkv'):
                    await self.bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(media_path),
                        caption=media_path.name[:200]
                    )
                elif suffix in ('.mp3', '.wav', '.ogg', '.m4a'):
                    await self.bot.send_audio(
                        chat_id=chat_id,
                        audio=FSInputFile(media_path),
                        caption=media_path.name[:200]
                    )
                else:
                    await self.bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(media_path)
                    )
                await asyncio.sleep(0.3)
            except Exception as e:
                self.logger.error(f"Failed to send media {media_path}: {e}")

    async def handle_photo(self, message: Message) -> None:
        """Handle photo messages.

        Downloads the image to a temp file and passes its path to the agent
        via the ``attachments`` kwarg so downstream tools (e.g. JiraToolkit)
        can reference the file.
        """
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        # Get the largest photo (last element is highest resolution)
        photo = message.photo[-1]
        caption = message.caption or "Describe this image"

        await self.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        try:
            # Download photo to a persistent temp file
            file = await self.bot.get_file(photo.file_id)
            tg_ext = Path(file.file_path).suffix if file.file_path else '.jpg'
            tmp = tempfile.NamedTemporaryFile(
                suffix=tg_ext, prefix='tg_photo_', delete=False
            )
            await self.bot.download_file(file.file_path, tmp)
            tmp.close()
            tmp_path = Path(tmp.name)

            attachment_paths = [str(tmp_path)]

            # Get conversation memory and user session
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            # FEAT-120: cache user message ID
            self._cache_message_id(chat_id, message.message_id, caption)

            # FEAT-120: prepend reply context to enriched caption
            reply_ctx = self._extract_reply_context(message)
            enriched_caption = f"{caption}\n\n[Attached image saved at: {tmp_path}]"
            if reply_ctx:
                enriched_caption = reply_ctx + enriched_caption

            # Call agent with image (if supported)
            with telegram_chat_scope(chat_id):
                if hasattr(self.agent, 'ask_with_image'):
                    response = await self.agent.ask_with_image(
                        self._enrich_question(enriched_caption, session),
                        image_path=tmp_path,
                        user_id=session.user_id,
                        session_id=session.session_id,
                        memory=memory,
                        attachments=attachment_paths,
                    )
                else:
                    response = await self._invoke_agent(
                        session,
                        enriched_caption,
                        memory=memory,
                        output_mode=OutputMode.TELEGRAM,
                        message=message,
                        attachments=attachment_paths,
                    )

            parsed = self._parse_response(response)
            sent = await self._send_parsed_response(message, parsed)

            # FEAT-120: cache bot message ID and store metadata
            bot_msg_id = sent.message_id if sent else 0
            self._cache_message_id(chat_id, bot_msg_id, str(parsed)[:200])
            await self._store_telegram_metadata(
                memory, session.user_id, session.session_id,
                message.message_id, bot_msg_id,
            )

            # NOTE: temp file is NOT deleted here.
            # Agent or downstream tools may still need the path.
            # Cleanup happens via OS temp directory rotation.

        except Exception as e:
            self.logger.error(f"Error processing photo: {e}", exc_info=True)
            await message.answer("❌ Sorry, I couldn't process that image.")

    async def handle_document(self, message: Message) -> None:
        """Handle document messages."""
        chat_id = message.chat.id

        if not self._is_authorized(chat_id):
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            return

        document = message.document

        await message.answer(
            f"📄 Received document: {document.file_name}\n"
            f"Document processing is not yet fully implemented."
        )

    # ─── Voice Note / Audio File Handler ─────────────────────────────────

    def _get_transcriber(self) -> "VoiceTranscriber":
        """Get or lazily create the VoiceTranscriber instance."""
        if self._transcriber is None:
            from ...voice.transcriber import VoiceTranscriber
            self._transcriber = VoiceTranscriber(self.config.voice_config)
        return self._transcriber

    async def close(self) -> None:
        """Release resources held by the wrapper (call on shutdown)."""
        if self._transcriber is not None:
            await self._transcriber.close()
            self._transcriber = None

    async def handle_voice(self, message: Message) -> None:
        """Handle voice note (ContentType.VOICE) and audio file (ContentType.AUDIO).

        Steps:
            1. Auth + voice-enabled check
            2. Duration pre-check (before download)
            3. Download to temp file via bot.get_file / bot.download_file
            4. Transcribe via VoiceTranscriber
            5. Optionally reply with italic transcription text
            6. Process transcribed text through the agent message flow
            7. Delete temp file in finally block
        """
        chat_id = message.chat.id
        content_type = "voice" if message.voice else "audio" if message.audio else "unknown"
        self.logger.info(
            "Chat %d: Received %s message (handle_voice entered)",
            chat_id, content_type,
        )

        if not self._is_authorized(chat_id):
            self.logger.warning(
                "Chat %d: Voice message rejected — not authorized", chat_id
            )
            await message.answer("⛔ You are not authorized to use this bot.")
            return

        if not await self._check_authentication(message):
            self.logger.info(
                "Chat %d: Voice message skipped — authentication check failed",
                chat_id,
            )
            return

        # Skip if voice is not configured
        if not self.config.voice_enabled:
            self.logger.info(
                "Chat %d: Voice message ignored — voice_config not enabled "
                "(voice_config=%s)",
                chat_id, self.config.voice_config,
            )
            return

        voice_config = self.config.voice_config

        # Extract file_id, duration, and preferred suffix from message type
        if message.voice:
            file_id = message.voice.file_id
            duration = message.voice.duration or 0
            suffix = ".ogg"   # Telegram voice notes are always OGG/Opus
            self.logger.debug(
                "Chat %d: Voice note — file_id=%s, duration=%ds",
                chat_id, file_id, duration,
            )
        elif message.audio:
            file_id = message.audio.file_id
            duration = message.audio.duration or 0
            # Determine suffix from MIME type
            mt = (message.audio.mime_type or "").lower()
            if "ogg" in mt:
                suffix = ".ogg"
            elif "wav" in mt:
                suffix = ".wav"
            elif "m4a" in mt or "mp4" in mt:
                suffix = ".m4a"
            else:
                suffix = ".mp3"
            self.logger.debug(
                "Chat %d: Audio file — file_id=%s, duration=%ds, mime=%s",
                chat_id, file_id, duration, message.audio.mime_type,
            )
        else:
            self.logger.warning(
                "Chat %d: handle_voice called but message has no voice/audio",
                chat_id,
            )
            return

        # Duration pre-check (avoids large downloads for over-limit audio)
        if duration > voice_config.max_audio_duration_seconds:
            await message.answer(
                f"⏱ Audio too long ({duration}s). "
                f"Maximum is {voice_config.max_audio_duration_seconds}s."
            )
            return

        self.logger.info(
            "Chat %d: Starting voice processing — duration=%ds, suffix=%s",
            chat_id, duration, suffix,
        )
        typing_task = asyncio.create_task(self._typing_indicator(chat_id))
        tmp_path: Optional[Path] = None

        try:
            # Download audio from Telegram CDN to a temp file
            self.logger.debug("Chat %d: Calling bot.get_file(%s)", chat_id, file_id)
            file = await self.bot.get_file(file_id)
            self.logger.debug(
                "Chat %d: Got file — file_path=%s", chat_id, file.file_path
            )
            if file.file_path:
                # Use the actual extension from the Telegram file path when available
                tg_ext = Path(file.file_path).suffix
                if tg_ext:
                    suffix = tg_ext

            tmp = tempfile.NamedTemporaryFile(
                suffix=suffix, prefix="tg_voice_", delete=False
            )
            await self.bot.download_file(file.file_path, tmp)
            tmp.close()
            tmp_path = Path(tmp.name)
            self.logger.info(
                "Chat %d: Downloaded voice to %s (%d bytes)",
                chat_id, tmp_path, tmp_path.stat().st_size,
            )

            # Transcribe
            self.logger.debug(
                "Chat %d: Starting transcription (backend=%s, language=%s)",
                chat_id, voice_config.backend.value, voice_config.language,
            )
            transcriber = self._get_transcriber()
            result = await transcriber.transcribe_file(
                tmp_path, language=voice_config.language
            )
            self.logger.info(
                "Chat %d: Transcription complete — text='%s' (lang=%s, %.1fs, %dms)",
                chat_id, result.text[:80], result.language,
                result.duration_seconds, result.processing_time_ms,
            )

            typing_task.cancel()

            if not result.text.strip():
                await message.answer(
                    "❓ Sorry, I couldn't understand the audio. "
                    "Please try again or send a text message."
                )
                return

            # Optionally show transcription to user before processing
            if voice_config.show_transcription:
                await message.answer(f"🎙 _{result.text}_", parse_mode="Markdown")

            # Process transcribed text through the normal agent flow
            memory = self._get_or_create_memory(chat_id)
            session = self._get_user_session(message)

            self.logger.info(
                "Chat %d (user %s): Voice transcription [%s]: %s...",
                chat_id,
                session.user_id,
                result.language or "auto",
                result.text[:60],
            )

            # FEAT-120: cache user message ID and prepend reply context
            transcribed_text = result.text
            self._cache_message_id(chat_id, message.message_id, transcribed_text)
            reply_ctx = self._extract_reply_context(message)
            if reply_ctx:
                transcribed_text = reply_ctx + transcribed_text

            with telegram_chat_scope(chat_id):
                response = await self._invoke_agent(
                    session,
                    transcribed_text,
                    memory=memory,
                    output_mode=OutputMode.TELEGRAM,
                    message=message,
                )

            parsed = self._parse_response(response)
            sent = await self._send_parsed_response(message, parsed)

            # FEAT-120: cache bot message ID and store metadata
            bot_msg_id = sent.message_id if sent else 0
            self._cache_message_id(chat_id, bot_msg_id, str(parsed)[:200])
            await self._store_telegram_metadata(
                memory, session.user_id, session.session_id,
                message.message_id, bot_msg_id,
            )

        except ValueError as exc:
            # Duration limit or config validation error from transcriber
            typing_task.cancel()
            self.logger.warning(
                "Voice validation error for chat %d: %s", chat_id, exc
            )
            await message.answer(f"⚠️ {exc}")
        except Exception as exc:
            typing_task.cancel()
            self.logger.error(
                "Error processing voice message for chat %d: %s",
                chat_id, exc, exc_info=True,
            )
            await message.answer(
                "❌ Sorry, I couldn't process that voice message. Please try again."
            )
        finally:
            typing_task.cancel()
            # Always clean up the temp file
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError as exc:
                    self.logger.debug("Could not delete temp file %s: %s", tmp_path, exc)

    def _parse_response(self, response: Any) -> ParsedResponse:
        """Parse agent response into structured content."""
        return parse_response(response)

    def _extract_response_text(self, response: Any) -> str:
        """Extract text content from agent response (backward compatibility)."""
        parsed = self._parse_response(response)
        return parsed.text

    async def _convert_svg_to_png(self, svg_path: Path) -> Path:
        """
        Convert SVG to PNG for Telegram compatibility.
        
        Telegram Bot API does not support SVG images, so we must convert
        to a rasterized format.
        
        Args:
            svg_path: Path to the SVG file
            
        Returns:
            Path to the converted PNG file
            
        Note:
            Requires one of: cairosvg, svglib+reportlab, or wand
        """
        png_path = svg_path.with_suffix('.png')
        
        # If PNG already exists (cached), use it
        if png_path.exists():
            return png_path
        
        # Try conversion backends
        loop = asyncio.get_event_loop()
        
        def _do_convert():
            # Backend 1: cairosvg (best quality)
            try:
                import cairosvg
                cairosvg.svg2png(
                    url=str(svg_path), 
                    write_to=str(png_path),
                    dpi=150,
                    output_width=1200  # Good resolution for mobile
                )
                return png_path
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"cairosvg failed: {e}")
            
            # Backend 2: svglib + reportlab
            try:
                from svglib.svglib import svg2rlg
                from reportlab.graphics import renderPM
                
                drawing = svg2rlg(str(svg_path))
                if drawing:
                    # Scale for good resolution
                    scale = 2.0
                    drawing.width *= scale
                    drawing.height *= scale
                    drawing.scale(scale, scale)
                    
                    renderPM.drawToFile(
                        drawing, 
                        str(png_path), 
                        fmt="PNG",
                        dpi=150
                    )
                    return png_path
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"svglib failed: {e}")
            
            # Backend 3: wand (ImageMagick)
            try:
                from wand.image import Image as WandImage
                
                with WandImage(filename=str(svg_path), resolution=150) as img:
                    img.format = 'png'
                    img.save(filename=str(png_path))
                return png_path
            except ImportError:
                pass
            except Exception as e:
                self.logger.warning(f"wand failed: {e}")
            
            raise ImportError(
                "No SVG conversion backend available. "
                "Install one of: cairosvg, svglib, or wand (imagemagick)"
            )
        
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                return await loop.run_in_executor(executor, _do_convert)
        except ImportError as e:
            self.logger.error(f"SVG conversion failed: {e}")
            raise

    async def _send_parsed_response(
        self,
        message: Message,
        parsed: ParsedResponse,
        prefix: str = ""
    ) -> Optional[Message]:
        """
        Send parsed response content to Telegram.

        Handles text, images, documents, code blocks, and tables.

        Returns:
            The first sent Message object (for message ID tracking), or None
            if nothing was sent or sending failed.
        """
        chat_id = message.chat.id
        first_sent: Optional[Message] = None

        # Build the text response
        text_parts = []

        if prefix:
            text_parts.append(prefix)

        if parsed.text:
            text_to_add = parsed.text
            if self.config.use_html:
                # Convert Markdown to HTML
                text_to_add = self._markdown_to_html(text_to_add)
            else:
                # Convert Headers to Bold for Legacy Markdown
                text_to_add = self._convert_headers_to_bold(text_to_add)
            text_parts.append(text_to_add)

        # Add code block if present
        if parsed.has_code:
            lang = parsed.code_language or ""
            if self.config.use_html:
                code_block = f"<pre><code class=\"language-{lang}\">\n{parsed.code}\n</code></pre>"
            else:
                code_block = f"```{lang}\n{parsed.code}\n```"
            text_parts.append(code_block)

        # Add table if present (as markdown)
        if parsed.has_table and parsed.table_markdown:
            if self.config.use_html:
                 # Tables are tricky in Telegram HTML. Best to use <pre> block for alignment.
                 text_parts.append(f"<pre>\n{parsed.table_markdown}\n</pre>")
            else:
                text_parts.append(f"```\n{parsed.table_markdown}\n```")

        # Send the text message
        full_text = "\n\n".join(text_parts)

        parse_mode = "HTML" if self.config.use_html else "Markdown"

        if full_text.strip():
            first_sent = await self._send_long_message(message, full_text, parse_mode=parse_mode)
        
        # Send charts
        if hasattr(parsed, 'charts') and parsed.charts:
            for chart in parsed.charts:
                try:
                    image_path = chart.path
                    
                    # SVG not supported by Telegram - convert to PNG
                    if chart.format.lower() == "svg" or image_path.suffix.lower() == '.svg':
                        self.logger.info(f"Converting SVG chart to PNG: {chart.path.name}")
                        image_path = await self._convert_svg_to_png(chart.path)
                    
                    # Send chart with title as caption
                    caption = f"📊 {chart.title}"
                    if chart.chart_type and chart.chart_type != "unknown":
                        caption += f" ({chart.chart_type.replace('_', ' ').title()})"
                    
                    if image_path.exists():
                        await self.bot.send_photo(
                            chat_id=chat_id,
                            photo=FSInputFile(image_path),
                            caption=caption[:200]  # Telegram caption limit
                        )
                        await asyncio.sleep(0.3)  # Rate limiting
                        
                        self.logger.info(f"Sent chart to Telegram: {chart.title}")
                except Exception as e:
                    self.logger.error(f"Failed to send chart '{chart.title}': {e}")
                    # Send error message instead
                    await message.answer(f"⚠️ Could not display chart: {chart.title}")
        
        # Send images as photos
        for image_path in parsed.images:
            try:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=FSInputFile(image_path),
                    caption=image_path.name[:200] if len(parsed.images) > 1 else None
                )
                await asyncio.sleep(0.3)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send image {image_path}: {e}")
        
        # Send documents
        for doc_path in parsed.documents:
            try:
                await self.bot.send_document(
                    chat_id=chat_id,
                    document=FSInputFile(doc_path),
                    caption=doc_path.name[:200]
                )
                await asyncio.sleep(0.3)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send document {doc_path}: {e}")
        
        # Send media (videos, audio)
        for media_path in parsed.media:
            try:
                suffix = media_path.suffix.lower()
                if suffix in ('.mp4', '.avi', '.mov', '.webm', '.mkv'):
                    await self.bot.send_video(
                        chat_id=chat_id,
                        video=FSInputFile(media_path),
                        caption=media_path.name[:200]
                    )
                elif suffix in ('.mp3', '.wav', '.ogg', '.m4a'):
                    await self.bot.send_audio(
                        chat_id=chat_id,
                        audio=FSInputFile(media_path),
                        caption=media_path.name[:200]
                    )
                else:
                    await self.bot.send_document(
                        chat_id=chat_id,
                        document=FSInputFile(media_path)
                    )
                await asyncio.sleep(0.3)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send media {media_path}: {e}")

        return first_sent

    async def _send_long_message(
        self,
        message: Message,
        text: str,
        max_length: int = 4096,
        parse_mode: str = "Markdown",
    ) -> Optional[Message]:
        """Send a long message, splitting if necessary.

        Returns:
            The first sent Message object, or None if nothing was sent.
        """
        if not text:
            text = "..."

        # Split into chunks if needed
        if len(text) <= max_length:
            chunks = [text]
        else:
            chunks = []
            current = ""
            for line in text.split('\n'):
                if len(current) + len(line) + 1 > max_length:
                    if current:
                        chunks.append(current)
                    current = line
                else:
                    current += ('\n' if current else '') + line
            if current:
                chunks.append(current)

        first_sent: Optional[Message] = None
        for chunk in chunks:
            sent = await self._send_safe_message(message, chunk, parse_mode=parse_mode)
            if first_sent is None:
                first_sent = sent
            await asyncio.sleep(0.3)  # Rate limiting
        return first_sent



    async def _send_response_files(self, message: Message, response: Any) -> None:
        """Send any file attachments from the agent response."""
        if not hasattr(response, 'files'):
            return

        files = response.files or []
        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                continue

            # Determine file type and send appropriately
            suffix = path.suffix.lower()
            if suffix in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                await message.answer_photo(FSInputFile(path))
            else:
                await message.answer_document(FSInputFile(path))

    def _markdown_to_html(self, text: str) -> str:
        """
        Convert Markdown text to Telegram-supported HTML.
        
        Telegram HTML support:
        <b>bold</b>, <strong>bold</strong>
        <i>italic</i>, <em>italic</em>
        <u>underline</u>, <ins>underline</ins>
        <s>strikethrough</s>, <strike>strikethrough</strike>, <del>strikethrough</del>
        <span class="tg-spoiler">spoiler</span>
        <a href="http://www.example.com/">inline URL</a>
        <code>inline fixed-width code</code>
        <pre>pre-formatted fixed-width code block</pre>
        """
        if not text:
            return ""
        
        try:
            # Convert markdown to HTML with basic extras
            html = markdown2.markdown(
                text, 
                extras=["strike", "tables", "fenced-code-blocks", "code-friendly"]
            )
            
            # Clean up HTML for Telegram
            
            # 1. Remove <p> tags (replace with double newline)
            html = html.replace("<p>", "").replace("</p>", "\n\n")
            
            # 2. Replace headers <h1>-<h6> with <b> (bold) + newline
            html = re.sub(r'<h[1-6]>(.*?)</h[1-6]>', r'<b>\1</b>\n', html)
            
            # 3. Handle lists <ul><li> -> • ...
            # Remove <ul> / </ul> wrapper
            html = html.replace("<ul>", "").replace("</ul>", "")
            # Replace <li> with bullet point
            html = html.replace("<li>", "• ").replace("</li>", "\n")

            # 3b. Handle ordered lists <ol><li> -> "1. ..." lines
            # Remove <ol> wrapper
            html = html.replace("<ol>", "").replace("</ol>", "")

            # Replace </li> with newline (same as unordered)
            html = html.replace("</li>", "\n")

            # Convert <li> items in ordered lists to "1. ", "2. "...
            n = 0
            def repl_li(_m):
                nonlocal n
                n += 1
                return f"{n}. "
            html = re.sub(r"<li>", repl_li, html)
            
            # 4. <br> -> \n
            html = html.replace("<br>", "\n").replace("<br />", "\n")
            
            return html.strip()
        except Exception as e:
            self.logger.warning(f"Error converting Markdown to HTML: {e}")
            return text

    def _convert_headers_to_bold(self, text: str) -> str:
        """
        Sanitize LLM Markdown output for Telegram's legacy Markdown v1 parser.

        Telegram legacy Markdown only supports: *italic*, _italic_, `code`,
        ```code block```, and [link](url).  LLM output commonly contains
        constructs that crash the parser:

        * ``**bold**`` (double-asterisk) → converted to ``*bold*``
        * ``* item`` / ``- item`` bullet lines → converted to ``• item``
          (prevents the leading ``*`` from being parsed as an entity opener)
        * ``# Header`` lines → converted to ``*Header*``
        """
        if not text:
            return ""
        # 1. Convert **bold** / __bold__ to *bold* (single-asterisk italic)
        result = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text, flags=re.DOTALL)
        result = re.sub(r'__(.+?)__', r'_\1_', result, flags=re.DOTALL)
        # 2. Convert bullet lines (* item  /  - item  /  + item) to • item
        #    Only at line-start, so code-block content is unaffected.
        result = re.sub(r'^[ \t]*[*\-+][ \t]+', '• ', result, flags=re.MULTILINE)
        # 3. Convert Markdown headers (# … ######) to *Header*
        result = re.sub(r'^#{1,6}\s+(.*)', r'*\1*', result, flags=re.MULTILINE)
        return result

    def _strip_markdown(self, text: str) -> str:
        """
        Remove Markdown formatting characters to produce safe plain text.

        Used as the plaintext fallback when Telegram's parser rejects the
        formatted message.  All common markup tokens (* _ ` [] fenced blocks)
        are stripped, leaving the raw content readable.
        """
        if not text:
            return ""

        # Remove fenced code blocks (```...```) — keep inner content
        result = re.sub(r'```[\w]*\n?(.*?)```', r'\1', text, flags=re.DOTALL)
        # Remove inline code (`...`)
        result = re.sub(r'`([^`]*)`', r'\1', result)
        # Remove bold/italic markers (**text**, *text*, __text__, _text_)
        result = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', result, flags=re.DOTALL)
        result = re.sub(r'_{1,2}(.*?)_{1,2}', r'\1', result, flags=re.DOTALL)
        # Remove Markdown links [text](url) → text
        result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', result)
        # Remove any remaining lone special chars that trip the parser
        result = re.sub(r'(?<!\\)[*_`\[\]]', '', result)
        return result

    # Backward-compat alias — kept so any external callers don't break.
    _escape_markdown_legacy = _strip_markdown

    # ─── NEW: Callback Handling Methods ───

    async def _handle_callback_query(self, callback_query: CallbackQuery) -> None:
        """
        Route incoming CallbackQuery to the correct agent handler.

        This is the single aiogram callback_query handler that routes
        all inline button clicks to the appropriate @telegram_callback
        handler on the agent.
        """
        data = callback_query.data
        if not data:
            await callback_query.answer("⚠️ Empty callback data")
            return

        # Match callback_data against registered prefixes
        match = self._callback_registry.match(data)
        if not match:
            self.logger.warning(
                f"Unhandled callback_data: {data!r} "
                f"(known prefixes: {self._callback_registry.prefixes})"
            )
            await callback_query.answer("⚠️ Unknown action")
            return

        handler_meta, payload = match
        user = callback_query.from_user

        # Build context for the handler
        context = CallbackContext(
            prefix=handler_meta.prefix,
            payload=payload,
            chat_id=(
                callback_query.message.chat.id
                if callback_query.message else 0
            ),
            user_id=user.id if user else 0,
            message_id=(
                callback_query.message.message_id
                if callback_query.message else 0
            ),
            username=user.username if user else None,
            first_name=user.first_name if user else None,
            raw_query=callback_query,
        )

        self.logger.info(
            f"Callback [{handler_meta.prefix}] from user "
            f"{context.user_id} ({context.display_name}): "
            f"payload={payload}"
        )

        try:
            # Answer the callback query immediately to prevent
            # Telegram's 30-second timeout for long-running handlers.
            try:
                await callback_query.answer("⏳ Processing…")
            except Exception:
                pass  # Best-effort; already expired is fine

            # Invoke the agent's callback handler
            result = await handler_meta.method(context)

            # Normalize result
            if not isinstance(result, CallbackResult):
                if isinstance(result, str):
                    result = CallbackResult(answer_text=result)
                else:
                    result = CallbackResult(answer_text="✅")

            # Apply the result to Telegram (skip re-answering the callback)
            await self._apply_callback_result(
                callback_query, result, already_answered=True,
            )

        except Exception as e:
            self.logger.error(
                f"Error in callback [{handler_meta.prefix}]: {e}",
                exc_info=True,
            )
            # Send error as a new message instead of callback answer
            # (the callback was already answered above).
            if callback_query.message:
                try:
                    await self.bot.send_message(
                        chat_id=callback_query.message.chat.id,
                        text=f"❌ Error: {str(e)[:500]}",
                    )
                except Exception:
                    pass

    async def _apply_callback_result(
        self,
        callback_query: CallbackQuery,
        result: CallbackResult,
        already_answered: bool = False,
    ) -> None:
        """Apply a CallbackResult to the Telegram conversation."""

        # 1. Answer the callback (dismisses loading spinner on the button)
        if not already_answered:
            try:
                await callback_query.answer(
                    text=result.answer_text or "",
                    show_alert=result.show_alert,
                )
            except Exception as e:
                self.logger.debug(f"Callback answer skipped: {e}")

        # 2. Edit the original message if requested
        if result.edit_message and callback_query.message:
            try:
                edit_kwargs = {
                    "chat_id": callback_query.message.chat.id,
                    "message_id": callback_query.message.message_id,
                    "text": result.edit_message,
                    "parse_mode": result.edit_parse_mode,
                }
                if result.remove_keyboard:
                    edit_kwargs["reply_markup"] = None
                elif result.reply_markup is not None:
                    edit_kwargs["reply_markup"] = result.reply_markup

                await self.bot.edit_message_text(**edit_kwargs)
            except Exception as e:
                self.logger.warning(f"Failed to edit message: {e}")

        # 3. Send a new reply message if requested
        if result.reply_text and callback_query.message:
            try:
                await self.bot.send_message(
                    chat_id=callback_query.message.chat.id,
                    text=result.reply_text,
                    parse_mode=result.reply_parse_mode,
                )
            except Exception as e:
                self.logger.warning(f"Failed to send reply: {e}")

    async def send_interactive_message(
        self,
        chat_id: int,
        text: str,
        keyboard: dict,
        parse_mode: str = "Markdown",
    ) -> int | None:
        """
        Send a proactive message with inline keyboard to a specific chat.

        Used by agents for CRON-triggered notifications (not user-initiated).

        Args:
            chat_id: Target Telegram chat ID.
            text: Message text.
            keyboard: InlineKeyboardMarkup dict from build_inline_keyboard().
            parse_mode: Parse mode for the text.

        Returns:
            Message ID of the sent message, or None on failure.
        """
        try:
            # Convert raw dict to aiogram InlineKeyboardMarkup
            if isinstance(keyboard, dict) and "inline_keyboard" in keyboard:
                markup = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(**btn) for btn in row]
                        for row in keyboard["inline_keyboard"]
                    ]
                )
            else:
                markup = keyboard

            msg = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=markup,
                parse_mode=parse_mode,
            )
            return msg.message_id
        except Exception as e:
            self.logger.error(
                f"Failed to send interactive message to chat {chat_id}: {e}"
            )
            return None
