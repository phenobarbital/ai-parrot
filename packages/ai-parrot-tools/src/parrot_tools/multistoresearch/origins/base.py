"""``SearchOrigin`` adapter contract (FEAT-379).

Every multi-search backend (vector store, PageIndex, GraphIndex,
ParrotWiki) is wrapped by a ``SearchOrigin`` adapter exposing a uniform
async surface that :class:`~parrot_tools.multistoresearch.toolkit.
MultiStoreSearchToolkit` orchestrates. Adapters normalize their backend's
native result type into :class:`~parrot.models.OriginHit`.

Adapters RAISE on backend failure — per-origin isolation (timeout +
error containment) is the toolkit's responsibility, not the adapter's.
"""
from abc import ABC, abstractmethod
from typing import List, Optional

from parrot.models import OriginHit, SearchOriginKind


class SearchOrigin(ABC):
    """Abstract adapter contract for one multi-search origin.

    Attributes:
        name: Adapter name, e.g. ``"pgvector"``, ``"wiki"``. Used to tag
            every :class:`~parrot.models.OriginHit` produced by this
            adapter and to identify the origin in toolkit responses.
        kind: The :class:`~parrot.models.SearchOriginKind` this adapter
            wraps.
        description: LLM-readable explanation of this origin — surfaced
            in ``OriginSection.description`` and ``list_search_origins``.
        supports_fts: Whether :meth:`fts_search` is meaningful for this
            adapter instance.
        timeout: Per-adapter timeout override in seconds. ``None`` means
            "use the toolkit default" (30.0s).
    """

    name: str
    kind: SearchOriginKind
    description: str
    supports_fts: bool = False
    timeout: Optional[float] = None

    @abstractmethod
    async def search(self, query: str, k: int) -> List[OriginHit]:
        """Run a native-ranking search against this origin.

        Args:
            query: The search query text.
            k: Maximum number of hits to return.

        Returns:
            Normalized hits in the origin's own native rank order.
        """
        raise NotImplementedError

    async def fts_search(self, query: str, k: int) -> List[OriginHit]:
        """Run a full-text search against this origin, if supported.

        Only meaningful when :attr:`supports_fts` is ``True``. The
        default implementation raises ``NotImplementedError`` — adapters
        that support FTS must override this method.

        Args:
            query: The search query text.
            k: Maximum number of hits to return.

        Returns:
            Normalized hits in the origin's own native FTS rank order.

        Raises:
            NotImplementedError: When this origin does not support FTS.
        """
        raise NotImplementedError(
            f"{self.name!r} ({type(self).__name__}) does not support fts_search"
        )
