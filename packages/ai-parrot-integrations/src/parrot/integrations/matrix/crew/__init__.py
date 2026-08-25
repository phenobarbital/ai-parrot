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

from .channels import ChannelManager
from .config import (
    ChannelConfig,
    CollaborativeConfig,
    MatrixCrewAgentEntry,
    MatrixCrewConfig,
    SpaceConfig,
    TunnelConfig,
)
from .coordinator import MatrixCoordinator
from .crew_wrapper import MatrixCrewAgentWrapper
from .delegation import DelegationRequest, HybridDelegator
from .mention import build_pill, build_reply_content, format_reply, parse_mention
from .registry import MatrixAgentCard, MatrixCrewRegistry
from .session import MatrixCollaborativeSession
from .session_models import (
    AgentRoundResult,
    CollaborativeSessionState,
    SessionPhase,
)
from .swarm import SwarmSessionManager
from .swarm_toolkit import AgentSwarmToolkit
from .transport import MatrixCrewTransport
from .tunnel import AgentTunnel, TunnelRegistry

__all__ = [
    "AgentSwarmToolkit",
    "AgentTunnel",
    "ChannelConfig",
    "ChannelManager",
    "CollaborativeConfig",
    "MatrixCrewConfig",
    "MatrixCrewAgentEntry",
    "SpaceConfig",
    "TunnelConfig",
    "TunnelRegistry",
    "MatrixCrewRegistry",
    "MatrixAgentCard",
    "MatrixCoordinator",
    "MatrixCrewAgentWrapper",
    "MatrixCrewTransport",
    "MatrixCollaborativeSession",
    "SessionPhase",
    "AgentRoundResult",
    "CollaborativeSessionState",
    "DelegationRequest",
    "HybridDelegator",
    "parse_mention",
    "format_reply",
    "build_pill",
    "build_reply_content",
    "SwarmSessionManager",
]
