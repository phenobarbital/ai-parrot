# TASK-170: Memo Tools Tests

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (1h)
**Depends-on**: TASK-167, TASK-168
**Assigned-to**: claude-session

---

## Context

> Unit tests for memo query tools.
> Validates tool behavior with mocked memo store.

---

## Scope

- Create `tests/test_memo_tools.py`
- Test `get_recent_memos` with various filters
- Test `get_memo_detail` found/not found cases
- Mock memo store to isolate tool logic

**NOT in scope**: Integration with actual filesystem.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_memo_tools.py` | CREATE | Tool unit tests |

---

## Implementation Notes

### Test Structure

```python
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta

from parrot.finance.tools.memo_tools import get_recent_memos, get_memo_detail
from parrot.finance.schemas import InvestmentMemo, Recommendation


@pytest.fixture
def sample_memos():
    """Create sample memos for testing."""
    return [
        InvestmentMemo(
            id="memo-001",
            created_at=datetime.utcnow() - timedelta(days=1),
            recommendations=[
                Recommendation(ticker="AAPL", action="BUY", ...),
            ],
            ...
        ),
        InvestmentMemo(
            id="memo-002",
            created_at=datetime.utcnow() - timedelta(days=5),
            recommendations=[
                Recommendation(ticker="GOOGL", action="HOLD", ...),
            ],
            ...
        ),
    ]


class TestGetRecentMemos:
    async def test_returns_recent_memos(self, sample_memos):
        """Get memos from last N days."""
        with patch("parrot.finance.tools.memo_tools.get_memo_store") as mock:
            mock.return_value.get_by_date = AsyncMock(return_value=sample_memos)

            result = await get_recent_memos(days=7)

            assert len(result) == 2
            assert result[0]["id"] == "memo-001"

    async def test_filters_by_ticker(self, sample_memos):
        """Filter by ticker symbol."""
        with patch("parrot.finance.tools.memo_tools.get_memo_store") as mock:
            mock.return_value.get_by_date = AsyncMock(return_value=sample_memos)

            result = await get_recent_memos(days=7, ticker="AAPL")

            assert len(result) == 1
            assert "AAPL" in result[0]["tickers"]

    async def test_returns_summary_not_full_memo(self, sample_memos):
        """Verify summary structure."""
        with patch("parrot.finance.tools.memo_tools.get_memo_store") as mock:
            mock.return_value.get_by_date = AsyncMock(return_value=sample_memos)

            result = await get_recent_memos(days=7)

            assert "id" in result[0]
            assert "date" in result[0]
            assert "consensus" in result[0]
            assert "recommendations" not in result[0]  # Full list not in summary


class TestGetMemoDetail:
    async def test_returns_full_memo(self, sample_memos):
        """Get full memo by ID."""
        with patch("parrot.finance.tools.memo_tools.get_memo_store") as mock:
            mock.return_value.get = AsyncMock(return_value=sample_memos[0])

            result = await get_memo_detail("memo-001")

            assert result is not None
            assert result["id"] == "memo-001"
            assert "recommendations" in result

    async def test_returns_none_if_not_found(self):
        """Return None for non-existent memo."""
        with patch("parrot.finance.tools.memo_tools.get_memo_store") as mock:
            mock.return_value.get = AsyncMock(return_value=None)

            result = await get_memo_detail("nonexistent")

            assert result is None
```

---

## Acceptance Criteria

- [x] Tests for get_recent_memos with days filter
- [x] Tests for get_recent_memos with ticker filter
- [x] Tests for get_memo_detail found case
- [x] Tests for get_memo_detail not found case
- [x] Tests verify return structure
- [x] All tests pass (18/18)
- [x] Memo store properly mocked

---

## Completion Note

`tests/test_memo_tools.py` was created during TASK-168 and already covers all criteria.
18 tests: 9 for `_serialize_memo` helper, 6 for `get_memo_detail`, 3 for `get_recent_memos`.
All mock the store via `patch("parrot.finance.tools.memo_tools.get_memo_store")`.
