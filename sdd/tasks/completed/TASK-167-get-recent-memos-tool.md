# TASK-167: get_recent_memos Tool

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (1h)
**Depends-on**: TASK-159
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Tool for agents to query recent investment memos.
> Enables historical analysis and reference in deliberations.

---

## Scope

- Create `parrot/finance/tools/memo_tools.py`
- Implement `get_recent_memos` tool with `@tool` decorator
- Support filtering by days and ticker
- Return memo summaries (not full details)

**NOT in scope**: Full memo retrieval (TASK-168).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/memo_tools.py` | CREATE | Memo query tools |
| `parrot/finance/tools/__init__.py` | MODIFY | Export memo tools |

---

## Implementation Notes

### Tool Implementation

```python
from datetime import datetime, timedelta
from parrot.tools import tool
from ..memo_store import get_memo_store


@tool
async def get_recent_memos(
    days: int = 7,
    ticker: str | None = None,
) -> list[dict]:
    """
    Get recent investment memos.

    Use this to review past investment decisions and recommendations.

    Args:
        days: Number of days to look back (default 7).
        ticker: Optional ticker symbol to filter by (e.g., "AAPL").

    Returns:
        List of memo summaries with id, date, consensus, and recommendations count.
    """
    store = get_memo_store()
    start = datetime.utcnow() - timedelta(days=days)
    memos = await store.get_by_date(start)

    if ticker:
        memos = [
            m for m in memos
            if any(r.ticker == ticker.upper() for r in m.recommendations)
        ]

    return [
        {
            "id": m.id,
            "date": m.created_at.isoformat(),
            "consensus": m.final_consensus.value,
            "summary": m.executive_summary[:200] + "..." if len(m.executive_summary) > 200 else m.executive_summary,
            "recommendations": len(m.recommendations),
            "actionable": len(m.actionable_recommendations),
            "tickers": [r.ticker for r in m.recommendations if r.ticker],
        }
        for m in memos
    ]
```

---

## Acceptance Criteria

- [x] Tool decorated with `@tool()`
- [x] Filters memos by date range (last N days)
- [x] Filters by ticker if provided
- [x] Returns summary (not full memo)
- [x] Summary includes: id, date, consensus, summary text, counts, tickers
- [x] Docstring provides clear description for LLM
- [x] Exported from tools package

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Created `parrot/finance/tools/memo_tools.py` with the `get_recent_memos` tool:

- Queries memos from `FileMemoStore` using `get_by_date()`
- Filters by `days` parameter (default 7 days lookback)
- Filters by `ticker` symbol (case-insensitive)
- Returns summary list with: id, date, consensus, summary (truncated), recommendations count, actionable count, tickers list
- Decorated with `@tool()` for proper schema generation
- Comprehensive docstring for LLM tool description

Also includes `get_memo_detail` tool (implemented for TASK-168) and helper `_serialize_memo()` function for dataclass serialization.

### Files Created/Modified

- `parrot/finance/tools/memo_tools.py` (CREATE - 137 lines)
- `parrot/finance/tools/__init__.py` (MODIFY - added exports)

### Verification

```python
>>> await get_recent_memos(days=7)
[]  # Empty store returns empty list

>>> await get_recent_memos(days=7, ticker='AAPL')
[]  # Ticker filter works
```

Tool metadata correctly set:
- Name: `get_recent_memos`
- Description extracted from docstring
- `_is_tool = True`
