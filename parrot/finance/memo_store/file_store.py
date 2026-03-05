"""Filesystem-based InvestmentMemo persistence.

Stores memos as JSON files organized by date:
    {base_path}/YYYY/MM/DD/{memo_id}.json

Follows the pattern of FileResearchMemory from FEAT-010:
- In-memory LRU cache (OrderedDict) for fast reads
- Fire-and-forget writes via asyncio.create_task()
- Async file I/O with aiofiles
- asyncio.Lock to protect shared state (cache, index, events)
- MemoMetadata index for efficient queries

Example:
    >>> store = FileMemoStore(base_path="investment_memos")
    >>> memo_id = await store.store(memo)
    >>> memo = await store.get(memo_id)
    >>> await store.log_event(memo_id, MemoEventType.EXECUTION_COMPLETED)
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

from .abstract import (
    AbstractMemoStore,
    MemoEvent,
    MemoEventType,
    MemoMetadata,
)


logger = logging.getLogger(__name__)


class FileMemoStore(AbstractMemoStore):
    """Filesystem-based investment memo store with in-memory cache.

    Persists InvestmentMemos to a date-organized directory structure:
        {base_path}/YYYY/MM/DD/{memo_id}.json

    Also maintains an append-only JSONL event log for audit trail.

    Attributes:
        base_path: Root directory for memo storage.
        cache_size: Maximum memos to keep in the in-memory cache.
    """

    def __init__(
        self,
        base_path: str = "investment_memos",
        cache_size: int = 100,
    ) -> None:
        """Initialize the file memo store.

        Args:
            base_path: Root directory for storage (created if not exists).
            cache_size: Maximum memos to keep in the in-memory cache.
        """
        self.base_path = Path(base_path)
        self.cache_size = cache_size

        # memo_id -> InvestmentMemo (OrderedDict for LRU order)
        self._cache: OrderedDict[str, Any] = OrderedDict()
        # memo_id -> MemoMetadata (lightweight index for queries)
        self._index: dict[str, MemoMetadata] = {}
        # In-memory event list for audit trail (until MemoEventLog is separate)
        self._events: list[MemoEvent] = []

        # Single lock protects cache, index, and events
        self._lock = asyncio.Lock()

        # Event log file path
        self._event_log_path: Optional[Path] = None

    # =========================================================================
    # CORE INTERFACE
    # =========================================================================

    async def store(self, memo: Any) -> str:
        """Persist an InvestmentMemo to filesystem.

        Immediately updates the in-memory cache and index, then fires
        off an async disk write without blocking the caller.

        Args:
            memo: The InvestmentMemo to store.

        Returns:
            The memo ID.

        Raises:
            IOError: If serialization fails.
        """
        memo_id = memo.id

        # Build metadata for the index
        tickers = list({r.asset for r in memo.recommendations})
        actionable = memo.actionable_recommendations

        metadata = MemoMetadata(
            memo_id=memo_id,
            created_at=memo.created_at,
            valid_until=memo.valid_until,
            consensus_level=memo.final_consensus.value
                if hasattr(memo.final_consensus, "value")
                else str(memo.final_consensus),
            tickers=tickers,
            recommendations_count=len(memo.recommendations),
            actionable_count=len(actionable),
            file_path=str(self._memo_path(memo)),
        )

        async with self._lock:
            await self._cache_put_locked(memo_id, memo)
            self._index[memo_id] = metadata

        # Fire-and-forget disk write
        asyncio.create_task(self._write_to_disk(memo))

        logger.debug("Stored memo %s (ticker=%s)", memo_id, tickers)
        return memo_id

    async def get(self, memo_id: str) -> Optional[Any]:
        """Retrieve an InvestmentMemo by ID.

        Checks in-memory cache first, then falls back to filesystem.

        Args:
            memo_id: The memo identifier.

        Returns:
            The InvestmentMemo or None if not found.
        """
        async with self._lock:
            cached = await self._cache_get_locked(memo_id)
            if cached is not None:
                return cached

            # Try the index for the file path
            if memo_id in self._index:
                file_path = Path(self._index[memo_id].file_path)
            else:
                file_path = None

        if file_path is not None and file_path.exists():
            return await self._load_from_disk(file_path, memo_id)

        # Fallback: scan all date directories
        return await self._find_on_disk(memo_id)

    async def get_by_date(
        self,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> list[Any]:
        """Get memos within a date range in chronological order.

        Scans the date-organized directory structure.

        Args:
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive). Defaults to now.

        Returns:
            List of InvestmentMemos in chronological order (oldest first).
        """
        if end_date is None:
            end_date = datetime.now(timezone.utc)

        results: list[Any] = []
        seen: set[str] = set()

        # Check cache first
        async with self._lock:
            for memo_id, memo in self._cache.items():
                created = memo.created_at
                if _in_date_range(created, start_date, end_date):
                    results.append(memo)
                    seen.add(memo_id)

        # Scan date directories
        date_dirs = self._get_date_dirs(start_date, end_date)
        for date_dir in date_dirs:
            if not date_dir.exists():
                continue
            for json_file in sorted(date_dir.glob("*.json")):
                memo_id = json_file.stem
                if memo_id in seen:
                    continue
                memo = await self._load_from_disk(json_file, memo_id)
                if memo is not None:
                    created = memo.created_at
                    if _in_date_range(created, start_date, end_date):
                        results.append(memo)
                        seen.add(memo_id)

        # Sort chronologically
        results.sort(key=lambda m: m.created_at)
        return results

    async def query(
        self,
        ticker: Optional[str] = None,
        consensus_level: Optional[str] = None,
        limit: int = 10,
    ) -> list[Any]:
        """Query memos by criteria, newest first.

        Uses the in-memory index for fast filtering. Falls back to disk
        for memos not in the index.

        Args:
            ticker: Filter by ticker in recommendations.
            consensus_level: Filter by consensus level.
            limit: Maximum results to return.

        Returns:
            Matching memos, newest first.
        """
        async with self._lock:
            index_snapshot = dict(self._index)

        # Filter the index
        matching_ids: list[str] = []
        for memo_id, meta in index_snapshot.items():
            if ticker and ticker.upper() not in [t.upper() for t in meta.tickers]:
                continue
            if consensus_level and meta.consensus_level != consensus_level:
                continue
            matching_ids.append(memo_id)

        # Sort by created_at from index (newest first)
        matching_ids.sort(
            key=lambda mid: index_snapshot[mid].created_at,
            reverse=True,
        )
        matching_ids = matching_ids[:limit]

        # Fetch full memos
        results: list[Any] = []
        for memo_id in matching_ids:
            memo = await self.get(memo_id)
            if memo is not None:
                results.append(memo)

        return results

    async def log_event(
        self,
        memo_id: str,
        event_type: MemoEventType,
        details: Optional[dict] = None,
    ) -> None:
        """Log a lifecycle event for a memo.

        Events are appended to in-memory list and persisted to JSONL.

        Args:
            memo_id: The memo identifier.
            event_type: Type of lifecycle event.
            details: Optional event context.
        """
        event = MemoEvent(
            memo_id=memo_id,
            event_type=event_type,
            details=details or {},
        )

        async with self._lock:
            self._events.append(event)

        # Fire-and-forget append to JSONL
        asyncio.create_task(self._append_event(event))
        logger.debug("Logged event %s for memo %s", event_type.value, memo_id)

    async def get_events(
        self,
        memo_id: Optional[str] = None,
        event_type: Optional[MemoEventType] = None,
        limit: int = 100,
    ) -> list[MemoEvent]:
        """Query memo lifecycle events.

        Reads from both the in-memory cache and the JSONL file on disk
        to ensure all events are returned, even after process restart.

        Args:
            memo_id: Filter by memo ID.
            event_type: Filter by event type.
            limit: Maximum results.

        Returns:
            Events, newest first.
        """
        events: list[MemoEvent] = []
        seen_ids: set[str] = set()

        # First, get events from in-memory cache
        async with self._lock:
            for event in self._events:
                if event.event_id not in seen_ids:
                    events.append(event)
                    seen_ids.add(event.event_id)

        # Then, read from JSONL file on disk
        event_log_path = self.base_path / "events" / "memo_events.jsonl"
        if event_log_path.exists():
            try:
                async with aiofiles.open(event_log_path, "r", encoding="utf-8") as f:
                    async for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            event_id = data.get("event_id", "")
                            if event_id in seen_ids:
                                continue

                            # Reconstruct MemoEvent from JSON
                            event = MemoEvent(
                                event_id=event_id,
                                memo_id=data.get("memo_id", ""),
                                event_type=MemoEventType(data.get("event_type", "created")),
                                timestamp=_parse_dt(data.get("timestamp")),
                                details=data.get("details", {}),
                            )
                            events.append(event)
                            seen_ids.add(event_id)
                        except (json.JSONDecodeError, ValueError, KeyError):
                            continue
            except Exception as exc:
                logger.warning("Failed to read event log: %s", exc)

        # Apply filters
        if memo_id:
            events = [e for e in events if e.memo_id == memo_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Newest first
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    # =========================================================================
    # LRU CACHE HELPERS (called while holding self._lock)
    # =========================================================================

    async def _cache_put_locked(self, memo_id: str, memo: Any) -> None:
        """Insert or update a memo in the LRU cache.

        Must be called while holding ``self._lock``.
        Moves existing entries to end (most-recently-used position) and
        evicts the oldest entry when the cache is at capacity.

        Args:
            memo_id: Unique memo identifier.
            memo: The InvestmentMemo to cache.
        """
        if memo_id in self._cache:
            # Already present — refresh recency
            self._cache.move_to_end(memo_id)
            self._cache[memo_id] = memo
        else:
            self._cache[memo_id] = memo
            # Evict least-recently-used entries until within limit
            while len(self._cache) > self.cache_size:
                evicted_id, _ = self._cache.popitem(last=False)
                logger.debug("LRU evicted memo %s", evicted_id)

    async def _cache_get_locked(self, memo_id: str) -> Optional[Any]:
        """Retrieve a memo from the LRU cache, updating recency.

        Must be called while holding ``self._lock``.

        Args:
            memo_id: Unique memo identifier.

        Returns:
            The cached InvestmentMemo, or None if not present.
        """
        if memo_id in self._cache:
            self._cache.move_to_end(memo_id)
            return self._cache[memo_id]
        return None

    # =========================================================================
    # PATH HELPERS
    # =========================================================================

    def _memo_path(self, memo: Any) -> Path:
        """Generate the filesystem path for a memo.

        Creates date-organized structure: {base_path}/YYYY/MM/DD/{id}.json

        Args:
            memo: The InvestmentMemo with id and created_at fields.

        Returns:
            The full path for this memo's JSON file.
        """
        dt = memo.created_at
        return (
            self.base_path
            / dt.strftime("%Y")
            / dt.strftime("%m")
            / dt.strftime("%d")
            / f"{memo.id}.json"
        )

    def _get_date_dirs(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[Path]:
        """Get all date directories within a range.

        Args:
            start_date: Start date (inclusive).
            end_date: End date (inclusive).

        Returns:
            List of existing Path objects for matching date directories.
        """
        dirs: list[Path] = []
        if not self.base_path.exists():
            return dirs

        for year_dir in sorted(self.base_path.iterdir()):
            if not year_dir.is_dir() or not year_dir.name.isdigit():
                continue
            year = int(year_dir.name)
            if year < start_date.year or year > end_date.year:
                continue

            for month_dir in sorted(year_dir.iterdir()):
                if not month_dir.is_dir() or not month_dir.name.isdigit():
                    continue
                month = int(month_dir.name)

                # Quick year/month range check
                ym = (year, month)
                start_ym = (start_date.year, start_date.month)
                end_ym = (end_date.year, end_date.month)
                if ym < start_ym or ym > end_ym:
                    continue

                for day_dir in sorted(month_dir.iterdir()):
                    if not day_dir.is_dir() or not day_dir.name.isdigit():
                        continue
                    dirs.append(day_dir)

        return dirs

    # =========================================================================
    # SERIALIZATION
    # =========================================================================

    def _serialize_memo(self, memo: Any) -> str:
        """Serialize an InvestmentMemo to a JSON string.

        Uses dataclasses.asdict() to convert the memo tree to a plain dict,
        then serializes with a custom datetime encoder.

        Args:
            memo: The InvestmentMemo dataclass instance.

        Returns:
            JSON string representation.
        """
        data = asdict(memo)
        return json.dumps(data, default=_json_default, indent=2, ensure_ascii=False)

    def _deserialize_memo(self, raw: str) -> Any:
        """Deserialize a JSON string back to an InvestmentMemo.

        Imports InvestmentMemo and related classes locally to avoid
        circular imports.

        Args:
            raw: JSON string from disk.

        Returns:
            An InvestmentMemo dataclass instance.

        Raises:
            ValueError: If the JSON cannot be deserialized.
        """
        from parrot.finance.schemas import (
            AssetClass,
            ConsensusLevel,
            MemoRecommendation,
            Platform,
            Position,
            PortfolioSnapshot,
            Signal,
            InvestmentMemo,
        )

        data = json.loads(raw)

        # Reconstruct recommendations
        recs = []
        for r in data.get("recommendations", []):
            recs.append(MemoRecommendation(
                id=r.get("id", ""),
                asset=r.get("asset", ""),
                asset_class=AssetClass(r.get("asset_class", "stock")),
                preferred_platform=(
                    Platform(r["preferred_platform"])
                    if r.get("preferred_platform")
                    else None
                ),
                signal=Signal(r.get("signal", "hold")),
                action=r.get("action", ""),
                sizing_pct=r.get("sizing_pct", 0.0),
                max_position_value=r.get("max_position_value"),
                entry_price_limit=r.get("entry_price_limit"),
                stop_loss=r.get("stop_loss"),
                take_profit=r.get("take_profit"),
                trailing_stop_pct=r.get("trailing_stop_pct"),
                consensus_level=ConsensusLevel(
                    r.get("consensus_level", "divided")
                ),
                bull_case=r.get("bull_case", ""),
                bear_case=r.get("bear_case", ""),
            ))

        # Reconstruct portfolio_snapshot
        ps_data = data.get("portfolio_snapshot")
        portfolio_snapshot = None
        if ps_data:
            positions = []
            for p in ps_data.get("open_positions", []):
                positions.append(Position(
                    asset=p.get("asset", ""),
                    asset_class=AssetClass(p.get("asset_class", "stock")),
                    platform=Platform(p.get("platform", "alpaca")),
                    quantity=p.get("quantity", 0.0),
                    avg_entry_price=p.get("avg_entry_price", 0.0),
                    current_price=p.get("current_price", 0.0),
                    unrealized_pnl_usd=p.get("unrealized_pnl_usd", 0.0),
                    unrealized_pnl_pct=p.get("unrealized_pnl_pct", 0.0),
                    stop_loss=p.get("stop_loss"),
                    take_profit=p.get("take_profit"),
                    opened_at=_parse_dt(p.get("opened_at")),
                ))
            portfolio_snapshot = PortfolioSnapshot(
                timestamp=_parse_dt(ps_data.get("timestamp")),
                total_value_usd=ps_data.get("total_value_usd", 0.0),
                cash_available_usd=ps_data.get("cash_available_usd", 0.0),
                exposure=ps_data.get("exposure", {}),
                open_positions=positions,
                daily_pnl_usd=ps_data.get("daily_pnl_usd", 0.0),
                daily_pnl_pct=ps_data.get("daily_pnl_pct", 0.0),
                max_drawdown_pct=ps_data.get("max_drawdown_pct", 0.0),
                daily_trades_executed=ps_data.get("daily_trades_executed", 0),
                daily_volume_usd=ps_data.get("daily_volume_usd", 0.0),
            )

        return InvestmentMemo(
            id=data.get("id", ""),
            created_at=_parse_dt(data.get("created_at")),
            valid_until=_parse_dt(data.get("valid_until")) if data.get("valid_until") else None,
            portfolio_snapshot=portfolio_snapshot,
            executive_summary=data.get("executive_summary", ""),
            market_conditions=data.get("market_conditions", ""),
            recommendations=recs,
            deliberation_rounds=data.get("deliberation_rounds", 1),
            final_consensus=ConsensusLevel(data.get("final_consensus", "divided")),
            source_report_ids=data.get("source_report_ids", []),
            deliberation_round_ids=data.get("deliberation_round_ids", []),
        )

    # =========================================================================
    # ASYNC I/O HELPERS
    # =========================================================================

    async def _write_to_disk(self, memo: Any) -> None:
        """Write a memo to disk at its date-organized path.

        Creates parent directories if they don't exist.
        Called via fire-and-forget.

        Args:
            memo: The InvestmentMemo to write.
        """
        path = self._memo_path(memo)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            content = self._serialize_memo(memo)
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(content)
            logger.debug("Wrote memo %s to %s", memo.id, path)
        except Exception as exc:
            logger.error("Failed to write memo %s: %s", memo.id, exc)

    async def _load_from_disk(self, path: Path, memo_id: str) -> Optional[Any]:
        """Load and deserialize a memo from disk.

        Adds the loaded memo to cache and index on success.

        Args:
            path: Path to the JSON file.
            memo_id: The memo ID (for cache/index keying).

        Returns:
            The InvestmentMemo or None on failure.
        """
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()
            memo = self._deserialize_memo(content)

            # Rebuild metadata and populate cache + index
            tickers = list({r.asset for r in memo.recommendations})
            actionable = memo.actionable_recommendations
            metadata = MemoMetadata(
                memo_id=memo.id,
                created_at=memo.created_at,
                valid_until=memo.valid_until,
                consensus_level=memo.final_consensus.value
                    if hasattr(memo.final_consensus, "value")
                    else str(memo.final_consensus),
                tickers=tickers,
                recommendations_count=len(memo.recommendations),
                actionable_count=len(actionable),
                file_path=str(path),
            )

            async with self._lock:
                await self._cache_put_locked(memo_id, memo)
                self._index[memo_id] = metadata

            return memo

        except Exception as exc:
            logger.warning("Failed to load memo from %s: %s", path, exc)
            return None

    async def _find_on_disk(self, memo_id: str) -> Optional[Any]:
        """Scan all date directories to find a memo by ID.

        Last-resort fallback for memos not in cache or index.

        Args:
            memo_id: The memo identifier.

        Returns:
            The InvestmentMemo or None if not found.
        """
        if not self.base_path.exists():
            return None

        target = f"{memo_id}.json"
        for json_file in self.base_path.rglob(target):
            return await self._load_from_disk(json_file, memo_id)

        return None

    async def _append_event(self, event: MemoEvent) -> None:
        """Append an event to the JSONL event log.

        Creates the event log file if it doesn't exist.
        Called via fire-and-forget.

        Args:
            event: The MemoEvent to append.
        """
        if self._event_log_path is None:
            event_log_dir = self.base_path / "events"
            try:
                event_log_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                logger.warning("Could not create event log dir: %s", exc)
                return
            self._event_log_path = event_log_dir / "memo_events.jsonl"

        try:
            event_dict = {
                "event_id": event.event_id,
                "memo_id": event.memo_id,
                "event_type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
                "details": event.details,
            }
            line = json.dumps(event_dict, ensure_ascii=False) + "\n"
            async with aiofiles.open(self._event_log_path, "a", encoding="utf-8") as f:
                await f.write(line)
        except Exception as exc:
            logger.warning("Failed to append event: %s", exc)


# =============================================================================
# HELPERS
# =============================================================================


def _json_default(obj: Any) -> Any:
    """Custom JSON encoder for types not handled by default.

    Handles datetime objects and Enum values.

    Args:
        obj: The object to encode.

    Returns:
        A JSON-serializable representation.

    Raises:
        TypeError: If the type is not supported.
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "value"):
        # Enum
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _parse_dt(value: Optional[str]) -> datetime:
    """Parse an ISO datetime string to a datetime object.

    Handles both timezone-aware and naive datetime strings.

    Args:
        value: ISO format datetime string or None.

    Returns:
        A timezone-aware datetime (UTC), or current UTC time if None.
    """
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _in_date_range(
    dt: datetime,
    start: datetime,
    end: datetime,
) -> bool:
    """Check if a datetime falls within an inclusive range.

    Normalizes timezone info before comparison.

    Args:
        dt: The datetime to check.
        start: Range start (inclusive).
        end: Range end (inclusive).

    Returns:
        True if dt is within [start, end].
    """
    # Make all timezone-aware for safe comparison
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return start <= dt <= end
