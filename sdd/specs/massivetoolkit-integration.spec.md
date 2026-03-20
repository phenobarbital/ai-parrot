# Feature Specification: MassiveToolkit Integration

**Feature ID**: FEAT-019
**Date**: 2026-03-02
**Author**: Antigravity
**Status**: approved
**Target version**: 1.0.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement
The `MassiveToolkit` provides institutional-grade data, but it needs to be integrated into PARROT's existing deliberation pipeline efficiently. A naive integration would have each research crew call the toolkit independently, leading to rate limit exhaustion and duplicated data. We need a centralized enrichment mechanism to gracefully insert Massive data before deliberation begins.

### Goals
- Insert a new **Enrichment Phase** between research collection (Layer 1) and deliberation (Layer 2) that runs on filtered candidate tickers.
- Consolidate candidate tickers across all research crews to avoid redundant API calls and optimize rate budgets.
- Add institutional-grade data (Options Chains, Earnings, Analyst Ratings, Short Interest/Volume) to the briefings before analysts see them.
- Ensure graceful degradation if MassiveToolkit is unavailable or times out.

### Non-Goals (explicitly out of scope)
- Altering the existing cron-driven schedules for Research Crews (Layer 1).
- Modifying how the actual Deliberation Phase (Layer 2) flows, apart from consuming the newly enriched data.
- Enriching crypto tickers, as Massive does not cover the required enrichment data for them.

---

## 2. Architectural Design

### Overview
A new **Enrichment Phase (Layer 1.5)** will be introduced. The `EnrichmentService` will extract candidate tickers from all research outputs, classify data needs based on asset class and mentions, batch fetch enrichment data from MassiveToolkit, and merge the enriched data back into the `ResearchBriefing` objects for deliberation.

### Component Diagram
```
┌─────────────────────────────────────────────────┐
│ Layer 1: RESEARCH (cron-driven, unchanged)      │
│ Output: ResearchBriefing per crew → Redis       │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ DeliberationTrigger checks data freshness       │
│ → All 5 briefings fresh?                        │
│   → Extract candidate tickers                   │
│   → START ENRICHMENT PHASE (new)                │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ NEW — Layer 1.5: ENRICHMENT PHASE               │
│                                                 │
│ EnrichmentService:                              │
│   1. Extract candidate tickers from briefings   │
│   2. Classify by asset class + data needs       │
│   3. Call MassiveToolkit.enrich_candidates()    │
│   4. Merge enrichment into ResearchBriefings    │
│   5. Store enriched briefings in Redis          │
│                                                 │
│ Duration: 2-5 minutes (rate-limit aware)        │
│ Fallback: Skip if Massive unavailable           │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ Layer 2: DELIBERATION (enriched briefings)      │
│                                                 │
│ Analysts now have access to:                    │
│   - Market Greeks (not estimated)               │
│   - Short interest/volume data                  │
│   - Revenue estimates + analyst targets         │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
            Dispatch → Execution
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `PipelineStateMachine` | modified | Adding `enriching` state between `researching` and `deliberating` |
| `run_trading_pipeline` | modified | Instantiates `EnrichmentService` and runs the enrichment phase |
| Analyst Prompts | modified | Update prompts for Equity, Sentiment, and Risk analysts to prioritize Massive data |

### Data Models
```python
@dataclass
class CandidateTicker:
    symbol: str
    asset_class: str
    mention_count: int
    max_relevance: float
    mentioned_by: list[str]
    data_needs: set[str]
```

### New Public Interfaces
```python
class EnrichmentService:
    async def enrich_briefings(
        self,
        briefings: dict[str, ResearchBriefing],
    ) -> dict[str, ResearchBriefing]:
        ...
```

---

## 3. Module Breakdown

### Module 1: EnrichmentService
- **Path**: `parrot/finance/enrichment.py`
- **Responsibility**: Orchestrates extracting candidate tickers, inferring data needs, fetching from Massive, computing derived analytics (Greeks/Squeeze scores), and merging the results back into existing briefings.
- **Depends on**: `MassiveToolkit`, `OptionsAnalyticsToolkit`, `QuantToolkit`

### Module 2: Pipeline FSM & Execution Updates
- **Path**: `parrot/finance/execution.py`, `parrot/finance/fsm.py`
- **Responsibility**: Updates the `PipelineStateMachine` to include the `enriching` phase. Modifies `run_trading_pipeline` to execute the enrichment phase between Layer 1 and Layer 2, with a graceful 5-minute timeout.
- **Depends on**: Module 1

### Module 3: Analyst Prompts Update
- **Path**: `parrot/finance/prompts.py`
- **Responsibility**: Add instructions to `ANALYST_EQUITY`, `ANALYST_SENTIMENT`, and `ANALYST_RISK` prompts to utilize the new Massive enrichment data specifically for accurate Greeks, short interest/volume, and earnings/ratings.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_extract_candidates` | EnrichmentService | Feed mock briefings with known tickers and verify ranking, dedup, asset class classification |
| `test_infer_data_needs` | EnrichmentService | Verify equity mentions get options+earnings, sentiment mentions get short data |
| `test_merge_into_briefings` | EnrichmentService | Verify enrichment items land in the correct crew's briefing with proper schema |

### Integration Tests
| Test | Description |
|---|---|
| `test_enrichment_service_e2e` | Mock MassiveToolkit, feed real briefing structure, verify end-to-end flow |
| `test_pipeline_enrichment_paths` | Run `run_trading_pipeline()` with and without `massive_toolkit`, verify both paths produce valid memos |
| `test_pipeline_timeout_fallback` | Set enrichment timeout to 1 sec, verify pipeline proceeds with raw briefings |
| `test_partial_failure` | Mock 3 of 5 Massive endpoints failing, verify partial enrichment is still merged |

---

## 5. Acceptance Criteria

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] Centralized `EnrichmentService` successfully batches and deduplicates API calls.
- [ ] Fallback path successfully triggers on timeout (>5 mins) without crashing the deliberation pipeline.
- [ ] Enriched `ResearchItem` objects correctly injected into `ResearchBriefing` lists for equity and sentiment crews.
- [ ] Performance benchmark: < 50 total enrichment API calls for top 15 candidates.

---

## 6. Implementation Notes & Constraints

### Constraints & Rate Limits
- Capped at maximum 15 tickers per cycle to stay within Massive rate budgets.
- Group API calls logic is crucial. Tickers needing only short interest should batch short interest calls, minimizing overall API usage.
- Hard timeout of 300s (5 minutes) across the entire enrichment phase.

### Configuration / Env Vars
```bash
MASSIVE_API_KEY=your_key_here
MASSIVE_ENRICHMENT_ENABLED=true           # Kill switch
MASSIVE_MAX_CANDIDATES=15                  # Max tickers per cycle
MASSIVE_MAX_CONCURRENT=3                   # Concurrent API calls
MASSIVE_ENRICHMENT_TIMEOUT=300             # Hard timeout seconds
MASSIVE_DEFAULT_EXPIRY_RANGE_DAYS=60       # Options chain filter
```

---

## 7. Open Questions

- [x] **Enrichment as a separate heartbeat vs inline**: Uses AI-Parrot scheduler to run every 30 minutes with caching results. (Resolved)
- [x] **Candidate extraction from portfolio**: Yes, enrich tickers in current portfolio even if not mentioned by crews. (Resolved)
- [x] **Event-driven enrichment**: Event-Driven Enrichment on high-relevance (>0.9) items. (Resolved)
- [ ] How should derived data errors gracefully fall back so as not to pollute the briefing with `None` datasets? — *Owner: TBD*: Yes

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-02 | Antigravity | Initial draft based on massive-deliberation.md |
