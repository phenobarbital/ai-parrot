# Feature Specification: Investment Memo Persistency

**Feature ID**: FEAT-024
**Date**: 2026-03-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Prior Exploration**: None

---

## 1. Motivation & Business Requirements

### Problem Statement

The Finance deliberation process produces an **InvestmentMemo** as its final artifact. This memo contains:
- Executive summary of market conditions
- Portfolio snapshot at decision time
- Actionable recommendations with consensus levels
- Deliberation metadata (rounds, source report IDs)

Currently, the InvestmentMemo is:
1. Created by `CommitteeDeliberation`
2. Converted to `TradingOrders` via `memo_to_orders()`
3. Passed to `OrderQueue` for execution
4. **Discarded** after execution completes

This means:
- **No audit trail** of investment decisions over time
- **No historical analysis** capability ("what did we recommend last month?")
- **No knowledge base** for future deliberations ("similar market conditions in the past")
- **No debugging** support for post-mortem analysis of trading outcomes

### Goals

- **Persistent storage**: Save every InvestmentMemo to filesystem as structured JSON
- **Organized by date**: Folder structure by year/month/day for easy navigation
- **Query API**: Find memos by date range, ticker, or consensus level
- **Audit trail**: Append-only log of memo events (created, executed, expired)
- **Fire-and-forget writes**: Async persistence without blocking the execution pipeline
- **Integration**: Hook into existing pipeline without modifying `CommitteeDeliberation`

### Non-Goals (explicitly out of scope)

- Database backend (filesystem only, like FileResearchMemory)
- Vector embeddings for semantic search (separate feature)
- UI for browsing memos (API only)
- Modification of existing InvestmentMemo schema
- Automatic cleanup/retention policies (Phase 2)

---

## 2. Architectural Design

### Overview

Implement a **MemoStore** following the pattern established by `FileResearchMemory` in FEAT-010. The store persists InvestmentMemos to filesystem with an in-memory cache for fast reads.

A **MemoEventLog** (append-only JSONL) tracks lifecycle events for audit purposes.

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CommitteeDeliberation                                 │
│                               │                                              │
│                               ▼                                              │
│                        InvestmentMemo                                        │
│                               │                                              │
│              ┌────────────────┼────────────────┐                            │
│              │                │                │                            │
│              ▼                ▼                ▼                            │
│     MemoStore.store()   memo_to_orders()   (existing)                       │
│      (fire-and-forget)        │                                             │
│              │                ▼                                              │
│              │          OrderQueue                                           │
│              │                │                                              │
│              │                ▼                                              │
│              │       ExecutionOrchestrator                                   │
│              │                │                                              │
│              │                ▼                                              │
│              └───────► MemoStore.log_event()                                │
│                        (execution_completed)                                 │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                            MemoStore                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    AbstractMemoStore                                   │ │
│  │   store() | get() | get_by_date() | query() | log_event()             │ │
│  └─────────────────────────────────┬──────────────────────────────────────┘ │
│                                    │                                        │
│               ┌────────────────────┼────────────────────┐                   │
│               ▼                    ▼                    ▼                   │
│  ┌────────────────────┐  ┌────────────────┐  ┌────────────────────┐        │
│  │ In-Memory Cache    │  │ FileBackend    │  │ MemoEventLog       │        │
│  │ (LRU, 100 memos)   │  │ (aiofiles)     │  │ (append-only JSONL)│        │
│  │                    │  │                │  │                    │        │
│  │ memo_id → Memo     │  │ memos/         │  │ memo_events.jsonl  │        │
│  └────────────────────┘  │  2026/         │  └────────────────────┘        │
│                          │   03/          │                                 │
│                          │    04/         │                                 │
│                          │     {id}.json  │                                 │
│                          └────────────────┘                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `InvestmentMemo` | reads | Pydantic model from schemas.py |
| `CommitteeDeliberation` | hook after | Store memo after generation |
| `ExecutionOrchestrator` | hook after | Log execution completion event |
| `FileResearchMemory` | pattern | Same filesystem persistence pattern |

### Data Models

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid


class MemoEventType(str, Enum):
    """Event types for memo lifecycle tracking."""
    CREATED = "created"
    ORDERS_GENERATED = "orders_generated"
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXPIRED = "expired"


@dataclass
class MemoEvent:
    """Event in the memo lifecycle for audit trail."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    memo_id: str = ""
    event_type: MemoEventType = MemoEventType.CREATED
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: dict = field(default_factory=dict)
    # e.g., {"orders_count": 3, "tickers": ["AAPL", "GOOGL"]}


@dataclass
class MemoMetadata:
    """Lightweight metadata for memo indexing."""
    memo_id: str
    created_at: datetime
    valid_until: Optional[datetime]
    consensus_level: str  # "UNANIMOUS", "MAJORITY", etc.
    tickers: list[str]  # Extracted from recommendations
    recommendations_count: int
    actionable_count: int
    file_path: str
```

---

## 3. Detailed Design

### 3.1 AbstractMemoStore

```python
# parrot/finance/memo_store/abstract.py

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from ..schemas import InvestmentMemo


class AbstractMemoStore(ABC):
    """Abstract interface for InvestmentMemo persistence."""

    @abstractmethod
    async def store(self, memo: InvestmentMemo) -> str:
        """
        Persist an InvestmentMemo.

        Args:
            memo: The InvestmentMemo to store.

        Returns:
            The memo ID.
        """
        ...

    @abstractmethod
    async def get(self, memo_id: str) -> Optional[InvestmentMemo]:
        """
        Retrieve a memo by ID.

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
    ) -> list[InvestmentMemo]:
        """
        Get memos within a date range.

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
    ) -> list[InvestmentMemo]:
        """
        Query memos by criteria.

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
        """
        Log a lifecycle event for a memo.

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
        """
        Query memo events.

        Args:
            memo_id: Filter by memo ID.
            event_type: Filter by event type.
            limit: Maximum results.

        Returns:
            Events, newest first.
        """
        ...
```

### 3.2 FileMemoStore Implementation

```python
# parrot/finance/memo_store/file_store.py

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles

from .abstract import AbstractMemoStore, MemoEvent, MemoEventType, MemoMetadata
from ..schemas import InvestmentMemo


class FileMemoStore(AbstractMemoStore):
    """Filesystem-based InvestmentMemo storage."""

    def __init__(
        self,
        base_path: str = "investment_memos",
        cache_size: int = 100,
    ):
        """
        Initialize the file-based memo store.

        Args:
            base_path: Root directory for memo storage.
            cache_size: LRU cache size for in-memory memos.
        """
        self.base_path = Path(base_path)
        self.cache_size = cache_size
        self._cache: dict[str, InvestmentMemo] = {}
        self._index: dict[str, MemoMetadata] = {}
        self._lock = asyncio.Lock()

        # Ensure directories exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "events").mkdir(exist_ok=True)

    def _memo_path(self, memo: InvestmentMemo) -> Path:
        """Get the file path for a memo based on creation date."""
        dt = memo.created_at
        return (
            self.base_path
            / str(dt.year)
            / f"{dt.month:02d}"
            / f"{dt.day:02d}"
            / f"{memo.id}.json"
        )

    async def store(self, memo: InvestmentMemo) -> str:
        """Persist memo to filesystem (fire-and-forget safe)."""
        path = self._memo_path(memo)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Serialize memo to JSON
        memo_dict = self._serialize_memo(memo)

        async with aiofiles.open(path, "w") as f:
            await f.write(json.dumps(memo_dict, indent=2, default=str))

        # Update cache and index
        async with self._lock:
            self._cache[memo.id] = memo
            self._index[memo.id] = self._extract_metadata(memo, str(path))

            # Evict oldest if cache full
            if len(self._cache) > self.cache_size:
                oldest = next(iter(self._cache))
                del self._cache[oldest]

        # Log creation event
        await self.log_event(memo.id, MemoEventType.CREATED)

        return memo.id

    async def get(self, memo_id: str) -> Optional[InvestmentMemo]:
        """Get memo by ID, using cache first."""
        # Check cache
        if memo_id in self._cache:
            return self._cache[memo_id]

        # Check index for path
        if memo_id in self._index:
            path = Path(self._index[memo_id].file_path)
            if path.exists():
                return await self._load_memo(path)

        # Scan filesystem (fallback)
        return await self._scan_for_memo(memo_id)

    def _serialize_memo(self, memo: InvestmentMemo) -> dict:
        """Convert InvestmentMemo to JSON-serializable dict."""
        # Handle dataclass serialization
        from dataclasses import asdict
        return asdict(memo)

    def _extract_metadata(
        self,
        memo: InvestmentMemo,
        file_path: str,
    ) -> MemoMetadata:
        """Extract lightweight metadata from a memo."""
        tickers = [r.ticker for r in memo.recommendations if r.ticker]
        return MemoMetadata(
            memo_id=memo.id,
            created_at=memo.created_at,
            valid_until=memo.valid_until,
            consensus_level=memo.final_consensus.value,
            tickers=tickers,
            recommendations_count=len(memo.recommendations),
            actionable_count=len(memo.actionable_recommendations),
            file_path=file_path,
        )
```

### 3.3 Pipeline Integration

```python
# Hook into ExecutionOrchestrator.run_pipeline()

class ExecutionOrchestrator:
    def __init__(
        self,
        memo_store: Optional[AbstractMemoStore] = None,
        ...
    ):
        self.memo_store = memo_store

    async def run_pipeline(self, ...):
        # ... existing deliberation code ...

        memo = await committee.run_deliberation(...)

        # ── NEW: Persist memo (fire-and-forget) ───────────────
        if self.memo_store:
            asyncio.create_task(
                self._persist_memo(memo)
            )

        # ... existing order processing ...

    async def _persist_memo(self, memo: InvestmentMemo) -> None:
        """Fire-and-forget memo persistence."""
        try:
            await self.memo_store.store(memo)
            self.logger.debug(f"Memo {memo.id} persisted")
        except Exception as e:
            self.logger.error(f"Failed to persist memo: {e}")

    async def _finalize_execution(
        self,
        memo: InvestmentMemo,
        reports: list[ExecutionReport],
    ) -> None:
        """Log execution completion event."""
        if self.memo_store:
            successful = sum(1 for r in reports if r.status == "filled")
            await self.memo_store.log_event(
                memo.id,
                MemoEventType.EXECUTION_COMPLETED,
                {
                    "total_orders": len(reports),
                    "successful": successful,
                    "failed": len(reports) - successful,
                },
            )
```

### 3.4 Query Tools for Agents

```python
# parrot/finance/tools/memo_tools.py

from parrot.tools import tool


@tool
async def get_recent_memos(
    days: int = 7,
    ticker: str | None = None,
) -> list[dict]:
    """
    Get recent investment memos.

    Args:
        days: Number of days to look back.
        ticker: Optional ticker to filter by.

    Returns:
        List of memo summaries with recommendations.
    """
    store = get_memo_store()
    start = datetime.utcnow() - timedelta(days=days)
    memos = await store.get_by_date(start)

    if ticker:
        memos = [
            m for m in memos
            if any(r.ticker == ticker for r in m.recommendations)
        ]

    return [
        {
            "id": m.id,
            "date": m.created_at.isoformat(),
            "consensus": m.final_consensus.value,
            "summary": m.executive_summary[:200],
            "recommendations": len(m.recommendations),
            "actionable": len(m.actionable_recommendations),
        }
        for m in memos
    ]


@tool
async def get_memo_detail(memo_id: str) -> dict | None:
    """
    Get full details of an investment memo.

    Args:
        memo_id: The memo identifier.

    Returns:
        Full memo data or None if not found.
    """
    store = get_memo_store()
    memo = await store.get(memo_id)
    if not memo:
        return None
    return asdict(memo)
```

---

## 4. Implementation Tasks

### Phase 1: Core Storage (Priority: P0)

| Task ID | Description | Effort | Dependencies |
|---------|-------------|--------|--------------|
| T1.1 | Create `AbstractMemoStore` interface | 1h | None |
| T1.2 | Implement `FileMemoStore` with filesystem backend | 3h | T1.1 |
| T1.3 | Implement in-memory LRU cache | 1h | T1.2 |
| T1.4 | Implement `MemoEventLog` (JSONL append) | 2h | T1.1 |
| T1.5 | Unit tests for FileMemoStore | 2h | T1.2, T1.4 |

### Phase 2: Pipeline Integration (Priority: P1)

| Task ID | Description | Effort | Dependencies |
|---------|-------------|--------|--------------|
| T2.1 | Add `memo_store` to `ExecutionOrchestrator` | 1h | T1.2 |
| T2.2 | Hook memo persistence after deliberation | 1h | T2.1 |
| T2.3 | Hook event logging after execution | 1h | T2.1, T1.4 |
| T2.4 | Integration tests with mock pipeline | 2h | T2.2, T2.3 |

### Phase 3: Query Tools (Priority: P2)

| Task ID | Description | Effort | Dependencies |
|---------|-------------|--------|--------------|
| T3.1 | Create `get_recent_memos` tool | 1h | T1.2 |
| T3.2 | Create `get_memo_detail` tool | 1h | T1.2 |
| T3.3 | Add memo tools to analyst toolkit | 1h | T3.1, T3.2 |
| T3.4 | Tool tests | 1h | T3.1, T3.2 |

---

## 5. Acceptance Criteria

### Functional Requirements

- [ ] `FileMemoStore.store()` persists InvestmentMemo to `{base_path}/YYYY/MM/DD/{id}.json`
- [ ] `FileMemoStore.get()` retrieves memo by ID (cache-first)
- [ ] `FileMemoStore.get_by_date()` returns memos in date range
- [ ] `FileMemoStore.query()` filters by ticker and consensus level
- [ ] `MemoEventLog` records lifecycle events to `memo_events.jsonl`
- [ ] Fire-and-forget writes don't block pipeline execution
- [ ] InvestmentMemo serializes/deserializes correctly (all fields preserved)

### Non-Functional Requirements

- [ ] Write latency < 100ms (async filesystem)
- [ ] Read latency < 50ms for cached memos
- [ ] Cache eviction follows LRU policy
- [ ] Event log is append-only (never modified)
- [ ] Directory structure created automatically

### Testing Requirements

- [ ] Unit tests for FileMemoStore CRUD operations
- [ ] Unit tests for MemoEventLog append/query
- [ ] Unit tests for cache eviction
- [ ] Integration tests with ExecutionOrchestrator
- [ ] Test memo serialization round-trip

---

## 6. Dependencies

### External Libraries

| Package | Version | Purpose |
|---------|---------|---------|
| `aiofiles` | existing | Async file I/O |

### Internal Dependencies

| Component | Purpose |
|-----------|---------|
| `InvestmentMemo` | Data model from schemas.py |
| `ExecutionOrchestrator` | Integration point |
| `FileResearchMemory` | Pattern reference |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `MEMO_STORE_PATH` | Base path for memo storage (default: `investment_memos/`) |

---

## 7. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Filesystem full | High | Low | Monitor disk usage, implement retention policy (Phase 2) |
| Memo serialization failure | Medium | Low | Comprehensive tests, fallback to string repr |
| Cache inconsistency | Low | Low | Lock on cache mutations, rebuild index on startup |
| Event log corruption | Medium | Very Low | JSONL format (line-level atomicity), checksum validation |

---

## 8. Future Enhancements (Out of Scope)

- **Retention policy**: Auto-delete memos older than N days
- **Vector search**: Embed memos for semantic similarity queries
- **Dashboard UI**: Browse and visualize memo history
- **Redis backend**: For distributed deployments
- **Export to BigQuery**: For long-term analytics
- **Memo diffing**: Compare recommendations over time

---

## 9. References

- Related Spec: `sdd/specs/finance-research-collective-memory.spec.md` (FEAT-010) - Pattern reference
- InvestmentMemo schema: `parrot/finance/schemas.py:448`
- ExecutionOrchestrator: `parrot/finance/execution.py`
