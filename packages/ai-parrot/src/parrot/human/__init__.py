"""
Human-in-the-Loop (HITL) Architecture for AI-Parrot.

Provides agent-level (HumanTool) and flow-level (HumanDecisionNode)
human interaction capabilities with pluggable communication channels.
"""
# Merge with the ai-parrot-integrations satellite, which contributes
# parrot/human/channels/telegram.py. Without extend_path this stays a
# single-directory package and the satellite's channel modules (resolved
# lazily below, e.g. TelegramHumanChannel) are never found.
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

import importlib
from typing import TYPE_CHECKING, Optional

from .models import (
    InteractionType,
    InteractionStatus,
    TimeoutAction,
    ConsensusMode,
    ChoiceOption,
    HumanInteraction,
    HumanResponse,
    InteractionResult,
    Severity,
    BusinessHours,
)
from .channels.base import HumanChannel
from .channels.cli import CLIDaemonHumanChannel, CLIHumanChannel
from .manager import HumanInteractionManager
from .tool import HumanTool
from .node import HumanDecisionNode

# Lazy: TelegramHumanChannel pulls aiogram (~1.5s). Resolved on access via
# PEP 562 __getattr__ below.
_LAZY_EXPORTS = {
    "TelegramHumanChannel": ".channels.telegram",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, package=__name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


if TYPE_CHECKING:
    from .channels.telegram import TelegramHumanChannel


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
    "Severity",
    "BusinessHours",
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
