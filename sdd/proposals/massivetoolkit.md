# MassiveToolkit — Brainstorming Spec

## Purpose & Motivation

Massive (ex-Polygon.io) is an institutional-grade market data provider with direct exchange feeds from NYSE, NASDAQ, CBOE, and OPRA. PARROT already has broad data coverage across 12+ APIs, but Massive fills **four specific high-value gaps** where no existing tool provides equivalent data quality:

1. **Options chain with pre-computed Greeks and IV** — Market-calibrated, not estimated
2. **Short Interest** — FINRA bi-monthly data, structured
3. **Short Volume** — Daily FINRA off-exchange short sale data
4. **Benzinga Earnings + Analyst Ratings** — Structured EPS estimates/actuals, consensus ratings with price targets

The design philosophy is **enrichment over replacement**: Massive is called on a narrow set of **pre-filtered candidate tickers** (5-15 symbols per cycle), not on broad market scans (hundreds of tickers). This keeps usage well within the free tier's 5 calls/min limit while providing data that no other PARROT tool can match.

### Rate Budget Analysis

| Endpoint | Frequency | Tickers/Cycle | Calls/Day |
|----------|-----------|---------------|-----------|
| Option Chain Snapshot | Per deliberation cycle (2-4x/day) | 5-10 | 20-40 |
| Short Interest | Once daily (bi-monthly data) | 10-15 | 10-15 |
| Short Volume | Once daily | 10-15 | 10-15 |
| Benzinga Earnings | Per deliberation cycle | 5-10 | 10-40 |
| Benzinga Analyst Ratings | Per deliberation cycle | 5-10 | 10-40 |
| **Total** | | | **70-150** |

Free tier limit: 7,200 calls/day. **Usage: ~1-2% of capacity.**

---

## Architecture & Integration

### Position in the PARROT Stack

```
Research Crews (Layer 1)
  ├── YFinanceTool, AlpacaMarketsToolkit, FinnhubToolkit, etc.
  └── Produce ResearchBriefing with candidate tickers
         ↓
  ┌─────────────────────────────────────────────────────┐
  │ ENRICHMENT LAYER (Layer 1.5) — NEW                  │
  │                                                     │
  │ MassiveToolkit → called AFTER research, BEFORE      │
  │                  deliberation, on filtered tickers   │
  │                                                     │
  │ OptionsAnalyticsToolkit → uses Massive Greeks as     │
  │                           input for strategy analysis│
  │                                                     │
  │ QuantToolkit → uses Massive short interest for       │
  │                risk/sentiment metrics                │
  └─────────────────────────────────────────────────────┘
         ↓
Analyst Committee (Layer 2) — receives enriched briefings
         ↓
CIO Deliberation (Layer 3)
         ↓
Secretary → InvestmentMemo (Layer 4)
         ↓
Execution (Layer 5)
```

### Design Principles

1. **Thin wrapper over `massive` Python SDK** — The official `massive` package (ex `polygon-api-client`) provides typed models, auto-pagination, and rate limit handling. We wrap it, not reimplement it.

2. **Follows AbstractToolkit pattern** — `@tool_schema` decorators, Pydantic input models, async methods returning `ToolResult`-compatible dicts.

3. **Caching layer** — Short Interest updates bi-monthly, Treasury Yields daily, Analyst Ratings weekly. Aggressive Redis caching with TTLs matching data freshness avoids wasting rate budget on stale data.

4. **Graceful degradation** — If Massive is unreachable or rate-limited, the pipeline continues with existing data from YFinance/Finnhub. Massive is enrichment, never a hard dependency.

---

## Dependency

```
pip install massive
```

The package was renamed from `polygon-api-client` in October 2025. Import path: `from massive import RESTClient`. The SDK defaults to `api.massive.com`; old `api.polygon.io` endpoints remain active.

```python
from massive import RESTClient

client = RESTClient(api_key="YOUR_KEY")

# Option chain with Greeks
for contract in client.list_snapshot_options_chain("AAPL"):
    print(contract.greeks.delta, contract.implied_volatility)

# Short interest
for si in client.list_short_interest("AAPL"):
    print(si.short_interest, si.days_to_cover)
```

---

## Tool 1: Options Chain with Greeks (`get_options_chain_enriched`)

### Massive Endpoint

`GET /v3/snapshot/options/{underlyingAsset}` — **Option Chain Snapshot**

Returns per contract: pricing (bid, ask, midpoint, last trade), **Greeks (delta, gamma, theta, vega)**, **implied volatility**, open interest, volume, break-even price, underlying price.

### Why Not YFinance

`YFinanceTool(action="options")` returns chains with bid/ask/volume/OI/IV but **no Greeks**. The IV values from Yahoo are also less reliable than OPRA-sourced data from Massive. Computing Greeks locally with Black-Scholes (as spec'd in `OptionsAnalyticsToolkit`) is an approximation — it assumes European options and continuous dividends. Massive's Greeks come from market makers' actual pricing models applied to real-time OPRA data.

### Architecture Decision: Massive Greeks as Ground Truth, Local BS for What-If

The `OptionsAnalyticsToolkit` should use Massive Greeks when available for:
- Current portfolio exposure calculations (risk analyst)
- PMCC scoring (equity analyst) — delta accuracy of LEAPS/short leg
- Spread analysis (equity analyst) — net position Greeks

The local Black-Scholes engine remains essential for:
- Scenario analysis ("what if IV increases 5%?")
- Pricing theoretical combinations that don't exist on the chain
- POP calculation (requires a pricing model, not just snapshot)
- When Massive data is unavailable (fallback)

### Input Model

```python
class OptionsChainInput(BaseModel):
    underlying: str = Field(
        ..., description="Underlying ticker symbol (e.g. 'AAPL')"
    )
    expiration_date_gte: str | None = Field(
        None, description="Min expiration date YYYY-MM-DD"
    )
    expiration_date_lte: str | None = Field(
        None, description="Max expiration date YYYY-MM-DD"
    )
    strike_price_gte: float | None = Field(
        None, description="Min strike price"
    )
    strike_price_lte: float | None = Field(
        None, description="Max strike price"
    )
    contract_type: str | None = Field(
        None, description="'call', 'put', or None for both"
    )
    limit: int = Field(
        250, description="Max contracts per page (API max: 250)"
    )
```

### Output Structure

```python
{
    "underlying": "AAPL",
    "underlying_price": 185.42,
    "timestamp": "2026-03-02T15:30:00Z",
    "contracts_count": 147,
    "contracts": [
        {
            "ticker": "O:AAPL250321C00185000",
            "strike": 185.0,
            "expiration": "2025-03-21",
            "contract_type": "call",
            "greeks": {
                "delta": 0.512,
                "gamma": 0.031,
                "theta": -0.145,
                "vega": 0.287,
            },
            "implied_volatility": 0.285,
            "open_interest": 12450,
            "volume": 3200,
            "bid": 4.85,
            "ask": 5.10,
            "midpoint": 4.975,
            "last_trade_price": 4.95,
            "break_even_price": 189.95,
        },
        # ...
    ],
    "source": "massive",
    "cached": False,
}
```

### Caching Strategy

Options Greeks change tick-by-tick, but for the pipeline's decision cadence (hours), a **15-minute Redis cache** is appropriate. The chain for a single underlying can be large (hundreds of contracts), so cache the filtered subset only.

```python
cache_key = f"massive:options_chain:{underlying}:{expiry_filter}:{strike_filter}"
ttl = 900  # 15 minutes
```

---

## Tool 2: Short Interest (`get_short_interest`)

### Massive Endpoint

`GET /v3/reference/short-interest/{stockTicker}` — **Short Interest**

Returns bi-monthly FINRA data: `short_interest` (total shares short), `avg_daily_volume`, `days_to_cover`, `settlement_date`.

### Why It Matters

The sentiment research crew explicitly lists "Short interest databases" as a priority source. High short interest (>20% of float) signals:
- Potential **short squeeze** candidates (equity analyst interest)
- **Bearish consensus** among institutional traders (sentiment signal)
- **Risk flag** for existing long positions (risk analyst concern)

Currently, `FinnhubToolkit` provides `short_ratio` via company profile but not historical short interest data or `days_to_cover`.

### Input Model

```python
class ShortInterestInput(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    limit: int = Field(10, description="Number of settlement periods to return")
    order: str = Field("desc", description="'asc' or 'desc' by date")
```

### Output Structure

```python
{
    "symbol": "GME",
    "latest": {
        "settlement_date": "2026-02-14",
        "short_interest": 15_234_567,
        "avg_daily_volume": 4_567_890,
        "days_to_cover": 3.34,
    },
    "history": [
        {"settlement_date": "2026-02-14", "short_interest": 15_234_567, ...},
        {"settlement_date": "2026-01-31", "short_interest": 14_890_123, ...},
        # ...
    ],
    "derived": {
        "short_interest_change_pct": 2.31,  # vs previous period
        "trend": "increasing",               # "increasing", "decreasing", "stable"
        "days_to_cover_zscore": 1.85,        # vs 12-month history
    },
    "source": "massive",
}
```

### Caching Strategy

Data updates **bi-monthly** (two settlement dates per month). Cache for **12 hours**.

```python
cache_key = f"massive:short_interest:{symbol}"
ttl = 43200  # 12 hours
```

---

## Tool 3: Short Volume (`get_short_volume`)

### Massive Endpoint

`GET /v3/reference/short-volume/{stockTicker}` — **Short Volume**

Returns daily FINRA data from off-exchange venues and ATS: `short_volume`, `short_exempt_volume`, `total_volume`, `date`.

### Complements Short Interest

Short Interest tells you the **cumulative open short position** (stock of shorts). Short Volume tells you the **daily flow** — what fraction of today's trading was short sales. Together they give a complete picture:
- Rising short volume + rising short interest = new short positions being built (bearish conviction)
- Rising short volume + flat short interest = short-term hedging or intraday shorts being covered same-day
- Falling short volume + falling short interest = short covering rally potential

### Input Model

```python
class ShortVolumeInput(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    date_from: str | None = Field(None, description="Start date YYYY-MM-DD")
    date_to: str | None = Field(None, description="End date YYYY-MM-DD")
    limit: int = Field(30, description="Number of trading days")
```

### Output Structure

```python
{
    "symbol": "TSLA",
    "data": [
        {
            "date": "2026-03-01",
            "short_volume": 12_345_678,
            "short_exempt_volume": 234_567,
            "total_volume": 45_678_901,
            "short_volume_ratio": 0.270,  # short_volume / total_volume
        },
        # ...
    ],
    "derived": {
        "avg_short_ratio_5d": 0.265,
        "avg_short_ratio_20d": 0.248,
        "current_vs_20d": "above_average",  # "above_average", "normal", "below_average"
        "trend_5d": "increasing",
    },
    "source": "massive",
}
```

### Caching Strategy

Daily data, published after market close. Cache for **6 hours**.

```python
cache_key = f"massive:short_volume:{symbol}:{date_to}"
ttl = 21600  # 6 hours
```

---

## Tool 4: Benzinga Earnings (`get_earnings_data`)

### Massive Endpoint

`GET /benzinga/v1/earnings` — **Earnings** (Benzinga partnership)

Returns structured earnings: `date`, `ticker`, `eps_estimate`, `eps_actual`, `eps_surprise`, `eps_surprise_pct`, `revenue_estimate`, `revenue_actual`, `revenue_surprise_pct`, `period`, `time` (BMO/AMC).

### Why Not Existing Sources

| Feature | FinnhubToolkit | YFinanceTool | Massive/Benzinga |
|---------|---------------|-------------|-----------------|
| EPS estimate vs actual | ✅ | ✅ (fragile) | ✅ |
| Revenue estimate vs actual | ❌ | ❌ | ✅ |
| Revenue surprise % | ❌ | ❌ | ✅ |
| Earnings timing (BMO/AMC) | ✅ | ❌ | ✅ |
| Historical reliability | Good | Frequent data gaps | Excellent (Benzinga source) |
| Forward calendar | ✅ | Partial | ✅ |

The **revenue component** is the critical addition. Revenue surprises often drive stock moves more than EPS (revenue is harder to manipulate with accounting). The equity analyst needs both for proper fundamental assessment.

### Input Model

```python
class EarningsDataInput(BaseModel):
    symbol: str | None = Field(None, description="Filter by ticker")
    date_from: str | None = Field(None, description="Start date YYYY-MM-DD")
    date_to: str | None = Field(None, description="End date YYYY-MM-DD")
    importance: int | None = Field(
        None, description="Filter by importance (0-5)"
    )
    limit: int = Field(50, description="Max results")
```

### Output Structure

```python
{
    "symbol": "AAPL",
    "earnings": [
        {
            "date": "2026-01-30",
            "time": "AMC",  # After Market Close
            "period": "Q1 2026",
            "eps_estimate": 2.35,
            "eps_actual": 2.42,
            "eps_surprise_pct": 2.98,
            "revenue_estimate": 124_500_000_000,
            "revenue_actual": 126_200_000_000,
            "revenue_surprise_pct": 1.37,
        },
        # ... historical
    ],
    "next_earnings": {
        "date": "2026-04-24",
        "time": "AMC",
        "eps_estimate": 1.62,
        "revenue_estimate": 95_400_000_000,
    },
    "derived": {
        "beat_rate_4q": 1.0,           # 4/4 quarters beat
        "avg_eps_surprise_4q": 3.45,   # avg surprise % last 4 quarters
        "avg_revenue_surprise_4q": 1.82,
        "trend": "consistent_beater",  # "consistent_beater", "mixed", "consistent_misser"
    },
    "source": "massive_benzinga",
}
```

---

## Tool 5: Benzinga Analyst Ratings (`get_analyst_ratings`)

### Massive Endpoint

`GET /benzinga/v1/analyst-ratings` — **Analyst Ratings**

Returns: `analyst_name`, `firm`, `rating_current`, `rating_prior`, `action` (upgrade/downgrade/initiate/reiterate), `price_target_current`, `price_target_prior`, `date`.

Also: `GET /benzinga/v1/consensus-ratings` — **Consensus Ratings** — Aggregated buy/hold/sell distribution, mean/high/low price targets.

### Why This Matters

The equity research crew lists "Analyst upgrades/downgrades from major firms" and "Analyst consensus changes" as priority sources. `FinnhubToolkit.finnhub_analyst_recommendations` provides aggregate buy/hold/sell counts but **not individual analyst actions, firm names, or price target changes**. For the equity analyst, knowing that *Goldman upgraded AAPL to Buy with a $220 target* is far more actionable than knowing *there are 35 buys and 5 holds*.

### Input Model

```python
class AnalystRatingsInput(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    action: str | None = Field(
        None,
        description="Filter: 'upgrade', 'downgrade', 'initiate', 'reiterate'"
    )
    date_from: str | None = Field(None, description="Start date YYYY-MM-DD")
    limit: int = Field(20, description="Max results")
    include_consensus: bool = Field(
        True, description="Also fetch consensus summary"
    )
```

### Output Structure

```python
{
    "symbol": "AAPL",
    "recent_actions": [
        {
            "date": "2026-02-28",
            "analyst": "John Smith",
            "firm": "Goldman Sachs",
            "action": "upgrade",
            "rating_prior": "Neutral",
            "rating_current": "Buy",
            "price_target_prior": 195.0,
            "price_target_current": 220.0,
        },
        # ...
    ],
    "consensus": {
        "buy": 35,
        "hold": 8,
        "sell": 2,
        "strong_buy": 12,
        "strong_sell": 0,
        "mean_target": 208.50,
        "high_target": 250.0,
        "low_target": 170.0,
        "consensus_rating": "Buy",
    },
    "derived": {
        "upgrades_30d": 3,
        "downgrades_30d": 1,
        "net_sentiment": "positive",     # based on upgrade/downgrade ratio
        "target_upside_pct": 12.4,       # (mean_target - current_price) / current_price
        "recent_momentum": "improving",  # based on recent action trend
    },
    "source": "massive_benzinga",
}
```

### Caching Strategy

Analyst actions happen sporadically (a few per week per ticker). Cache for **4 hours**.

```python
cache_key = f"massive:analyst_ratings:{symbol}"
ttl = 14400  # 4 hours
```

---

## The Toolkit Class

```python
class MassiveToolkit(AbstractToolkit):
    """
    Premium market data enrichment from Massive.com (ex-Polygon.io).
    
    Provides institutional-grade data not available from free APIs:
    - Options chains with exchange-computed Greeks and IV
    - FINRA short interest and short volume data
    - Benzinga earnings with revenue estimates/actuals
    - Benzinga analyst ratings with individual analyst actions
    
    Design philosophy: Enrichment on filtered candidates, not broad scans.
    Called between research collection and deliberation, on 5-15 tickers
    identified as candidates by research crews.
    
    Allocated to:
    - equity_analyst: options chain, earnings, analyst ratings
    - sentiment_analyst: short interest, short volume
    - risk_analyst: options chain Greeks (portfolio exposure)
    """

    name = "massive_toolkit"

    def __init__(self, api_key: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key or os.environ.get("MASSIVE_API_KEY")
        if not self.api_key:
            raise ValueError("MASSIVE_API_KEY required")
        self._client = RESTClient(api_key=self.api_key)
        self._redis = None  # Injected or lazy-loaded from PARROT's Redis pool
```

### Tool Methods

| Method | Endpoint | Primary Consumer |
|--------|----------|-----------------|
| `get_options_chain_enriched` | Option Chain Snapshot | equity_analyst, risk_analyst |
| `get_short_interest` | Short Interest | sentiment_analyst |
| `get_short_volume` | Short Volume | sentiment_analyst |
| `get_earnings_data` | Benzinga Earnings | equity_analyst |
| `get_analyst_ratings` | Benzinga Analyst Ratings + Consensus | equity_analyst |

### Convenience Aggregators

Beyond the 5 individual tools, the toolkit exposes two higher-order methods that aren't tool-schema-decorated (they're for internal pipeline use, not direct agent calls):

```python
async def enrich_ticker(self, symbol: str, include: list[str] | None = None) -> dict:
    """
    One-call enrichment for a single ticker.
    Fetches all relevant Massive data in parallel.
    
    Args:
        symbol: Ticker to enrich
        include: Subset of ["options", "short_interest", "short_volume", 
                 "earnings", "analyst_ratings"]. None = all.
    
    Returns:
        Combined dict with all enrichment data.
    
    Used by: EnrichmentService (see integration spec)
    """

async def enrich_candidates(
    self, 
    symbols: list[str], 
    include: list[str] | None = None,
    max_concurrent: int = 3,
) -> dict[str, dict]:
    """
    Batch enrichment for multiple tickers with rate-limit-aware concurrency.
    
    Uses asyncio.Semaphore(max_concurrent) to avoid hitting 5 calls/min.
    With max_concurrent=3, even worst case (5 endpoints * 15 tickers = 75 calls)
    completes in ~15 minutes while staying under rate limit.
    
    For typical case (15 tickers, selective endpoints), completes in ~3-5 minutes.
    """
```

---

## File Layout

```
parrot/tools/massive/
├── __init__.py          # exports MassiveToolkit
├── client.py            # RESTClient wrapper with retry/rate-limit logic
├── models.py            # Pydantic input models for all 5 tools
├── cache.py             # Redis caching layer with per-endpoint TTLs
└── toolkit.py           # MassiveToolkit (AbstractToolkit subclass)
```

---

## Dependencies

- `massive` (PyPI) — Official SDK, replaces `polygon-api-client`
- `redis` — Already in PARROT (for caching layer)
- No other new dependencies.

---

## Error Handling & Graceful Degradation

```python
class MassiveToolkitError(Exception):
    """Base error for Massive toolkit."""

class MassiveRateLimitError(MassiveToolkitError):
    """Rate limit hit — back off and retry or skip."""

class MassiveDataUnavailableError(MassiveToolkitError):
    """Endpoint returned empty or plan doesn't include this data."""
```

Every tool method wraps calls in try/except and returns partial results:

```python
async def get_options_chain_enriched(self, underlying: str, ...) -> dict:
    try:
        # Check cache first
        cached = await self._cache_get(cache_key)
        if cached:
            return {**cached, "cached": True}
        
        # Fetch from Massive
        chain = await asyncio.to_thread(
            self._client.list_snapshot_options_chain, underlying, params={...}
        )
        result = self._transform_chain(chain)
        
        # Cache and return
        await self._cache_set(cache_key, result, ttl=900)
        return {**result, "cached": False}
        
    except Exception as e:
        self.logger.warning(f"Massive options chain failed for {underlying}: {e}")
        return {
            "underlying": underlying,
            "error": str(e),
            "fallback": "use_yfinance_options",
            "source": "massive_error",
        }
```

The pipeline's enrichment service checks for `"error"` in the result and falls back to existing tools transparently.

---

## Testing Strategy

- **Mock the SDK** — Unit tests with mocked `RESTClient` responses
- **Integration test** — Single-ticker enrichment against Massive sandbox (free tier)
- **Rate limit test** — Simulate 5 calls/min constraint with 20 tickers and verify Semaphore behavior
- **Cache test** — Verify Redis caching prevents redundant API calls
- **Degradation test** — Simulate API timeout and verify fallback dict is returned

---

## Open Questions

1. **Benzinga endpoints require expansion packs** — These are paid add-ons on top of the base Massive plan. Need to verify if the free tier includes Benzinga data or if it requires at least the Starter plan ($199/month). If Benzinga is paid-only, the toolkit should detect this and disable those tools gracefully: Bezinga is paid-only

2. **Options chain pagination** — A single underlying like SPY can have thousands of contracts. The SDK auto-paginates, but this could consume multiple API calls per request. Should we default to filtering by expiry range (e.g., next 60 days) to keep call count low?: Yes

3. **WebSocket for real-time options** — Massive offers WebSocket streaming for options trades/quotes. For MVP this is unnecessary (snapshot-based enrichment is sufficient), but Phase 2 could add a streaming monitor for portfolio positions' Greeks updates during market hours.

4. **Economy endpoints** — Massive also has `Inflation`, `Inflation Expectations`, `Labor Market`, and `Treasury Yields` endpoints. The macro research crew could use these, but `FredAPITool` already covers most of this. Worth adding only if FRED proves unreliable or if Massive's formatting is significantly more convenient.