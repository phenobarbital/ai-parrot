# Feature Specification: CIO Memory Context

**Feature ID**: FEAT-025
**Date**: 2026-03-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: next
**Prior Exploration**: None

---

## 1. Motivation & Business Requirements

### Problem Statement

The CIO (Chief Investment Officer) agent orchestrates the deliberation process but currently operates **without historical context**. Each deliberation is treated as a fresh start, losing valuable information:

1. **No track record visibility** — The CIO cannot see past decisions, their outcomes, or patterns in committee recommendations.

2. **No learning from history** — Previous executive summaries contain distilled wisdom that could inform current deliberations (e.g., "we were bullish on X last week and it worked out" or "we ignored Y risk and got burned").

3. **No consistency checking** — Without seeing recent decisions, the CIO cannot enforce position consistency or flag sudden sentiment reversals without justification.

4. **Missing pattern recognition** — Market regime patterns, sector rotations, and recurring themes are invisible to the CIO.

### Goals

- **CIOMemoryContext**: Injectable dataclass providing historical deliberation context
- **Track record injection**: Last 10 deliberations' executive summaries in `<track_record>` block
- **Context builder**: `_build_cio_context()` function following `_build_executor_context` pattern
- **Integration with MemoStore**: Pull historical memos from FEAT-024's persistence layer
- **Graceful degradation**: Works without history (empty track record on first run)

### Non-Goals (explicitly out of scope)

- Automated outcome tracking (positions PnL vs. recommendations) — separate feature
- Full memo content injection (only executive summaries to save context)
- Analyst-level track records (this is CIO-specific)
- Real-time position updates during deliberation

---

## 2. Architectural Design

### Overview

Implement a **CIOMemoryContext** dataclass that aggregates historical deliberation summaries and is injected into the CIO agent's dynamic context before each deliberation round. This follows the established pattern of `_build_executor_context()` in `execution.py`.

### Component Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        CommitteeDeliberation                                 │
│                               │                                              │
│                    ┌──────────┴──────────┐                                  │
│                    ▼                     │                                  │
│         CIOMemoryContext.build()         │                                  │
│                    │                     │                                  │
│    ┌───────────────┼───────────────┐     │                                  │
│    ▼               ▼               ▼     │                                  │
│ MemoStore    PortfolioState   MarketContext                                 │
│ (FEAT-024)    (current)        (current)                                    │
│    │                                     │                                  │
│    ▼                                     │                                  │
│ Last 10 executive_summaries              │                                  │
│    │                                     │                                  │
│    └─────────────────────────────────────┘                                  │
│                    │                                                        │
│                    ▼                                                        │
│         _build_cio_context()                                                │
│                    │                                                        │
│                    ▼                                                        │
│    ┌──────────────────────────────┐                                        │
│    │      <cio_memory_context>    │                                        │
│    │                              │                                        │
│    │  <track_record>              │                                        │
│    │    [executive summaries]     │                                        │
│    │  </track_record>             │                                        │
│    │                              │                                        │
│    │  <recent_positions>          │                                        │
│    │    [current holdings]        │                                        │
│    │  </recent_positions>         │                                        │
│    │                              │                                        │
│    │  <consistency_alerts>        │                                        │
│    │    [sentiment reversals]     │                                        │
│    │  </consistency_alerts>       │                                        │
│    │                              │                                        │
│    └──────────────────────────────┘                                        │
│                    │                                                        │
│                    ▼                                                        │
│              CIO Agent.ask()                                                │
│              (with dynamic context)                                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Before deliberation starts**: `CommitteeDeliberation` calls `CIOMemoryContext.build()`
2. **MemoStore query**: Fetch last 10 InvestmentMemos (or available if < 10)
3. **Extract summaries**: Pull `executive_summary` field from each memo
4. **Build context**: Format as XML blocks using `_build_cio_context()`
5. **Inject into CIO**: Pass as `system_prompt=` in CIO agent's `ask()` call

---

## 3. Detailed Module Design

### 3.1 CIOMemoryContext Dataclass

**Location**: `parrot/finance/schemas.py`

```python
@dataclass
class CIOMemoryContext:
    """Context injected into CIO agent before deliberation.

    Provides historical track record and current state for informed
    decision-making.
    """
    # Historical track record (last N deliberations)
    track_record: list[TrackRecordEntry] = field(default_factory=list)

    # Current portfolio state (positions, exposure)
    current_positions: list[dict] = field(default_factory=list)

    # Consistency alerts (detected sentiment reversals)
    consistency_alerts: list[str] = field(default_factory=list)

    # Metadata
    history_depth: int = 10  # Number of deliberations to include
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class TrackRecordEntry:
    """Single entry in CIO's track record."""
    memo_id: str
    date: str
    executive_summary: str
    consensus_level: str  # "unanimous", "strong", "majority", "split"
    recommendations_count: int
    primary_ticker: str | None = None  # Most prominent recommendation
```

### 3.2 Context Builder Function

**Location**: `parrot/finance/swarm.py`

```python
def _build_cio_context(memory_context: CIOMemoryContext) -> str:
    """Build dynamic context for CIO agent.

    Follows pattern established by _build_executor_context in execution.py.

    Args:
        memory_context: CIOMemoryContext with historical data.

    Returns:
        XML-formatted context string for injection.
    """
    ctx = ""

    # Track record block
    track_record_data = [
        {
            "memo_id": entry.memo_id,
            "date": entry.date,
            "executive_summary": entry.executive_summary,
            "consensus": entry.consensus_level,
            "recommendations": entry.recommendations_count,
            "primary_ticker": entry.primary_ticker,
        }
        for entry in memory_context.track_record
    ]
    ctx += _build_context_block("track_record", track_record_data)

    # Current positions block
    if memory_context.current_positions:
        ctx += _build_context_block("current_positions", memory_context.current_positions)

    # Consistency alerts block
    if memory_context.consistency_alerts:
        ctx += _build_context_block("consistency_alerts", memory_context.consistency_alerts)

    return ctx
```

### 3.3 MemoStore Integration

**Location**: `parrot/finance/research/memory/memo_store.py` (from FEAT-024)

Add query method:

```python
async def get_recent_memos(
    self,
    limit: int = 10,
    exclude_current: bool = True,
) -> list[InvestmentMemo]:
    """Get the N most recent investment memos.

    Args:
        limit: Maximum number of memos to return.
        exclude_current: Exclude memos from current day (for deliberation context).

    Returns:
        List of InvestmentMemo objects, newest first.
    """
```

### 3.4 CommitteeDeliberation Integration

**Location**: `parrot/finance/swarm.py`

Modify `_run_cio_round()` to inject memory context:

```python
async def _run_cio_round(
    self,
    analyst_reports: list[AnalystReportOutput],
    memory_context: CIOMemoryContext | None = None,
) -> CIODeliberationOutput:
    """Run CIO deliberation round with optional memory context."""

    # Build dynamic context
    dynamic_ctx = ""
    if memory_context:
        dynamic_ctx = _build_cio_context(memory_context)

    # Existing analyst report context
    dynamic_ctx += _build_analyst_reports_context(analyst_reports)

    # Run CIO agent with context
    response = await self._cio.ask(
        prompt=deliberation_prompt,
        system_prompt=dynamic_ctx,  # Dynamic context injection
    )
```

---

## 4. Acceptance Criteria

### Unit Tests

1. `test_cio_memory_context_creation` — CIOMemoryContext can be instantiated with defaults
2. `test_track_record_entry_fields` — TrackRecordEntry has all required fields
3. `test_build_cio_context_with_track_record` — Context includes `<track_record>` block
4. `test_build_cio_context_empty_track_record` — Works with empty history
5. `test_build_cio_context_with_positions` — Context includes `<current_positions>` block
6. `test_build_cio_context_with_alerts` — Context includes `<consistency_alerts>` block

### Integration Tests

7. `test_memo_store_get_recent_memos` — Returns last N memos sorted by date
8. `test_cio_round_with_memory_context` — CIO receives track record in context
9. `test_deliberation_pipeline_with_history` — Full pipeline uses memory context

### Verification Commands

```bash
# Unit tests
pytest tests/test_cio_memory_context.py -v

# Integration tests
pytest tests/integration/test_cio_memory_integration.py -v -m integration

# Full deliberation with context
python -m parrot.finance.cli deliberate --with-history --ticker SPY
```

---

## 5. Implementation Tasks

| Task | Priority | Effort | Description |
|------|----------|--------|-------------|
| CIOMemoryContext dataclass | High | S | Add to schemas.py with TrackRecordEntry |
| _build_cio_context function | High | S | Context builder following executor pattern |
| MemoStore.get_recent_memos | High | M | Query method for FEAT-024 MemoStore |
| CommitteeDeliberation integration | High | M | Inject context into CIO rounds |
| Unit tests | Medium | M | Test context building and dataclasses |
| Integration tests | Medium | M | Test full pipeline with history |
| Documentation | Low | S | Update CLAUDE.md with new patterns |

---

## 6. Dependencies

- **FEAT-024 (Investment Memo Persistency)**: Required for MemoStore to query historical memos
- **Existing**: `CommitteeDeliberation`, `CIO_ARBITER` prompt, `_build_context_block` helper

---

## 7. Open Questions

1. **Track record depth**: Is 10 deliberations sufficient? Should this be configurable per deployment?: Configurable per deployment, but default 10.

2. **Summary truncation**: Executive summaries can be long. Should we truncate to N characters for context efficiency?: if executive summary is long then replaced with the bullet list of recommendations.

3. **Position integration**: Should current positions come from PortfolioManager or be passed externally?: comes from PortfolioManager.

4. **Consistency detection**: Should we auto-detect sentiment reversals, or is this a separate feature?: we need to detect sentiment reversals to optimize the decision.

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| MemoStore not implemented (FEAT-024) | Medium | High | Graceful degradation with empty track record |
| Context size exceeds token limits | Low | Medium | Truncate summaries, limit to 10 entries |
| Performance impact on deliberation | Low | Low | Async memo fetching, caching |

---

## 9. Future Considerations

- **Outcome tracking**: Link recommendations to actual position PnL for feedback loop
- **Pattern detection**: ML-based regime detection from track record
- **Cross-session memory**: Persist CIO insights across restarts
- **Analyst track records**: Similar pattern for individual analysts
