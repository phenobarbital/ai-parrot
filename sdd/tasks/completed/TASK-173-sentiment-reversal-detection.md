# TASK-173: Sentiment Reversal Detection

**Feature**: CIO Memory Context (FEAT-025)
**Spec**: `sdd/specs/finance-cio-memory-context.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-171
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Per user's answer to Open Question #4: "we need to detect sentiment reversals
> to optimize the decision." This task implements logic to compare current
> analyst recommendations against recent track record entries and flag
> significant sentiment changes (e.g., switching from bullish to bearish on
> a ticker without justification).

---

## Scope

- Implement `detect_sentiment_reversals()` function
- Compare current analyst recommendations against recent track record
- Flag reversals: bullish → bearish or bearish → bullish on same ticker
- Output human-readable alert strings for `CIOMemoryContext.consistency_alerts`
- Handle edge cases: new tickers, first deliberation, no history

**NOT in scope**: ML-based pattern detection, outcome tracking, analyst-level reversal tracking.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/swarm.py` | MODIFY | Add `detect_sentiment_reversals()` function |

---

## Implementation Notes

### Reversal Detection Logic
1. Extract ticker + direction (buy/sell/hold) from each TrackRecordEntry's recommendations
2. Extract ticker + direction from current analyst reports
3. Compare: if a ticker's direction changed significantly, generate alert
4. Alert format: "Sentiment reversal on {TICKER}: was {previous_direction} ({date}), now {current_direction}. Ensure this is justified."

### Input Data
- `track_record: list[TrackRecordEntry]` — recent history
- `current_recommendations: list[dict]` — from current analyst reports

### Output
- `list[str]` — human-readable consistency alerts

---

## Acceptance Criteria

- [x] `detect_sentiment_reversals()` function implemented
- [x] Detects bullish → bearish reversals
- [x] Detects bearish → bullish reversals
- [x] Ignores new tickers (no history to compare)
- [x] Returns empty list when no reversals or no history
- [x] Alert messages are clear and actionable
- [x] Ruff check passes

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Added `detect_sentiment_reversals(track_record, current_recommendations) -> list[str]` to `parrot/finance/swarm.py`.
- Builds {ticker: polarity} from current_recommendations (BUY→bullish, SELL→bearish, HOLD→skip)
- Extracts historical polarity from `TrackRecordEntry.executive_summary` keyword matching (bullish/bearish keywords)
- Uses `primary_ticker` as the ticker to track per entry
- Compares and generates: "Sentiment reversal on {TICKER}: was {prev} ({date}), now {current}. Ensure this is justified."
- Returns empty list for new tickers, no history, or empty recommendations
