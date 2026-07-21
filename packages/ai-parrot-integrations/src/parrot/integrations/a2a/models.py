"""
Data models for exposing AI-Parrot agents as A2A (Agent-to-Agent) services.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from navconfig import config


@dataclass
class A2AAgentConfig:
    """
    Configuration for a single agent exposed via the A2A protocol.

    Models a ``kind: a2a`` entry in ``integrations_bots.yaml``. Wraps a
    registered agent with ``A2AServer``, optionally protected by
    ``A2ASecurityMiddleware`` (JWT, API key, mTLS, HMAC, or Basic auth), and
    optionally wired to a ``CredentialBroker`` built from the inline
    ``credentials`` list.

    Attributes:
        name: Agent name (used as key in YAML and for env var fallback prefix).
        chatbot_id: ID/name of the bot in BotManager (used with get_bot()).
        kind: Integration type discriminator — always ``"a2a"``.
        url: Public base URL for this A2A agent (used in the AgentCard).
        base_path: Base path for the A2A routes (default ``"/a2a"``).
        port: Dedicated TCP port for this agent. When ``None`` the agent's
            routes are mounted on the shared aiohttp app.
        tags: Tags describing the agent, surfaced in the AgentCard.
        welcome_message: Message sent when a new conversation starts.
        system_prompt_override: Override the agent's default system prompt.
        output_mode: Output mode requested from the agent on every A2A turn
            (default ``"text"`` — markdown-free plain text, since A2A
            consumers such as Microsoft Copilot render TextParts literally).
            Set to ``"default"`` to keep the agent's native (markdown) output.
        jwt_secret: Shared secret for JWT auth on inbound A2A requests.
        api_key: Shared secret for API-Key auth on inbound A2A requests.
        api_key_header: Header name that carries ``api_key`` (default
            ``"X-API-Key"``).
        mtls_ca_cert: Path to the CA cert used to validate client certs for
            mTLS auth.
        hmac_secret: Shared secret for HMAC-signed request auth.
        basic_credentials: Mapping of username to password for Basic auth.
        security_policy: Raw ``SecurityPolicy`` fields (require_auth,
            allowed_schemes, allowed_agents, etc.), forwarded as-is.
        enable_credential_broker: If True, build a ``CredentialBroker`` from
            ``credentials`` and pass it to ``A2AServer``.
        credentials: Inline list of provider credential dicts (raw, parsed
            into ``ProviderCredentialConfig`` at startup time).
    """

    name: str
    chatbot_id: str
    kind: str = "a2a"
    url: Optional[str] = None
    base_path: str = "/a2a"
    port: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    welcome_message: Optional[str] = None
    system_prompt_override: Optional[str] = None
    output_mode: str = "text"

    # Security
    jwt_secret: Optional[str] = None
    api_key: Optional[str] = None
    api_key_header: str = "X-API-Key"
    mtls_ca_cert: Optional[str] = None
    hmac_secret: Optional[str] = None
    basic_credentials: Optional[Dict[str, str]] = None
    security_policy: Optional[Dict[str, Any]] = None

    # Credential broker
    enable_credential_broker: bool = False
    credentials: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        """
        Resolve security secrets from environment variables when not
        provided directly in the YAML config.

        Falls back to ``{AGENT_NAME}_JWT_SECRET``, ``{AGENT_NAME}_API_KEY``,
        and ``{AGENT_NAME}_HMAC_SECRET`` environment variables.
        """
        prefix = self.name.upper()
        if not self.jwt_secret:
            self.jwt_secret = config.get(f"{prefix}_JWT_SECRET")
        if not self.api_key:
            self.api_key = config.get(f"{prefix}_API_KEY")
        if not self.hmac_secret:
            self.hmac_secret = config.get(f"{prefix}_HMAC_SECRET")
        if not self.mtls_ca_cert:
            self.mtls_ca_cert = config.get(f"{prefix}_MTLS_CA_CERT")

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "A2AAgentConfig":
        """Create config from dictionary (YAML parsed data).

        Args:
            name: Agent name used as YAML key and env var prefix.
            data: Parsed YAML dictionary for this agent.

        Returns:
            Fully initialised ``A2AAgentConfig`` instance.
        """
        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            url=data.get("url"),
            base_path=data.get("base_path", "/a2a"),
            port=data.get("port"),
            tags=data.get("tags", []),
            welcome_message=data.get("welcome_message"),
            system_prompt_override=data.get("system_prompt_override"),
            output_mode=data.get("output_mode", "text"),
            jwt_secret=data.get("jwt_secret"),
            api_key=data.get("api_key"),
            api_key_header=data.get("api_key_header", "X-API-Key"),
            mtls_ca_cert=data.get("mtls_ca_cert"),
            hmac_secret=data.get("hmac_secret"),
            basic_credentials=data.get("basic_credentials"),
            security_policy=data.get("security_policy"),
            enable_credential_broker=data.get("enable_credential_broker", False),
            credentials=data.get("credentials", []),
        )
