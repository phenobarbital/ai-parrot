"""
Human-in-the-Loop (HITL) Architecture for AI-Parrot.

Provides agent-level (HumanTool) and flow-level (HumanDecisionNode)
human interaction capabilities with pluggable communication channels.
"""
from .models import (
    InteractionType,
    InteractionStatus,
    TimeoutAction,
    ConsensusMode,
    ChoiceOption,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
)
from .channels.base import HumanChannel
from .channels.cli import CLIDaemonHumanChannel, CLIHumanChannel
from .channels.telegram import TelegramHumanChannel
from .manager import HumanInteractionManager
from .tool import HumanTool
from .node import HumanDecisionNode

__all__ = [
    # Models
    "InteractionType",
    "InteractionStatus",
    "TimeoutAction",
    "ConsensusMode",
    "ChoiceOption",
    "HumanInteraction",
    "HumanResponse",
    "InteractionResult",
    # Channels
    "HumanChannel",
    "CLIHumanChannel",
    "CLIDaemonHumanChannel",
    "TelegramHumanChannel",
    # Engine
    "HumanInteractionManager",
    # Consumers
    "HumanTool",
    "HumanDecisionNode",
]
