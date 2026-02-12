"""Pydantic models and configuration for AgentService."""
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DeliveryChannel(str, Enum):
    """Supported delivery channels for task results."""
    WEBHOOK = "webhook"
    TELEGRAM = "telegram"
    TEAMS = "teams"
    EMAIL = "email"
    LOG = "log"
    REDIS_STREAM = "redis_stream"


class TaskPriority(int, Enum):
    """Task priority levels (lower = higher priority)."""
    CRITICAL = 1
    HIGH = 3
    NORMAL = 5
    LOW = 7
    BACKGROUND = 9


class TaskStatus(str, Enum):
    """Task lifecycle states."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeliveryConfig(BaseModel):
    """Channel-specific delivery parameters."""
    channel: DeliveryChannel = DeliveryChannel.LOG

    # Webhook
    webhook_url: Optional[str] = None

    # Telegram
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[int] = None

    # Teams
    teams_webhook_url: Optional[str] = None

    # Email
    email_recipients: Optional[List[str]] = None
    email_subject: Optional[str] = None

    # Redis Stream
    response_stream: Optional[str] = None

    # Extra provider-specific kwargs
    extra: Dict[str, Any] = Field(default_factory=dict)


class AgentTask(BaseModel):
    """A task to be executed by an agent."""
    task_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    agent_name: str
    prompt: str
    priority: int = Field(default=TaskPriority.NORMAL, ge=1, le=10)
    status: TaskStatus = TaskStatus.PENDING

    # Execution context
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    method_name: Optional[str] = None

    # Delivery
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    scheduled_at: Optional[datetime] = None

    # Crew support
    crew_name: Optional[str] = None
    execution_mode: Optional[str] = None

    class Config:
        use_enum_values = True


class TaskResult(BaseModel):
    """Result of an agent task execution."""
    task_id: str
    agent_name: str
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=datetime.now)


class HeartbeatConfig(BaseModel):
    """Configuration for periodic agent heartbeats."""
    agent_name: str
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    prompt_template: str = "Perform your scheduled check."
    delivery: DeliveryConfig = Field(default_factory=DeliveryConfig)
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentServiceConfig(BaseModel):
    """Top-level configuration for AgentService."""
    redis_url: str = "redis://localhost:6379"
    redis_db: int = 0

    # Worker pool
    max_workers: int = 10

    # Redis Streams
    task_stream: str = "parrot:agent_tasks"
    result_stream: str = "parrot:agent_results"
    consumer_group: str = "agent_service"
    consumer_name: Optional[str] = None

    # Heartbeats
    heartbeats: List[HeartbeatConfig] = Field(default_factory=list)

    # Timeouts
    task_timeout_seconds: int = 300
    shutdown_timeout_seconds: int = 30

    # Logging
    log_level: str = "INFO"
