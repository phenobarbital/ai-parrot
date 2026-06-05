"""
parrot_tools.computer — Computer-Use Agent package.

Provides vision-based browser automation through Google Gemini computer-use
models. Includes data models, async Playwright backend, toolkit, and agent.
"""
from parrot_tools.computer.models import (
    EnvState,
    ComputerUseConfig,
    ComputerTask,
    TaskResult,
    LoopResult,
)

__all__ = [
    "EnvState",
    "ComputerUseConfig",
    "ComputerTask",
    "TaskResult",
    "LoopResult",
    "AsyncComputerBackend",
    "ComputerInteractionToolkit",
    "ComputerAgent",
]


def __getattr__(name: str):
    """Lazy import for heavy components to avoid circular imports."""
    if name == "AsyncComputerBackend":
        from parrot_tools.computer.backend import AsyncComputerBackend
        return AsyncComputerBackend
    if name == "ComputerInteractionToolkit":
        from parrot_tools.computer.toolkit import ComputerInteractionToolkit
        return ComputerInteractionToolkit
    if name == "ComputerAgent":
        from parrot_tools.computer.agent import ComputerAgent
        return ComputerAgent
    raise AttributeError(f"module 'parrot_tools.computer' has no attribute {name!r}")
