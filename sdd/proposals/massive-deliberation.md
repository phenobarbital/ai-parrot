# Massive Enrichment — Deliberation Pipeline Integration Spec

## Overview

This document describes **how** the `MassiveToolkit` integrates into PARROT's existing deliberation pipeline. The toolkit spec (Document 04) covers *what* each tool does. This spec covers *when*, *where*, and *by whom* each tool is called, and what architectural changes are needed to support the enrichment layer.

The core idea: insert a new **Enrichment Phase** between research collection (Layer 1) and deliberation (Layer 2) that runs on filtered candidate tickers, adding institutional-grade data to the briefings before analysts see them.

---

## Current Pipeline Flow (Before Massive)

```
┌─────────────────────────────────────────────────┐
│ Layer 1: RESEARCH (cron-driven)                 │
│                                                 │
│ 5 Research Crews run on schedule:               │
│   macro_crew  → FredAPITool, MarketauxToolkit   │
│   equity_crew → YFinanceTool, FinnhubToolkit    │
│   crypto_crew → CoinGeckoTool, BinanceTool      │
│   sentiment_crew → FearGreedTool, MarketauxTool │
│   risk_crew   → YFinanceTool, AlpacaToolkit     │
│                                                 │
│ Output: ResearchBriefing per crew               │
│         stored in Redis via pub/sub             │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ DeliberationTrigger checks data freshness       │
│ → All 5 briefings fresh? → Start deliberation   │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│ Layer 2: DELIBERATION                           │
│                                                 │
│ FSM: idle → researching → deliberating          │
│                                                 │
│ Phase 1: Cross-pollination                      │
│   Sub-A: macro_analyst + sentiment_analyst      │
│   Sub-B: equity + crypto + risk (receive A)     │
│                                                 │
│ Phase 2: CIO-led deliberation (up to 3 rounds) │
│                                                 │
│ Phase 3: Secretary → InvestmentMemo             │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
            Dispatch → Execution
```

---

## Proposed Pipeline Flow (With Massive Enrichment)

```
┌─────────────────────────────────────────────────┐
│ Layer 1: RESEARCH (cron-driven, unchanged)      │
│                                                 │
│ 5 Research Crews run on schedule                │
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
│   3. Call MassiveToolkit.enrich_candidates()     │
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
│                                                 │
│ Phase 1 → Phase 2 → Phase 3 (unchanged flow)   │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
            Dispatch → Execution
```

### Key Design Decision: Enrichment as a Phase, Not a Tool Allocation

Two approaches were considered:

**Option A: Allocate MassiveToolkit to research crews** — The equity crew would call `get_options_chain_enriched()` directly during research, alongside YFinance and Finnhub.

**Option B (chosen): Dedicated enrichment phase after research** — A service extracts candidate tickers from all research outputs and enriches them in batch.

Why Option B wins:
- **Cross-crew intelligence** — The enrichment service sees candidates from *all* crews, not just one. A stock mentioned by both equity and sentiment crews gets enriched once, not twice.
- **Rate budget optimization** — Centralized control of API calls. No risk of equity and sentiment crews independently calling Massive for the same ticker.
- **Cleaner separation** — Research crews remain focused on broad data collection. Enrichment is a focused, targeted pass on candidates.
- **Timing control** — Enrichment runs only when deliberation is about to start, ensuring data freshness. Research crews run on fixed schedules that might be hours before deliberation.

---

## EnrichmentService — New Component

### File Location

```
parrot/finance/enrichment.py
```

### Class Design

```python
class EnrichmentService:
    """
    Extracts candidate tickers from research briefings and enriches them
    with Massive.com premium data before deliberation begins.
    
    Sits between DeliberationTrigger and CommitteeDeliberation in the pipeline.
    """
    
    def __init__(
        self,
        massive_toolkit: MassiveToolkit,
        redis_client: Redis,
        options_analytics: OptionsAnalyticsToolkit | None = None,
        quant_toolkit: QuantToolkit | None = None,
    ):
        self.massive = massive_toolkit
        self.redis = redis_client
        self.options_analytics = options_analytics
        self.quant_toolkit = quant_toolkit
        self.logger = logging.getLogger("TradingSwarm.EnrichmentService")
    
    async def enrich_briefings(
        self,
        briefings: dict[str, ResearchBriefing],
    ) -> dict[str, ResearchBriefing]:
        """
        Main entry point. Takes raw briefings, returns enriched briefings.
        
        Steps:
        1. Extract candidate tickers
        2. Classify data needs per ticker
        3. Fetch from Massive (with caching)
        4. Optionally compute derived analytics
        5. Merge into briefings
        """
```

### Step 1: Candidate Ticker Extraction

Research briefings contain `ResearchItem` objects with `assets_mentioned: list[str]`. The enrichment service scans all briefings and builds a priority-ranked candidate list:

```python
async def _extract_candidates(
    self,
    briefings: dict[str, ResearchBriefing],
) -> list[CandidateTicker]:
    """
    Extract and rank candidate tickers from all research briefings.
    
    Ranking criteria:
    - Mentioned by multiple crews → higher priority
    - High relevance_score in research items → higher priority
    - Mentioned in equity or crypto domain → eligible for enrichment
    - Mentioned in sentiment domain → eligible for short interest
    
    Returns: Sorted list of CandidateTicker, max 15 tickers.
    """
    
    ticker_scores: dict[str, CandidateTicker] = {}
    
    for crew_id, briefing in briefings.items():
        for item in briefing.items:
            for asset in item.assets_mentioned:
                if asset not in ticker_scores:
                    ticker_scores[asset] = CandidateTicker(
                        symbol=asset,
                        asset_class=self._infer_asset_class(asset),
                        mention_count=0,
                        max_relevance=0.0,
                        mentioned_by=[],
                        data_needs=set(),
                    )
                candidate = ticker_scores[asset]
                candidate.mention_count += 1
                candidate.max_relevance = max(
                    candidate.max_relevance, item.relevance_score
                )
                candidate.mentioned_by.append(crew_id)
                candidate.data_needs.update(
                    self._infer_data_needs(crew_id, item)
                )
    
    # Sort by mention count (desc), then relevance (desc)
    ranked = sorted(
        ticker_scores.values(),
        key=lambda c: (c.mention_count, c.max_relevance),
        reverse=True,
    )
    
    # Cap at 15 tickers to stay within rate budget
    return ranked[:15]
```

### Step 2: Data Needs Classification

Not every ticker needs every Massive endpoint. The classification is based on asset class and which crews mentioned it:

```python
def _infer_data_needs(
    self, crew_id: str, item: ResearchItem,
) -> set[str]:
    """
    Determine which Massive endpoints are relevant for this mention.
    """
    needs = set()
    
    # Options data only makes sense for US stocks
    if item.domain in ("equity",) and item.raw_data.get("data_type") in (
        "earnings", "price_action", "analyst_upgrade", "sector_move"
    ):
        needs.add("options")
        needs.add("earnings")
        needs.add("analyst_ratings")
    
    # Short interest/volume for equity mentions in sentiment context
    if item.domain in ("equity", "sentiment"):
        needs.add("short_interest")
        needs.add("short_volume")
    
    # Crypto tickers don't go through Massive (no coverage)
    # Macro indicators don't need per-ticker enrichment
    
    return needs
```

### Step 3: Fetch from Massive

Uses `MassiveToolkit.enrich_candidates()` with the classified needs:

```python
async def _fetch_enrichment(
    self,
    candidates: list[CandidateTicker],
) -> dict[str, dict]:
    """
    Parallel fetch from Massive with rate-limit-aware concurrency.
    
    Groups candidates by data needs to minimize API calls:
    - Tickers needing only short_interest → batch those calls
    - Tickers needing full enrichment → all 5 endpoints
    
    Returns: {symbol: {enrichment_data}}
    """
    
    results = {}
    
    for candidate in candidates:
        if candidate.asset_class == "crypto":
            # Massive has crypto OHLC but not the enrichment data we need
            continue
        
        include = list(candidate.data_needs)
        if not include:
            continue
        
        try:
            result = await self.massive.enrich_ticker(
                candidate.symbol, include=include
            )
            results[candidate.symbol] = result
        except Exception as e:
            self.logger.warning(
                f"Enrichment failed for {candidate.symbol}: {e}"
            )
            results[candidate.symbol] = {"error": str(e)}
    
    return results
```

### Step 4: Derived Analytics (Optional)

If `OptionsAnalyticsToolkit` and `QuantToolkit` are available, compute derived metrics from the raw Massive data:

```python
async def _compute_derived(
    self,
    enrichment: dict[str, dict],
) -> dict[str, dict]:
    """
    Use other toolkits to compute derived analytics from Massive data.
    
    - OptionsAnalyticsToolkit: Net Greeks for portfolio exposure,
      PMCC suitability scores from chain with real Greeks
    - QuantToolkit: Short squeeze score combining short interest +
      short volume + days to cover
    """
    
    for symbol, data in enrichment.items():
        
        # If we have options chain with Greeks, compute portfolio exposure
        if "options" in data and self.options_analytics and "error" not in data.get("options", {}):
            chain = data["options"]["contracts"]
            # Use real Greeks from Massive (not BS estimates)
            data["derived_options"] = {
                "iv_skew": self._compute_iv_skew_from_chain(chain),
                "put_call_oi_ratio": self._compute_pc_oi_ratio(chain),
                "max_pain_strike": self._compute_max_pain(chain),
            }
        
        # If we have both short interest and short volume, compute combined score
        if "short_interest" in data and "short_volume" in data:
            si = data.get("short_interest", {})
            sv = data.get("short_volume", {})
            if "error" not in si and "error" not in sv:
                data["derived_short"] = {
                    "squeeze_score": self._compute_squeeze_score(si, sv),
                    "conviction_signal": self._interpret_short_signals(si, sv),
                }
    
    return enrichment
```

### Step 5: Merge into Briefings

The enrichment data is injected into the existing `ResearchBriefing` structure as additional `ResearchItem` entries:

```python
async def _merge_into_briefings(
    self,
    briefings: dict[str, ResearchBriefing],
    enrichment: dict[str, dict],
) -> dict[str, ResearchBriefing]:
    """
    Merge Massive enrichment data into the appropriate crew briefings.
    
    Routing:
    - options, earnings, analyst_ratings → equity briefing
    - short_interest, short_volume → sentiment briefing
    - portfolio_greeks_exposure → risk briefing
    
    Each enrichment datum becomes a new ResearchItem with 
    source="massive:{endpoint}" and domain matching the target crew.
    """
    
    for symbol, data in enrichment.items():
        if "error" in data:
            continue
        
        # Route options + earnings + analyst data to equity briefing
        if "options" in data or "earnings" in data or "analyst_ratings" in data:
            equity_items = []
            
            if "options" in data and "error" not in data["options"]:
                equity_items.append(ResearchItem(
                    source="massive:options_chain",
                    source_url=f"https://api.massive.com/v3/snapshot/options/{symbol}",
                    domain="equity",
                    title=f"Options chain with Greeks for {symbol}",
                    summary=self._summarize_options(data["options"]),
                    raw_data={
                        "data_type": "options_chain",
                        "greeks_source": "exchange_computed",
                        **data["options"],
                    },
                    relevance_score=0.8,
                    assets_mentioned=[symbol],
                ))
            
            if "earnings" in data and "error" not in data["earnings"]:
                equity_items.append(ResearchItem(
                    source="massive:benzinga_earnings",
                    source_url="https://api.massive.com/benzinga/v1/earnings",
                    domain="equity",
                    title=f"Earnings data for {symbol}",
                    summary=self._summarize_earnings(data["earnings"]),
                    raw_data={
                        "data_type": "earnings",
                        **data["earnings"],
                    },
                    relevance_score=0.85,
                    assets_mentioned=[symbol],
                ))
            
            if "analyst_ratings" in data and "error" not in data["analyst_ratings"]:
                equity_items.append(ResearchItem(
                    source="massive:benzinga_analyst_ratings",
                    source_url="https://api.massive.com/benzinga/v1/analyst-ratings",
                    domain="equity",
                    title=f"Analyst ratings for {symbol}",
                    summary=self._summarize_ratings(data["analyst_ratings"]),
                    raw_data={
                        "data_type": "analyst_upgrade",
                        **data["analyst_ratings"],
                    },
                    relevance_score=0.75,
                    assets_mentioned=[symbol],
                ))
            
            if equity_items:
                briefings["equity"].items.extend(equity_items)
        
        # Route short data to sentiment briefing
        if "short_interest" in data or "short_volume" in data:
            sentiment_items = []
            
            if "short_interest" in data and "error" not in data["short_interest"]:
                sentiment_items.append(ResearchItem(
                    source="massive:short_interest",
                    source_url=f"https://api.massive.com/v3/reference/short-interest/{symbol}",
                    domain="sentiment",
                    title=f"Short interest data for {symbol}",
                    summary=self._summarize_short_interest(data["short_interest"]),
                    raw_data={
                        "data_type": "short_interest",
                        **data["short_interest"],
                    },
                    relevance_score=0.8,
                    assets_mentioned=[symbol],
                ))
            
            if "short_volume" in data and "error" not in data["short_volume"]:
                sentiment_items.append(ResearchItem(
                    source="massive:short_volume",
                    source_url=f"https://api.massive.com/v3/reference/short-volume/{symbol}",
                    domain="sentiment",
                    title=f"Short volume data for {symbol}",
                    summary=self._summarize_short_volume(data["short_volume"]),
                    raw_data={
                        "data_type": "short_interest",  # Matches sentiment schema
                        **data["short_volume"],
                    },
                    relevance_score=0.75,
                    assets_mentioned=[symbol],
                ))
            
            if "derived_short" in data:
                sentiment_items.append(ResearchItem(
                    source="massive:derived_short_analysis",
                    source_url="",
                    domain="sentiment",
                    title=f"Short squeeze analysis for {symbol}",
                    summary=self._summarize_squeeze(data["derived_short"]),
                    raw_data={
                        "data_type": "short_interest",
                        **data["derived_short"],
                    },
                    relevance_score=0.85,
                    assets_mentioned=[symbol],
                ))
            
            if sentiment_items:
                briefings["sentiment"].items.extend(sentiment_items)
    
    return briefings
```

---

## Pipeline FSM Changes

### New Phase in PipelineStateMachine

```python
class PipelineStateMachine(StateMachine):
    """Updated FSM with enrichment phase."""
    
    idle = State("idle", initial=True)
    researching = State("researching")
    enriching = State("enriching")        # ← NEW
    deliberating = State("deliberating")
    dispatching = State("dispatching")
    executing = State("executing")
    monitoring = State("monitoring")
    completed = State("completed", final=True)
    halted = State("halted")
    failed = State("failed", final=True)
    
    start_research = idle.to(researching)
    start_enrichment = researching.to(enriching)  # ← NEW
    start_deliberation = (
        idle.to(deliberating)
        | researching.to(deliberating)    # Direct path (no Massive)
        | enriching.to(deliberating)      # ← NEW (enriched path)
    )
    # ... rest unchanged
```

The `researching → deliberating` direct path is preserved for when Massive is unavailable (graceful degradation).

---

## Changes to `run_trading_pipeline()`

### Updated Pipeline in `parrot/finance/execution.py`

```python
async def run_trading_pipeline(
    agent_class: type[AbstractBot],
    briefings: dict,
    portfolio: PortfolioSnapshot,
    constraints: ExecutorConstraints,
    stock_tools: list[AbstractTool] | None = None,
    crypto_tools: list[AbstractTool] | None = None,
    monitor_tools: list[AbstractTool] | None = None,
    # NEW parameters:
    massive_toolkit: MassiveToolkit | None = None,
    options_analytics: OptionsAnalyticsToolkit | None = None,
    quant_toolkit: QuantToolkit | None = None,
) -> dict[str, Any]:
    
    pipeline_fsm = PipelineStateMachine(pipeline_id="trading")
    
    # ... (bus setup unchanged) ...
    
    try:
        # ── NEW: ENRICHMENT PHASE ────────────────────────────────
        if massive_toolkit:
            pipeline_fsm.start_enrichment()
            logger.info("=" * 60)
            logger.info("PIPELINE: Enrichment phase (Massive.com)")
            logger.info("=" * 60)
            
            enrichment_service = EnrichmentService(
                massive_toolkit=massive_toolkit,
                redis_client=redis_pool,
                options_analytics=options_analytics,
                quant_toolkit=quant_toolkit,
            )
            
            try:
                briefings = await asyncio.wait_for(
                    enrichment_service.enrich_briefings(briefings),
                    timeout=300,  # 5-minute hard timeout
                )
                logger.info("Enrichment complete. Proceeding to deliberation.")
            except asyncio.TimeoutError:
                logger.warning("Enrichment timed out. Proceeding with raw briefings.")
            except Exception as e:
                logger.warning(f"Enrichment failed: {e}. Proceeding with raw briefings.")
        
        # ── DELIBERATION (receives enriched briefings) ───────────
        pipeline_fsm.start_deliberation()
        # ... (rest unchanged — committee.run_deliberation uses briefings)
```

The enrichment phase has a **5-minute hard timeout**. If Massive is slow or unavailable, the pipeline proceeds with unenriched briefings — exactly the same behavior as before Massive was integrated.

---

## Changes to Analyst Prompts

The analysts need to know enriched data might be present in their briefings. Minor prompt updates:

### Equity Analyst Prompt Addition

```python
# Append to ANALYST_EQUITY prompt, inside <sources_priority>:
"""
- Massive.com enrichment data (when available):
  - Options chains with exchange-computed Greeks (source: massive:options_chain)
  - Benzinga earnings with revenue estimates (source: massive:benzinga_earnings)
  - Benzinga analyst ratings with individual actions (source: massive:benzinga_analyst_ratings)
  When these are present, prefer their data over YFinance options data
  as Massive Greeks are exchange-computed (more accurate than estimates).
"""
```

### Sentiment Analyst Prompt Addition

```python
# Append to ANALYST_SENTIMENT prompt, inside <sources_priority>:
"""
- Massive.com enrichment data (when available):
  - FINRA short interest with days-to-cover (source: massive:short_interest)
  - Daily short volume ratios (source: massive:short_volume)
  - Derived short squeeze scores (source: massive:derived_short_analysis)
  When present, use these as your primary short interest data source.
  Pay special attention to the squeeze_score and conviction_signal fields.
"""
```

### Risk Analyst Prompt Addition

```python
# Append to ANALYST_RISK prompt:
"""
- When options chain data with exchange-computed Greeks is available
  (source: massive:options_chain), use these for portfolio Greeks exposure
  calculations instead of estimated values. Fields: delta, gamma, theta, vega
  per contract, implied_volatility from OPRA data.
"""
```

---

## Data Flow Diagram (Per Deliberation Cycle)

```
Research Crews (every 1-4 hours)
     │
     ├── equity_crew → mentions AAPL, NVDA, MSFT, TSLA, META
     ├── sentiment_crew → mentions AAPL, GME, TSLA, AMC
     ├── crypto_crew → mentions BTC, ETH, SOL (not enriched)
     ├── macro_crew → mentions SPY, TLT (index/ETF)
     └── risk_crew → mentions AAPL, NVDA, BTC (portfolio holdings)
                │
                ▼
     CandidateExtractor
     │  AAPL: 3 mentions (equity, sentiment, risk) → PRIORITY 1
     │  TSLA: 2 mentions (equity, sentiment) → PRIORITY 2
     │  NVDA: 2 mentions (equity, risk) → PRIORITY 3
     │  GME:  1 mention (sentiment) → PRIORITY 4
     │  META: 1 mention (equity) → PRIORITY 5
     │  MSFT: 1 mention (equity) → PRIORITY 6
     │  AMC:  1 mention (sentiment) → PRIORITY 7
     │  SPY:  1 mention (macro) → PRIORITY 8 (ETF, options only)
     │
     │  Top 15 selected, crypto excluded from Massive calls
                │
                ▼
     MassiveToolkit.enrich_candidates()
     │
     │  AAPL → options + earnings + analyst_ratings + short_interest + short_volume
     │  TSLA → options + earnings + analyst_ratings + short_interest + short_volume
     │  NVDA → options + earnings + analyst_ratings + short_interest + short_volume
     │  GME  → short_interest + short_volume (sentiment-only mention)
     │  META → options + earnings + analyst_ratings
     │  MSFT → options + earnings + analyst_ratings
     │  AMC  → short_interest + short_volume
     │  SPY  → options (ETF, no earnings/ratings)
     │
     │  Total API calls: ~30-35 (well within 5/min over ~7 minutes)
                │
                ▼
     Merge into briefings
     │
     │  equity_briefing += [options chains, earnings, ratings for AAPL,TSLA,NVDA,META,MSFT]
     │  sentiment_briefing += [short interest/volume for AAPL,TSLA,GME,AMC + squeeze scores]
     │  risk_briefing += [no direct merge, but data available in Redis for risk tools]
                │
                ▼
     Enriched briefings → CommitteeDeliberation.run_deliberation()
```

---

## Redis Storage Schema

Enrichment data is cached in Redis for two reasons: (1) avoid re-fetching within the same cycle, and (2) make data available to tools that run during deliberation (e.g., QuantToolkit computing risk metrics).

```
massive:options_chain:{symbol}     → JSON, TTL 900s (15 min)
massive:short_interest:{symbol}    → JSON, TTL 43200s (12 hours)
massive:short_volume:{symbol}:{date} → JSON, TTL 21600s (6 hours)
massive:earnings:{symbol}          → JSON, TTL 14400s (4 hours)
massive:analyst_ratings:{symbol}   → JSON, TTL 14400s (4 hours)
massive:enrichment_run:{timestamp} → JSON, TTL 86400s (audit trail, 24 hours)
```

The `enrichment_run` key stores metadata about each enrichment pass: which tickers were enriched, which endpoints succeeded/failed, total API calls used, duration. Useful for monitoring rate budget usage.

---

## Configuration

### Environment Variables

```bash
MASSIVE_API_KEY=your_key_here
MASSIVE_ENRICHMENT_ENABLED=true           # Kill switch
MASSIVE_MAX_CANDIDATES=15                  # Max tickers per cycle
MASSIVE_MAX_CONCURRENT=3                   # Concurrent API calls
MASSIVE_ENRICHMENT_TIMEOUT=300             # Hard timeout seconds
MASSIVE_DEFAULT_EXPIRY_RANGE_DAYS=60       # Options chain filter
```

### Runtime Toggle

```python
# In pipeline configuration or ExecutorConstraints:
enrichment_config = {
    "enabled": True,
    "endpoints": ["options", "short_interest", "short_volume", 
                   "earnings", "analyst_ratings"],
    "max_candidates": 15,
    "timeout_seconds": 300,
}
```

Individual endpoints can be disabled if Benzinga expansion packs aren't purchased:

```python
enrichment_config = {
    "enabled": True,
    "endpoints": ["options", "short_interest", "short_volume"],
    # Benzinga endpoints disabled (not in current plan)
}
```

---

## File Layout (New Files)

```
parrot/finance/
├── enrichment.py           # EnrichmentService (new)
├── execution.py            # Updated run_trading_pipeline()
├── fsm.py                  # Updated PipelineStateMachine
└── prompts.py              # Minor analyst prompt additions

parrot/tools/massive/
├── __init__.py
├── client.py
├── models.py
├── cache.py
└── toolkit.py
```

---

## Testing Strategy

- **Unit: CandidateExtractor** — Feed mock briefings with known tickers and verify ranking, dedup, asset class classification
- **Unit: DataNeedsClassifier** — Verify equity mentions get options+earnings, sentiment mentions get short data
- **Unit: BriefingMerger** — Verify enrichment items land in the correct crew's briefing with proper schema
- **Integration: EnrichmentService** — Mock MassiveToolkit, feed real briefing structure, verify end-to-end flow
- **Integration: Pipeline** — Run `run_trading_pipeline()` with and without `massive_toolkit` parameter, verify both paths produce valid memos
- **Degradation: Timeout** — Set enrichment timeout to 1 second, verify pipeline proceeds with raw briefings
- **Degradation: Partial failure** — Mock 3 of 5 endpoints failing, verify partial enrichment is still merged
- **Rate budget: Concurrency** — Monitor actual API call count with 15 tickers and verify < 50 calls

---

## Phased Rollout

### Phase 1: Options Chain + Short Interest (MVP)

- Implement `get_options_chain_enriched` and `get_short_interest`
- Implement `EnrichmentService` with basic candidate extraction
- Wire into pipeline with feature flag
- Validate against free tier limits

### Phase 2: Full Enrichment

- Add `get_short_volume`, `get_earnings_data`, `get_analyst_ratings`
- Add derived analytics (squeeze scores, IV skew from real chain)
- Integrate with `OptionsAnalyticsToolkit` for portfolio Greeks

### Phase 3: Cross-Toolkit Synergies

- `OptionsAnalyticsToolkit` uses Massive Greeks as input for PMCC scoring
- `QuantToolkit` uses short interest for squeeze probability models
- `TechnicalAnalysisTool` ATR stop-losses validated against options IV
- Secretary uses analyst consensus targets for `MemoRecommendation.target_price`

---

## Open Questions

1. **Enrichment as a separate heartbeat vs inline** — Should the enrichment run on its own cron schedule (e.g., every 30 min during market hours, caching results) rather than inline during the pipeline? Pros: reduces deliberation startup latency. Cons: data might be 30 min stale when deliberation starts: Uses AI-Parrot scheduler to run every 30 minutes with caching results.

2. **Candidate extraction from portfolio** — Should the enrichment service also enrich tickers that are in the *current portfolio* but weren't mentioned by any research crew? This would give the risk analyst updated Greeks and short interest for existing positions even if no crew reported on them: Yes.

3. **Event-driven enrichment** — When a research item has high relevance_score (>0.9) for a ticker, should that trigger immediate enrichment via Redis pub/sub rather than waiting for the batch enrichment phase? This would give the fastest possible data for breaking events: Even-Driven Enrichment.