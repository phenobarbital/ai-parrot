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
