from enum import Enum

class AgentStatus(Enum):
    """Status of an Agent."""
    IDLE = "idle"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
