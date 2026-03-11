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

from .config import MatrixCrewAgentEntry, MatrixCrewConfig
from .coordinator import MatrixCoordinator
from .crew_wrapper import MatrixCrewAgentWrapper
from .mention import build_pill, format_reply, parse_mention
from .registry import MatrixAgentCard, MatrixCrewRegistry
from .transport import MatrixCrewTransport

__all__ = [
    "MatrixCrewConfig",
    "MatrixCrewAgentEntry",
    "MatrixCrewRegistry",
    "MatrixAgentCard",
    "MatrixCoordinator",
    "MatrixCrewAgentWrapper",
    "MatrixCrewTransport",
    "parse_mention",
    "format_reply",
    "build_pill",
]
