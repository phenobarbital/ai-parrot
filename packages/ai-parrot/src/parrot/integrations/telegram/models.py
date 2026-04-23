"""
Data models for Telegram bot configuration.
"""
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Any
from navconfig import config

logger = logging.getLogger(__name__)

# Known providers that can be referenced from YAML ``post_auth_actions``.
# This is a soft allow-list used only by ``TelegramBotsConfig.validate()`` to
# emit a warning; the actual registry of providers is populated at runtime.
_KNOWN_POST_AUTH_PROVIDERS = frozenset({"jira"})

if TYPE_CHECKING:
    from parrot.voice.transcriber import VoiceTranscriberConfig


@dataclass
class PostAuthAction:
    """
    Configuration for a secondary authentication action to chain after
    primary authentication (e.g., Jira OAuth2 3LO after BasicAuth).

    Attributes:
        provider: Name of the secondary auth provider (e.g., "jira",
                  "confluence", "github"). Must match a registered
                  ``PostAuthProvider`` at runtime.
        required: If True, failure of this secondary auth rolls back the
                  primary authentication session. If False (default), the
                  primary session remains authenticated even on failure.
    """
    provider: str
    required: bool = False


@dataclass
class TelegramAgentConfig:
    """
    Configuration for a single agent exposed via Telegram.

    Attributes:
        name: Agent name (used as key in YAML and for env var fallback).
        chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
        bot_token: Telegram bot token. If not provided, reads from
                   {NAME}_TELEGRAM_TOKEN environment variable.
        allowed_chat_ids: Optional list of chat IDs that can use this bot.
                          If None, the bot is accessible to all chats.
        welcome_message: Custom message sent when user issues /start command.
        system_prompt_override: Override the agent's default system prompt.
        commands: Custom commands that map to agent methods.
                  Format: {"command_name": "agent_method_name"}
                  E.g.:   {"report": "generate_report"}
        enable_group_mentions: Allow bot to respond to @mentions in groups.
        enable_group_commands: Allow bot to respond to /ask command in groups.
        reply_in_thread: Reply as thread to original message in groups.
        enable_channel_posts: Allow bot to process channel posts with @mentions.
    """
    name: str
    chatbot_id: str
    bot_token: Optional[str] = None
    allowed_chat_ids: Optional[List[int]] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    kind: str = "telegram"
    commands: Dict[str, str] = field(default_factory=dict)
    # Group/channel support settings
    enable_group_mentions: bool = True
    enable_group_commands: bool = True
    reply_in_thread: bool = True
    enable_channel_posts: bool = False
    register_menu: bool = True
    # Authentication settings
    auth_url: Optional[str] = None
    login_page_url: Optional[str] = None
    enable_login: bool = True
    use_html: bool = False
    force_authentication: bool = False
    # Auth method selection: "basic" (Navigator) or "oauth2"
    auth_method: str = "basic"
    # FEAT-109: multi-method list. When set, takes priority over auth_method.
    # Populated by __post_init__ from auth_method when not explicitly set.
    auth_methods: List[str] = field(default_factory=list)
    # OAuth2 settings (used when auth_method="oauth2")
    oauth2_provider: str = "google"
    oauth2_client_id: Optional[str] = None
    oauth2_client_secret: Optional[str] = None
    oauth2_scopes: Optional[List[str]] = None
    oauth2_redirect_uri: Optional[str] = None
    # Azure SSO settings (used when auth_method="azure")
    azure_auth_url: Optional[str] = None
    # Voice transcription settings
    voice_config: Optional["VoiceTranscriberConfig"] = None
    # Post-authentication actions (secondary auth providers chained after primary)
    post_auth_actions: List[PostAuthAction] = field(default_factory=list)
    # Per-user agent isolation.
    # True  (default): the wrapper keeps one shared agent instance and
    #                  hands each user a private clone of the agent's
    #                  ToolManager. Cheap startup, but concurrent messages
    #                  for the same wrapper serialize on an asyncio lock
    #                  because the shared agent's ``tool_manager`` is
    #                  mutated per request.
    # False          : the wrapper builds an entire per-user agent via
    #                  ``AbstractBot.clone_for_user`` and stashes it on
    #                  the user session. Heavier, but removes the lock
    #                  and supports agents with tool state held on
    #                  ``self``. Requires the agent subclass to
    #                  implement ``clone_for_user``.
    singleton_agent: bool = True

    # Hard ceiling (seconds) for a single ``agent.ask`` invocation from
    # Telegram. When the agent (or a tool it calls) hangs — typically a
    # blocking HTTP call inside ``asyncio.to_thread`` with no timeout —
    # this prevents ``self._agent_lock`` from being held forever, which
    # would otherwise freeze every user on the bot silently. Matches the
    # 120s default used by the Slack wrapper for consistency.
    agent_timeout: float = 120.0
    # Document handling settings (FEAT-120)
    max_document_size_mb: int = 20
    # Reply context enrichment (FEAT-120)
    enable_reply_context: bool = True

    def __post_init__(self):
        """Resolve bot_token, auth_url, OAuth2, and Azure credentials from environment.

        Falls back to {AGENT_NAME}_TELEGRAM_TOKEN for bot_token.
        Falls back to NAVIGATOR_AUTH_URL for auth_url.
        Falls back to {AGENT_NAME}_OAUTH2_CLIENT_ID / _SECRET for OAuth2 credentials.
        Falls back to {AGENT_NAME}_AZURE_AUTH_URL for azure_auth_url; when still
        unset and auth_url is available, derives azure_auth_url by replacing the
        trailing ``/login`` endpoint with ``/azure/``.

        FEAT-109: normalizes ``auth_methods`` list from the legacy ``auth_method``
        singleton when not explicitly set, and validates entries.
        """
        if not self.bot_token:
            env_var_name = f"{self.name.upper()}_TELEGRAM_TOKEN"
            self.bot_token = config.get(env_var_name)
        if not self.auth_url:
            self.auth_url = config.get('NAVIGATOR_AUTH_URL')

        # FEAT-109: Normalize auth_methods.
        # When not explicitly set, derive from the legacy auth_method singleton.
        if not self.auth_methods:
            if self.auth_method:
                self.auth_methods = [self.auth_method]
            # else: no auth configured — leave empty

        # Validate every entry in the normalized list.
        _ALLOWED_AUTH_METHODS = {"basic", "azure", "oauth2"}
        unknown = [m for m in self.auth_methods if m not in _ALLOWED_AUTH_METHODS]
        if unknown:
            raise ValueError(
                f"Agent '{self.name}': unknown auth_methods entries: "
                f"{unknown}. Allowed: {sorted(_ALLOWED_AUTH_METHODS)}"
            )

        name_upper = self.name.upper()

        # Resolve OAuth2 credentials from env vars when oauth2 is in the list.
        # Generalizes the former auth_method == "oauth2" branch.
        if "oauth2" in self.auth_methods:
            if not self.oauth2_client_id:
                self.oauth2_client_id = config.get(
                    f"{name_upper}_OAUTH2_CLIENT_ID"
                )
            if not self.oauth2_client_secret:
                self.oauth2_client_secret = config.get(
                    f"{name_upper}_OAUTH2_CLIENT_SECRET"
                )

        # Resolve Azure auth URL from env var or derive from auth_url.
        # Generalizes the former auth_method == "azure" branch.
        if "azure" in self.auth_methods:
            if not self.azure_auth_url:
                self.azure_auth_url = config.get(
                    f"{name_upper}_AZURE_AUTH_URL"
                )
            # Derive azure_auth_url from auth_url when still not set
            if not self.azure_auth_url and self.auth_url:
                base = self.auth_url.rstrip("/")
                # Strip trailing endpoint name if it looks like an action endpoint
                # (e.g. /login) but NOT base path segments (e.g. /auth)
                if base.endswith("/login"):
                    base = base.rsplit("/", 1)[0]
                self.azure_auth_url = f"{base}/azure/"

    @property
    def voice_enabled(self) -> bool:
        """Return True if voice transcription is configured and enabled."""
        return self.voice_config is not None and self.voice_config.enabled

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> 'TelegramAgentConfig':
        """Create config from dictionary (YAML parsed data)."""
        # Parse voice_config if provided
        voice_config = None
        if voice_data := data.get('voice_config'):
            from parrot.voice.transcriber import VoiceTranscriberConfig
            if isinstance(voice_data, dict):
                voice_config = VoiceTranscriberConfig(**voice_data)
            elif isinstance(voice_data, VoiceTranscriberConfig):
                voice_config = voice_data

        # Parse post_auth_actions if provided
        post_auth_actions: List[PostAuthAction] = []
        if pa_data := data.get('post_auth_actions'):
            for entry in pa_data:
                if isinstance(entry, PostAuthAction):
                    post_auth_actions.append(entry)
                elif isinstance(entry, dict):
                    post_auth_actions.append(
                        PostAuthAction(
                            provider=entry['provider'],
                            required=bool(entry.get('required', False)),
                        )
                    )

        # FEAT-109: parse auth_methods — accept list or string form.
        raw_auth_methods = data.get('auth_methods')
        if isinstance(raw_auth_methods, str):
            auth_methods: List[str] = [raw_auth_methods]
        elif isinstance(raw_auth_methods, list):
            auth_methods = list(raw_auth_methods)
        else:
            auth_methods = []

        return cls(
            name=name,
            chatbot_id=data.get('chatbot_id', name),  # Default to name if not specified
            bot_token=data.get('bot_token'),
            allowed_chat_ids=data.get('allowed_chat_ids'),
            welcome_message=data.get('welcome_message'),
            system_prompt_override=data.get('system_prompt_override'),
            commands=data.get('commands', {}),
            enable_group_mentions=data.get('enable_group_mentions', True),
            enable_group_commands=data.get('enable_group_commands', True),
            reply_in_thread=data.get('reply_in_thread', True),
            enable_channel_posts=data.get('enable_channel_posts', False),
            register_menu=data.get('register_menu', True),
            auth_url=data.get('auth_url'),
            login_page_url=data.get('login_page_url'),
            enable_login=data.get('enable_login', True),
            use_html=data.get('use_html', False),
            force_authentication=data.get('force_authentication', False),
            auth_method=data.get('auth_method', 'basic'),
            auth_methods=auth_methods,
            oauth2_provider=data.get('oauth2_provider', 'google'),
            oauth2_client_id=data.get('oauth2_client_id'),
            oauth2_client_secret=data.get('oauth2_client_secret'),
            oauth2_scopes=data.get('oauth2_scopes'),
            oauth2_redirect_uri=data.get('oauth2_redirect_uri'),
            azure_auth_url=data.get('azure_auth_url'),
            voice_config=voice_config,
            post_auth_actions=post_auth_actions,
            singleton_agent=bool(data.get('singleton_agent', True)),
            agent_timeout=float(data.get('agent_timeout', 120.0)),
            max_document_size_mb=int(data.get('max_document_size_mb', 20)),
            enable_reply_context=bool(data.get('enable_reply_context', True)),
        )


@dataclass
class TelegramBotsConfig:
    """
    Root configuration for all Telegram bots.

    Loaded from {ENV_DIR}/telegram_bots.yaml.

    Example YAML structure:
        agents:
          HRAgent:
            chatbot_id: hr_agent
            welcome_message: "Hello! I'm your HR Assistant."
            # bot_token: optional - defaults to HRAGENT_TELEGRAM_TOKEN env var
    """
    agents: Dict[str, TelegramAgentConfig] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TelegramBotsConfig':
        """Create config from dictionary (YAML parsed data)."""
        agents = {}
        agents_data = data.get('agents', {})
        for name, agent_data in agents_data.items():
            agents[name] = TelegramAgentConfig.from_dict(name, agent_data)
        return cls(agents=agents)

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors.

        Iterates over every agent and checks:
        - Required fields (chatbot_id, bot_token).
        - Per-method requirements for every entry in auth_methods:
          - ``"oauth2"`` → oauth2_client_id + oauth2_client_secret required.
          - ``"azure"``  → azure_auth_url or auth_url required.
        - Multi-auth constraint: when auth_methods has >= 2 entries,
          login_page_url must be set AND reference ``login_multi.html``.
        - Soft warning for unknown post_auth_actions providers (unchanged).

        Returns:
            List of error message strings (empty when config is valid).
        """
        errors = []
        for name, agent_config in self.agents.items():
            if not agent_config.chatbot_id:
                errors.append(f"Agent '{name}': missing 'chatbot_id'")
            if not agent_config.bot_token:
                errors.append(
                    f"Agent '{name}': missing bot_token (set in YAML or "
                    f"env var {name.upper()}_TELEGRAM_TOKEN)"
                )

            # FEAT-109: per-method validation — iterates auth_methods list.
            for method in agent_config.auth_methods:
                if method == "oauth2":
                    if not agent_config.oauth2_client_id:
                        errors.append(
                            f"Agent '{name}': auth_method 'oauth2' requires "
                            f"oauth2_client_id (set in YAML or "
                            f"env var {name.upper()}_OAUTH2_CLIENT_ID)"
                        )
                    if not agent_config.oauth2_client_secret:
                        errors.append(
                            f"Agent '{name}': auth_method 'oauth2' requires "
                            f"oauth2_client_secret (set in YAML or "
                            f"env var {name.upper()}_OAUTH2_CLIENT_SECRET)"
                        )
                elif method == "azure":
                    if not agent_config.azure_auth_url and not agent_config.auth_url:
                        errors.append(
                            f"Agent '{name}': auth_method 'azure' requires "
                            f"azure_auth_url or a derivable auth_url "
                            f"(set azure_auth_url in YAML or "
                            f"env var {name.upper()}_AZURE_AUTH_URL)"
                        )

            # FEAT-109: oauth2 cannot be combined with other methods.
            # login_multi.html renders basic and azure buttons only; there is
            # no OAuth2 button and the PKCE state machine cannot be driven
            # from a shared chooser page.
            if "oauth2" in agent_config.auth_methods and len(agent_config.auth_methods) > 1:
                errors.append(
                    f"Agent '{name}': 'oauth2' cannot be combined with other "
                    f"auth_methods {agent_config.auth_methods!r}. "
                    f"login_multi.html does not implement an OAuth2 flow. "
                    f"Use auth_method: oauth2 alone, or remove oauth2 from "
                    f"auth_methods and use basic/azure for multi-auth."
                )

            # FEAT-109: multi-auth login page constraint.
            if len(agent_config.auth_methods) >= 2:
                if not agent_config.login_page_url:
                    errors.append(
                        f"Agent '{name}': auth_methods has "
                        f"{len(agent_config.auth_methods)} entries but "
                        f"login_page_url is unset. Multi-auth bots must use "
                        f"the shared chooser page (login_multi.html)."
                    )
                elif "login_multi.html" not in agent_config.login_page_url.lower():
                    errors.append(
                        f"Agent '{name}': auth_methods has "
                        f"{len(agent_config.auth_methods)} entries but "
                        f"login_page_url does not reference 'login_multi.html'. "
                        f"Multi-auth bots must use the shared chooser page."
                    )

            # Soft warning for unknown post_auth_actions providers.
            # Providers are registered at runtime, so we can't hard-fail here.
            for action in agent_config.post_auth_actions:
                if action.provider not in _KNOWN_POST_AUTH_PROVIDERS:
                    logger.warning(
                        "Agent '%s': post_auth_actions references unknown "
                        "provider '%s'. Ensure a PostAuthProvider is "
                        "registered for it at runtime.",
                        name,
                        action.provider,
                    )
        return errors
