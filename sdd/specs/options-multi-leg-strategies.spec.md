# Feature Specification: Multi-Leg Options Strategy Execution

**Feature ID**: FEAT-023
**Date**: 2026-03-04
**Author**: Claude
**Status**: approved
**Target version**: next
**Prior Exploration**: `sdd/proposals/options-strategies-iron-spreads.brainstorm.md`

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot's finance module currently supports single-leg order execution for stocks/ETFs (`AlpacaWriteToolkit`) and crypto (`BinanceWriteToolkit`). However, **there is no capability to execute multi-leg options strategies** such as Iron Butterfly, Iron Condor, or other defined-risk spreads.

These strategies are essential for:
1. **Income generation in range-bound markets** — Both Iron Butterfly and Iron Condor are theta-positive (benefit from time decay)
2. **Defined-risk trading** — Max profit and max loss are known at entry
3. **Volatility plays** — Short Iron Butterfly for IV crush after earnings, Long Iron Butterfly for vol expansion

Current gaps:
- **CIO Agent** cannot select options strategies for portfolio allocation
- **Executor** has no tools to place atomic 4-leg orders
- **Risk Analyst** cannot evaluate Greeks exposure of options positions
- **Portfolio** is limited to directional equity/crypto trades only

### Goals

- Create `AlpacaOptionsToolkit` for multi-leg options order execution
- Implement Iron Butterfly and Iron Condor strategy builders
- Automatic strike selection based on delta targets, IV percentile, and liquidity
- Position monitoring and management tools (Greeks, P&L, close positions)
- Integration with CIO decision-making prompts
- Integration with Risk Analyst for exposure analysis
- Paper trading support before production deployment

### Non-Goals (explicitly out of scope)

- Options analytics/pricing (covered by FEAT-015: OptionsAnalyticsToolkit)
- American-style binomial pricing (Phase 2)
- Full volatility surface construction (Phase 2)
- Auto-management daemon with position rolling (Phase 2)
- Backtesting framework for options strategies (Phase 2)
- Support for brokers other than Alpaca (IBKR options in separate spec)

---

## 2. Architectural Design

### Overview

A new `AlpacaOptionsToolkit` that uses Alpaca's Trading API to execute multi-leg options orders (`OrderClass.MLEG`). The toolkit provides strategy builders via a `StrategyFactory` pattern that constructs properly structured 4-leg orders for Iron Butterfly and Iron Condor strategies.

### Component Diagram

```
Layer 2: Analyst Committee
    │
    ├── CIO Agent
    │   └── Decides: "Use Iron Butterfly" or "Use Iron Condor"
    │         based on IV percentile, market outlook, risk budget
    │
    └── Risk Analyst
        └── Evaluates Greeks exposure, position concentration
              │
              ▼
Layer 3: Execution
    │
    ├── ExecutionOrchestrator
    │       │
    │       └── ExecutorAgent (Options)
    │               │
    │               └── AlpacaOptionsToolkit
    │                       │
    │                       ├── StrategyFactory
    │                       │   ├── iron_butterfly()
    │                       │   └── iron_condor()
    │                       │
    │                       ├── Strike Selection Engine
    │                       │   ├── find_atm_strike()
    │                       │   ├── find_otm_by_delta()
    │                       │   └── validate_liquidity()
    │                       │
    │                       └── Order Execution
    │                           ├── place_mleg_order()
    │                           ├── get_positions()
    │                           └── close_position()
    │                                   │
    │                                   ▼
    │                           Alpaca Trading API
    │                           (OrderClass.MLEG)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` | extends | Base class for toolkit methods |
| `@tool_schema` | uses | Decorator for tool method definitions |
| `OptionsAnalyticsToolkit` | collaborates | Greeks calculations, strategy P&L analysis |
| `ExecutionOrchestrator` | consumer | Routes options orders to this toolkit |
| `AlpacaWriteToolkit` | peer | Shares Alpaca client config patterns |
| `CIO Agent` | consumer | Calls strategy tools based on deliberation |
| `Risk Analyst` | consumer | Calls position analysis tools |

### Data Models

```python
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field

class OptionsLeg(BaseModel):
    """Single leg of an options position."""
    symbol: str  # OCC symbol: AAPL240315C00150000
    contract_type: Literal["call", "put"]
    strike: float
    expiration: date
    side: Literal["long", "short"]
    quantity: int
    entry_price: float
    current_price: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

class OptionsPosition(BaseModel):
    """Multi-leg options position with aggregated Greeks."""
    position_id: str
    strategy_type: Literal["iron_butterfly", "iron_condor", "vertical", "straddle", "strangle"]
    underlying: str
    legs: list[OptionsLeg]
    entry_date: datetime
    expiration: date
    net_credit: float  # Positive for credit spreads
    max_profit: float
    max_loss: float
    breakevens: list[float]
    current_pnl: float | None = None
    current_pnl_pct: float | None = None

    # Aggregated position Greeks
    position_delta: float | None = None
    position_gamma: float | None = None
    position_theta: float | None = None
    position_vega: float | None = None

class OptionsStrategyConfig(BaseModel):
    """Configuration for building an options strategy."""
    strategy_type: Literal["iron_butterfly", "iron_condor"]
    underlying: str
    expiration_days: int = Field(default=30, ge=7, le=60)
    wing_width: float = Field(default=5.0, gt=0)
    short_delta: float = Field(default=0.30, ge=0.15, le=0.45)  # Iron Condor only
    max_risk_pct: float = Field(default=5.0, ge=1.0, le=20.0)
    min_open_interest: int = Field(default=50, ge=10)
    max_bid_ask_spread_pct: float = Field(default=10.0, ge=1.0)

class OptionsStrategyRecommendation(BaseModel):
    """CIO recommendation for an options strategy."""
    strategy_type: Literal["iron_butterfly", "iron_condor"]
    underlying: str
    rationale: str
    iv_percentile: float
    expected_move: float
    target_expiration_dte: int
    suggested_wing_width: float
    estimated_credit: float
    max_risk: float
    risk_reward_ratio: float
    confidence: float  # 0-1
```

---

## 3. Detailed Design

### 3.1 AlpacaOptionsToolkit

```python
# parrot/finance/tools/alpaca_options.py

class AlpacaOptionsToolkit(AbstractToolkit):
    """Toolkit for multi-leg options strategies on Alpaca."""

    def __init__(self, paper: bool = True):
        """
        Initialize Alpaca options toolkit.

        Args:
            paper: If True, use Alpaca paper trading environment.
        """
        self.paper = paper
        self.client = TradingClient(
            api_key=config.get("ALPACA_API_KEY"),
            secret_key=config.get("ALPACA_SECRET_KEY"),
            paper=paper,
        )
        self.data_client = OptionHistoricalDataClient(
            api_key=config.get("ALPACA_API_KEY"),
            secret_key=config.get("ALPACA_SECRET_KEY"),
        )
        self.logger = logging.getLogger(__name__)

    # ─────────────────────────────────────────────────────────────
    # DATA RETRIEVAL
    # ─────────────────────────────────────────────────────────────

    @tool_schema(GetOptionsChainInput)
    async def get_options_chain(
        self,
        underlying: str,
        min_dte: int = 14,
        max_dte: int = 42,
        strike_range_pct: float = 10.0,
    ) -> dict:
        """
        Fetch options chain with Greeks for an underlying.

        Args:
            underlying: Ticker symbol (e.g., 'SPY', 'AAPL')
            min_dte: Minimum days to expiration
            max_dte: Maximum days to expiration
            strike_range_pct: Strike range as % of underlying price

        Returns:
            Options chain with calls/puts, Greeks, and liquidity metrics
        """
        ...

    # ─────────────────────────────────────────────────────────────
    # STRATEGY EXECUTION
    # ─────────────────────────────────────────────────────────────

    @tool_schema(PlaceIronButterflyInput)
    async def place_iron_butterfly(
        self,
        underlying: str,
        expiration_days: int = 30,
        wing_width: float = 5.0,
        max_risk_pct: float = 5.0,
        quantity: int = 1,
    ) -> dict:
        """
        Place a short iron butterfly strategy.

        The iron butterfly profits from low volatility and time decay.
        Short strikes are placed at-the-money (ATM), with long wings
        equidistant above and below.

        Structure:
        - Long Put @ ATM - wing_width (OTM)
        - Short Put @ ATM
        - Short Call @ ATM
        - Long Call @ ATM + wing_width (OTM)

        Best used when:
        - IV percentile > 50 (high IV expected to decrease)
        - Expecting price to stay near current level
        - After earnings or catalysts (IV crush play)

        Args:
            underlying: Ticker symbol (e.g., 'SPY', 'AAPL')
            expiration_days: Target days to expiration (14-42)
            wing_width: Distance from ATM for long strikes
            max_risk_pct: Maximum risk as % of buying power
            quantity: Number of contracts

        Returns:
            dict with order_id, position details, max_profit, max_loss, breakevens
        """
        ...

    @tool_schema(PlaceIronCondorInput)
    async def place_iron_condor(
        self,
        underlying: str,
        expiration_days: int = 30,
        short_delta: float = 0.30,
        wing_width: float = 5.0,
        max_risk_pct: float = 5.0,
        quantity: int = 1,
    ) -> dict:
        """
        Place a short iron condor strategy.

        The iron condor profits from range-bound markets with a wider
        profit zone than iron butterfly but lower credit received.

        Structure:
        - Long Put @ short_put_strike - wing_width (far OTM)
        - Short Put @ short_put_strike (OTM, ~short_delta)
        - Short Call @ short_call_strike (OTM, ~short_delta)
        - Long Call @ short_call_strike + wing_width (far OTM)

        Best used when:
        - Range-bound market with clear support/resistance
        - Want wider margin of error than iron butterfly
        - Lower credit but higher probability of profit

        Args:
            underlying: Ticker symbol
            expiration_days: Target DTE
            short_delta: Target absolute delta for short strikes (0.20-0.40)
            wing_width: Distance for long strikes from short strikes
            max_risk_pct: Maximum risk as % of buying power
            quantity: Number of contracts

        Returns:
            dict with order_id, position details, max_profit, max_loss, breakevens
        """
        ...

    # ─────────────────────────────────────────────────────────────
    # POSITION MANAGEMENT
    # ─────────────────────────────────────────────────────────────

    @tool_schema(GetOptionsPositionsInput)
    async def get_options_positions(
        self,
        underlying: str | None = None,
    ) -> list[dict]:
        """
        Get current options positions with P&L and Greeks.

        Args:
            underlying: Filter by underlying symbol (optional)

        Returns:
            List of OptionsPosition dicts with current values
        """
        ...

    @tool_schema(CloseOptionsPositionInput)
    async def close_options_position(
        self,
        position_id: str,
        close_type: Literal["market", "limit"] = "market",
        limit_credit: float | None = None,
    ) -> dict:
        """
        Close an existing multi-leg options position.

        Args:
            position_id: Position identifier
            close_type: Order type for closing
            limit_credit: For limit orders, target credit to receive

        Returns:
            Close confirmation with realized P&L
        """
        ...

    @tool_schema(GetPositionGreeksInput)
    async def get_position_greeks(
        self,
        position_id: str,
    ) -> dict:
        """
        Get current Greeks for a specific position.

        Returns aggregated position Greeks:
        - position_delta: Net delta exposure
        - position_gamma: Gamma risk (acceleration)
        - position_theta: Daily time decay (positive for credit spreads)
        - position_vega: Volatility sensitivity
        """
        ...
```

### 3.2 StrategyFactory

```python
# parrot/finance/tools/options_strategies.py

class StrategyFactory:
    """Factory for building options strategy leg configurations."""

    @staticmethod
    def iron_butterfly(
        underlying_price: float,
        wing_width: float = 5.0,
    ) -> list[StrategyLeg]:
        """
        Build an iron butterfly centered at underlying price.

        Args:
            underlying_price: Current price of underlying
            wing_width: Distance from ATM for long strikes

        Returns:
            List of 4 StrategyLeg configurations
        """
        atm_strike = round(underlying_price)
        return [
            StrategyLeg(contract_type="put", strike=atm_strike - wing_width, side="buy"),
            StrategyLeg(contract_type="put", strike=atm_strike, side="sell"),
            StrategyLeg(contract_type="call", strike=atm_strike, side="sell"),
            StrategyLeg(contract_type="call", strike=atm_strike + wing_width, side="buy"),
        ]

    @staticmethod
    def iron_condor(
        short_put_strike: float,
        short_call_strike: float,
        wing_width: float = 5.0,
    ) -> list[StrategyLeg]:
        """
        Build an iron condor with specified short strikes.

        Args:
            short_put_strike: Strike for short put (OTM)
            short_call_strike: Strike for short call (OTM)
            wing_width: Distance for long strikes

        Returns:
            List of 4 StrategyLeg configurations
        """
        return [
            StrategyLeg(contract_type="put", strike=short_put_strike - wing_width, side="buy"),
            StrategyLeg(contract_type="put", strike=short_put_strike, side="sell"),
            StrategyLeg(contract_type="call", strike=short_call_strike, side="sell"),
            StrategyLeg(contract_type="call", strike=short_call_strike + wing_width, side="buy"),
        ]
```

### 3.3 Strike Selection Engine

```python
# parrot/finance/tools/strike_selection.py

class StrikeSelectionEngine:
    """Engine for selecting optimal strikes based on criteria."""

    def __init__(self, data_client: OptionHistoricalDataClient):
        self.data_client = data_client

    async def find_atm_strike(
        self,
        options: list[dict],
        underlying_price: float,
    ) -> dict | None:
        """Find the at-the-money strike."""
        return min(
            options,
            key=lambda x: abs(x['strike_price'] - underlying_price),
            default=None
        )

    async def find_strike_by_delta(
        self,
        options: list[dict],
        target_delta: float,
        contract_type: Literal["call", "put"],
    ) -> dict | None:
        """Find strike closest to target delta."""
        # Filter by contract type
        filtered = [o for o in options if o['contract_type'] == contract_type]
        if not filtered:
            return None

        return min(
            filtered,
            key=lambda x: abs(abs(x.get('delta', 0)) - target_delta),
            default=None
        )

    async def validate_liquidity(
        self,
        option: dict,
        min_oi: int = 50,
        max_spread_pct: float = 10.0,
    ) -> bool:
        """Validate option meets liquidity thresholds."""
        oi = option.get('open_interest', 0)
        bid = option.get('bid', 0)
        ask = option.get('ask', 0)

        if oi < min_oi:
            return False

        if bid > 0:
            spread_pct = ((ask - bid) / bid) * 100
            if spread_pct > max_spread_pct:
                return False

        return True
```

### 3.4 Multi-Leg Order Execution

```python
# Core order execution using Alpaca MLEG

async def _place_mleg_order(
    self,
    legs: list[StrategyLeg],
    contracts: dict[str, dict],
    quantity: int = 1,
) -> dict:
    """
    Place a multi-leg options order via Alpaca.

    Args:
        legs: Strategy leg configurations
        contracts: Resolved contract symbols for each leg
        quantity: Number of spreads to trade
    """
    order_legs = []
    for leg in legs:
        contract = contracts[f"{leg.contract_type}_{leg.strike}"]
        order_legs.append(
            OptionLegRequest(
                symbol=contract['symbol'],
                side=OrderSide.BUY if leg.side == "buy" else OrderSide.SELL,
                ratio_qty=1,
            )
        )

    req = MarketOrderRequest(
        qty=quantity,
        order_class=OrderClass.MLEG,
        time_in_force=TimeInForce.DAY,
        legs=order_legs,
    )

    loop = asyncio.get_running_loop()
    order = await loop.run_in_executor(
        None,
        self.client.submit_order,
        req
    )

    return {
        "order_id": order.id,
        "status": order.status.value,
        "legs": [leg.symbol for leg in order_legs],
    }
```

### 3.5 CIO Integration

Add to CIO prompt:

```python
CIO_OPTIONS_STRATEGIES_PROMPT = """
<options_strategies>
You have access to options strategy tools for generating income in range-bound markets:

## Available Strategies

1. **Iron Butterfly** (`place_iron_butterfly`)
   - Use when: IV percentile > 50, expecting price stability at specific level
   - Pros: Higher credit received
   - Cons: Narrower profit zone, requires precise timing
   - Best after: Earnings, FDA decisions, or other catalysts (IV crush)

2. **Iron Condor** (`place_iron_condor`)
   - Use when: Range-bound market, want wider margin of error
   - Pros: Wider profit zone, higher probability of profit
   - Cons: Lower credit received
   - Best for: Consistent income in stable markets

## Decision Framework

| Condition | Strategy | Rationale |
|-----------|----------|-----------|
| IV percentile > 70 | Iron Butterfly | Maximize IV crush credit |
| IV percentile 40-70 | Iron Condor | Balance credit vs. probability |
| Clear range, low IV | Iron Condor | Wide wings for safety |
| Post-catalyst | Iron Butterfly | Capture vol contraction |

## Risk Limits
- Maximum 5% of portfolio in any single options strategy
- Maximum 15% total options exposure
- Minimum 14 DTE, maximum 45 DTE
- Only trade underlyings with sufficient liquidity (OI > 50)

## Tool Usage
- `place_iron_butterfly(underlying, expiration_days, wing_width, max_risk_pct)`
- `place_iron_condor(underlying, expiration_days, short_delta, wing_width, max_risk_pct)`
- `get_options_positions()` — Check existing options positions
- `close_options_position(position_id)` — Close before expiration

Always check buying power before placing trades.
</options_strategies>
"""
```

### 3.6 Risk Analyst Integration

Add tools for Risk Analyst:

```python
@tool()
async def analyze_options_portfolio_risk(self) -> dict:
    """
    Analyze aggregate options risk for the portfolio.

    Returns:
    - total_options_exposure: Total premium at risk
    - net_delta: Aggregate delta (directional exposure)
    - net_gamma: Aggregate gamma (convexity risk)
    - net_theta: Daily time decay (positive = collecting)
    - net_vega: Volatility sensitivity
    - positions_by_expiration: Count by DTE bucket
    - concentration_risk: Exposure by underlying
    """
    ...

@tool()
async def stress_test_options_positions(
    self,
    underlying_move_pct: float = 5.0,
    iv_change_pct: float = 20.0,
) -> dict:
    """
    Stress test options positions for adverse scenarios.

    Args:
        underlying_move_pct: Hypothetical underlying move
        iv_change_pct: Hypothetical IV change

    Returns:
        P&L impact for each position under stress scenarios
    """
    ...
```

---

## 4. Implementation Tasks

### Phase 1: Core Toolkit (Priority: P0)

| Task ID | Description | Effort | Dependencies |
|---------|-------------|--------|--------------|
| T1.1 | Create `AlpacaOptionsToolkit` base class | 2h | None |
| T1.2 | Implement `get_options_chain()` with Greeks | 3h | T1.1 |
| T1.3 | Implement `StrategyFactory` | 2h | None |
| T1.4 | Implement `StrikeSelectionEngine` | 3h | T1.2 |
| T1.5 | Implement `place_iron_butterfly()` | 4h | T1.3, T1.4 |
| T1.6 | Implement `place_iron_condor()` | 3h | T1.3, T1.4 |
| T1.7 | Implement `get_options_positions()` | 2h | T1.1 |
| T1.8 | Implement `close_options_position()` | 2h | T1.7 |
| T1.9 | Unit tests with mocked Alpaca client | 4h | T1.5, T1.6 |

### Phase 2: Integration (Priority: P1)

| Task ID | Description | Effort | Dependencies |
|---------|-------------|--------|--------------|
| T2.1 | Add schemas to `parrot/finance/schemas.py` | 1h | None |
| T2.2 | Update CIO prompt with options strategies | 2h | T1.5, T1.6 |
| T2.3 | Add options tools to CIO toolset | 1h | T2.2 |
| T2.4 | Add Risk Analyst options tools | 3h | T1.7 |
| T2.5 | Integration tests with paper trading | 4h | T1.9 |

### Phase 3: Polish (Priority: P2)

| Task ID | Description | Effort | Dependencies |
|---------|-------------|--------|--------------|
| T3.1 | Greeks caching for performance | 2h | T1.2 |
| T3.2 | Position P&L tracking | 2h | T1.7 |
| T3.3 | Documentation and examples | 2h | T2.5 |

---

## 5. Acceptance Criteria

### Functional Requirements

- [ ] `place_iron_butterfly()` places a valid 4-leg order on Alpaca paper
- [ ] `place_iron_condor()` places a valid 4-leg order on Alpaca paper
- [ ] Strike selection respects delta targets and liquidity thresholds
- [ ] Risk validation rejects orders exceeding `max_risk_pct` of buying power
- [ ] `get_options_positions()` returns current positions with Greeks
- [ ] `close_options_position()` closes all 4 legs atomically
- [ ] CIO can recommend and execute options strategies based on IV/market conditions

### Non-Functional Requirements

- [ ] All toolkit methods are async
- [ ] Paper trading is default (production requires explicit opt-in)
- [ ] Execution latency < 2 seconds for order placement
- [ ] Greeks refresh rate configurable (default: on-demand)
- [ ] Comprehensive logging for order lifecycle

### Testing Requirements

- [ ] Unit tests for StrategyFactory (leg structure validation)
- [ ] Unit tests for StrikeSelectionEngine (ATM, delta, liquidity)
- [ ] Integration tests with Alpaca paper trading
- [ ] Mock tests for error handling (insufficient BP, illiquid strikes)

---

## 6. Dependencies

### External Libraries

| Package | Version | Purpose |
|---------|---------|---------|
| `alpaca-py` | >=0.10.0 | Trading and Data API |
| `numpy` | existing | Numerical calculations |
| `pandas` | existing | Options chain DataFrames |

### Internal Dependencies

| Component | Purpose |
|-----------|---------|
| `AbstractToolkit` | Base class |
| `OptionsAnalyticsToolkit` | Greeks calculations (FEAT-015) |
| `AlpacaWriteToolkit` | Config patterns, client setup |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca API key |
| `ALPACA_SECRET_KEY` | Alpaca secret key |
| `ALPACA_PAPER` | Paper trading flag (default: true) |

---

## 7. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| Early assignment on short legs | High | Low | Monitor ex-dividend dates, close before assignment risk |
| Illiquid strikes causing poor fills | Medium | Medium | Enforce OI/spread thresholds, use limit orders |
| IV spike after entry | Medium | Medium | Position sizing limits, Greeks monitoring |
| Multi-leg order partial fill | High | Low | Alpaca handles atomically; verify with paper tests |
| API rate limits on Greeks refresh | Low | Medium | Implement caching, batch requests |

---

## 8. Future Enhancements (Out of Scope)

- Auto-management daemon (close at 50% profit, roll at 21 DTE)
- Additional strategies: verticals, calendars, diagonals, straddles, strangles
- Backtesting framework with historical options data
- IBKR options execution toolkit
- Volatility surface visualization

---

## 9. References

- Alpaca Iron Butterfly Guide: https://alpaca.markets/learn/iron-butterfly
- Alpaca Iron Condor vs Butterfly: https://alpaca.markets/learn/iron-condor-vs-iron-butterfly
- Alpaca Multi-Leg Orders: https://docs.alpaca.markets/docs/multi-leg-orders
- Prior Exploration: `sdd/proposals/options-strategies-iron-spreads.brainstorm.md`
- Related Spec: `sdd/specs/options-analytics.spec.md` (FEAT-015)
