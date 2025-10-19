from typing import Optional, Union, Dict, Any
from datetime import datetime, timezone, timedelta
from enum import Enum
from dataclasses import dataclass, field

class JobStatus(str, Enum):
    """Status of async job execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """Represents an asynchronous execution job."""
    job_id: str
    obj_id: str
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
    def id(self) -> str:
        """Job ID (RQ uses 'id', yours uses 'job_id')."""
        return self.job_id

    def get_status(self) -> str:
        """
        Get job status as string.

        RQ uses get_status() method, yours has status as attribute.
        """
        return self.status.value

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
            'obj_id': self.obj_id,
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

    @property
    def is_finished(self) -> bool:
        """Check if job completed successfully."""
        return self.status == JobStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Check if job failed."""
        return self.status in [JobStatus.FAILED, JobStatus.CANCELLED]

    @property
    def is_started(self) -> bool:
        """Check if job has started."""
        return self.status == JobStatus.RUNNING

    @property
    def is_queued(self) -> bool:
        """Check if job is queued."""
        return self.status == JobStatus.PENDING

    @property
    def exc_info(self) -> Optional[str]:
        """Exception info (RQ uses 'exc_info', yours uses 'error')."""
        return self.error

    @property
    def ended_at(self) -> Optional[datetime]:
        """When job ended (RQ uses 'ended_at', yours uses 'completed_at')."""
        return self.completed_at

    @property
    def meta(self) -> Dict[str, Any]:
        """Job metadata (for progress tracking, etc.)."""
        return self.metadata

    def refresh(self):
        """
        Refresh job data (RQ jobs have this method).

        For your in-memory JobManager, this is a no-op since
        we're working with the same object reference.
        """
        pass

    def __repr__(self) -> str:
        return f"Job(id={self.id}, status={self.get_status()})"
