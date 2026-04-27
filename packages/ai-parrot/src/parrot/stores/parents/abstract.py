"""Abstract base class for parent document searchers.

This module defines the composable `ParentSearcher` strategy interface that
decouples *where* parent payloads live from *how* the bot retrieves them.

The interface follows the async-first pattern of the project:
- One required `async` method: `fetch`.
- Optional `health_check` that defaults to True.

Implementations MUST NOT raise on individual misses (missing parent IDs are
normal data gaps). Raising is reserved for infrastructure failures such as
connection loss or query errors.
"""
from abc import ABC, abstractmethod
from typing import Dict, List

from parrot.stores.models import Document


class AbstractParentSearcher(ABC):
    """Composable strategy for fetching parent documents by ID.

    Implementations MUST:
    - Return a dict keyed by ``parent_document_id``.
    - Silently omit IDs that cannot be found (data gaps are normal).
    - Raise only on infrastructure failures (connection lost, etc.).

    The bot calls :meth:`fetch` with the deduplicated set of
    ``parent_document_id`` values extracted from retrieval results, and
    uses the returned mapping to substitute parents for children in the
    LLM context.
    """

    @abstractmethod
    async def fetch(self, parent_ids: List[str]) -> Dict[str, Document]:
        """Fetch parent documents by their IDs.

        Args:
            parent_ids: List of parent document IDs to retrieve.  An empty
                list is a valid input and MUST return an empty dict without
                hitting any backend.

        Returns:
            Mapping of ``{parent_document_id: Document}``.  IDs that were
            not found are simply absent from the returned dict.  The caller
            (the bot) is responsible for falling back to the child document
            when a parent is missing.

        Raises:
            Exception: Only for infrastructure failures (network/DB errors).
                Individual misses MUST NOT raise.
        """

    async def health_check(self) -> bool:
        """Optional readiness probe.

        Override in concrete implementations to verify the backend is
        reachable before serving requests.

        Returns:
            True if the backend is reachable, False otherwise.
        """
        return True
