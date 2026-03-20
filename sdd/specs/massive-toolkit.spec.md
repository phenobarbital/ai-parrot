# Feature Specification: MassiveToolkit

**Feature ID**: FEAT-018
**Date**: 2026-03-02
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

PARROT's finance research pipeline has broad market data coverage across 12+ APIs, but four specific high-value data gaps remain where no existing tool provides equivalent quality:

1. **Options chain with pre-computed Greeks and IV** — Market-calibrated from OPRA, not estimated
2. **Short Interest** — FINRA bi-monthly data (total shares short, days to cover)
3. **Short Volume** — Daily FINRA off-exchange short sale data
4. **Benzinga Earnings + Analyst Ratings** — Structured EPS/revenue estimates/actuals, individual analyst actions with price targets

These gaps affect the deliberation layer's ability to make informed decisions:
- Risk analyst cannot accurately assess options exposure without real Greeks
- Sentiment analyst lacks short interest data explicitly required in crew prompts
- Equity analyst has incomplete earnings data (no revenue surprise) and only aggregate analyst ratings

Massive.com (ex-Polygon.io) provides institutional-grade data with direct exchange feeds from NYSE, NASDAQ, CBOE, and OPRA that fills these gaps.

### Goals

- **Enrichment over replacement**: Massive is called on pre-filtered candidate tickers (5-15 symbols per cycle), not broad scans
- **Thin wrapper over SDK**: Use the official `massive` Python package with typed models and auto-pagination
- **Aggressive caching**: TTLs match data freshness (bi-monthly for short interest, 15 min for options)
- **Graceful degradation**: If Massive fails, pipeline continues with YFinance/Finnhub fallbacks
- **Rate budget compliance**: Stay well within free tier's 5 calls/min (estimated 70-150 calls/day, ~1-2% of 7,200/day capacity)

### Non-Goals (explicitly out of scope)

- Real-time WebSocket streaming for options (Phase 2)
- Economy endpoints (Inflation, Treasury Yields) — FRED covers this
- Benzinga news endpoints — MarketauxTool already provides news
- Broad market scans (hundreds of tickers)
- Replacing existing tools — this is enrichment only

---

## 2. Architectural Design

### Overview

MassiveToolkit is positioned as an **enrichment layer** (Layer 1.5) between research collection and deliberation. It receives filtered candidate tickers from research crews and enriches them with institutional-grade data before the analyst committee deliberates.

The toolkit follows the `AbstractToolkit` pattern with Redis caching and graceful error handling.

### Component Diagram

```
Research Crews (Layer 1)
  ├── YFinanceTool, AlpacaMarketsToolkit, FinnhubToolkit, etc.
  └── Produce ResearchBriefing with candidate tickers
         ↓
  ┌─────────────────────────────────────────────────────┐
  │ ENRICHMENT LAYER (Layer 1.5)                        │
  │                                                     │
  │ MassiveToolkit                                      │
  │   ├── get_options_chain_enriched()                  │
  │   ├── get_short_interest()                          │
  │   ├── get_short_volume()                            │
  │   ├── get_earnings_data()                           │
  │   └── get_analyst_ratings()                         │
  │                                                     │
  │ Called AFTER research, BEFORE deliberation          │
  │ On filtered tickers (5-15 symbols)                  │
  └─────────────────────────────────────────────────────┘
         ↓
Analyst Committee (Layer 2) — receives enriched briefings
         ↓
CIO Deliberation (Layer 3)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Base class for tool generation |
| `ToolCache` | uses | Redis caching layer from `parrot/tools/cache.py` |
| `HTTPService` | uses | For custom HTTP calls if SDK insufficient |
| `OptionsAnalyticsToolkit` | consumes | Uses Massive Greeks as ground truth input |
| `QuantToolkit` | consumes | Uses short interest for risk/sentiment metrics |
| Research Crews | producer | Provides tickers to enrich |
| Analyst Committee | consumer | Receives enriched data |

### Data Models

```python
# Input models for each tool

class OptionsChainInput(BaseModel):
    underlying: str = Field(..., description="Underlying ticker symbol (e.g. 'AAPL')")
    expiration_date_gte: str | None = Field(None, description="Min expiration date YYYY-MM-DD")
    expiration_date_lte: str | None = Field(None, description="Max expiration date YYYY-MM-DD")
    strike_price_gte: float | None = Field(None, description="Min strike price")
    strike_price_lte: float | None = Field(None, description="Max strike price")
    contract_type: str | None = Field(None, description="'call', 'put', or None for both")
    limit: int = Field(250, description="Max contracts per page (API max: 250)")


class ShortInterestInput(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    limit: int = Field(10, description="Number of settlement periods to return")
    order: str = Field("desc", description="'asc' or 'desc' by date")


class ShortVolumeInput(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    date_from: str | None = Field(None, description="Start date YYYY-MM-DD")
    date_to: str | None = Field(None, description="End date YYYY-MM-DD")
    limit: int = Field(30, description="Number of trading days")


class EarningsDataInput(BaseModel):
    symbol: str | None = Field(None, description="Filter by ticker")
    date_from: str | None = Field(None, description="Start date YYYY-MM-DD")
    date_to: str | None = Field(None, description="End date YYYY-MM-DD")
    importance: int | None = Field(None, description="Filter by importance (0-5)")
    limit: int = Field(50, description="Max results")


class AnalystRatingsInput(BaseModel):
    symbol: str = Field(..., description="Stock ticker symbol")
    action: str | None = Field(None, description="Filter: 'upgrade', 'downgrade', 'initiate', 'reiterate'")
    date_from: str | None = Field(None, description="Start date YYYY-MM-DD")
    limit: int = Field(20, description="Max results")
    include_consensus: bool = Field(True, description="Also fetch consensus summary")
```

### New Public Interfaces

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
    """

    name = "massive_toolkit"

    def __init__(self, api_key: str | None = None, **kwargs): ...

    # Tool methods (exposed to agents)
    async def get_options_chain_enriched(
        self, underlying: str, expiration_date_gte: str | None = None, ...
    ) -> dict: ...

    async def get_short_interest(self, symbol: str, limit: int = 10, ...) -> dict: ...

    async def get_short_volume(self, symbol: str, date_from: str | None = None, ...) -> dict: ...

    async def get_earnings_data(self, symbol: str | None = None, ...) -> dict: ...

    async def get_analyst_ratings(self, symbol: str, ...) -> dict: ...

    # Internal convenience methods (not tool-decorated)
    async def enrich_ticker(self, symbol: str, include: list[str] | None = None) -> dict: ...

    async def enrich_candidates(
        self, symbols: list[str], include: list[str] | None = None, max_concurrent: int = 3
    ) -> dict[str, dict]: ...
```

---

## 3. Module Breakdown

### Module 1: Input Models (`models.py`)

- **Path**: `parrot/tools/massive/models.py`
- **Responsibility**: Pydantic input models for all 5 tools
- **Depends on**: None

### Module 2: Client Wrapper (`client.py`)

- **Path**: `parrot/tools/massive/client.py`
- **Responsibility**: Wrap Massive SDK's `RESTClient` with retry logic, rate limit handling, async execution
- **Depends on**: `massive` SDK

### Module 3: Cache Layer (`cache.py`)

- **Path**: `parrot/tools/massive/cache.py`
- **Responsibility**: Redis caching with per-endpoint TTLs
- **Depends on**: `parrot/tools/cache.py` (ToolCache)

### Module 4: Toolkit Implementation (`toolkit.py`)

- **Path**: `parrot/tools/massive/toolkit.py`
- **Responsibility**: Main `MassiveToolkit` class with all 5 tool methods
- **Depends on**: Module 1, Module 2, Module 3

### Module 5: Package Init (`__init__.py`)

- **Path**: `parrot/tools/massive/__init__.py`
- **Responsibility**: Export `MassiveToolkit` and key models
- **Depends on**: Module 4

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_options_chain_input_validation` | models.py | Validates input model constraints |
| `test_short_interest_input_validation` | models.py | Validates input model constraints |
| `test_client_retry_logic` | client.py | Verifies retry on transient errors |
| `test_client_rate_limit_handling` | client.py | Verifies backoff on 429 response |
| `test_cache_key_generation` | cache.py | Verifies unique cache keys per endpoint/params |
| `test_cache_ttl_per_endpoint` | cache.py | Verifies correct TTLs (15min options, 12h short interest, etc.) |
| `test_toolkit_init_missing_key` | toolkit.py | Raises ValueError without MASSIVE_API_KEY |
| `test_options_chain_transform` | toolkit.py | Transforms SDK response to expected output |
| `test_short_interest_derived_metrics` | toolkit.py | Calculates trend, change_pct correctly |
| `test_graceful_degradation` | toolkit.py | Returns fallback dict on API error |

### Integration Tests

| Test | Description |
|---|---|
| `test_options_chain_real_api` | Fetch AAPL options chain from Massive sandbox |
| `test_short_interest_real_api` | Fetch GME short interest from Massive |
| `test_enrich_ticker_all_endpoints` | Call enrich_ticker with all 5 data types |
| `test_enrich_candidates_rate_limit` | Verify Semaphore limits concurrent calls |
| `test_cache_prevents_duplicate_calls` | Verify second call hits cache, not API |

### Test Data / Fixtures

```python
@pytest.fixture
def mock_massive_client():
    """Mock RESTClient with predefined responses."""
    client = MagicMock()
    client.list_snapshot_options_chain.return_value = [
        MagicMock(
            ticker="O:AAPL250321C00185000",
            strike_price=185.0,
            expiration_date="2025-03-21",
            contract_type="call",
            greeks=MagicMock(delta=0.512, gamma=0.031, theta=-0.145, vega=0.287),
            implied_volatility=0.285,
            open_interest=12450,
            day=MagicMock(volume=3200),
            last_quote=MagicMock(bid=4.85, ask=5.10, midpoint=4.975),
        )
    ]
    return client


@pytest.fixture
def mock_redis_cache():
    """In-memory cache for testing."""
    return {}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/test_massive*.py -v`)
- [ ] Integration tests pass against Massive sandbox (free tier)
- [ ] `get_options_chain_enriched` returns Greeks (delta, gamma, theta, vega) and IV
- [ ] `get_short_interest` returns days_to_cover and derived trend metrics
- [ ] `get_short_volume` returns daily short_volume_ratio and 5d/20d averages
- [ ] `get_earnings_data` returns revenue_surprise_pct (not just EPS)
- [ ] `get_analyst_ratings` returns individual analyst actions with firm names
- [ ] Redis caching works with correct TTLs per endpoint
- [ ] Graceful degradation returns `{"error": ..., "fallback": "use_yfinance_options"}` on failure
- [ ] Rate limiting stays under 5 calls/min during batch enrichment
- [ ] No breaking changes to existing public API
- [ ] Documentation updated with usage examples

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Use `AbstractToolkit` pattern from `parrot/tools/toolkit.py`
- Follow async-first design — wrap SDK sync calls with `asyncio.to_thread()`
- Pydantic models for all input/output structures
- Comprehensive logging with `self.logger`
- Use `ToolCache` from `parrot/tools/cache.py` for Redis integration

### Architecture Decision: Massive Greeks as Ground Truth

The `OptionsAnalyticsToolkit` should use Massive Greeks when available for:
- Current portfolio exposure calculations (risk analyst)
- PMCC scoring (equity analyst) — delta accuracy of LEAPS/short leg
- Spread analysis (equity analyst) — net position Greeks

The local Black-Scholes engine remains essential for:
- Scenario analysis ("what if IV increases 5%?")
- Pricing theoretical combinations that don't exist on the chain
- POP calculation (requires a pricing model, not just snapshot)
- When Massive data is unavailable (fallback)

### Caching Strategy

| Endpoint | TTL | Rationale |
|---|---|---|
| Options Chain | 15 min | Greeks change tick-by-tick, but decision cadence is hours |
| Short Interest | 12 hours | Data updates bi-monthly |
| Short Volume | 6 hours | Daily data, published after market close |
| Earnings | 24 hours | Quarterly data, rarely changes |
| Analyst Ratings | 4 hours | Sporadic updates (few per week per ticker) |

### Known Risks / Gotchas

- **Benzinga endpoints require paid plan** — Benzinga data is a paid add-on. Toolkit must detect this and disable those tools gracefully if not available.
- **Options chain pagination** — SPY can have thousands of contracts. Default to filtering by expiry range (next 60 days) to keep call count low.
- **SDK is sync** — The `massive` SDK uses synchronous HTTP. Wrap all calls in `asyncio.to_thread()` to avoid blocking the event loop.
- **Package rename** — The SDK was renamed from `polygon-api-client` to `massive` in October 2025. Import path is `from massive import RESTClient`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `massive` | `>=1.0` | Official Massive SDK (ex-Polygon) |
| `redis` | existing | Already in project for caching |

---

## 7. Open Questions

- [x] Benzinga endpoints require expansion packs — **Resolved**: Benzinga is paid-only. Detect and disable gracefully.
- [x] Options chain pagination — **Resolved**: Default to filtering by expiry range (next 60 days).
- [ ] WebSocket for real-time options — *Deferred to Phase 2*
- [ ] Economy endpoints (Treasury Yields, etc.) — *Not needed, FRED covers this*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-02 | Jesus Lara | Initial draft from brainstorming doc |
