# TASK-171: CIOMemoryContext & TrackRecordEntry Dataclasses

**Feature**: CIO Memory Context (FEAT-025)
**Spec**: `sdd/specs/finance-cio-memory-context.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Define the core data structures for CIO historical context injection.
> CIOMemoryContext aggregates track record, positions, and consistency alerts.
> TrackRecordEntry represents a single past deliberation summary.

---

## Scope

- Add `TrackRecordEntry` dataclass to `parrot/finance/schemas.py`
- Add `CIOMemoryContext` dataclass to `parrot/finance/schemas.py`
- Configurable `history_depth` (default 10)
- Summary truncation: if executive_summary exceeds 500 chars, replace with recommendation bullet list
- `generated_at` auto-populated with current timestamp

**NOT in scope**: Context builder function, MemoStore integration, sentiment detection.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/schemas.py` | MODIFY | Add TrackRecordEntry and CIOMemoryContext dataclasses |

---

## Implementation Notes

### TrackRecordEntry Fields
- `memo_id: str` — unique memo identifier
- `date: str` — ISO date of deliberation
- `executive_summary: str` — summary text (or recommendation bullets if too long)
- `consensus_level: str` — "unanimous", "strong", "majority", "split"
- `recommendations_count: int` — number of recommendations in memo
- `primary_ticker: str | None` — most prominent recommendation ticker

### CIOMemoryContext Fields
- `track_record: list[TrackRecordEntry]` — last N deliberations
- `current_positions: list[dict]` — from PortfolioManager
- `consistency_alerts: list[str]` — detected sentiment reversals
- `history_depth: int = 10` — configurable per deployment
- `generated_at: str` — auto ISO timestamp

### Summary Truncation Logic
Per user's answer to Open Question #2: if executive_summary is long (>500 chars), replace with the bullet list of recommendations from the memo.

---

## Acceptance Criteria

- [x] `TrackRecordEntry` dataclass created with all required fields
- [x] `CIOMemoryContext` dataclass created with configurable history_depth
- [x] Both exported from `parrot/finance/schemas.py`
- [x] `generated_at` auto-populated on creation
- [x] Ruff check passes

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Added section 11 to `parrot/finance/schemas.py`:
- `TrackRecordEntry` dataclass: memo_id, date, executive_summary, consensus_level, recommendations_count, primary_ticker (optional)
- `CIOMemoryContext` dataclass: track_record, current_positions, consistency_alerts, history_depth=10, generated_at (auto-set to UTC ISO string)
- Both use `@dataclass` + `field()` consistent with existing schemas patterns
- Ruff clean, imports verified
