"""Platform-neutral queued command value contracts."""

from datetime import datetime
from typing import Any, Awaitable, Callable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ParseMode = Literal["keyword", "positional", "raw"]


class QueuedCommandSpec(BaseModel):
    """Configuration attached to a queued command method."""

    command: str
    description: str
    parse_mode: ParseMode = "raw"
    aliases: tuple[str, ...] = ()
    prepare: Optional[str] = None
    max_runtime: float = 1800.0
    max_queue_wait: float = 1800.0
    max_concurrent: int = 2
    concurrency_group: Optional[str] = None


class PreparedCommand(BaseModel):
    """Arguments and display metadata produced before job admission."""

    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = Field(default_factory=dict)
    label: str = ""
    dedup_key: Optional[str] = None


class Requester(BaseModel):
    """Platform-neutral identity and delivery location for a requester."""

    platform: Literal["telegram", "msteams", "slack"]
    user_id: str
    chat_id: str
    thread_id: Optional[str] = None
    message_id: Optional[str] = None
    display_name: Optional[str] = None

    @property
    def actor(self) -> str:
        """Return the platform-scoped identity used for job ownership."""

        return f"{self.platform}:{self.user_id}"


class JobNotice(BaseModel):
    """Terminal job information delivered to the originating conversation."""

    job_id: str
    command: str
    label: str
    status: Literal["completed", "failed", "cancelled", "timed_out"]
    result: Any = None
    error: Optional[str] = None
    elapsed_s: float = 0.0


class SubmitOutcome(BaseModel):
    """Immediate outcome of attempting to submit a queued command."""

    status: Literal["accepted", "duplicate", "rejected"]
    job_id: Optional[str] = None
    label: str = ""
    message: str


class JobView(BaseModel):
    """Requester-visible snapshot of a queued command job."""

    job_id: str
    command: str
    label: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "expired"]
    progress: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    summary: Optional[str] = None


class QueuedCommand(BaseModel):
    """A discovered bound command and its optional preparation hook."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    spec: QueuedCommandSpec
    method_name: str
    method: Callable[..., Any]
    prepare: Optional[Callable[..., Any]] = None


class CommandUsageError(ValueError):
    """Indicate that preparation rejected input without creating a job."""


Deliver = Callable[[JobNotice], Awaitable[None]]
