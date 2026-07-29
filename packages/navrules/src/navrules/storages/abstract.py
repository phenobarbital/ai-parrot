"""AbstractStorage: async source of rule definitions.

Generic version of the rewards storage contract: a storage yields plain spec
dicts; turning specs into domain objects (rewards, payrate policies...) is
the consumer's job (rewards keeps its ``_create_rewards`` factory).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any


class StorageError(Exception):
    """Raised on storage open/read failures."""


class AbstractStorage(ABC):
    """Async context-managed source of rule definitions."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"navrules.{type(self).__name__}")

    @abstractmethod
    async def load(self) -> list[dict[str, Any]]:
        """Load and return all definition dicts from the storage."""

    async def open(self) -> None:
        """Open the storage connection (optional override)."""

    async def close(self) -> None:
        """Close the storage connection (optional override)."""

    async def __aenter__(self) -> "AbstractStorage":
        await self.open()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
