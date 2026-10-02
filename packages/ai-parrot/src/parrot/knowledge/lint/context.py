"""Per-run lazy cache over the wiki store (FEAT-625)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.knowledge.lint.models import LintOptions
from parrot.knowledge.wiki.store import BaseWikiStore


class LintContext:
    """Lazily loads and caches pages/edges/memories for one lint run."""

    def __init__(
        self,
        store: BaseWikiStore,
        *,
        root: Path | None = None,
        config: Any | None = None,
        options: LintOptions | None = None,
    ) -> None:
        self.store = store
        self.root = root
        self.config = config
        self.options = options or LintOptions()
        self.logger = logging.getLogger(__name__)
        self._pages: list[dict[str, Any]] | None = None
        self._edges: list[dict[str, Any]] | None = None
        self._memories: list[dict[str, Any]] | None = None
        self.extras: dict[str, Any] = {}

    async def pages(self) -> list[dict[str, Any]]:
        """All pages with bodies (``store.dump_pages``), cached."""
        if self._pages is None:
            self._pages = await self.store.dump_pages()
        return self._pages

    async def edges(self) -> list[dict[str, Any]]:
        """All edges (``store.dump_edges``: src, dst, rel), cached."""
        if self._edges is None:
            self._edges = await self.store.dump_edges()
        return self._edges

    async def page_ids(self) -> set[str]:
        """Set of every ``concept_id`` in the plane."""
        return {str(page["concept_id"]) for page in await self.pages()}

    async def memories(self) -> list[dict[str, Any]]:
        """Memory page stubs (``origin='memory'``), cached."""
        if self._memories is None:
            stats = await self.store.stats()
            self._memories = await self.store.list_pages(origin=["memory"], limit=int(stats["pages"]))
        return self._memories

    def invalidate(self) -> None:
        """Drop every cache (called by the runner after fixes)."""
        self._pages = None
        self._edges = None
        self._memories = None
        self.extras.clear()
