"""
Data models for Microsoft 365 Agents SDK bot configuration.
"""
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from navconfig import config


@dataclass
class MSAgentSDKConfig:
    """
    Configuration for a single agent exposed via Microsoft 365 Agents SDK.

    Supports two authentication modes:
    - Azure AD (production): provide ``client_id``, ``client_secret``, and
      ``tenant_id`` (or rely on env var fallback).
    - Anonymous (local development): set ``anonymous_auth = True`` and omit
      Azure AD credentials.

    Attributes:
        name: Agent name (used as key in YAML and for env var fallback prefix).
        chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
        client_id: Microsoft App ID / Azure AD application (client) ID.
        client_secret: Microsoft App password / Azure AD client secret.
        tenant_id: Azure AD tenant ID for single-tenant apps; None for
            multi-tenant.
        anonymous_auth: If True, skip JWT validation. Use only for local
            development; never in production.
        api_key: Shared secret for API-Key inbound auth. When set, the wrapper
            accepts a request carrying this value in ``api_key_header`` (in
            addition to Bot Framework JWTs). Needed for Copilot Studio's
            "Microsoft 365 Agents SDK" connection, which does NOT accept the
            "None" auth option — it requires API Key or OAuth 2.0. The bot still
            needs its Azure AD credentials to authenticate the OUTBOUND reply.
        api_key_header: Header name that carries ``api_key`` (default
            ``"x-api-key"``). Must match the header configured in Copilot's
            "API Key" connection auth.
        app_type: Azure AD application type — ``"SingleTenant"`` (default) or
            ``"MultiTenant"``. This drives the OUTBOUND token authority: a
            multi-tenant Bot Framework app must mint its reply token against the
            ``botframework.com`` authority (not the bot's home tenant), or the
            Bot Connector rejects the reply with HTTP 401 (Teams especially).
        authority: Explicit OAuth authority override. When unset it is derived
            from ``app_type``/``tenant_id``. Set this only for sovereign clouds
            or non-standard setups.
        kind: Integration type discriminator — always ``"msagentsdk"``.
        welcome_message: Message sent when a new member joins the conversation.
        system_prompt_override: Override the agent's default system prompt.
        endpoint: Custom messaging route path to register for this bot. When
            unset the wrapper derives the per-bot path
            ``/api/msagentsdk/{safe_id}/messages``. Set this to the Bot
            Framework standard ``"/api/messages"`` when the channel (Copilot
            Studio, Teams, the Bot Framework Emulator) is hard-wired to that
            endpoint. The per-bot path is always ALSO registered, so the bot
            stays reachable by its canonical URL regardless of this override.
        oauth_connections: Maps tool name to Azure Bot OAuth connection name
            for per-user token acquisition via the Bot Framework Token Service.
            Example: ``{"o365": "graph_sso", "jira": "jira_oauth"}``.
            When empty, user-token acquisition is disabled (backward compatible).
        obo_scopes: Maps tool name to a list of OBO target scopes for
            Microsoft-cluster APIs that require on-behalf-of token exchange.
            Example: ``{"o365": ["https://graph.microsoft.com/.default"]}``.
            Only relevant when ``oauth_connections`` is non-empty.
    """

    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    api_key: Optional[str] = None
    api_key_header: str = "x-api-key"
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    kind: str = "msagentsdk"
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    endpoint: Optional[str] = None
    oauth_connections: Dict[str, str] = field(default_factory=dict)
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """
        Resolve Azure AD credentials from environment variables when not
        provided directly in the YAML config.

        Falls back to ``{AGENT_NAME}_MICROSOFT_APP_ID``,
        ``{AGENT_NAME}_MICROSOFT_APP_PASSWORD``, and
        ``{AGENT_NAME}_MICROSOFT_TENANT_ID`` environment variables.
        """
        prefix = self.name.upper()
        if not self.client_id:
            self.client_id = config.get(f"{prefix}_MICROSOFT_APP_ID")
        if not self.client_secret:
            self.client_secret = config.get(f"{prefix}_MICROSOFT_APP_PASSWORD")
        if not self.tenant_id:
            self.tenant_id = config.get(f"{prefix}_MICROSOFT_TENANT_ID")
        # App type / authority overrides (default to SingleTenant when unset).
        env_app_type = config.get(f"{prefix}_MICROSOFT_APP_TYPE")
        if env_app_type:
            self.app_type = env_app_type
        if not self.authority:
            self.authority = config.get(f"{prefix}_MICROSOFT_AUTHORITY")
        # API-Key inbound auth (e.g. Copilot Studio connection).
        if not self.api_key:
            self.api_key = config.get(f"{prefix}_API_KEY")
        env_api_key_header = config.get(f"{prefix}_API_KEY_HEADER")
        if env_api_key_header:
            self.api_key_header = env_api_key_header
        # Custom messaging endpoint override (e.g. "/api/messages").
        if not self.endpoint:
            self.endpoint = config.get(f"{prefix}_ENDPOINT")
        # Per-user OAuth connections (JSON-encoded env var fallback).
        if not self.oauth_connections:
            raw = config.get(f"{prefix}_OAUTH_CONNECTIONS")
            if raw:
                try:
                    self.oauth_connections = json.loads(raw)
                except (ValueError, TypeError):
                    pass
        # OBO scopes for Microsoft-cluster APIs (JSON-encoded env var fallback).
        if not self.obo_scopes:
            raw = config.get(f"{prefix}_OBO_SCOPES")
            if raw:
                try:
                    self.obo_scopes = json.loads(raw)
                except (ValueError, TypeError):
                    pass

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentSDKConfig":
        """Create config from dictionary (YAML parsed data).

        Args:
            name: Agent name used as YAML key and env var prefix.
            data: Parsed YAML dictionary for this agent.

        Returns:
            Fully initialised ``MSAgentSDKConfig`` instance.
        """
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            tenant_id=data.get("tenant_id"),
            anonymous_auth=data.get("anonymous_auth", False),
            api_key=data.get("api_key"),
            api_key_header=data.get("api_key_header", "x-api-key"),
            app_type=data.get("app_type", "SingleTenant"),
            authority=data.get("authority"),
            welcome_message=data.get("welcome_message"),
            system_prompt_override=data.get("system_prompt_override"),
            endpoint=data.get("endpoint"),
            oauth_connections=data.get("oauth_connections", {}),
            obo_scopes=data.get("obo_scopes", {}),
        )
