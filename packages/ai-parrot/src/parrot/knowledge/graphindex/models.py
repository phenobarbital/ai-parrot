"""Framework-free document shapes for graphindex loaders (FEAT-540 M6)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class GraphDocument(BaseModel):
    """page_content + metadata — the two fields graphindex reads from a loader document."""

    page_content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class DocumentLoader(Protocol):
    """What the loader extractor needs: an async load() returning documents."""

    async def load(self) -> list[GraphDocument]: ...
