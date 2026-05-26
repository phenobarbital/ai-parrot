"""Matrix multi-agent crew integration package.

Provides all components needed to run a crew of AI agents on a Matrix
homeserver via the Application Service protocol.

Public API::

    from parrot.integrations.matrix.crew import (
        MatrixCrewConfig,
        MatrixCrewAgentEntry,
        MatrixCrewRegistry,
        MatrixAgentCard,
        MatrixCoordinator,
        MatrixCrewAgentWrapper,
        MatrixCrewTransport,
        parse_mention,
        format_reply,
        build_pill,
    )
"""

from .config import CollaborativeConfig, MatrixCrewAgentEntry, MatrixCrewConfig
from .coordinator import MatrixCoordinator
from .crew_wrapper import MatrixCrewAgentWrapper
from .mention import build_pill, build_reply_content, format_reply, parse_mention
from .registry import MatrixAgentCard, MatrixCrewRegistry
from .session_models import (
    AgentRoundResult,
    CollaborativeSessionState,
    SessionPhase,
)
from .transport import MatrixCrewTransport

__all__ = [
    "CollaborativeConfig",
    "MatrixCrewConfig",
    "MatrixCrewAgentEntry",
    "MatrixCrewRegistry",
    "MatrixAgentCard",
    "MatrixCoordinator",
    "MatrixCrewAgentWrapper",
    "MatrixCrewTransport",
    "SessionPhase",
    "AgentRoundResult",
    "CollaborativeSessionState",
    "parse_mention",
    "format_reply",
    "build_pill",
    "build_reply_content",
]
