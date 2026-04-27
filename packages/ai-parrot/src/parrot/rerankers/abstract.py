"""Abstract base class for relevance rerankers.

This module defines the ``AbstractReranker`` ABC that all reranker implementations
must subclass. It follows the same async-first lifecycle pattern as ``AbstractClient``
and ``AbstractStore``:

- One required async method: ``rerank()``.
- Two optional lifecycle hooks: ``load()`` and ``cleanup()``.

Example:
    Implementing a custom reranker::

        from parrot.rerankers import AbstractReranker
        from parrot.rerankers.models import RerankedDocument
        from parrot.stores.models import SearchResult

        class MyReranker(AbstractReranker):
            async def rerank(
                self,
                query: str,
                documents: list[SearchResult],
                top_n: int | None = None,
            ) -> list[RerankedDocument]:
                # score and sort documents ...
                return reranked_docs
"""

from abc import ABC, abstractmethod
from typing import Optional

from parrot.rerankers.models import RerankedDocument
from parrot.stores.models import SearchResult


class AbstractReranker(ABC):
    """Abstract base class for relevance rerankers.

    All reranker implementations must subclass this class and implement the
    ``rerank()`` method.  The optional ``load()`` and ``cleanup()`` lifecycle
    hooks default to no-ops and can be overridden to manage heavy resources
    (e.g. GPU memory, model downloads).

    Contract: On internal failure, implementations MUST NOT raise from
    ``rerank()``.  Instead they MUST return the input documents wrapped as
    ``RerankedDocument`` with ``rerank_score=float('nan')`` and the original
    ordering preserved, allowing the caller to apply a safe fallback policy.
    """

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[SearchResult],
        top_n: Optional[int] = None,
    ) -> list[RerankedDocument]:
        """Score ``(query, document)`` pairs and return them sorted by relevance.

        Args:
            query: User query text.
            documents: Candidate documents from upstream retrieval.
            top_n: If set, return only the top N results. If ``None``, return
                all documents reranked.

        Returns:
            Reranked documents in descending score order.
            Length is ``min(top_n, len(documents))`` when ``top_n`` is set,
            or ``len(documents)`` otherwise.

            On internal failure the implementation MUST NOT raise; it MUST
            return the input documents wrapped as ``RerankedDocument`` with
            ``rerank_score=float('nan')`` and the original ordering preserved.
        """

    async def load(self) -> None:
        """Eager model load.

        Called to explicitly load/warm-up the model before the first
        ``rerank()`` call.  Default implementation is a no-op; subclasses
        override this to perform expensive initialisation.
        """

    async def cleanup(self) -> None:
        """Release resources (GPU memory, executors, etc.).

        Called when the reranker is no longer needed.  Default implementation
        is a no-op; subclasses override to release GPU memory or thread pools.
        """
