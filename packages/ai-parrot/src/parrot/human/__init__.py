"""
Human-in-the-Loop (HITL) Architecture for AI-Parrot.

Provides agent-level (HumanTool) and flow-level (HumanDecisionNode)
human interaction capabilities with pluggable communication channels.
"""
from typing import Optional

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


# Process-wide default HumanInteractionManager.
# Set by IntegrationBotManager when it wires HITL channels so that
# HumanTool instances constructed inside agent_tools() (before the
# integration has started) can resolve the manager lazily at invocation time.
_default_manager: Optional[HumanInteractionManager] = None


def set_default_human_manager(manager: Optional[HumanInteractionManager]) -> None:
    """Register the process-wide default HumanInteractionManager."""
    global _default_manager
    _default_manager = manager


def get_default_human_manager() -> Optional[HumanInteractionManager]:
    """Return the process-wide default HumanInteractionManager, if any."""
    return _default_manager


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
    "set_default_human_manager",
    "get_default_human_manager",
    # Consumers
    "HumanTool",
    "HumanDecisionNode",
]
