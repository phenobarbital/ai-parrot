# TASK-168: get_memo_detail Tool

**Feature**: Investment Memo Persistency (FEAT-024)
**Spec**: `sdd/specs/finance-investment-memo-persistency.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (1h)
**Depends-on**: TASK-159
**Assigned-to**: claude-session

---

## Context

> Tool for agents to retrieve full memo details by ID.
> Used after identifying relevant memos via get_recent_memos.

---

## Scope

- Add `get_memo_detail` tool to `memo_tools.py`
- Return full memo data as dict
- Return None if memo not found
- Include all fields: recommendations, market_conditions, etc.

**NOT in scope**: Event history (could be separate tool).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/tools/memo_tools.py` | MODIFY | Add get_memo_detail tool |

---

## Implementation Notes

### Tool Implementation

```python
from dataclasses import asdict

@tool
async def get_memo_detail(memo_id: str) -> dict | None:
    """
    Get full details of an investment memo.

    Use this to retrieve the complete memo including all recommendations,
    market conditions, and deliberation details.

    Args:
        memo_id: The memo identifier (from get_recent_memos).

    Returns:
        Full memo data or None if not found.
    """
    store = get_memo_store()
    memo = await store.get(memo_id)

    if not memo:
        return None

    # Convert to dict, handling nested dataclasses
    result = asdict(memo)

    # Convert datetime objects to ISO strings
    if "created_at" in result:
        result["created_at"] = memo.created_at.isoformat()
    if "valid_until" in result and memo.valid_until:
        result["valid_until"] = memo.valid_until.isoformat()

    return result
```

### Return Structure

```python
{
    "id": "memo-001",
    "created_at": "2026-03-04T10:30:00Z",
    "valid_until": "2026-03-04T16:00:00Z",
    "executive_summary": "...",
    "market_conditions": {...},
    "portfolio_snapshot": {...},
    "recommendations": [
        {"ticker": "AAPL", "action": "BUY", "quantity": 100, ...},
        ...
    ],
    "deliberation_rounds": 3,
    "final_consensus": "MAJORITY",
    "source_report_ids": ["report-001", "report-002"],
}
```

---

## Acceptance Criteria

- [x] Tool decorated with `@tool`
- [x] Returns full memo data as dict
- [x] Returns None if memo not found
- [x] All fields included (recommendations, market_conditions, etc.)
- [x] Datetime fields serialized as ISO strings
- [x] Docstring provides clear description for LLM

---

## Completion Note

Implemented `get_memo_detail` tool in `parrot/finance/tools/memo_tools.py`.
Added `_serialize_memo()` helper for recursive serialization of dataclasses, enums,
datetimes, lists, and dicts. 18 tests in `tests/test_memo_tools.py` (all passing).
Ruff check clean.
