"""ResultStorage abstract base class for pluggable crew/flow result persistence."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ResultStorage(ABC):
    """Abstract pluggable backend for crew/flow execution result persistence.

    Implementations must be async-safe and idempotent on ``close()``.

    Attributes:
        None (contract via abstract methods only).
    """

    @abstractmethod
    async def save(self, collection: str, document: dict[str, Any]) -> None:
        """Persist a single execution document.

        Args:
            collection: Target collection or table name (e.g. ``"crew_executions"``).
            document: Execution result document to persist.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release any underlying connection/pool. Safe to call multiple times."""
