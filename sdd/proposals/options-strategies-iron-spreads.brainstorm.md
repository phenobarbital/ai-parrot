# Brainstorm: Iron Butterfly & Iron Condor Strategies

**Date**: 2026-03-04
**Author**: Claude
**Status**: exploration
**Recommended Option**: Option B (AlpacaOptionsToolkit with Strategy Patterns)
**Sources**:
- https://alpaca.markets/learn/iron-butterfly
- https://alpaca.markets/learn/iron-condor-vs-iron-butterfly

---

## Problem Statement

El sistema de Finance actualmente soporta órdenes simples de stocks/ETFs y crypto a través de `AlpacaWriteToolkit` y `BinanceWriteToolkit`. Sin embargo, **no existe capacidad para ejecutar estrategias de opciones multi-leg** como Iron Butterfly o Iron Condor.

Estas estrategias son fundamentales para:
1. **Generar income en mercados laterales** — ambas estrategias son theta-positive (benefician del time decay)
2. **Risk-defined trades** — max profit y max loss conocidos de antemano
3. **Volatility plays** — Short Iron Butterfly para IV crush, Long Iron Butterfly para vol expansion

**Quién está afectado:**
- **CIO Agent** — No puede elegir estrategias de opciones para el portfolio
- **Risk Analyst** — No puede evaluar Greeks de posiciones de opciones
- **Executor** — No tiene herramientas para colocar órdenes multi-leg
- **Portfolio** — Limita las oportunidades de generación de alpha en mercados range-bound

---

## Technical Background

### Iron Butterfly

Una estrategia de 4 legs con strikes ATM en el centro:

```
Legs:                          P&L Profile:
Long Put  @ K1 (OTM)                 |     /\
Short Put @ K2 (ATM)        Max Profit|----/  \----
Short Call @ K2 (ATM)                 |   /    \
Long Call @ K3 (OTM)                  |  /      \
                            Max Loss  |-/        \-
                                      K1   K2    K3
```

**Configuración (underlying @ $100):**
| Leg | Strike | Premium |
|-----|--------|---------|
| Long Put | $95 | -$0.50 |
| Short Put | $100 | +$2.00 |
| Short Call | $100 | +$2.00 |
| Long Call | $105 | -$0.50 |
| **Net Credit** | — | **$3.00** |

**Risk/Reward:**
- Max Profit: $300 (net credit × 100)
- Max Loss: $200 (spread width $5 - credit $3) × 100
- Breakevens: $97.00, $103.00

### Iron Condor

Una estrategia de 4 legs con shorts OTM (wider profit zone):

```
Legs:                          P&L Profile:
Long Put  @ K1 (far OTM)              |    /‾‾‾‾\
Short Put @ K2 (OTM)        Max Profit|---/      \---
Short Call @ K3 (OTM)                 |  /        \
Long Call @ K4 (far OTM)    Max Loss  |-/          \-
                                      K1  K2    K3  K4
```

**Risk/Reward (típico):**
- Max Profit: Menor que Iron Butterfly
- Max Loss: Mayor que Iron Butterfly
- Breakevens: Más separados (wider profit zone)

### Comparación

| Aspecto | Iron Butterfly | Iron Condor |
|---------|---------------|-------------|
| Short Strikes | ATM | OTM |
| Profit Zone | Narrow | Wide |
| Max Credit | Higher | Lower |
| Win Rate | Lower | Higher |
| Gamma Risk | Higher | Lower |
| Best For | Pin risk, high IV | Range-bound, consistent income |

---

## Constraints & Requirements

### Funcionales
- **Multi-leg order execution** — 4 legs en una sola orden atómica
- **Greeks calculation** — Delta, Gamma, Theta, Vega para evaluación de riesgo
- **Strategy selection** — CIO debe poder elegir entre Iron Butterfly / Iron Condor
- **Automatic strike selection** — Basado en IV, delta targets, y OI thresholds
- **Position management** — Monitoreo y cierre de posiciones existentes

### No Funcionales
- **Paper trading primero** — Alpaca paper environment antes de producción
- **Risk limits** — Max loss como % de buying power (5% default)
- **Liquidity filters** — Open Interest ≥ 50, bid-ask spread < 10%
- **Expiration constraints** — 14-42 DTE para balance theta/gamma

### Técnicos
- **Alpaca Trading API** — `alpaca-py` para órdenes
- **Alpaca Data API** — Options snapshots con Greeks
- **Async-first** — Todas las operaciones deben ser async
- **Pydantic schemas** — Validación de inputs/outputs

---

## Options Explored

### Option A: Standalone Functions (Minimal)

Implementar funciones standalone para cada estrategia sin abstracción de toolkit.

**Approach:**
```python
# parrot/finance/tools/options_strategies.py
from parrot.tools import tool

@tool()
async def place_iron_butterfly(
    underlying: str,
    expiration_days: int = 30,
    risk_percent: float = 5.0,
) -> dict:
    """Place a short iron butterfly on the underlying."""
    # Direct Alpaca API calls
    ...

@tool()
async def place_iron_condor(
    underlying: str,
    expiration_days: int = 30,
    risk_percent: float = 5.0,
) -> dict:
    """Place a short iron condor on the underlying."""
    ...
```

**Pros:**
- Implementación rápida
- Sin cambios a la arquitectura existente
- Fácil de testear en aislamiento

**Cons:**
- Duplicación de código entre estrategias
- Sin abstracción para nuevas estrategias futuras
- Greeks calculation duplicado
- Difícil de extender (straddles, strangles, verticals)

**Effort:** Low (2-3 días)

---

### Option B: AlpacaOptionsToolkit (Recommended)

Crear un toolkit completo para opciones con patrones de estrategia reutilizables.

**Approach:**

```python
# parrot/finance/tools/alpaca_options.py
from parrot.tools.toolkit import AbstractToolkit

class OptionsStrategyLeg(BaseModel):
    """Single leg of an options strategy."""
    contract_type: Literal["call", "put"]
    strike: float
    side: Literal["buy", "sell"]
    ratio: int = 1

class OptionsStrategy(BaseModel):
    """Abstract options strategy configuration."""
    name: str
    legs: list[OptionsStrategyLeg]
    max_profit: float | None = None
    max_loss: float | None = None
    breakevens: list[float] = []

class AlpacaOptionsToolkit(AbstractToolkit):
    """Toolkit for multi-leg options strategies on Alpaca."""

    def __init__(self, paper: bool = True):
        self.client = TradingClient(
            api_key=config.get("ALPACA_API_KEY"),
            secret_key=config.get("ALPACA_SECRET_KEY"),
            paper=paper,
        )
        self.data_client = OptionHistoricalDataClient(...)

    async def get_options_chain(
        self,
        underlying: str,
        expiration_range: tuple[int, int] = (14, 42),
    ) -> pd.DataFrame:
        """Fetch options chain with Greeks."""
        ...

    async def calculate_strategy_metrics(
        self,
        strategy: OptionsStrategy,
        underlying_price: float,
    ) -> dict:
        """Calculate max profit, max loss, breakevens, Greeks."""
        ...

    @tool_schema(PlaceIronButterflyInput)
    async def place_iron_butterfly(
        self,
        underlying: str,
        expiration_days: int = 30,
        wing_width: float = 5.0,
        max_risk_pct: float = 5.0,
    ) -> dict:
        """
        Place a short iron butterfly strategy.

        The iron butterfly profits from low volatility and time decay.
        Short strikes are placed at-the-money (ATM).

        Args:
            underlying: Ticker symbol (e.g., 'SPY', 'AAPL')
            expiration_days: Target days to expiration (14-42)
            wing_width: Distance from ATM for long strikes
            max_risk_pct: Maximum risk as % of buying power

        Returns:
            Order details including max profit, max loss, breakevens
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
    ) -> dict:
        """
        Place a short iron condor strategy.

        The iron condor profits from range-bound markets with wider
        profit zone than iron butterfly but lower credit.

        Args:
            underlying: Ticker symbol
            expiration_days: Target DTE
            short_delta: Target delta for short strikes (0.20-0.40)
            wing_width: Distance for long strikes
            max_risk_pct: Maximum risk as % of buying power
        """
        ...

    @tool_schema(CloseOptionsPositionInput)
    async def close_options_position(
        self,
        position_id: str,
        close_type: Literal["market", "limit"] = "market",
        limit_price: float | None = None,
    ) -> dict:
        """Close an existing multi-leg options position."""
        ...

    @tool_schema(GetOptionsPositionsInput)
    async def get_options_positions(
        self,
        underlying: str | None = None,
    ) -> list[dict]:
        """Get current options positions with P&L and Greeks."""
        ...
```

**Strategy Factory Pattern:**

```python
class StrategyFactory:
    """Factory for building options strategies."""

    @staticmethod
    def iron_butterfly(
        underlying_price: float,
        wing_width: float = 5.0,
    ) -> OptionsStrategy:
        """Build an iron butterfly centered at underlying price."""
        atm_strike = round(underlying_price)
        return OptionsStrategy(
            name="iron_butterfly",
            legs=[
                OptionsStrategyLeg(contract_type="put", strike=atm_strike - wing_width, side="buy"),
                OptionsStrategyLeg(contract_type="put", strike=atm_strike, side="sell"),
                OptionsStrategyLeg(contract_type="call", strike=atm_strike, side="sell"),
                OptionsStrategyLeg(contract_type="call", strike=atm_strike + wing_width, side="buy"),
            ],
        )

    @staticmethod
    def iron_condor(
        underlying_price: float,
        short_put_strike: float,
        short_call_strike: float,
        wing_width: float = 5.0,
    ) -> OptionsStrategy:
        """Build an iron condor with specified short strikes."""
        return OptionsStrategy(
            name="iron_condor",
            legs=[
                OptionsStrategyLeg(contract_type="put", strike=short_put_strike - wing_width, side="buy"),
                OptionsStrategyLeg(contract_type="put", strike=short_put_strike, side="sell"),
                OptionsStrategyLeg(contract_type="call", strike=short_call_strike, side="sell"),
                OptionsStrategyLeg(contract_type="call", strike=short_call_strike + wing_width, side="buy"),
            ],
        )
```

**Pros:**
- Extensible para más estrategias (straddles, strangles, calendars, diagonals)
- Greeks centralizados en un lugar
- Pattern Factory permite composición de estrategias
- Integración limpia con CIO decision-making
- Testeable con mocks de Alpaca client

**Cons:**
- Mayor esfuerzo inicial
- Requiere más testing (multi-leg orders son complejos)
- Necesita manejo de casos edge (splits, dividends, assignments)

**Effort:** Medium (5-7 días)

**Libraries / Tools:**
| Package | Purpose | Notes |
|---------|---------|-------|
| `alpaca-py` | Trading & Data API | Already installed |
| `py_vollib` | Black-Scholes Greeks | For validation |
| `numpy` | Numerical ops | Already installed |

---

### Option C: Full Options Engine con Strategy Optimizer

Engine completo con backtesting, optimización de strikes, y auto-management.

**Approach:**

Además de lo de Option B, incluir:
- **Strategy Optimizer** — Selecciona strikes óptimos basado en IV percentile, expected move, y historical win rate
- **Auto-management** — Cierra posiciones automáticamente al hit target profit (50-75% of max)
- **Backtesting** — Simula estrategias sobre datos históricos
- **Position Sizing** — Kelly criterion o fixed fractional basado en edge histórico

```python
class OptionsStrategyOptimizer:
    """Optimize strategy parameters based on market conditions."""

    async def find_optimal_iron_butterfly(
        self,
        underlying: str,
        iv_percentile_threshold: float = 50.0,
        target_ror: float = 0.30,  # 30% return on risk
    ) -> OptionsStrategy | None:
        """
        Find optimal iron butterfly if conditions are favorable.

        Returns None if IV percentile is below threshold or no
        suitable expiration exists.
        """
        ...

    async def should_close_position(
        self,
        position: OptionsPosition,
        current_pnl_pct: float,
        days_to_expiration: int,
    ) -> tuple[bool, str]:
        """
        Determine if position should be closed.

        Rules:
        - Close at 50% max profit
        - Close at 21 DTE (gamma risk increases)
        - Close if underlying breaches breakeven
        """
        ...

class OptionsPositionMonitor:
    """Monitor and auto-manage options positions."""

    async def run_monitoring_loop(self, interval: int = 60):
        """Continuously monitor positions and trigger closes."""
        while self._running:
            positions = await self.toolkit.get_options_positions()
            for pos in positions:
                should_close, reason = await self.optimizer.should_close_position(pos)
                if should_close:
                    await self.toolkit.close_options_position(pos.id)
                    self.logger.info(f"Closed {pos.symbol}: {reason}")
            await asyncio.sleep(interval)
```

**Pros:**
- Sistema completamente autónomo
- Backtesting permite validar estrategias
- Auto-management reduce intervención manual
- Optimización mejora edge

**Cons:**
- Complejidad significativa
- Requiere datos históricos de opciones (costoso)
- Backtesting de opciones es complejo (IV surface, early assignment)
- Over-engineering para MVP

**Effort:** High (2-3 semanas)

---

## Integration with CIO Agent

El CIO agent necesita poder decidir cuándo usar estas estrategias:

```python
# parrot/finance/prompts.py - CIO prompt addition

CIO_OPTIONS_STRATEGIES = """
<options_strategies>
You have access to options strategy tools for generating income in range-bound markets:

1. **Iron Butterfly** — Use when:
   - IV percentile > 50 (high IV expected to decrease)
   - Expecting price to stay near current level
   - After earnings or catalysts (IV crush play)
   - Higher credit but narrower profit zone

2. **Iron Condor** — Use when:
   - Range-bound market with clear support/resistance
   - Want wider margin of error
   - Lower credit but higher probability of profit

Tool Usage:
- `place_iron_butterfly(underlying, expiration_days, wing_width, max_risk_pct)`
- `place_iron_condor(underlying, expiration_days, short_delta, wing_width, max_risk_pct)`
- `get_options_positions()` — Check existing options positions
- `close_options_position(position_id)` — Close before expiration

Risk Limits:
- Maximum 5% of portfolio in any single options strategy
- Maximum 15% total options exposure
- Always check buying power before placing trades
</options_strategies>
"""
```

---

## Schemas

```python
# parrot/finance/schemas.py additions

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
    """Multi-leg options position."""
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

    # Aggregated Greeks
    position_delta: float | None = None
    position_gamma: float | None = None
    position_theta: float | None = None
    position_vega: float | None = None

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

## Risk Management Integration

El Risk Analyst debe evaluar posiciones de opciones:

```python
# Addition to risk analyst tools

@tool()
async def analyze_options_position_risk(
    position_id: str,
) -> dict:
    """
    Analyze risk metrics for an options position.

    Returns:
    - Greeks exposure (delta, gamma, theta, vega)
    - P&L at various underlying price levels
    - Days to expiration risk (gamma acceleration)
    - Probability of profit (based on current IV)
    - Early assignment risk (for short legs)
    """
    ...

@tool()
async def get_portfolio_options_exposure(self) -> dict:
    """
    Get aggregate options exposure for the portfolio.

    Returns:
    - Total options premium at risk
    - Net delta exposure
    - Net vega exposure (volatility risk)
    - Expiration calendar (positions by DTE)
    - Concentration risk by underlying
    """
    ...
```

---

## Implementation Roadmap

### Phase 1: Core Toolkit (Option B - Recommended)
1. Create `AlpacaOptionsToolkit` with basic structure
2. Implement `get_options_chain()` with Greeks
3. Implement `place_iron_butterfly()`
4. Implement `place_iron_condor()`
5. Add position monitoring tools
6. Unit tests with mocked Alpaca client

### Phase 2: CIO Integration
1. Add options strategy tools to CIO toolset
2. Update CIO prompt with options decision criteria
3. Add `OptionsStrategyRecommendation` schema
4. Integration tests with paper trading

### Phase 3: Risk Integration
1. Add options risk tools to Risk Analyst
2. Implement portfolio-level options exposure tracking
3. Add options positions to deliberation display

### Phase 4: (Future) Auto-Management
1. Position monitor daemon
2. Auto-close at profit targets
3. Roll forward mechanics
4. Backtesting framework

---

## Code from Alpaca Articles

### Core Dependencies
```python
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    OptionLegRequest,
    MarketOrderRequest,
    GetOptionContractsRequest
)
from alpaca.trading.enums import (
    OrderSide,
    OrderClass,
    TimeInForce,
    ContractType
)
from alpaca.data.requests import OptionSnapshotRequest
from alpaca.data.historical.option import OptionHistoricalDataClient
```

### Multi-Leg Order Execution
```python
# From Alpaca Iron Butterfly article
order_legs = [
    OptionLegRequest(symbol=long_put['symbol'], side=OrderSide.BUY, ratio_qty=1),
    OptionLegRequest(symbol=short_put['symbol'], side=OrderSide.SELL, ratio_qty=1),
    OptionLegRequest(symbol=short_call['symbol'], side=OrderSide.SELL, ratio_qty=1),
    OptionLegRequest(symbol=long_call['symbol'], side=OrderSide.BUY, ratio_qty=1)
]

req = MarketOrderRequest(
    qty=1,
    order_class=OrderClass.MLEG,  # Multi-leg order
    time_in_force=TimeInForce.DAY,
    legs=order_legs
)

order = trade_client.submit_order(req)
```

### Greeks from Snapshot
```python
def get_option_greeks(option_symbol: str) -> dict:
    """Get Greeks from Alpaca option snapshot."""
    req = OptionSnapshotRequest(symbol_or_symbols=option_symbol)
    snapshot = data_client.get_option_snapshot(req)

    return {
        'iv': snapshot.implied_volatility,
        'delta': snapshot.greeks.delta,
        'gamma': snapshot.greeks.gamma,
        'theta': snapshot.greeks.theta,
        'vega': snapshot.greeks.vega,
        'mid_price': (snapshot.latest_quote.bid_price +
                      snapshot.latest_quote.ask_price) / 2
    }
```

### Strike Selection Logic
```python
def find_atm_strike(options: list, underlying_price: float) -> dict:
    """Find the at-the-money strike."""
    return min(
        options,
        key=lambda x: abs(x['strike_price'] - underlying_price)
    )

def find_otm_strikes(options: list, underlying_price: float, target_delta: float) -> dict:
    """Find OTM strikes at target delta."""
    return min(
        options,
        key=lambda x: abs(abs(x['delta']) - target_delta)
    )
```

### Risk Validation
```python
def validate_risk(
    spread_width: float,
    premium_received: float,
    buying_power: float,
    max_risk_pct: float = 0.05
) -> bool:
    """Validate that max loss stays within risk limits."""
    max_loss = (spread_width - premium_received) * 100  # Per contract
    max_allowed = buying_power * max_risk_pct
    return max_loss <= max_allowed
```

---

## Testing Strategy

### Unit Tests
```python
# tests/test_alpaca_options_toolkit.py

@pytest.fixture
def mock_alpaca_client():
    """Mock Alpaca trading client."""
    with patch('parrot.finance.tools.alpaca_options.TradingClient') as mock:
        yield mock

class TestIronButterflyPlacement:
    async def test_places_four_legs(self, mock_alpaca_client):
        """Verify 4-leg order structure."""
        toolkit = AlpacaOptionsToolkit(paper=True)
        result = await toolkit.place_iron_butterfly("SPY", expiration_days=30)

        call_args = mock_alpaca_client.submit_order.call_args
        assert len(call_args.legs) == 4

    async def test_respects_risk_limit(self, mock_alpaca_client):
        """Verify risk limit enforcement."""
        toolkit = AlpacaOptionsToolkit(paper=True)
        # Setup mock to return high premium (would exceed risk)
        ...

        with pytest.raises(RiskLimitExceeded):
            await toolkit.place_iron_butterfly("SPY", max_risk_pct=0.01)
```

### Integration Tests (Paper Trading)
```python
@pytest.mark.integration
@pytest.mark.skipif(not ALPACA_PAPER_CONFIGURED, reason="Alpaca paper not configured")
class TestPaperTrading:
    async def test_full_iron_butterfly_lifecycle(self):
        """Place, monitor, and close an iron butterfly on paper."""
        toolkit = AlpacaOptionsToolkit(paper=True)

        # Place
        result = await toolkit.place_iron_butterfly("SPY", expiration_days=30)
        assert result['order_status'] in ['filled', 'accepted']

        # Check position
        positions = await toolkit.get_options_positions()
        assert len(positions) > 0

        # Close
        close_result = await toolkit.close_options_position(result['position_id'])
        assert close_result['status'] == 'closed'
```

---

## Summary

| Option | Effort | Extensibility | Risk | Recommendation |
|--------|--------|---------------|------|----------------|
| A: Standalone Functions | Low | Low | Low | Quick MVP only |
| **B: AlpacaOptionsToolkit** | **Medium** | **High** | **Medium** | **Recommended** |
| C: Full Options Engine | High | Very High | High | Future enhancement |

**Recomendación:** Implementar **Option B** como base sólida que permite:
1. CIO tome decisiones sobre estrategias de opciones
2. Executor coloque órdenes multi-leg atómicas
3. Risk Analyst evalúe Greeks y exposición
4. Extensión futura a más estrategias sin rewrite

El código de Alpaca está bien documentado y la API de multi-leg orders (`OrderClass.MLEG`) está madura. El mayor riesgo es el manejo de edge cases (assignments, splits, illiquidity) que requieren testing exhaustivo en paper antes de producción.
