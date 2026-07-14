"""
Data models for AgentCrew API.

Defines structures for crew definitions, job management, and execution tracking.

The core definition models (ExecutionMode, AgentDefinition, FlowRelation,
CrewDefinition) now live in ``parrot.models.crew_definition`` and are
re-exported here for backward compatibility.
"""
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel, Field

# Re-exports — canonical location is parrot.models.crew_definition
from parrot.models.crew_definition import (  # noqa: F401
    ExecutionMode,
    AgentDefinition,
    ToolNodeDefinition,
    FlowRelation,
    CrewDefinition,
)


class JobStatus(str, Enum):
    """Status of async job execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CrewQueryRequest(BaseModel):
    """Request to query a crew."""

    crew_id: str = Field(description="ID of the crew to query")
    query: Union[str, Dict[str, str]] = Field(
        description="Query for the crew (string for all agents, dict for specific agents)"
    )
    execution_mode: Optional[ExecutionMode] = Field(
        default=None,
        description="Override the crew's default execution mode"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="User identifier"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier"
    )
    synthesis_prompt: Optional[str] = Field(
        default=None,
        description="Optional synthesis prompt for parallel research mode"
    )
    kwargs: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional arguments for execution"
    )


@dataclass
class CrewJob:
    """Represents an asynchronous crew execution job."""

    job_id: str
    crew_id: str
    query: Union[str, Dict[str, str]]
    status: JobStatus = JobStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    execution_mode: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_time(self) -> Optional[float]:
        """Calculate elapsed time in seconds."""
        if self.started_at:
            end_time = self.completed_at or datetime.now(timezone.utc)
            return (end_time - self.started_at).total_seconds()
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'job_id': self.job_id,
            'crew_id': self.crew_id,
            'status': self.status.value,
            'query': self.query,
            'result': self.result,
            'error': self.error,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'elapsed_time': self.elapsed_time,
            'execution_mode': self.execution_mode,
            'metadata': self.metadata
        }


class CrewListResponse(BaseModel):
    """Response for listing crews."""

    crews: List[Dict[str, Any]] = Field(
        description="List of crew definitions"
    )
    total: int = Field(description="Total number of crews")


class CrewJobResponse(BaseModel):
    """Response when creating a new job."""

    job_id: str = Field(description="Unique job identifier for tracking")
    crew_id: str = Field(description="ID of the crew being executed")
    status: JobStatus = Field(description="Current job status")
    message: str = Field(description="Human-readable message")
    created_at: str = Field(description="Job creation timestamp")
    execution_mode: ExecutionMode = Field(description="Execution mode used for this job")


class CrewJobStatusResponse(BaseModel):
    """Response for job status check."""

    job_id: str = Field(description="Job identifier")
    crew_id: str = Field(description="Crew identifier")
    status: JobStatus = Field(description="Current job status")
    result: Optional[Any] = Field(
        default=None,
        description="Result if completed"
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed"
    )
    elapsed_time: Optional[float] = Field(
        default=None,
        description="Execution time in seconds"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional execution metadata"
    )
    execution_mode: Optional[ExecutionMode] = Field(
        default=None,
        description="Execution mode used for this job"
    )


class ExecutionFilter(BaseModel):
    """Filters for listing saved executions.

    Attributes:
        crew_name: Restrict results to a single crew name.
        method: Restrict results to a single execution method (e.g. ``"run_flow"``).
        date_from: Only include executions at or after this timestamp.
        date_to: Only include executions at or before this timestamp.
    """

    crew_name: Optional[str] = Field(
        default=None,
        description="Restrict results to a single crew name"
    )
    method: Optional[str] = Field(
        default=None,
        description="Restrict results to a single execution method"
    )
    date_from: Optional[datetime] = Field(
        default=None,
        description="Only include executions at or after this timestamp"
    )
    date_to: Optional[datetime] = Field(
        default=None,
        description="Only include executions at or before this timestamp"
    )


class ExecutionSummary(BaseModel):
    """Summary of a saved execution for list responses.

    Attributes:
        id: Unique identifier of the saved execution record.
        crew_name: Name of the crew that produced this execution.
        method: Execution method used (e.g. ``"run_sequential"``).
        prompt: Original prompt/query, if captured.
        user_id: Identifier of the user who triggered the execution.
        tenant: Tenant the execution belongs to. Defaults to ``"global"``.
        timestamp: When the execution was persisted.
        status: Execution status. Defaults to ``"success"``.
    """

    id: str = Field(description="Unique identifier of the saved execution record")
    crew_name: str = Field(description="Name of the crew that produced this execution")
    method: str = Field(description="Execution method used (e.g. 'run_sequential')")
    prompt: Optional[str] = Field(
        default=None,
        description="Original prompt/query, if captured"
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Identifier of the user who triggered the execution"
    )
    tenant: str = Field(
        default="global",
        description="Tenant the execution belongs to"
    )
    timestamp: datetime = Field(description="When the execution was persisted")
    status: str = Field(
        default="success",
        description="Execution status"
    )


class ExecutionDetail(ExecutionSummary):
    """Full execution record with payload, extending :class:`ExecutionSummary`.

    Attributes:
        session_id: Session identifier associated with the execution.
        payload: Full execution result payload.
    """

    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier associated with the execution"
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Full execution result payload"
    )


class ReplayRequest(BaseModel):
    """Request body for replaying a saved execution.

    Currently empty — reserved as a future extension point (e.g. prompt
    overrides).
    """


class ScheduleRequest(BaseModel):
    """Request body for scheduling a saved execution.

    Attributes:
        schedule_type: One of ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB.
        schedule_config: Schedule configuration payload for the given type.
        created_by: Identifier of the user creating the schedule.
        created_email: Email of the user creating the schedule.
        metadata: Additional metadata to store with the schedule.
        callbacks: Optional list of callback configurations.
    """

    schedule_type: str = Field(
        description="Schedule type: ONCE, DAILY, WEEKLY, MONTHLY, INTERVAL, CRON, CRONTAB"
    )
    schedule_config: Dict[str, Any] = Field(
        description="Schedule configuration payload for the given type"
    )
    created_by: Optional[int] = Field(
        default=None,
        description="Identifier of the user creating the schedule"
    )
    created_email: Optional[str] = Field(
        default=None,
        description="Email of the user creating the schedule"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata to store with the schedule"
    )
    callbacks: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Optional list of callback configurations"
    )


class PaginatedResponse(BaseModel):
    """Paginated list response.

    Attributes:
        items: Page of execution summaries.
        total: Total number of matching records (ignoring pagination).
        limit: Page size used for this response.
        offset: Number of records skipped before this page.
    """

    items: List[ExecutionSummary] = Field(description="Page of execution summaries")
    total: int = Field(description="Total number of matching records")
    limit: int = Field(description="Page size used for this response")
    offset: int = Field(description="Number of records skipped before this page")
