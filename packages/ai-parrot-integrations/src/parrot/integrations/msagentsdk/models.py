"""
Data models for Microsoft 365 Agents SDK bot configuration.
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional
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
    """

    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_id: Optional[str] = None
    anonymous_auth: bool = False
    app_type: str = "SingleTenant"
    authority: Optional[str] = None
    kind: str = "msagentsdk"
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None

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
            app_type=data.get("app_type", "SingleTenant"),
            authority=data.get("authority"),
            welcome_message=data.get("welcome_message"),
            system_prompt_override=data.get("system_prompt_override"),
        )
