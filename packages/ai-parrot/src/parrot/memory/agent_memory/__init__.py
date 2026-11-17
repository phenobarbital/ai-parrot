"""Agent persistent-memory contracts; no eager storage or brain imports."""

from __future__ import annotations

from typing import Any

from .models import (
    AgentMemoryConfig,
    ChatStorageEvidenceRef,
    MemoryEvent,
    MemoryRequestScope,
    MemoryWriteReceipt,
)

__all__ = [
    "AgentMemoryMixin",
    "AgentMemoryConfig",
    "ChatStorageEvidenceRef",
    "MemoryEvent",
    "MemoryRequestScope",
    "MemoryWriteReceipt",
]


def __getattr__(name: str) -> Any:
    """Load the lifecycle facade without importing storage or brain modules eagerly."""
    if name == "AgentMemoryMixin":
        from .mixin import AgentMemoryMixin

        globals()[name] = AgentMemoryMixin
        return AgentMemoryMixin
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
