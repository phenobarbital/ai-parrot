"""Pydantic models and configuration for the hooks system."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class HookType(str, Enum):
    """Supported hook types."""
    SCHEDULER = "scheduler"
    FILE_WATCHDOG = "file_watchdog"
    POSTGRES_LISTEN = "postgres_listen"
    IMAP_WATCHDOG = "imap_watchdog"
    JIRA_WEBHOOK = "jira_webhook"
    FILE_UPLOAD = "file_upload"
    BROKER_REDIS = "broker_redis"
    BROKER_RABBITMQ = "broker_rabbitmq"
    BROKER_MQTT = "broker_mqtt"
    BROKER_SQS = "broker_sqs"
    SHAREPOINT = "sharepoint"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    MSTEAMS = "msteams"
    WHATSAPP_REDIS = "whatsapp_redis"
    MATRIX = "matrix"
    FILESYSTEM = "filesystem"


class HookEvent(BaseModel):
    """Unified event emitted by any hook into the orchestrator."""
    hook_id: str
    hook_type: HookType
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)

    # Optional routing hints for the orchestrator
    target_type: Optional[str] = None   # "agent" or "crew"
    target_id: Optional[str] = None     # agent/crew name
    task: Optional[str] = None          # prompt override


# ---------------------------------------------------------------------------
# Per-hook configuration models
# ---------------------------------------------------------------------------

class SchedulerHookConfig(BaseModel):
    """Configuration for the APScheduler-based hook."""
    name: str = "scheduler"
    enabled: bool = True
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    prompt_template: str = "Perform your scheduled check."
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FileWatchdogHookConfig(BaseModel):
    """Configuration for file-system watchdog hook."""
    name: str = "file_watchdog"
    enabled: bool = True
    directory: str
    patterns: List[str] = Field(default_factory=lambda: ["*"])
    events: List[str] = Field(
        default_factory=lambda: ["created", "modified", "deleted", "moved"]
    )
    recursive: bool = True
    not_empty: bool = False
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PostgresHookConfig(BaseModel):
    """Configuration for PostgreSQL LISTEN/NOTIFY hook."""
    name: str = "postgres_listen"
    enabled: bool = True
    dsn: Optional[str] = None
    channel: str = "notifications"
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IMAPHookConfig(BaseModel):
    """Configuration for IMAP mailbox monitoring hook."""
    name: str = "imap_watchdog"
    enabled: bool = True
    host: str
    port: int = 993
    user: str
    password: str
    mailbox: str = "INBOX"
    use_ssl: bool = True
    interval: int = 60
    authmech: Optional[str] = None
    search: Dict[str, Optional[str]] = Field(default_factory=lambda: {"UNSEEN": None})
    # Optional tagged email filtering
    tag: Optional[str] = None
    alias_address: Optional[str] = None
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class JiraWebhookConfig(BaseModel):
    """Configuration for Jira webhook receiver."""
    name: str = "jira_webhook"
    enabled: bool = True
    url: str = "/api/v1/hooks/jira"
    secret_token: Optional[str] = None
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FileUploadHookConfig(BaseModel):
    """Configuration for HTTP file upload hook."""
    name: str = "file_upload"
    enabled: bool = True
    url: str = "/api/v1/hooks/upload"
    methods: List[str] = Field(default_factory=lambda: ["POST", "PUT"])
    allowed_mime_types: Optional[List[str]] = None
    allowed_file_names: Optional[List[str]] = None
    upload_dir: Optional[str] = None
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BrokerHookConfig(BaseModel):
    """Configuration for message broker hooks (Redis, RabbitMQ, MQTT, SQS)."""
    name: str = "broker"
    enabled: bool = True
    broker_type: str = "redis"  # redis, rabbitmq, mqtt, sqs

    # Redis Streams
    stream_name: Optional[str] = None
    group_name: str = "default_group"
    consumer_name: str = "default_consumer"

    # RabbitMQ
    queue_name: Optional[str] = None
    routing_key: str = ""
    exchange_name: str = ""
    exchange_type: str = "topic"
    prefetch_count: int = 1

    # MQTT
    broker_url: Optional[str] = None
    topics: List[str] = Field(default_factory=list)

    # SQS
    max_messages: int = 10
    wait_time: int = 10
    idle_sleep: int = 5

    # Connection credentials
    credentials: Optional[Dict[str, Any]] = None

    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SharePointHookConfig(BaseModel):
    """Configuration for SharePoint webhook hook."""
    name: str = "sharepoint"
    enabled: bool = True
    url: str = "/api/v1/hooks/sharepoint"
    webhook_url: str = ""  # Public URL Microsoft Graph will POST to
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    tenant_name: Optional[str] = None
    site_name: Optional[str] = None
    host: Optional[str] = None
    folder_path: Optional[str] = None
    resource: Optional[str] = None
    client_state: str = "parrot_state"
    changetype: str = "updated"
    renewal_interval: int = 86400  # 24 hours
    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MessagingHookConfig(BaseModel):
    """Configuration for messaging platform hooks (Telegram, WhatsApp, MS Teams)."""
    name: str
    enabled: bool = True
    platform: str  # "telegram", "whatsapp", "msteams"
    url: str = "/api/v1/hooks/messaging"  # webhook endpoint

    # Keyword / command filters (only trigger on matching messages)
    trigger_keywords: Optional[List[str]] = None
    trigger_commands: Optional[List[str]] = None
    trigger_pattern: Optional[str] = None  # regex pattern

    target_type: str = "agent"
    target_id: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WhatsAppRedisHookConfig(BaseModel):
    """Configuration for WhatsApp Redis Bridge hook."""

    # Basic hook config
    name: str = "whatsapp_hook"
    enabled: bool = True
    target_type: Optional[str] = "agent"
    target_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Redis connection
    redis_url: str = "redis://localhost:6379"
    channel: str = "whatsapp:messages"

    # WhatsApp Bridge
    bridge_url: str = "http://localhost:8765"
    auto_reply: bool = True

    # Message filtering
    command_prefix: str = ""
    allowed_phones: Optional[List[str]] = None
    allowed_groups: Optional[List[str]] = None

    # Advanced routing
    routes: Optional[List[Dict[str, Any]]] = None

    @model_validator(mode="after")
    def _normalize(self) -> "WhatsAppRedisHookConfig":
        """Normalize phone numbers and route keywords."""
        if self.allowed_phones:
            self.allowed_phones = [p.strip() for p in self.allowed_phones]
        if self.routes:
            for route in self.routes:
                if "phones" in route:
                    route["phones"] = [p.strip() for p in route["phones"]]
                if "keywords" in route:
                    route["keywords"] = [k.strip().lower() for k in route["keywords"]]
        return self



class MatrixHookConfig(BaseModel):
    """Configuration for Matrix protocol hook."""

    # Basic hook config
    name: str = "matrix_hook"
    enabled: bool = True
    target_type: Optional[str] = "agent"
    target_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Matrix connection
    homeserver: str = "http://localhost:8008"
    bot_mxid: str = ""
    access_token: str = ""
    device_id: str = "PARROT"

    # Message filtering
    command_prefix: str = "!ask"
    allowed_users: Optional[List[str]] = None  # MXIDs (e.g. @user:server)

    # Room routing: room_id → agent/crew name
    room_routing: Optional[Dict[str, str]] = None

    # Auto-reply
    auto_reply: bool = True

    @model_validator(mode="after")
    def _normalize(self) -> "MatrixHookConfig":
        """Normalize MXIDs."""
        if self.allowed_users:
            self.allowed_users = [u.strip() for u in self.allowed_users]
        return self


class FilesystemHookConfig(BaseModel):
    """Configuration for FilesystemTransport hook."""

    # Basic hook config
    name: str = "filesystem_hook"
    enabled: bool = True
    target_type: Optional[str] = "agent"
    target_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # Transport config (accepts dict or FilesystemTransportConfig)
    transport: Dict[str, Any] = Field(default_factory=dict)

    # Message filtering
    command_prefix: str = ""
    allowed_agents: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# WhatsApp Redis Hook — factory helpers
# ---------------------------------------------------------------------------


def create_simple_whatsapp_hook(
    agent_name: str,
    allowed_phones: Optional[List[str]] = None,
    command_prefix: str = "",
) -> WhatsAppRedisHookConfig:
    """Create a simple WhatsApp hook that routes all messages to one agent."""
    return WhatsAppRedisHookConfig(
        name=f"whatsapp_{agent_name}",
        target_type="agent",
        target_id=agent_name,
        allowed_phones=allowed_phones,
        command_prefix=command_prefix,
        auto_reply=True,
    )


def create_multi_agent_whatsapp_hook(
    default_agent: str,
    routes: List[Dict[str, Any]],
    command_prefix: str = "",
) -> WhatsAppRedisHookConfig:
    """Create a multi-agent WhatsApp hook with keyword/phone routing."""
    return WhatsAppRedisHookConfig(
        name="whatsapp_router",
        target_type="agent",
        target_id=default_agent,
        routes=routes,
        command_prefix=command_prefix,
        auto_reply=True,
    )


def create_crew_whatsapp_hook(
    crew_id: str,
    allowed_phones: Optional[List[str]] = None,
    command_prefix: str = "!",
) -> WhatsAppRedisHookConfig:
    """Create a WhatsApp hook that routes messages to an AgentCrew."""
    return WhatsAppRedisHookConfig(
        name=f"whatsapp_crew_{crew_id}",
        target_type="crew",
        target_id=crew_id,
        allowed_phones=allowed_phones,
        command_prefix=command_prefix,
        auto_reply=True,
    )
