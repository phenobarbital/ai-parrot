"""
Data models for MS Teams bot configuration.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Any

from navconfig import config
from parrot.integrations.knowledge_upload.models import KnowledgeUploadConfig
from parrot.outputs.cards.spec import DEFAULT_ADAPTIVE_CARD_VERSION

logger = logging.getLogger(__name__)


class UnsignedSubmitConfigError(ValueError):
    """The FormDesigner Teams branch has a bearer token but no signing secret."""


def _validated_tenant_map(value: Any, *, source: str) -> Optional[Dict[str, str]]:
    """Validate a FormDesigner tenant map fail-closed.

    ``None`` and ``{}`` mean "no map". Anything else must be a dict of
    non-empty strings to non-empty strings — a configured-but-broken map
    silently changes tenant resolution, so it raises instead of being ignored.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        if not value:
            return None
        if all(isinstance(key, str) and key and isinstance(val, str) and val for key, val in value.items()):
            return dict(value)
    raise ValueError(f"formdesigner_tenant_map from {source} must be a JSON object of non-empty strings")


if TYPE_CHECKING:
    from .voice.models import VoiceTranscriberConfig


@dataclass
class MSTeamsAgentConfig:
    """
    Configuration for a single agent exposed via MS Teams.

    Attributes:
        name: Agent name.
        chatbot_id: ID/name of the bot in BotManager.
        client_id: Microsoft App ID.
        client_secret: Microsoft App Password.
        kind: Integration type (msteams).
        welcome_message: Custom welcome message.
        commands: Custom commands map.
        dialog: Optional dialog configuration.
        voice_config: Optional voice transcription configuration.
    """

    name: str
    chatbot_id: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    app_type: str = "MultiTenant"
    app_tenantid: Optional[str] = None
    kind: str = "msteams"
    welcome_message: Optional[str] = None
    commands: Dict[str, str] = field(default_factory=dict)
    dialog: Optional[Any] = None
    forms_directory: Optional[str] = None
    enable_group_mentions: bool = True
    enable_group_commands: bool = True
    # User/conversation whitelisting
    allowed_conversation_ids: Optional[List[str]] = None
    allowed_user_ids: Optional[List[str]] = None
    # Chat-driven knowledge upload (FEAT-647) — opt-in, disabled by default.
    knowledge_upload: KnowledgeUploadConfig = field(default_factory=KnowledgeUploadConfig)
    voice_config: Optional["VoiceTranscriberConfig"] = None
    adaptive_card_version: str = DEFAULT_ADAPTIVE_CARD_VERSION

    # Jira OAuth 2.0 (3LO) configuration — FEAT-225
    # When set, MSTeamsAgentWrapper will initialize a JiraOAuthManager and wire
    # the /connect_jira, /disconnect_jira, and /jira_status text commands.
    jira_client_id: Optional[str] = None
    jira_client_secret: Optional[str] = None
    jira_redirect_uri: Optional[str] = None

    # FormDesigner card submissions — FEAT-551
    # The bot forwards `_formdesigner` Action.Submit envelopes to POST .../forms/{uid}/data.
    formdesigner_allowed_hosts: Optional[List[str]] = None  # None/[] disables the branch
    formdesigner_submit_token: Optional[str] = None  # Authorization: Bearer (private forms)
    formdesigner_submit_secret: Optional[str] = None  # HMAC secret; envelopes must carry a valid sig when set
    formdesigner_submit_timeout: float = 15.0
    formdesigner_api_base_path: str = "/api/v1"  # must match setup_form_api(base_path=...) on the FormDesigner side
    formdesigner_allow_unsigned_submissions: bool = False
    """Accept unsigned submit envelopes. DEVELOPMENT ONLY — logs a WARNING on every startup.

    When False (the default) a bearer token without a signing secret is refused at
    construction: tenant/form_uid are client-supplied, so an unsigned envelope is
    unauthenticated routing forwarded under the bot's own credentials.
    """
    formdesigner_tenant_map: Optional[Dict[str, str]] = None
    """Azure AD tenant GUID -> FormDesigner tenant slug. A mapped GUID overrides the envelope's claim."""
    # FEAT-729: user authentication lane
    oauth_connection_name: Optional[str] = None  # Azure Bot OAuth connection (Graph-scoped)
    auth_required: bool = False  # auth is opt-in; True fails closed
    navigator_auth_url: Optional[str] = None  # e.g. https://host/api/v1/login
    prefer_id_token: bool = True  # send id_token for strong JWKS verification
    # FormDesigner form serving (FEAT-734) — read/render side used by TeamsFormDesignerMixin
    formdesigner_mode: str = "remote"  # "remote" (HTTP) | "local" (in-process FormRegistry)
    formdesigner_base_url: Optional[str] = None  # read/render origin (remote mode)
    formdesigner_tenant: Optional[str] = None  # last-resort FormDesigner tenant slug
    formdesigner_public_url: Optional[str] = None  # public origin for envelope URLs (local mode)
    formdesigner_render_timeout: float = 15.0

    def __post_init__(self):
        """
        Resolve credentials and whitelists from environment variables if not provided.
        """
        if not self.client_id:
            env_var_name = f"{self.name.upper()}_MICROSOFT_APP_ID"
            self.client_id = config.get(env_var_name)
        if not self.client_secret:
            env_var_name = f"{self.name.upper()}_MICROSOFT_APP_PASSWORD"
            self.client_secret = config.get(env_var_name)
        if not self.app_tenantid:
            self.app_tenantid = config.get(f"{self.name.upper()}_APP_TENANTID") or config.get("APP_TENANTID")
        # Jira OAuth env fallbacks
        if not self.jira_client_id:
            self.jira_client_id = config.get(f"{self.name.upper()}_JIRA_CLIENT_ID")
        if not self.jira_client_secret:
            self.jira_client_secret = config.get(f"{self.name.upper()}_JIRA_CLIENT_SECRET")
        if not self.jira_redirect_uri:
            self.jira_redirect_uri = config.get(f"{self.name.upper()}_JIRA_REDIRECT_URI")
        # FormDesigner env fallbacks (FEAT-551)
        if not self.formdesigner_submit_token:
            self.formdesigner_submit_token = config.get(f"{self.name.upper()}_FORMDESIGNER_SUBMIT_TOKEN")
        if not self.formdesigner_submit_secret:
            self.formdesigner_submit_secret = config.get(f"{self.name.upper()}_FORMDESIGNER_SUBMIT_SECRET")
        if not self.formdesigner_allowed_hosts:
            raw_hosts = config.get(f"{self.name.upper()}_FORMDESIGNER_ALLOWED_HOSTS")
            if raw_hosts:
                self.formdesigner_allowed_hosts = [h.strip().lower() for h in str(raw_hosts).split(",") if h.strip()]
        if self.formdesigner_api_base_path == "/api/v1":
            env_base_path = config.get(f"{self.name.upper()}_FORMDESIGNER_API_BASE_PATH")
            if env_base_path:
                self.formdesigner_api_base_path = str(env_base_path)
        # FormDesigner form-serving env fallbacks (FEAT-734)
        name_upper_fd = self.name.upper()
        if not self.formdesigner_base_url:
            self.formdesigner_base_url = config.get(f"{name_upper_fd}_FORMDESIGNER_BASE_URL")
        if not self.formdesigner_tenant:
            self.formdesigner_tenant = config.get(f"{name_upper_fd}_FORMDESIGNER_TENANT")
        if not self.formdesigner_public_url:
            self.formdesigner_public_url = config.get(f"{name_upper_fd}_FORMDESIGNER_PUBLIC_URL")
        if self.formdesigner_mode == "remote":
            env_mode = config.get(f"{name_upper_fd}_FORMDESIGNER_MODE")
            if env_mode:
                self.formdesigner_mode = str(env_mode).strip().lower()
        if self.formdesigner_mode not in ("remote", "local"):
            raise ValueError(
                f"MSTeams[{self.name}]: formdesigner_mode must be 'remote' or 'local', got {self.formdesigner_mode!r}"
            )
        if not self.formdesigner_allow_unsigned_submissions:
            raw_allow = config.get(f"{self.name.upper()}_FORMDESIGNER_ALLOW_UNSIGNED")
            if isinstance(raw_allow, bool):
                self.formdesigner_allow_unsigned_submissions = raw_allow
            elif isinstance(raw_allow, str):
                self.formdesigner_allow_unsigned_submissions = raw_allow.lower() in {"1", "true", "yes"}
        self.formdesigner_tenant_map = _validated_tenant_map(
            self.formdesigner_tenant_map, source=f"MSTeams[{self.name}] config"
        )
        if self.formdesigner_tenant_map is None:
            env_name = f"{self.name.upper()}_FORMDESIGNER_TENANT_MAP"
            raw_map = config.get(env_name)
            if raw_map:
                try:
                    parsed_map = json.loads(raw_map)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"formdesigner_tenant_map from {env_name} is not valid JSON") from exc
                self.formdesigner_tenant_map = _validated_tenant_map(parsed_map, source=env_name)
        if self.formdesigner_allowed_hosts and self.formdesigner_submit_token and not self.formdesigner_submit_secret:
            if self.formdesigner_allow_unsigned_submissions:
                logger.warning(
                    "%s: FormDesigner submit envelopes are NOT signature-verified "
                    "(%s_FORMDESIGNER_SUBMIT_SECRET unset, unsigned submissions explicitly allowed). "
                    "Any Teams user can target another tenant on an allowed host. Development only.",
                    self.name,
                    self.name.upper(),
                )
            else:
                raise UnsignedSubmitConfigError(
                    f"{self.name}: FormDesigner submissions are enabled with a bearer token but no "
                    f"signing secret. Set {self.name.upper()}_FORMDESIGNER_SUBMIT_SECRET (and the "
                    f"matching teams_signing_secret on the FormDesigner side), or set "
                    f"formdesigner_allow_unsigned_submissions=True for development."
                )
        # Resolve whitelists from env vars (comma-separated)
        name_upper = self.name.upper()
        if self.allowed_conversation_ids is None:
            env_val = config.get(f"{name_upper}_ALLOWED_CONVERSATION_IDS")
            if env_val:
                self.allowed_conversation_ids = [s.strip() for s in env_val.split(",") if s.strip()]
        if self.allowed_user_ids is None:
            env_val = config.get(f"{name_upper}_ALLOWED_USER_IDS")
            if env_val:
                self.allowed_user_ids = [s.strip() for s in env_val.split(",") if s.strip()]

    @property
    def APP_ID(self) -> str:
        return self.client_id

    @property
    def APP_PASSWORD(self) -> str:
        return self.client_secret

    @property
    def APP_TYPE(self) -> str:
        return self.app_type

    @property
    def APP_TENANTID(self) -> Optional[str]:
        return self.app_tenantid

    @property
    def voice_enabled(self) -> bool:
        """Check if voice transcription is enabled."""
        return self.voice_config is not None and self.voice_config.enabled

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "MSTeamsAgentConfig":
        """Create config from dictionary."""
        # Parse voice_config if provided
        voice_config = None
        if voice_data := data.get("voice_config"):
            from .voice.models import VoiceTranscriberConfig

            if isinstance(voice_data, dict):
                voice_config = VoiceTranscriberConfig(**voice_data)
            elif isinstance(voice_data, VoiceTranscriberConfig):
                voice_config = voice_data

        return cls(
            name=name,
            chatbot_id=data.get("chatbot_id", name),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            app_type=data.get("app_type", "MultiTenant"),
            app_tenantid=data.get("app_tenantid"),
            welcome_message=data.get("welcome_message"),
            commands=data.get("commands", {}),
            dialog=data.get("dialog"),
            enable_group_mentions=data.get("enable_group_mentions", True),
            enable_group_commands=data.get("enable_group_commands", True),
            allowed_conversation_ids=data.get("allowed_conversation_ids"),
            allowed_user_ids=data.get("allowed_user_ids"),
            knowledge_upload=KnowledgeUploadConfig.model_validate(data.get("knowledge_upload") or {}),
            voice_config=voice_config,
            adaptive_card_version=data.get("adaptive_card_version", DEFAULT_ADAPTIVE_CARD_VERSION),
            # Jira OAuth (FEAT-225)
            jira_client_id=data.get("jira_client_id"),
            jira_client_secret=data.get("jira_client_secret"),
            jira_redirect_uri=data.get("jira_redirect_uri"),
            # FormDesigner (FEAT-551)
            formdesigner_allowed_hosts=data.get("formdesigner_allowed_hosts"),
            formdesigner_submit_token=data.get("formdesigner_submit_token"),
            formdesigner_submit_secret=data.get("formdesigner_submit_secret"),
            formdesigner_submit_timeout=float(data.get("formdesigner_submit_timeout", 15.0)),
            formdesigner_api_base_path=data.get("formdesigner_api_base_path", "/api/v1"),
            formdesigner_allow_unsigned_submissions=bool(data.get("formdesigner_allow_unsigned_submissions", False)),
            formdesigner_tenant_map=data.get("formdesigner_tenant_map"),
            # User authentication lane (FEAT-729)
            oauth_connection_name=data.get("oauth_connection_name"),
            auth_required=bool(data.get("auth_required", False)),
            navigator_auth_url=data.get("navigator_auth_url"),
            prefer_id_token=bool(data.get("prefer_id_token", True)),
            # FormDesigner form serving (FEAT-734)
            formdesigner_mode=data.get("formdesigner_mode", "remote"),
            formdesigner_base_url=data.get("formdesigner_base_url"),
            formdesigner_tenant=data.get("formdesigner_tenant"),
            formdesigner_public_url=data.get("formdesigner_public_url"),
            formdesigner_render_timeout=float(data.get("formdesigner_render_timeout", 15.0)),
        )
