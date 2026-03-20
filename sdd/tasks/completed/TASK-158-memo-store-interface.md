# TASK-158: AbstractMemoStore Interface

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1h)
**Depends-on**: None
**Assigned-to**: claude-session
**Completed**: 2026-03-04

---

## Context

> Abstract interface defining the contract for InvestmentMemo persistence.
> Follows the same pattern as AbstractResearchMemory from FEAT-010.

---

## Scope

- Create `parrot/finance/memo_store/__init__.py`
- Create `parrot/finance/memo_store/abstract.py` with `AbstractMemoStore`
- Define `MemoEventType` enum for lifecycle events
- Define `MemoEvent` dataclass for audit trail
- Define `MemoMetadata` dataclass for indexing

**NOT in scope**: Implementation (that's TASK-159).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/memo_store/__init__.py` | CREATE | Package init with exports |
| `parrot/finance/memo_store/abstract.py` | CREATE | Abstract interface |

---

## Implementation Notes

### Interface Methods

```python
class AbstractMemoStore(ABC):
    async def store(self, memo: InvestmentMemo) -> str: ...
    async def get(self, memo_id: str) -> Optional[InvestmentMemo]: ...
    async def get_by_date(self, start_date: datetime, end_date: Optional[datetime] = None) -> list[InvestmentMemo]: ...
    async def query(self, ticker: Optional[str] = None, consensus_level: Optional[str] = None, limit: int = 10) -> list[InvestmentMemo]: ...
    async def log_event(self, memo_id: str, event_type: MemoEventType, details: Optional[dict] = None) -> None: ...
    async def get_events(self, memo_id: Optional[str] = None, event_type: Optional[MemoEventType] = None, limit: int = 100) -> list[MemoEvent]: ...
```

---

## Acceptance Criteria

- [x] `AbstractMemoStore` ABC defined with all methods
- [x] `MemoEventType` enum with CREATED, ORDERS_GENERATED, EXECUTION_STARTED, EXECUTION_COMPLETED, EXECUTION_FAILED, EXPIRED
- [x] `MemoEvent` dataclass with event_id, memo_id, event_type, timestamp, details
- [x] `MemoMetadata` dataclass with memo_id, created_at, valid_until, consensus_level, tickers, recommendations_count, actionable_count, file_path
- [x] All classes exported from `__init__.py`
- [x] Type hints on all methods
- [x] Docstrings following Google style

---

## Completion Note

**Completed**: 2026-03-04
**Implemented by**: claude-session

### Summary

Created the `parrot/finance/memo_store/` package with:

1. **`abstract.py`** (170 lines):
   - `MemoEventType` enum with 6 event types for lifecycle tracking
   - `MemoEvent` dataclass with all required fields for audit trail
   - `MemoMetadata` dataclass for lightweight indexing
   - `AbstractMemoStore` ABC with 6 abstract methods:
     - `store()` - Persist a memo
     - `get()` - Retrieve by ID
     - `get_by_date()` - Date range query
     - `query()` - Criteria-based query
     - `log_event()` - Audit trail logging
     - `get_events()` - Event query

2. **`__init__.py`**:
   - Exports all public classes
   - Module docstring with usage example

### Files Created

- `parrot/finance/memo_store/__init__.py`
- `parrot/finance/memo_store/abstract.py`

### Verification

- All ruff checks pass
- Module imports correctly
- All 6 MemoEventType values present
