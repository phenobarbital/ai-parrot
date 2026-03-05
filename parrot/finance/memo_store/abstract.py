"""Abstract interface for InvestmentMemo persistence.

This module defines the contract for memo storage backends following
the same pattern as AbstractResearchMemory from FEAT-010.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class MemoEventType(str, Enum):
    """Event types for memo lifecycle tracking.

    Used in the MemoEventLog for audit trail and debugging.
    """

    CREATED = "created"
    ORDERS_GENERATED = "orders_generated"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXPIRED = "expired"


@dataclass
class MemoEvent:
    """Event in the memo lifecycle for audit trail.

    Each event represents a state transition in the memo's lifecycle,
    from creation through execution completion or expiration.

    Attributes:
        event_id: Unique identifier for this event.
        memo_id: The memo this event relates to.
        event_type: Type of lifecycle event.
        timestamp: When the event occurred (UTC).
        details: Optional additional context (e.g., order counts, tickers).
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memo_id: str = ""
    event_type: MemoEventType = MemoEventType.CREATED
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: dict = field(default_factory=dict)


@dataclass
class MemoMetadata:
    """Lightweight metadata for memo indexing.

    Used for quick lookups without loading full memo content.

    Attributes:
        memo_id: Unique identifier for the memo.
        created_at: When the memo was created (UTC).
        valid_until: Expiration time for the memo.
        consensus_level: Final consensus from deliberation.
        tickers: List of ticker symbols in recommendations.
        recommendations_count: Total number of recommendations.
        actionable_count: Number of actionable recommendations.
        file_path: Path to the memo file on disk.
    """

    memo_id: str
    created_at: datetime
    valid_until: Optional[datetime]
    consensus_level: str
    tickers: list[str]
    recommendations_count: int
    actionable_count: int
    file_path: str


# Forward reference for type hints - actual import happens in implementations
# to avoid circular imports
InvestmentMemo = "InvestmentMemo"


class AbstractMemoStore(ABC):
    """Abstract interface for InvestmentMemo persistence.

    This defines the contract for memo storage backends. Implementations
    can use filesystem, database, or other storage mechanisms.

    The interface supports:
    - CRUD operations for memos
    - Date-based and criteria-based queries
    - Lifecycle event logging for audit trails
    """

    @abstractmethod
    async def store(self, memo: "InvestmentMemo") -> str:
        """Persist an InvestmentMemo.

        Args:
            memo: The InvestmentMemo to store.

        Returns:
            The memo ID.

        Raises:
            IOError: If storage fails.
        """
        ...

    @abstractmethod
    async def get(self, memo_id: str) -> Optional["InvestmentMemo"]:
        """Retrieve a memo by ID.

        Args:
            memo_id: The memo identifier.

        Returns:
            The InvestmentMemo or None if not found.
        """
        ...

    @abstractmethod
    async def get_by_date(
        self,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> list["InvestmentMemo"]:
        """Get memos within a date range.

        Args:
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive). Defaults to now.

        Returns:
            List of memos in chronological order.
        """
        ...

    @abstractmethod
    async def query(
        self,
        ticker: Optional[str] = None,
        consensus_level: Optional[str] = None,
        limit: int = 10,
    ) -> list["InvestmentMemo"]:
        """Query memos by criteria.

        Args:
            ticker: Filter by ticker in recommendations.
            consensus_level: Filter by consensus level.
            limit: Maximum results to return.

        Returns:
            Matching memos, newest first.
        """
        ...

    @abstractmethod
    async def log_event(
        self,
        memo_id: str,
        event_type: MemoEventType,
        details: Optional[dict] = None,
    ) -> None:
        """Log a lifecycle event for a memo.

        Events are appended to an audit log and never modified.

        Args:
            memo_id: The memo identifier.
            event_type: Type of event.
            details: Optional event details.
        """
        ...

    @abstractmethod
    async def get_events(
        self,
        memo_id: Optional[str] = None,
        event_type: Optional[MemoEventType] = None,
        limit: int = 100,
    ) -> list[MemoEvent]:
        """Query memo events.

        Args:
            memo_id: Filter by memo ID.
            event_type: Filter by event type.
            limit: Maximum results.

        Returns:
            Events, newest first.
        """
        ...
