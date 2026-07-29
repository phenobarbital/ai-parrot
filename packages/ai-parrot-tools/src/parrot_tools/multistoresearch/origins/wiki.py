"""``ParrotWikiOrigin`` — LLM-Wiki / ``WikiStore`` adapter (FEAT-379).

Calls :class:`~parrot.knowledge.wiki.store.BaseWikiStore` **directly**
(``search_fts`` / ``search_vector``) — this adapter intentionally does
NOT delegate to :class:`~parrot.knowledge.wiki.search.WikiCombinedSearch`
(decision: PageIndex/GraphIndex have their own dedicated adapters;
wiki-plane results stay purely tagged as the ``"wiki"`` origin).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable, List, Optional

from parrot.models import OriginHit, SearchOriginKind

from .base import SearchOrigin

if TYPE_CHECKING:  # pragma: no cover — type hints only
    from parrot.knowledge.wiki.store import BaseWikiStore


class ParrotWikiOrigin(SearchOrigin):
    """Adapter wrapping a ``BaseWikiStore`` (SQLite or in-memory backend).

    Always FTS-capable (``supports_fts=True``): ``search_fts`` is the
    lexical-search entry point on every wiki-store backend. The vector
    leg is only active when an async ``embedder`` is configured, since
    ``search_vector`` takes an **embedding**, not free text.

    Args:
        store: A :class:`BaseWikiStore` instance (e.g. ``SQLiteWikiStore``,
            ``InMemoryWikiStore``).
        embedder: Optional async callable ``(text: str) -> list[float]``
            used to embed the query before calling ``store.search_vector``.
            When ``None`` (default), ``search`` always uses the FTS leg.
        category: Optional exact category pre-filter forwarded to
            ``search_fts``.
        name: Adapter name. Defaults to ``"wiki"``.
        description: LLM-readable explanation of this origin. Defaults to
            a description of the LLM-Wiki plane and its two legs.
        timeout: Optional per-adapter timeout override in seconds.
    """

    kind = SearchOriginKind.WIKI
    supports_fts = True

    def __init__(
        self,
        store: "BaseWikiStore",
        embedder: Optional[Callable[[str], Awaitable[List[float]]]] = None,
        category: Optional[str] = None,
        name: str = "wiki",
        description: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self.category = category
        self.name = name
        self.description = description or (
            "ParrotWiki (LLM-Wiki) origin — lexical BM25 search over the "
            "wiki plane"
            + (
                ", plus dense cosine-similarity search when an embedder "
                "is configured."
                if embedder is not None
                else " (no embedder configured — lexical search only)."
            )
        )
        self.timeout = timeout

    async def search(self, query: str, k: int) -> List[OriginHit]:
        """Search the wiki plane: vector leg if configured, else FTS.

        Args:
            query: The search query text.
            k: Maximum number of hits to return.

        Returns:
            Normalized hits in the backend's native return order.
        """
        if self._embedder is not None:
            embedding = await self._embedder(query)
            rows = await self._store.search_vector(embedding, limit=k)
        else:
            rows = await self._store.search_fts(
                query, category=self.category, limit=k
            )
        return self._normalize(rows)

    async def fts_search(self, query: str, k: int) -> List[OriginHit]:
        """Run the wiki store's lexical ``search_fts`` leg.

        Args:
            query: The search query text.
            k: Maximum number of hits to return.

        Returns:
            Normalized hits in the store's native BM25 rank order.
        """
        rows = await self._store.search_fts(query, category=self.category, limit=k)
        return self._normalize(rows)

    def _normalize(self, rows: List[dict]) -> List[OriginHit]:
        """Normalize wiki-store row dicts into origin-tagged ``OriginHit``s.

        Row dicts carry ``concept_id``, ``node_id``, ``title``, ``category``,
        ``summary``, ``source_id``, ``token_count``, ``score`` (see
        ``SQLiteWikiStore.search_fts`` / ``search_vector``).
        """
        hits = []
        for idx, row in enumerate(rows):
            title = row.get("title") or ""
            summary = row.get("summary") or ""
            content = f"{title}\n{summary}".strip() if (title or summary) else str(
                row.get("concept_id", "")
            )
            hits.append(
                OriginHit(
                    id=row.get("concept_id"),
                    content=content,
                    score=row.get("score"),
                    metadata={
                        "concept_id": row.get("concept_id"),
                        "node_id": row.get("node_id"),
                        "category": row.get("category"),
                        "source_id": row.get("source_id"),
                    },
                    origin=self.name,
                    origin_kind=self.kind,
                    native_rank=idx + 1,
                )
            )
        return hits
