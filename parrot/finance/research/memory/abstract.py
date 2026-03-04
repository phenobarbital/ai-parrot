"""
Research Memory Abstract Interface
===================================

Abstract base class for research memory storage.

This module defines the `ResearchMemory` ABC that implementations must
follow. It mirrors the pattern established by `ConversationMemory` in
`parrot/memory/abstract.py`.

Implementations:
- FileResearchMemory: Filesystem-based storage with in-memory cache
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from navconfig.logging import logging

from .schemas import AuditEvent, ResearchDocument


class ResearchMemory(ABC):
    """Abstract base class for research memory storage.

    Follows the pattern established by ConversationMemory.
    Implementations must handle storage, retrieval, and lifecycle
    of research documents produced by research crews.

    The memory system provides:
    - Deduplication: Research crews can check if research exists before running
    - Pull model: Analysts query the memory instead of receiving pushed data
    - Cross-pollination: Analysts can access research from other domains
    - Audit trail: All operations are logged for debugging and auditing

    Example:
        >>> memory = FileResearchMemory(base_path="/var/data/research")
        >>> await memory.start()
        >>>
        >>> # Store a document
        >>> doc_id = await memory.store(document)
        >>>
        >>> # Check if research exists (for deduplication)
        >>> exists = await memory.exists("research_crew_macro", "2026-03-03")
        >>>
        >>> # Get latest for a domain
        >>> latest = await memory.get_latest("macro")
    """

    def __init__(self, debug: bool = False):
        """Initialize the research memory.

        Args:
            debug: Enable debug logging if True.
        """
        self.logger = logging.getLogger(
            f"parrot.finance.research.memory.{self.__class__.__name__}"
        )
        self.debug = debug

    @abstractmethod
    async def start(self) -> None:
        """Initialize the memory system.

        Called during service startup. Implementations should:
        - Create necessary directories/connections
        - Run cache warmup if enabled
        - Initialize any background tasks

        Raises:
            RuntimeError: If initialization fails.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the memory system.

        Called during service shutdown. Implementations should:
        - Flush any pending writes
        - Close connections
        - Cancel background tasks
        """
        pass

    @abstractmethod
    async def store(self, document: ResearchDocument) -> str:
        """Store a research document.

        This is the primary write operation. Documents are indexed by
        (crew_id, period_key) for deduplication. If a document with the
        same key exists, it will be overwritten.

        Args:
            document: The research document to store.

        Returns:
            The document ID (useful for logging/tracking).

        Raises:
            ValueError: If document is invalid.
            IOError: If storage fails.
        """
        pass

    @abstractmethod
    async def get(
        self,
        crew_id: str,
        period_key: str,
    ) -> Optional[ResearchDocument]:
        """Get a specific research document by crew and period.

        This is the primary lookup for deduplication checks. Research
        crews use this to verify they haven't already run for a period.

        Args:
            crew_id: The research crew identifier (e.g., "research_crew_macro").
            period_key: The period in ISO format (e.g., "2026-03-03" or
                "2026-03-03T14:00:00").

        Returns:
            The document if found, None otherwise.
        """
        pass

    @abstractmethod
    async def exists(
        self,
        crew_id: str,
        period_key: str,
    ) -> bool:
        """Check if a research document exists.

        Fast existence check without loading the full document.
        Used by research crews for deduplication.

        Args:
            crew_id: The research crew identifier.
            period_key: The period in ISO format.

        Returns:
            True if document exists, False otherwise.
        """
        pass

    @abstractmethod
    async def get_latest(
        self,
        domain: str,
    ) -> Optional[ResearchDocument]:
        """Get the most recent research document for a domain.

        Used by analysts to pull the latest research for their domain.
        Returns the document with the most recent generated_at timestamp.

        Args:
            domain: The research domain (macro, equity, crypto, sentiment, risk).

        Returns:
            The latest document if found, None otherwise.
        """
        pass

    @abstractmethod
    async def get_history(
        self,
        domain: str,
        last_n: int = 5,
    ) -> list[ResearchDocument]:
        """Get the N most recent documents for a domain.

        Useful for analysts who want to compare current research
        with previous periods for trend analysis.

        Args:
            domain: The research domain.
            last_n: Number of documents to retrieve (default 5).

        Returns:
            List of documents ordered by generated_at descending (newest first).
            Empty list if no documents exist.
        """
        pass

    @abstractmethod
    async def query(
        self,
        domains: Optional[list[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[ResearchDocument]:
        """Query documents with filters.

        Flexible query interface for cross-pollination and analysis.
        Analysts can query multiple domains simultaneously.

        Args:
            domains: Filter by domains (None = all domains).
            since: Filter documents generated after this time (inclusive).
            until: Filter documents generated before this time (inclusive).

        Returns:
            List of matching documents ordered by generated_at descending.
        """
        pass

    @abstractmethod
    async def cleanup(
        self,
        retention_days: int = 7,
    ) -> int:
        """Archive documents older than retention period.

        Moves documents to _historical/ folder instead of deleting.
        This preserves data for potential future analysis while keeping
        the active storage clean.

        Args:
            retention_days: Days to retain documents in active storage.

        Returns:
            Count of documents archived.
        """
        pass

    @abstractmethod
    async def get_audit_events(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        event_type: Optional[str] = None,
    ) -> list[AuditEvent]:
        """Query audit trail events.

        The audit trail logs all memory operations for debugging
        and compliance purposes.

        Args:
            since: Filter events after this time (inclusive).
            until: Filter events before this time (inclusive).
            event_type: Filter by event type (stored, accessed, expired, cleaned).

        Returns:
            List of matching audit events ordered by timestamp ascending.
        """
        pass
