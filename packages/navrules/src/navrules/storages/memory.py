"""MemoryStorage: in-memory definitions (tests, embedded configs)."""
from __future__ import annotations

from typing import Any, Sequence

from .abstract import AbstractStorage


class MemoryStorage(AbstractStorage):
    """Serves a pre-built list of definition dicts."""

    def __init__(self, definitions: Sequence[dict[str, Any]]) -> None:
        super().__init__()
        self._definitions = list(definitions)

    async def load(self) -> list[dict[str, Any]]:
        return list(self._definitions)
