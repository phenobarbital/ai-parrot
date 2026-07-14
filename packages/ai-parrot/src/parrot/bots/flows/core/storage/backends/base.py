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

    async def fetch(self, collection: str, execution_id: str) -> list[dict[str, Any]]:
        """Return all documents in *collection* matching *execution_id*.

        Non-abstract on purpose: existing third-party ``ResultStorage``
        subclasses that predate the read API keep working (they simply
        don't support ``fetch()`` until they opt in).

        Args:
            collection: Target collection or table name.
            execution_id: Crew-level execution id to match documents against.

        Returns:
            List of persisted documents whose ``execution_id`` matches.

        Raises:
            NotImplementedError: Always, unless overridden by a subclass.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement fetch()"
        )

    async def list(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List persisted execution documents, newest first.

        Backends that support read operations must override this method.
        The default implementation raises ``NotImplementedError`` so that
        existing write-only backends continue to work unchanged.

        Args:
            collection: Target collection or table name.
            filters: Optional plain-dict filters (e.g. ``tenant``, ``user_id``).
            limit: Maximum number of documents to return.
            offset: Number of documents to skip (pagination).

        Returns:
            A list of execution documents.

        Raises:
            NotImplementedError: If the backend does not support ``list()``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support list()"
        )

    async def get(
        self,
        collection: str,
        record_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve a single execution document by its record id.

        Args:
            collection: Target collection or table name.
            record_id: Unique identifier of the record (UUID as string).

        Returns:
            The execution document, or ``None`` if not found.

        Raises:
            NotImplementedError: If the backend does not support ``get()``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support get()"
        )

    async def delete(
        self,
        collection: str,
        record_id: str,
    ) -> bool:
        """Delete a single execution document by its record id.

        Args:
            collection: Target collection or table name.
            record_id: Unique identifier of the record (UUID as string).

        Returns:
            ``True`` if a record was deleted, ``False`` otherwise.

        Raises:
            NotImplementedError: If the backend does not support ``delete()``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support delete()"
        )

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count persisted execution documents matching the given filters.

        Args:
            collection: Target collection or table name.
            filters: Optional plain-dict filters (e.g. ``tenant``, ``user_id``).

        Returns:
            The number of matching documents.

        Raises:
            NotImplementedError: If the backend does not support ``count()``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support count()"
        )
