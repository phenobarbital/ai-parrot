# TASK-172: _build_cio_context Function

**Feature**: CIO Memory Context (FEAT-025)
**Spec**: `sdd/specs/finance-cio-memory-context.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-171
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Context builder function that formats CIOMemoryContext into XML blocks
> for injection into the CIO agent's system prompt. Follows the pattern
> established by `_build_executor_context()` in `execution.py` and
> `_build_context_block()` helper in `swarm.py`.

---

## Scope

- Implement `_build_cio_context(memory_context: CIOMemoryContext) -> str`
- Generate `<track_record>` XML block with executive summaries
- Generate `<current_positions>` XML block with portfolio state from PortfolioManager
- Generate `<consistency_alerts>` XML block with sentiment reversals
- Handle empty states gracefully (empty track record, no positions, no alerts)

**NOT in scope**: MemoStore queries, CommitteeDeliberation wiring, sentiment detection logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/swarm.py` | MODIFY | Add `_build_cio_context()` function |

---

## Implementation Notes

### Pattern Reference
Use `_build_context_block()` helper already in swarm.py:

```python
def _build_context_block(tag: str, data) -> str:
    ctx = f"<{tag}>\n"
    ctx += json.dumps(data, indent=2, default=str)
    ctx += f"\n</{tag}>\n"
    return ctx
```

### Track Record Data Shape
Each entry serialized as:
```json
{
    "memo_id": "memo-2026-03-04-001",
    "date": "2026-03-04",
    "executive_summary": "...",
    "consensus": "strong",
    "recommendations": 5,
    "primary_ticker": "SPY"
}
```

### Position Data
Comes from PortfolioManager — pass through as list[dict].

---

## Acceptance Criteria

- [x] `_build_cio_context()` function implemented in `swarm.py`
- [x] Generates `<track_record>` block with serialized TrackRecordEntry list
- [x] Generates `<current_positions>` block when positions exist
- [x] Generates `<consistency_alerts>` block when alerts exist
- [x] Returns empty string sections gracefully for missing data
- [x] Ruff check passes

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Extended `_build_cio_context()` in `parrot/finance/swarm.py` with an optional `memory_context: CIOMemoryContext | None = None` parameter. When provided:
- Adds `<track_record>` block (serialized entries with memo_id, date, summary, consensus, etc.)
- Adds `<current_positions>` block when positions exist
- Adds `<consistency_alerts>` block when alerts exist
- Empty sections omitted gracefully (not added if list is empty)

Also added `CIOMemoryContext` and `TrackRecordEntry` imports from `.schemas`.
