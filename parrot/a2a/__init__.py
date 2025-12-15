"""
A2A (Agent-to-Agent) Protocol Implementation for AI-Parrot.

Exposes AI-Parrot agents as A2A-compliant microservices,
enabling inter-agent communication across network boundaries.
"""

from .server import A2AServer, A2AEnabledMixin
from .client import A2AClient
from .models import (
    AgentCard,
    AgentSkill,
    AgentCapabilities,
    Task,
    TaskState,
    TaskStatus,
    Message,
    Part,
    Artifact,
)

__all__ = [
    # Server
    "A2AServer",
    "A2AEnabledMixin",
    # Client
    "A2AClient",
    # Models
    "AgentCard",
    "AgentSkill",
    "AgentCapabilities",
    "Task",
    "TaskState",
    "TaskStatus",
    "Message",
    "Part",
    "Artifact",
]
