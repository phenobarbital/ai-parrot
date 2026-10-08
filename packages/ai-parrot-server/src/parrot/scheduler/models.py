from typing import Any, Optional
from datetime import datetime
import uuid
from asyncdb.models import Model, Field
import hashlib
import json
from dataclasses import dataclass, field
from datetime import timezone
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, field_validator

JOB_DEFINITION_VERSION: int = 1


def utcnow() -> datetime:
    """Return ``datetime.now(timezone.utc)``; the scheduler package's only clock."""
    return datetime.now(timezone.utc)


class AgentSchedule(Model):
    """
    Database model for storing agent schedules.

    SQL Table Creation:
    CREATE TABLE IF NOT EXISTS navigator.agents_scheduler (
        schedule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        agent_id VARCHAR NOT NULL,
        agent_name VARCHAR NOT NULL,
        prompt TEXT,
        method_name VARCHAR,
        schedule_type VARCHAR NOT NULL,
        schedule_config JSONB NOT NULL,
        enabled BOOLEAN DEFAULT TRUE,
        created_by INTEGER,
        created_email VARCHAR,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        last_run TIMESTAMP WITH TIME ZONE,
        next_run TIMESTAMP WITH TIME ZONE,
        run_count INTEGER DEFAULT 0,
        metadata JSONB DEFAULT '{}'::JSONB,
        is_crew BOOLEAN DEFAULT FALSE,
        send_result JSONB DEFAULT '{}'::JSONB,
        scheduler_type VARCHAR DEFAULT 'default',
        callbacks JSONB DEFAULT '[]'::JSONB
    );

    CREATE INDEX idx_agents_scheduler_enabled ON navigator.agents_scheduler(enabled);
    CREATE INDEX idx_agents_scheduler_agent ON navigator.agents_scheduler(agent_name);
    """

    schedule_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    agent_id: str = Field(required=True)
    agent_name: str = Field(required=True)
    prompt: Optional[str] = Field(required=False)
    method_name: Optional[str] = Field(required=False)
    schedule_type: str = Field(required=True)
    schedule_config: dict = Field(required=True, default_factory=dict)
    enabled: bool = Field(required=False, default=True)
    created_by: Optional[int] = Field(required=False)
    created_email: Optional[str] = Field(required=False)
    created_at: datetime = Field(required=False, default_factory=datetime.now)
    updated_at: datetime = Field(required=False, default_factory=datetime.now)
    last_run: Optional[datetime] = Field(required=False)
    next_run: Optional[datetime] = Field(required=False)
    run_count: int = Field(required=False, default=0)
    metadata: dict = Field(required=False, default_factory=dict)
    is_crew: bool = Field(required=False, default=False)
    send_result: dict = Field(required=False, default_factory=dict)
    scheduler_type: str = Field(required=False, default="default")
    callbacks: list = Field(required=False, default_factory=list)

    class Meta:
        driver = "pg"
        name = "agents_scheduler"
        schema = "navigator"
        strict = True
        frozen = False


class ServiceSchedule(Model):
    """asyncdb model for ``navigator.service_scheduler`` (backend='db' rows only).

    CREATE TABLE IF NOT EXISTS navigator.service_scheduler (
        schedule_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        target_kind VARCHAR NOT NULL,                 -- agent | crew | service
        target_name VARCHAR NOT NULL,
        target_id VARCHAR,
        tenant VARCHAR,                               -- reserved; enforcement is §8 Q1
        prompt TEXT,
        method_name VARCHAR,
        schedule_type VARCHAR NOT NULL,
        schedule_config JSONB NOT NULL,
        enabled BOOLEAN DEFAULT TRUE,
        created_by INTEGER,
        created_email VARCHAR,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW(),
        last_run TIMESTAMPTZ,
        next_run TIMESTAMPTZ,
        run_count INTEGER DEFAULT 0,
        last_status VARCHAR,                          -- success | error | target_missing | lock_unavailable
        last_error TEXT,
        last_error_at TIMESTAMPTZ,
        last_result TEXT,                             -- _format_result(), truncated to _LAST_RESULT_MAX_CHARS
        last_result_at TIMESTAMPTZ,
        consecutive_failures INTEGER DEFAULT 0,
        last_delivery_status VARCHAR,
        last_delivery_at TIMESTAMPTZ,
        last_callbacks JSONB DEFAULT '[]'::JSONB,
        metadata JSONB DEFAULT '{}'::JSONB,           -- call kwargs ONLY
        send_result JSONB DEFAULT '{}'::JSONB,
        callbacks JSONB DEFAULT '[]'::JSONB
    );
    CREATE INDEX idx_service_scheduler_enabled ON navigator.service_scheduler(enabled);
    CREATE INDEX idx_service_scheduler_target ON navigator.service_scheduler(target_kind, target_name);
    """

    schedule_id: uuid.UUID = Field(primary_key=True, default_factory=uuid.uuid4)
    target_kind: str = Field(required=True)
    target_name: str = Field(required=True)
    target_id: Optional[str] = Field(required=False)
    tenant: Optional[str] = Field(required=False)
    prompt: Optional[str] = Field(required=False)
    method_name: Optional[str] = Field(required=False)
    schedule_type: str = Field(required=True)
    schedule_config: dict = Field(required=True, default_factory=dict)
    enabled: bool = Field(required=False, default=True)
    created_by: Optional[int] = Field(required=False)
    created_email: Optional[str] = Field(required=False)
    created_at: datetime = Field(required=False, default_factory=utcnow)
    updated_at: datetime = Field(required=False, default_factory=utcnow)
    last_run: Optional[datetime] = Field(required=False)
    next_run: Optional[datetime] = Field(required=False)
    run_count: int = Field(required=False, default=0)
    last_status: Optional[str] = Field(required=False)
    last_error: Optional[str] = Field(required=False)
    last_error_at: Optional[datetime] = Field(required=False)
    last_result: Optional[str] = Field(required=False)
    last_result_at: Optional[datetime] = Field(required=False)
    consecutive_failures: int = Field(required=False, default=0)
    last_delivery_status: Optional[str] = Field(required=False)
    last_delivery_at: Optional[datetime] = Field(required=False)
    last_callbacks: list = Field(required=False, default_factory=list)
    metadata: dict = Field(required=False, default_factory=dict)
    send_result: dict = Field(required=False, default_factory=dict)
    callbacks: list = Field(required=False, default_factory=list)

    class Meta:
        driver = "pg"
        name = "service_scheduler"
        schema = "navigator"
        strict = True
        frozen = False

    def to_definition(self) -> "JobDefinition":
        """Map a db row to a ``JobDefinition(backend='db', misfire_grace_time=300)``."""
        return JobDefinition(
            schedule_id=str(self.schedule_id),
            backend="db",
            target_kind=self.target_kind,
            target_name=self.target_name,
            target_id=self.target_id,
            tenant=self.tenant,
            prompt=self.prompt,
            method_name=self.method_name,
            schedule_type=self.schedule_type,
            schedule_config=self.schedule_config,
            metadata=self.metadata,
            send_result=self.send_result,
            callbacks=self.callbacks,
            misfire_grace_time=300,
            created_by=self.created_by,
            created_email=self.created_email,
            created_at=self.created_at,
        )

    @classmethod
    def from_definition(cls, definition: "JobDefinition") -> "ServiceSchedule":
        """Build a row from a definition without copying run-state columns."""
        return cls(
            schedule_id=uuid.UUID(definition.schedule_id),
            target_kind=definition.target_kind,
            target_name=definition.target_name,
            target_id=definition.target_id,
            tenant=definition.tenant,
            prompt=definition.prompt,
            method_name=definition.method_name,
            schedule_type=definition.schedule_type,
            schedule_config=definition.schedule_config,
            created_by=definition.created_by,
            created_email=definition.created_email,
            created_at=definition.created_at,
            metadata=definition.metadata,
            send_result=definition.send_result,
            callbacks=definition.callbacks,
        )


class JobDefinition(BaseModel):
    """Backend-independent, JSON-serializable job definition (spec §2)."""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    backend: Literal["db", "redis", "code"]
    target_kind: str
    target_name: str
    target_id: Optional[str] = None
    tenant: Optional[str] = None
    prompt: Optional[str] = None
    method_name: Optional[str] = None
    schedule_type: str
    schedule_config: dict[str, Any]
    metadata: dict[str, Any] = {}
    send_result: dict[str, Any] = {}
    callbacks: list[dict[str, Any]] = []
    misfire_grace_time: Optional[int] = None
    created_by: Optional[int] = None
    created_email: Optional[str] = None
    created_at: Optional[datetime] = None

    def model_post_init(self, __context: Any) -> None:
        """Set the creation timestamp when a caller did not supply one."""
        del __context
        if self.created_at is None:
            self.created_at = utcnow()

    @field_validator("schedule_config", "metadata", "send_result", "callbacks")
    @classmethod
    def _json_only(cls, value: Any, info: Any) -> Any:
        """Reject values that do not survive ``json.dumps`` (spec S8: Redis kwargs are data-only)."""
        try:
            json.dumps(value)
        except TypeError as exc:
            raise ValueError(f"{info.field_name} must be JSON-serializable") from exc
        return value


class RunState(BaseModel):
    """What every ``RunStateStore.read()`` returns (spec §2)."""

    schedule_id: str
    backend: str
    enabled: bool
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    last_result: Optional[str] = None
    last_result_at: Optional[datetime] = None
    consecutive_failures: int = 0
    last_delivery_status: Optional[str] = None
    last_delivery_at: Optional[datetime] = None
    last_callbacks: list[dict[str, Any]] = []


@dataclass(frozen=True)
class FireContext:
    """Per-fire context; ``fire_id = f"{schedule_id}:{scheduled_at.isoformat()}"``."""

    fire_id: str
    scheduled_at: datetime
    run_now: bool = False

    @classmethod
    def for_fire(cls, schedule_id: str, scheduled_at: datetime, *, run_now: bool = False) -> "FireContext":
        """Build the context using the coordinator claim key's timestamp representation."""
        return cls(fire_id=f"{schedule_id}:{scheduled_at.isoformat()}", scheduled_at=scheduled_at, run_now=run_now)


@dataclass
class CodeJobRecord:
    """Process-local record for a ``@schedule``-declared job (replaces the ``_auto_tasks`` dict)."""

    job_id: str
    target_name: str
    method_name: str
    method: Callable[..., Awaitable[Any]]
    schedule_type: str
    schedule_config: dict[str, Any]
    send_result: Optional[dict[str, Any]] = None
    callbacks: list[dict[str, Any]] = field(default_factory=list)
    success_callback: Optional[Callable[..., Any]] = None
    enabled: bool = True

    def to_definition(self) -> JobDefinition:
        """Expose the record through the uniform API without serializing its callable."""
        return JobDefinition(
            schedule_id=self.job_id,
            backend="code",
            target_kind="service",
            target_name=self.target_name,
            method_name=self.method_name,
            schedule_type=self.schedule_type,
            schedule_config=self.schedule_config,
            send_result=self.send_result or {},
            callbacks=self.callbacks,
        )


def schedule_fingerprint(definition: JobDefinition) -> str:
    """Return the sha256 of the definition fields that affect its scheduled behavior."""
    payload = json.dumps(
        {
            "target_kind": definition.target_kind,
            "target_name": definition.target_name,
            "target_id": definition.target_id,
            "prompt": definition.prompt,
            "method_name": definition.method_name,
            "schedule_type": definition.schedule_type,
            "schedule_config": definition.schedule_config,
            "metadata": definition.metadata,
            "send_result": definition.send_result,
            "callbacks": definition.callbacks,
            "misfire_grace_time": definition.misfire_grace_time,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
