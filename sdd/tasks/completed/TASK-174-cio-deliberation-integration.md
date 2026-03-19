# TASK-174: CommitteeDeliberation CIO Context Integration

**Feature**: CIO Memory Context (FEAT-025)
**Spec**: `sdd/specs/finance-cio-memory-context.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-3h)
**Depends-on**: TASK-172, TASK-173, TASK-167
**Assigned-to**: claude-session
**Completed**: 2026-03-05

---

## Context

> Wire CIOMemoryContext into the CommitteeDeliberation pipeline.
> Before each CIO deliberation round, build the memory context by:
> 1. Fetching recent memos from MemoStore (TASK-167 / FEAT-024)
> 2. Getting current positions from PortfolioManager
> 3. Running sentiment reversal detection
> 4. Injecting via `_build_cio_context()` into CIO agent's ask() call

---

## Scope

- Modify `CommitteeDeliberation._run_cio_round()` to accept and use `CIOMemoryContext`
- Add `CIOMemoryContext.build()` classmethod or factory for constructing from MemoStore
- Fetch positions from PortfolioManager (per user answer to Q#3)
- Integrate sentiment reversal detection from TASK-173
- Graceful degradation: if MemoStore unavailable (FEAT-024 not complete), use empty context
- Apply summary truncation rule (Q#2): long summaries → bullet list of recommendations

**NOT in scope**: MemoStore implementation itself (FEAT-024), new prompt modifications.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/swarm.py` | MODIFY | Wire CIOMemoryContext into `_run_cio_round()` and deliberation pipeline |

---

## Implementation Notes

### Build Flow
```python
async def build_cio_memory_context(
    memo_store: MemoStore | None,
    portfolio_manager: PortfolioManager | None,
    current_recommendations: list[dict] | None = None,
    history_depth: int = 10,
) -> CIOMemoryContext:
    """Build CIO memory context from available sources."""
    track_record = []
    if memo_store:
        memos = await memo_store.get_recent_memos(limit=history_depth)
        track_record = [
            TrackRecordEntry(
                memo_id=m.id,
                date=m.created_at,
                executive_summary=_truncate_summary(m),
                consensus_level=m.final_consensus,
                recommendations_count=len(m.recommendations),
                primary_ticker=m.recommendations[0].ticker if m.recommendations else None,
            )
            for m in memos
        ]

    positions = []
    if portfolio_manager:
        positions = await portfolio_manager.get_positions_summary()

    alerts = []
    if track_record and current_recommendations:
        alerts = detect_sentiment_reversals(track_record, current_recommendations)

    return CIOMemoryContext(
        track_record=track_record,
        current_positions=positions,
        consistency_alerts=alerts,
        history_depth=history_depth,
    )
```

### Summary Truncation
Per Q#2: if `executive_summary` > 500 chars, replace with bullet list of recommendation tickers + directions.

### Dependency on FEAT-024
TASK-167 (`get_recent_memos` tool) must be done for full functionality. If not available, `build_cio_memory_context` should gracefully return empty track record.

---

## Acceptance Criteria

- [x] `build_cio_memory_context()` factory function implemented
- [x] `_run_cio()` accepts optional `CIOMemoryContext` parameter
- [x] CIO agent receives `<track_record>` in dynamic context
- [x] Positions passed through from run_deliberation portfolio_dict
- [x] Sentiment reversals injected as `<consistency_alerts>`
- [x] Graceful degradation when MemoStore unavailable
- [x] Summary truncation applied for long summaries (`_truncate_summary()`)
- [x] Ruff check passes

---

## Completion Note

**Completed**: 2026-03-05
**Implemented by**: claude-session

### Summary

Modified `parrot/finance/swarm.py`:
1. Added `AbstractMemoStore` import
2. Added `_truncate_summary()` helper: returns summary or bullet list if >500 chars
3. Added `build_cio_memory_context()` async function: queries memo store, builds TrackRecordEntry list, detects reversals, returns CIOMemoryContext
4. Added `memo_store: AbstractMemoStore | None = None` to `CommitteeDeliberation.__init__()`
5. Updated `run_deliberation()` to build CIO memory context when memo_store is set
6. Updated `_phase_deliberation()` to accept and pass `cio_memory` to `_run_cio()`
7. Updated `_run_cio()` to accept `memory_context` and pass to `_build_cio_context()`
