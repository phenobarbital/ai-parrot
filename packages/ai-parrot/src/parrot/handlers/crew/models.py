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
