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
        enable_semantic_cards: If True (default), a ``SemanticUIResult``
            returned by the agent (FEAT-303) is rendered as an Adaptive Card;
            if False, the plain-text path is always used even when the model
            is present.
        max_table_rows: Maximum number of table rows rendered in a Semantic
            UI table card before truncating with a "showing N of M" note
            (FEAT-303).
        max_card_bytes: Maximum serialized Semantic UI card size in bytes;
            exceeding it triggers the plain-text fallback (FEAT-303).
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
    enable_semantic_cards: bool = True
    max_table_rows: int = 50
    max_card_bytes: int = 25_000

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


@dataclass
class MSAgentIntegrationConfig:
    """
    Configuration for a full-featured Microsoft Agents SDK bot exposed via
    ``kind: msagent`` entries in ``integrations_bots.yaml``.

    Extends the minimal ``MSAgentSDKConfig`` surface with a
    ``CredentialBroker`` (built from the inline ``credentials`` list), O365
    OAuth2 SSO/OBO infrastructure, and an automatic A2A companion surface
    (sharing the same broker). Use ``to_msagentsdk_config()`` to obtain the
    inner ``MSAgentSDKConfig`` consumed by ``MSAgentSDKWrapper``.

    Attributes:
        name: Agent name (used as key in YAML and for env var fallback prefix).
        chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
        kind: Integration type discriminator — always ``"msagent"``.
        microsoft_app_id: Microsoft App ID / Azure AD application (client) ID.
            Forwarded to ``MSAgentSDKConfig.client_id``.
        microsoft_app_password: Microsoft App password / Azure AD client
            secret. Forwarded to ``MSAgentSDKConfig.client_secret``.
        microsoft_tenant_id: Azure AD tenant ID for single-tenant apps.
            Forwarded to ``MSAgentSDKConfig.tenant_id``.
        anonymous_auth: If True, skip JWT validation (local dev only).
        api_key: Shared secret for API-Key inbound auth.
        api_key_header: Header name that carries ``api_key``.
        app_type: Azure AD application type — ``"SingleTenant"`` or
            ``"MultiTenant"``.
        authority: Explicit OAuth authority override.
        welcome_message: Message sent when a new member joins.
        system_prompt_override: Override the agent's default system prompt.
        endpoint: Custom messaging route path override.
        oauth_connections: Maps tool name to Azure Bot OAuth connection name.
        obo_scopes: Maps tool name to a list of OBO target scopes.
        url: Public base URL for the automatic A2A companion surface.
        tags: Tags describing the agent, surfaced in the companion AgentCard.
        enable_credential_broker: If True, build a ``CredentialBroker`` from
            ``credentials`` and pass it to ``MSAgentSDKWrapper`` and the A2A
            companion.
        credentials: Inline list of provider credential dicts (raw, parsed
            into ``ProviderCredentialConfig`` at startup time).
        o365_client_id: Azure AD application (client) ID for O365 OAuth2 SSO.
        o365_client_secret: Azure AD client secret for O365 OAuth2 SSO.
        o365_tenant_id: Azure AD tenant ID for O365 OAuth2 SSO.
        redirect_uri: OAuth2 redirect URI for the O365 SSO flow.
        jwt_secret: Shared secret for JWT auth on the A2A companion surface.
        debug: If True, enable verbose debug logging for this bot.
    """

    name: str
    chatbot_id: str
    kind: str = "msagent"

    # MS Agent SDK fields (forwarded to MSAgentSDKConfig)
    microsoft_app_id: Optional[str] = None
    microsoft_app_password: Optional[str] = None
    microsoft_tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    api_key: Optional[str] = None
    api_key_header: str = "x-api-key"
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    endpoint: Optional[str] = None
    oauth_connections: Dict[str, str] = field(default_factory=dict)
    obo_scopes: Dict[str, List[str]] = field(default_factory=dict)

    # A2A companion (always on)
    url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    # Output mode requested from the agent on A2A companion turns
    # ("text" = markdown-free plain text for Copilot; "default" = native output).
    output_mode: str = "text"

    # Credential broker
    enable_credential_broker: bool = False
    credentials: List[Dict[str, Any]] = field(default_factory=list)

    # O365 OAuth infra
    o365_client_id: Optional[str] = None
    o365_client_secret: Optional[str] = None
    o365_tenant_id: Optional[str] = None
    redirect_uri: Optional[str] = None

    # JWT for A2A companion
    jwt_secret: Optional[str] = None
    debug: bool = False

    def __post_init__(self) -> None:
        """
        Resolve Azure AD, O365, and security credentials from environment
        variables when not provided directly in the YAML config.

        Falls back to ``{AGENT_NAME}_MICROSOFT_APP_ID``,
        ``{AGENT_NAME}_MICROSOFT_APP_PASSWORD``,
        ``{AGENT_NAME}_MICROSOFT_TENANT_ID``, ``{AGENT_NAME}_O365_CLIENT_ID``,
        ``{AGENT_NAME}_O365_CLIENT_SECRET``, ``{AGENT_NAME}_O365_TENANT_ID``,
        and ``{AGENT_NAME}_JWT_SECRET`` environment variables.
        """
        prefix = self.name.upper()
        if not self.microsoft_app_id:
            self.microsoft_app_id = config.get(f"{prefix}_MICROSOFT_APP_ID")
        if not self.microsoft_app_password:
            self.microsoft_app_password = config.get(f"{prefix}_MICROSOFT_APP_PASSWORD")
        if not self.microsoft_tenant_id:
            self.microsoft_tenant_id = config.get(f"{prefix}_MICROSOFT_TENANT_ID")
        env_app_type = config.get(f"{prefix}_MICROSOFT_APP_TYPE")
        if env_app_type:
            self.app_type = env_app_type
        if not self.authority:
            self.authority = config.get(f"{prefix}_MICROSOFT_AUTHORITY")
        if not self.api_key:
            self.api_key = config.get(f"{prefix}_API_KEY")
        env_api_key_header = config.get(f"{prefix}_API_KEY_HEADER")
        if env_api_key_header:
            self.api_key_header = env_api_key_header
        if not self.endpoint:
            self.endpoint = config.get(f"{prefix}_ENDPOINT")
        if not self.oauth_connections:
            raw = config.get(f"{prefix}_OAUTH_CONNECTIONS")
            if raw:
                try:
                    self.oauth_connections = json.loads(raw)
                except (ValueError, TypeError):
                    pass
        if not self.obo_scopes:
            raw = config.get(f"{prefix}_OBO_SCOPES")
            if raw:
                try:
                    self.obo_scopes = json.loads(raw)
                except (ValueError, TypeError):
                    pass
        if not self.o365_client_id:
            self.o365_client_id = config.get(f"{prefix}_O365_CLIENT_ID")
        if not self.o365_client_secret:
            self.o365_client_secret = config.get(f"{prefix}_O365_CLIENT_SECRET")
        if not self.o365_tenant_id:
            self.o365_tenant_id = config.get(f"{prefix}_O365_TENANT_ID")
        if not self.redirect_uri:
            self.redirect_uri = config.get(f"{prefix}_REDIRECT_URI")
        if not self.jwt_secret:
            self.jwt_secret = config.get(f"{prefix}_JWT_SECRET")

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSAgentIntegrationConfig":
        """Create config from dictionary (YAML parsed data).

        Args:
            name: Agent name used as YAML key and env var prefix.
            data: Parsed YAML dictionary for this agent.

        Returns:
            Fully initialised ``MSAgentIntegrationConfig`` instance.
        """
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            microsoft_app_id=data.get("microsoft_app_id"),
            microsoft_app_password=data.get("microsoft_app_password"),
            microsoft_tenant_id=data.get("microsoft_tenant_id"),
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
            url=data.get("url"),
            tags=data.get("tags", []),
            output_mode=data.get("output_mode", "text"),
            enable_credential_broker=data.get("enable_credential_broker", False),
            credentials=data.get("credentials", []),
            o365_client_id=data.get("o365_client_id"),
            o365_client_secret=data.get("o365_client_secret"),
            o365_tenant_id=data.get("o365_tenant_id"),
            redirect_uri=data.get("redirect_uri"),
            jwt_secret=data.get("jwt_secret"),
            debug=data.get("debug", False),
        )

    def to_msagentsdk_config(self) -> MSAgentSDKConfig:
        """Convert to the inner ``MSAgentSDKConfig`` used by ``MSAgentSDKWrapper``.

        Returns:
            ``MSAgentSDKConfig`` populated from the MS Agent SDK fields of
            this config.
        """
        return MSAgentSDKConfig(
            name=self.name,
            chatbot_id=self.chatbot_id,
            client_id=self.microsoft_app_id,
            client_secret=self.microsoft_app_password,
            tenant_id=self.microsoft_tenant_id,
            anonymous_auth=self.anonymous_auth,
            api_key=self.api_key,
            api_key_header=self.api_key_header,
            app_type=self.app_type,
            authority=self.authority,
            welcome_message=self.welcome_message,
            system_prompt_override=self.system_prompt_override,
            endpoint=self.endpoint,
            oauth_connections=self.oauth_connections,
            obo_scopes=self.obo_scopes,
        )
