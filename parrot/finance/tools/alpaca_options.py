"""Alpaca options toolkit for multi-leg options strategy execution.

This toolkit provides tools for trading options on Alpaca, including:
- Options chain retrieval with Greeks
- Multi-leg strategy placement (Iron Butterfly, Iron Condor)
- Position management and P&L tracking

Environment Variables:
    ALPACA_TRADING_API_KEY: Alpaca trading API key
    ALPACA_TRADING_API_SECRET: Alpaca trading API secret
    ALPACA_PCB_PAPER: Set to True for paper trading (default: True)

Usage:
    toolkit = AlpacaOptionsToolkit(paper=True)
    tools = toolkit.get_tools()
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from navconfig import config
from navconfig.logging import logging
from pydantic import BaseModel, Field

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, OptionLegRequest
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionSnapshotRequest
from alpaca.common.exceptions import APIError

from ...tools.toolkit import AbstractToolkit
from ...tools.decorators import tool_schema
from .strike_selection import StrikeSelectionEngine, StrikeSelectionError


class AlpacaOptionsError(RuntimeError):
    """Raised when an Alpaca options operation fails."""


# =============================================================================
# Greeks Caching
# =============================================================================


class GreeksCache:
    """TTL-based cache for options Greeks snapshots.

    Caches individual option contract snapshots to reduce API calls.
    Greeks don't change rapidly, so caching for 1-5 minutes is acceptable.

    Attributes:
        ttl: Time-to-live in seconds for cached entries.
    """

    def __init__(self, ttl_seconds: int = 60):
        """Initialize the Greeks cache.

        Args:
            ttl_seconds: Time-to-live for cached entries (default: 60).
        """
        self.ttl = ttl_seconds
        self._cache: Dict[str, tuple[datetime, Dict[str, Any]]] = {}
        self._logger = logging.getLogger("GreeksCache")

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached data for a symbol if not expired.

        Args:
            symbol: Option symbol (OCC format).

        Returns:
            Cached data if valid, None if expired or not found.
        """
        if symbol in self._cache:
            ts, data = self._cache[symbol]
            if datetime.now() - ts < timedelta(seconds=self.ttl):
                self._logger.debug("Cache HIT for %s", symbol)
                return data
            del self._cache[symbol]
            self._logger.debug("Cache EXPIRED for %s", symbol)
        else:
            self._logger.debug("Cache MISS for %s", symbol)
        return None

    def set(self, symbol: str, data: Dict[str, Any]) -> None:
        """Store data in cache with current timestamp.

        Args:
            symbol: Option symbol (OCC format).
            data: Data to cache.
        """
        self._cache[symbol] = (datetime.now(), data)
        self._logger.debug("Cache SET for %s", symbol)

    def invalidate(self, symbol: str) -> None:
        """Remove a symbol from cache.

        Args:
            symbol: Option symbol to invalidate.
        """
        if self._cache.pop(symbol, None) is not None:
            self._logger.debug("Cache INVALIDATED for %s", symbol)

    def invalidate_by_underlying(self, underlying: str) -> int:
        """Invalidate all cached entries for an underlying symbol.

        Args:
            underlying: Underlying symbol (e.g., 'SPY').

        Returns:
            Number of entries invalidated.
        """
        underlying_upper = underlying.upper()
        to_remove = [
            sym for sym in self._cache
            if sym.startswith(underlying_upper)
        ]
        for sym in to_remove:
            del self._cache[sym]
        if to_remove:
            self._logger.debug(
                "Cache INVALIDATED %d entries for underlying %s",
                len(to_remove),
                underlying,
            )
        return len(to_remove)

    def clear(self) -> None:
        """Clear all cached entries."""
        count = len(self._cache)
        self._cache.clear()
        self._logger.debug("Cache CLEARED (%d entries)", count)

    @property
    def size(self) -> int:
        """Return current cache size."""
        return len(self._cache)


# =============================================================================
# Pydantic input schemas
# =============================================================================


class GetOptionsChainInput(BaseModel):
    """Input schema for get_options_chain tool."""

    underlying: str = Field(
        ...,
        description="Underlying symbol (e.g., 'SPY', 'AAPL').",
    )
    min_dte: int = Field(
        default=7,
        ge=0,
        description="Minimum days to expiration.",
    )
    max_dte: int = Field(
        default=45,
        ge=1,
        description="Maximum days to expiration.",
    )
    strike_range_pct: float = Field(
        default=10.0,
        gt=0,
        le=50,
        description="Strike range as % of underlying price (each side).",
    )


class PlaceIronButterflyInput(BaseModel):
    """Input schema for place_iron_butterfly tool."""

    underlying: str = Field(
        ...,
        description="Underlying symbol (e.g., 'SPY', 'AAPL').",
    )
    expiration_days: int = Field(
        default=30,
        ge=7,
        le=60,
        description="Target days to expiration (DTE).",
    )
    wing_width: float = Field(
        default=5.0,
        gt=0,
        description="Distance from ATM to wing strikes in dollars.",
    )
    quantity: int = Field(
        default=1,
        ge=1,
        description="Number of contracts to trade.",
    )
    max_risk_pct: float = Field(
        default=5.0,
        ge=1.0,
        le=20.0,
        description="Maximum risk as % of buying power.",
    )


class PlaceIronCondorInput(BaseModel):
    """Input schema for place_iron_condor tool."""

    underlying: str = Field(
        ...,
        description="Underlying symbol (e.g., 'SPY', 'AAPL').",
    )
    expiration_days: int = Field(
        default=30,
        ge=7,
        le=60,
        description="Target days to expiration (DTE).",
    )
    short_delta: float = Field(
        default=0.30,
        ge=0.15,
        le=0.45,
        description="Target delta for short strikes (e.g., 0.30 for 30-delta).",
    )
    wing_width: float = Field(
        default=5.0,
        gt=0,
        description="Distance from short strikes to wing strikes in dollars.",
    )
    quantity: int = Field(
        default=1,
        ge=1,
        description="Number of contracts to trade.",
    )
    max_risk_pct: float = Field(
        default=5.0,
        ge=1.0,
        le=20.0,
        description="Maximum risk as % of buying power.",
    )


class GetOptionsPositionsInput(BaseModel):
    """Input schema for get_options_positions tool."""

    underlying: Optional[str] = Field(
        default=None,
        description="Filter by underlying symbol (e.g., 'SPY'). None returns all.",
    )


class CloseOptionsPositionInput(BaseModel):
    """Input schema for close_options_position tool."""

    position_id: str = Field(
        ...,
        description="Position ID in format 'UNDERLYING_EXPIRATION' (e.g., 'SPY_2024-03-15').",
    )
    order_type: str = Field(
        default="market",
        description="Order type: 'market' for immediate close, 'limit' for target price.",
    )
    limit_credit: Optional[float] = Field(
        default=None,
        description="For limit orders, target net credit to receive. Required if order_type='limit'.",
    )


# =============================================================================
# Risk Analysis Input Schemas
# =============================================================================


class AnalyzeOptionsPortfolioRiskInput(BaseModel):
    """Input schema for analyze_options_portfolio_risk tool."""

    include_greeks: bool = Field(
        default=True,
        description="Include aggregate Greeks (delta, gamma, theta, vega).",
    )
    group_by_expiration: bool = Field(
        default=True,
        description="Group positions by expiration date bucket.",
    )
    group_by_underlying: bool = Field(
        default=True,
        description="Show concentration by underlying symbol.",
    )


class StressTestOptionsPositionsInput(BaseModel):
    """Input schema for stress_test_options_positions tool."""

    underlying_move_pct: float = Field(
        default=5.0,
        ge=1.0,
        le=20.0,
        description="Hypothetical underlying price move as percentage (e.g., 5.0 for ±5%).",
    )
    iv_change_pct: float = Field(
        default=20.0,
        ge=5.0,
        le=50.0,
        description="Hypothetical IV change as percentage (e.g., 20.0 for ±20%).",
    )
    position_id: Optional[str] = Field(
        default=None,
        description="Specific position to stress test. None tests all positions.",
    )


class GetPositionGreeksInput(BaseModel):
    """Input schema for get_position_greeks tool."""

    position_id: str = Field(
        ...,
        description="Position ID in format 'UNDERLYING_EXPIRATION' (e.g., 'SPY_2024-03-15').",
    )


class AlpacaOptionsToolkit(AbstractToolkit):
    """Options trading toolkit for Alpaca multi-leg strategies.

    Provides tools for:
    - Fetching options chains with Greeks
    - Placing Iron Butterfly and Iron Condor strategies
    - Managing options positions
    - Tracking P&L

    The toolkit initializes both a TradingClient (for order execution)
    and an OptionHistoricalDataClient (for options data and Greeks).

    Attributes:
        name: Toolkit identifier for registration.
        description: Human-readable toolkit description.
        paper: Whether to use paper trading (default: True).
    """

    name: str = "alpaca_options_toolkit"
    description: str = (
        "Execute multi-leg options strategies on Alpaca: "
        "Iron Butterfly, Iron Condor, position management."
    )

    def __init__(
        self,
        paper: bool = True,
        greeks_cache_ttl: int = 60,
        **kwargs,
    ):
        """Initialize the AlpacaOptionsToolkit.

        Args:
            paper: Use paper trading if True (default). Set False for live trading.
            greeks_cache_ttl: TTL in seconds for Greeks cache (default: 60).
            **kwargs: Additional arguments passed to AbstractToolkit.
        """
        super().__init__(**kwargs)
        self.logger = logging.getLogger("AlpacaOptionsToolkit")

        # API credentials
        self.api_key = (
            config.get("ALPACA_TRADING_API_KEY")
            or config.get("ALPACA_MARKETS_CLIENT_ID")
        )
        self.api_secret = (
            config.get("ALPACA_TRADING_API_SECRET")
            or config.get("ALPACA_MARKETS_CLIENT_SECRET")
        )

        # Paper trading configuration
        self.paper = paper if paper is not None else config.get(
            "ALPACA_PCB_PAPER", section="finance", fallback=True
        )
        self.base_url = config.get(
            "ALPACA_API_BASE_URL", section="finance", fallback=None
        )

        # Lazy-initialized clients
        self._trading_client: Optional[TradingClient] = None
        self._data_client: Optional[OptionHistoricalDataClient] = None

        # Greeks cache for reducing API calls
        self._greeks_cache = GreeksCache(ttl_seconds=greeks_cache_ttl)

        self.logger.info(
            "AlpacaOptionsToolkit initialized (paper=%s)", self.paper
        )

    @property
    def trading_client(self) -> TradingClient:
        """Lazy-initialize the TradingClient for order execution.

        Returns:
            Configured TradingClient instance.

        Raises:
            AlpacaOptionsError: If API credentials are not configured.
        """
        if self._trading_client is None:
            if not self.api_key or not self.api_secret:
                raise AlpacaOptionsError(
                    "ALPACA_TRADING_API_KEY / SECRET not configured. "
                    "Set these environment variables to use options trading."
                )
            kw: Dict[str, Any] = {}
            if self.base_url:
                kw["url_override"] = self.base_url
            self._trading_client = TradingClient(
                self.api_key,
                self.api_secret,
                paper=self.paper,
                **kw
            )
            self.logger.debug("TradingClient initialized (paper=%s)", self.paper)
        return self._trading_client

    @property
    def data_client(self) -> OptionHistoricalDataClient:
        """Lazy-initialize the OptionHistoricalDataClient for options data.

        Returns:
            Configured OptionHistoricalDataClient instance.

        Raises:
            AlpacaOptionsError: If API credentials are not configured.
        """
        if self._data_client is None:
            if not self.api_key or not self.api_secret:
                raise AlpacaOptionsError(
                    "ALPACA_TRADING_API_KEY / SECRET not configured. "
                    "Set these environment variables to fetch options data."
                )
            self._data_client = OptionHistoricalDataClient(
                self.api_key,
                self.api_secret
            )
            self.logger.debug("OptionHistoricalDataClient initialized")
        return self._data_client

    async def get_account(self) -> Dict[str, Any]:
        """Get the Alpaca trading account summary.

        Returns:
            Account details including buying power and equity.

        Raises:
            AlpacaOptionsError: If API call fails.
        """
        try:
            acct = await asyncio.to_thread(self.trading_client.get_account)
            return acct.model_dump()
        except APIError as exc:
            raise AlpacaOptionsError(f"Get account failed: {exc}") from exc

    async def _get_underlying_price(self, symbol: str) -> float:
        """Get the current price of the underlying asset.

        Args:
            symbol: Underlying symbol (e.g., 'SPY').

        Returns:
            Current price as float.
        """
        # Use trading client to get last trade price
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockLatestTradeRequest

        stock_client = StockHistoricalDataClient(self.api_key, self.api_secret)
        req = StockLatestTradeRequest(symbol_or_symbols=symbol)
        result = await asyncio.to_thread(stock_client.get_stock_latest_trade, req)

        if symbol in result:
            return float(result[symbol].price)
        raise AlpacaOptionsError(f"Could not get price for {symbol}")

    @tool_schema(GetOptionsChainInput)
    async def get_options_chain(
        self,
        underlying: str,
        min_dte: int = 7,
        max_dte: int = 45,
        strike_range_pct: float = 10.0,
    ) -> Dict[str, Any]:
        """Fetch options chain with Greeks for an underlying symbol.

        Retrieves all option contracts within the specified expiration
        and strike range, including real-time Greeks and quotes.

        Args:
            underlying: Underlying symbol (e.g., 'SPY', 'AAPL').
            min_dte: Minimum days to expiration (default: 7).
            max_dte: Maximum days to expiration (default: 45).
            strike_range_pct: Strike range as % of underlying price (default: 10%).

        Returns:
            Dictionary with:
            - underlying: Symbol name
            - underlying_price: Current price
            - calls: List of call contracts with Greeks
            - puts: List of put contracts with Greeks
            - expiration_dates: List of available expirations

        Raises:
            AlpacaOptionsError: If API call fails.
        """
        try:
            # Get underlying price for strike filtering
            underlying_price = await self._get_underlying_price(underlying.upper())

            # Calculate date range
            today = date.today()
            min_date = today + timedelta(days=min_dte)
            max_date = today + timedelta(days=max_dte)

            # Calculate strike range
            strike_offset = underlying_price * (strike_range_pct / 100)
            min_strike = underlying_price - strike_offset
            max_strike = underlying_price + strike_offset

            self.logger.debug(
                "Fetching options chain for %s: strikes %.2f-%.2f, DTE %d-%d",
                underlying,
                min_strike,
                max_strike,
                min_dte,
                max_dte,
            )

            # Fetch option chain using OptionChainRequest
            req = OptionChainRequest(
                underlying_symbol=underlying.upper(),
                expiration_date_gte=min_date,
                expiration_date_lte=max_date,
                strike_price_gte=min_strike,
                strike_price_lte=max_strike,
            )
            chain = await asyncio.to_thread(
                self.data_client.get_option_chain, req
            )

            # Process results
            calls: List[Dict[str, Any]] = []
            puts: List[Dict[str, Any]] = []
            expiration_dates: set = set()

            for symbol, snapshot in chain.items():
                # Parse option symbol to extract details
                # Format: AAPL240315C00170000
                contract_info = self._parse_option_symbol(symbol)
                if not contract_info:
                    continue

                contract_data = {
                    "symbol": symbol,
                    "underlying": contract_info["underlying"],
                    "expiration": contract_info["expiration"],
                    "strike": contract_info["strike"],
                    "contract_type": contract_info["contract_type"],
                    "bid": None,
                    "ask": None,
                    "bid_size": None,
                    "ask_size": None,
                    "iv": snapshot.implied_volatility,
                    "delta": None,
                    "gamma": None,
                    "theta": None,
                    "vega": None,
                    "rho": None,
                }

                # Add quote data if available
                if snapshot.latest_quote:
                    contract_data["bid"] = snapshot.latest_quote.bid_price
                    contract_data["ask"] = snapshot.latest_quote.ask_price
                    contract_data["bid_size"] = snapshot.latest_quote.bid_size
                    contract_data["ask_size"] = snapshot.latest_quote.ask_size

                # Add Greeks if available
                if snapshot.greeks:
                    contract_data["delta"] = snapshot.greeks.delta
                    contract_data["gamma"] = snapshot.greeks.gamma
                    contract_data["theta"] = snapshot.greeks.theta
                    contract_data["vega"] = snapshot.greeks.vega
                    contract_data["rho"] = snapshot.greeks.rho

                # Cache the contract data for reuse in get_position_greeks
                self._greeks_cache.set(symbol, contract_data)

                # Categorize by contract type
                if contract_info["contract_type"] == "call":
                    calls.append(contract_data)
                else:
                    puts.append(contract_data)

                expiration_dates.add(contract_info["expiration"])

            # Sort by expiration then strike
            calls.sort(key=lambda x: (x["expiration"], x["strike"]))
            puts.sort(key=lambda x: (x["expiration"], x["strike"]))

            return {
                "underlying": underlying.upper(),
                "underlying_price": underlying_price,
                "calls": calls,
                "puts": puts,
                "expiration_dates": sorted(list(expiration_dates)),
                "total_contracts": len(calls) + len(puts),
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Get options chain failed: {exc}"
            ) from exc

    def _parse_option_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Parse OCC option symbol format.

        OCC format: SYMBOL + YYMMDD + C/P + STRIKE (8 digits, no decimal)
        Example: AAPL240315C00170000 = AAPL March 15, 2024 $170 Call

        Args:
            symbol: OCC-formatted option symbol.

        Returns:
            Dictionary with underlying, expiration, strike, contract_type
            or None if parsing fails.
        """
        try:
            # Find where the date starts (6 digits before C/P indicator)
            # Symbol format varies, so find C or P that's followed by 8 digits
            for i in range(len(symbol) - 15, 0, -1):
                if symbol[i:i + 6].isdigit():
                    # Found date portion
                    underlying = symbol[:i]
                    date_str = symbol[i:i + 6]
                    contract_type_char = symbol[i + 6]
                    strike_str = symbol[i + 7:i + 15]

                    # Parse date (YYMMDD)
                    year = 2000 + int(date_str[:2])
                    month = int(date_str[2:4])
                    day = int(date_str[4:6])
                    expiration = f"{year}-{month:02d}-{day:02d}"

                    # Parse contract type
                    contract_type = "call" if contract_type_char == "C" else "put"

                    # Parse strike (8 digits, last 3 are decimals)
                    strike = float(strike_str) / 1000

                    return {
                        "underlying": underlying,
                        "expiration": expiration,
                        "strike": strike,
                        "contract_type": contract_type,
                    }

            return None
        except (ValueError, IndexError):
            self.logger.warning("Could not parse option symbol: %s", symbol)
            return None

    @tool_schema(PlaceIronButterflyInput)
    async def place_iron_butterfly(
        self,
        underlying: str,
        expiration_days: int = 30,
        wing_width: float = 5.0,
        quantity: int = 1,
        max_risk_pct: float = 5.0,
    ) -> Dict[str, Any]:
        """Place an Iron Butterfly options strategy.

        An Iron Butterfly is a neutral strategy that profits from low volatility.
        It consists of:
        - Long Put at ATM - wing_width
        - Short Put at ATM
        - Short Call at ATM (same strike)
        - Long Call at ATM + wing_width

        Maximum profit occurs when underlying closes exactly at the short strike.
        Maximum loss is limited to wing_width minus net credit received.

        Args:
            underlying: Underlying symbol (e.g., 'SPY', 'AAPL').
            expiration_days: Target DTE for expiration (default: 30).
            wing_width: Distance from ATM to wing strikes (default: 5.0).
            quantity: Number of contracts (default: 1).
            max_risk_pct: Maximum risk as % of buying power (default: 5.0).

        Returns:
            Dictionary with:
            - order_id: Alpaca order ID
            - strategy: "iron_butterfly"
            - underlying: Symbol
            - expiration: Expiration date
            - strikes: Dict with all 4 strike prices
            - net_credit: Estimated net credit received
            - max_profit: Maximum profit (net credit)
            - max_loss: Maximum loss (wing_width - credit)
            - breakevens: [lower, upper] breakeven prices
            - quantity: Number of contracts

        Raises:
            AlpacaOptionsError: If order fails or risk limits exceeded.
        """
        try:
            # Get account to check buying power
            account = await self.get_account()
            buying_power = float(account.get("buying_power", 0))

            # Get underlying price
            underlying_price = await self._get_underlying_price(underlying.upper())

            # Get options chain
            chain = await self.get_options_chain(
                underlying=underlying,
                min_dte=expiration_days - 7,
                max_dte=expiration_days + 7,
                strike_range_pct=15.0,
            )

            if not chain["calls"] or not chain["puts"]:
                raise AlpacaOptionsError(
                    f"No options found for {underlying} with DTE ~{expiration_days}"
                )

            # Use strike selection engine
            engine = StrikeSelectionEngine()

            # Find the best expiration (closest to target DTE)
            target_expiration = None
            min_diff = float("inf")
            for exp in chain["expiration_dates"]:
                # Parse expiration and calculate DTE
                from datetime import datetime
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                dte = (exp_date - date.today()).days
                diff = abs(dte - expiration_days)
                if diff < min_diff:
                    min_diff = diff
                    target_expiration = exp

            if not target_expiration:
                raise AlpacaOptionsError("No valid expiration found")

            # Select strikes for iron butterfly
            try:
                strikes = engine.select_iron_butterfly_strikes(
                    calls=chain["calls"],
                    puts=chain["puts"],
                    underlying_price=underlying_price,
                    wing_width=wing_width,
                    expiration=target_expiration,
                )
            except StrikeSelectionError as e:
                raise AlpacaOptionsError(f"Strike selection failed: {e}") from e

            # Calculate P&L metrics
            # Net credit = (short put mid + short call mid) - (long put mid + long call mid)
            short_put_mid = (strikes.short_put["bid"] + strikes.short_put["ask"]) / 2
            short_call_mid = (strikes.short_call["bid"] + strikes.short_call["ask"]) / 2
            long_put_mid = (strikes.long_put["bid"] + strikes.long_put["ask"]) / 2
            long_call_mid = (strikes.long_call["bid"] + strikes.long_call["ask"]) / 2

            net_credit = (short_put_mid + short_call_mid) - (long_put_mid + long_call_mid)
            net_credit_total = net_credit * 100 * quantity  # Per contract = 100 shares

            # Calculate actual wing width (discrete strikes might differ from requested)
            put_width = strikes.short_put["strike"] - strikes.long_put["strike"]
            call_width = strikes.long_call["strike"] - strikes.short_call["strike"]
            actual_wing_width = max(put_width, call_width)

            max_profit = net_credit_total
            max_loss = (actual_wing_width * 100 * quantity) - net_credit_total

            # Validate risk
            risk_pct = (max_loss / buying_power) * 100
            if risk_pct > max_risk_pct:
                raise AlpacaOptionsError(
                    f"Risk {risk_pct:.1f}% exceeds max {max_risk_pct}% of buying power. "
                    f"Max loss: ${max_loss:.2f}, Buying power: ${buying_power:.2f}"
                )

            # Calculate breakevens
            atm_strike = strikes.short_put["strike"]
            lower_breakeven = atm_strike - net_credit
            upper_breakeven = atm_strike + net_credit

            # Build MLEG order
            legs = [
                OptionLegRequest(
                    symbol=strikes.long_put["symbol"],
                    side=OrderSide.BUY,
                    ratio_qty=1,
                ),
                OptionLegRequest(
                    symbol=strikes.short_put["symbol"],
                    side=OrderSide.SELL,
                    ratio_qty=1,
                ),
                OptionLegRequest(
                    symbol=strikes.short_call["symbol"],
                    side=OrderSide.SELL,
                    ratio_qty=1,
                ),
                OptionLegRequest(
                    symbol=strikes.long_call["symbol"],
                    side=OrderSide.BUY,
                    ratio_qty=1,
                ),
            ]

            # Use LimitOrderRequest for multi-leg strategies to avoid slippage
            # limit_price for MLEG should be the net credit/debit
            order_request = LimitOrderRequest(
                symbol=underlying.upper(),
                qty=quantity,
                limit_price=round(net_credit, 2),
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                legs=legs,
            )

            self.logger.info(
                "Placing Iron Butterfly: %s @ %s, strikes: %s/%s/%s, qty=%d",
                underlying,
                target_expiration,
                strikes.long_put["strike"],
                atm_strike,
                strikes.long_call["strike"],
                quantity,
            )

            # Submit order
            order = await asyncio.to_thread(
                self.trading_client.submit_order, order_request
            )

            # Invalidate Greeks cache for this underlying after order placement
            self._greeks_cache.invalidate_by_underlying(underlying)

            return {
                "order_id": str(order.id),
                "status": str(order.status),
                "strategy": "iron_butterfly",
                "underlying": underlying.upper(),
                "expiration": target_expiration,
                "strikes": {
                    "long_put": strikes.long_put["strike"],
                    "short_put": strikes.short_put["strike"],
                    "short_call": strikes.short_call["strike"],
                    "long_call": strikes.long_call["strike"],
                },
                "net_credit": round(net_credit_total, 2),
                "max_profit": round(max_profit, 2),
                "max_loss": round(max_loss, 2),
                "breakevens": [round(lower_breakeven, 2), round(upper_breakeven, 2)],
                "quantity": quantity,
                "underlying_price": underlying_price,
                "paper": self.paper,
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Place Iron Butterfly failed: {exc}"
            ) from exc

    @tool_schema(PlaceIronCondorInput)
    async def place_iron_condor(
        self,
        underlying: str,
        expiration_days: int = 30,
        short_delta: float = 0.30,
        wing_width: float = 5.0,
        quantity: int = 1,
        max_risk_pct: float = 5.0,
    ) -> Dict[str, Any]:
        """Place an Iron Condor options strategy.

        An Iron Condor is a neutral strategy that profits from low volatility
        and range-bound underlying movement. It consists of:
        - Long Put at short_put_strike - wing_width
        - Short Put at OTM delta (e.g., -0.30)
        - Short Call at OTM delta (e.g., +0.30)
        - Long Call at short_call_strike + wing_width

        Maximum profit occurs when underlying closes between short strikes.
        Maximum loss is limited to wing_width minus net credit received.

        Args:
            underlying: Underlying symbol (e.g., 'SPY', 'AAPL').
            expiration_days: Target DTE for expiration (default: 30).
            short_delta: Target delta for short strikes (default: 0.30).
            wing_width: Distance from short strikes to wings (default: 5.0).
            quantity: Number of contracts (default: 1).
            max_risk_pct: Maximum risk as % of buying power (default: 5.0).

        Returns:
            Dictionary with:
            - order_id: Alpaca order ID
            - strategy: "iron_condor"
            - underlying: Symbol
            - expiration: Expiration date
            - strikes: Dict with all 4 strike prices
            - net_credit: Estimated net credit received
            - max_profit: Maximum profit (net credit)
            - max_loss: Maximum loss (wing_width - credit)
            - breakevens: [lower, upper] breakeven prices
            - quantity: Number of contracts

        Raises:
            AlpacaOptionsError: If order fails or risk limits exceeded.
        """
        try:
            # Get account to check buying power
            account = await self.get_account()
            buying_power = float(account.get("buying_power", 0))

            # Get underlying price
            underlying_price = await self._get_underlying_price(underlying.upper())

            # Get options chain
            chain = await self.get_options_chain(
                underlying=underlying,
                min_dte=expiration_days - 7,
                max_dte=expiration_days + 7,
                strike_range_pct=20.0,  # Wider range for condor
            )

            if not chain["calls"] or not chain["puts"]:
                raise AlpacaOptionsError(
                    f"No options found for {underlying} with DTE ~{expiration_days}"
                )

            # Use strike selection engine
            engine = StrikeSelectionEngine()

            # Find the best expiration (closest to target DTE)
            target_expiration = None
            min_diff = float("inf")
            for exp in chain["expiration_dates"]:
                from datetime import datetime
                exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
                dte = (exp_date - date.today()).days
                diff = abs(dte - expiration_days)
                if diff < min_diff:
                    min_diff = diff
                    target_expiration = exp

            if not target_expiration:
                raise AlpacaOptionsError("No valid expiration found")

            # Select strikes for iron condor
            try:
                strikes = engine.select_iron_condor_strikes(
                    calls=chain["calls"],
                    puts=chain["puts"],
                    underlying_price=underlying_price,
                    short_delta=short_delta,
                    wing_width=wing_width,
                    expiration=target_expiration,
                )
            except StrikeSelectionError as e:
                raise AlpacaOptionsError(f"Strike selection failed: {e}") from e

            # Validate OTM condition
            if not (strikes.short_put["strike"] < underlying_price < strikes.short_call["strike"]):
                raise AlpacaOptionsError(
                    f"Invalid condor: short strikes must be OTM. "
                    f"Put {strikes.short_put['strike']} < "
                    f"Underlying {underlying_price} < "
                    f"Call {strikes.short_call['strike']}"
                )

            # Calculate P&L metrics
            short_put_mid = (strikes.short_put["bid"] + strikes.short_put["ask"]) / 2
            short_call_mid = (strikes.short_call["bid"] + strikes.short_call["ask"]) / 2
            long_put_mid = (strikes.long_put["bid"] + strikes.long_put["ask"]) / 2
            long_call_mid = (strikes.long_call["bid"] + strikes.long_call["ask"]) / 2

            net_credit = (short_put_mid + short_call_mid) - (long_put_mid + long_call_mid)
            net_credit_total = net_credit * 100 * quantity

            # Calculate actual wing width (discrete strikes might differ from requested)
            put_width = strikes.short_put["strike"] - strikes.long_put["strike"]
            call_width = strikes.long_call["strike"] - strikes.short_call["strike"]
            actual_wing_width = max(put_width, call_width)

            max_profit = net_credit_total
            max_loss = (actual_wing_width * 100 * quantity) - net_credit_total

            # Validate risk
            risk_pct = (max_loss / buying_power) * 100
            if risk_pct > max_risk_pct:
                raise AlpacaOptionsError(
                    f"Risk {risk_pct:.1f}% exceeds max {max_risk_pct}% of buying power. "
                    f"Max loss: ${max_loss:.2f}, Buying power: ${buying_power:.2f}"
                )

            # Calculate breakevens
            lower_breakeven = strikes.short_put["strike"] - net_credit
            upper_breakeven = strikes.short_call["strike"] + net_credit

            # Build MLEG order
            legs = [
                OptionLegRequest(
                    symbol=strikes.long_put["symbol"],
                    side=OrderSide.BUY,
                    ratio_qty=1,
                ),
                OptionLegRequest(
                    symbol=strikes.short_put["symbol"],
                    side=OrderSide.SELL,
                    ratio_qty=1,
                ),
                OptionLegRequest(
                    symbol=strikes.short_call["symbol"],
                    side=OrderSide.SELL,
                    ratio_qty=1,
                ),
                OptionLegRequest(
                    symbol=strikes.long_call["symbol"],
                    side=OrderSide.BUY,
                    ratio_qty=1,
                ),
            ]

            # Use LimitOrderRequest for multi-leg strategies to avoid slippage
            # limit_price for MLEG should be the net credit/debit
            order_request = LimitOrderRequest(
                symbol=underlying.upper(),
                qty=quantity,
                limit_price=round(net_credit, 2),
                order_class=OrderClass.MLEG,
                time_in_force=TimeInForce.DAY,
                legs=legs,
            )

            self.logger.info(
                "Placing Iron Condor: %s @ %s, strikes: %s/%s/%s/%s, delta=%.2f, qty=%d",
                underlying,
                target_expiration,
                strikes.long_put["strike"],
                strikes.short_put["strike"],
                strikes.short_call["strike"],
                strikes.long_call["strike"],
                short_delta,
                quantity,
            )

            # Submit order
            order = await asyncio.to_thread(
                self.trading_client.submit_order, order_request
            )

            # Invalidate Greeks cache for this underlying after order placement
            self._greeks_cache.invalidate_by_underlying(underlying)

            return {
                "order_id": str(order.id),
                "status": str(order.status),
                "strategy": "iron_condor",
                "underlying": underlying.upper(),
                "expiration": target_expiration,
                "strikes": {
                    "long_put": strikes.long_put["strike"],
                    "short_put": strikes.short_put["strike"],
                    "short_call": strikes.short_call["strike"],
                    "long_call": strikes.long_call["strike"],
                },
                "short_delta": short_delta,
                "net_credit": round(net_credit_total, 2),
                "max_profit": round(max_profit, 2),
                "max_loss": round(max_loss, 2),
                "breakevens": [round(lower_breakeven, 2), round(upper_breakeven, 2)],
                "quantity": quantity,
                "underlying_price": underlying_price,
                "paper": self.paper,
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Place Iron Condor failed: {exc}"
            ) from exc

    @tool_schema(GetOptionsPositionsInput)
    async def get_options_positions(
        self,
        underlying: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get current options positions with Greeks and P&L.

        Retrieves all open options positions from Alpaca, groups them by
        strategy (identifying butterflies, condors, spreads), and calculates
        current P&L for each position.

        Args:
            underlying: Optional filter by underlying symbol. None returns all.

        Returns:
            Dictionary with:
            - positions: List of position dicts with legs, P&L, Greeks
            - total_positions: Number of positions
            - total_pnl: Aggregate P&L across all positions

        Raises:
            AlpacaOptionsError: If API call fails.
        """
        try:
            # Get all positions
            all_positions = await asyncio.to_thread(
                self.trading_client.get_all_positions
            )

            # Filter to options positions (symbols match OCC format)
            options_positions = []
            for pos in all_positions:
                symbol = pos.symbol
                parsed = self._parse_option_symbol(symbol)
                if parsed:
                    # Apply underlying filter if specified
                    if underlying and parsed["underlying"].upper() != underlying.upper():
                        continue
                    options_positions.append({
                        "raw_position": pos,
                        "parsed": parsed,
                    })

            if not options_positions:
                return {
                    "positions": [],
                    "total_positions": 0,
                    "total_pnl": 0.0,
                }

            # Get current snapshots for all options (use cache where available)
            symbols = [p["raw_position"].symbol for p in options_positions]
            snapshots: Dict[str, Any] = {}
            symbols_to_fetch: List[str] = []

            # Check cache first for each symbol
            for sym in symbols:
                cached = self._greeks_cache.get(sym)
                if cached:
                    snapshots[sym] = cached
                else:
                    symbols_to_fetch.append(sym)

            # Fetch only uncached symbols from API
            if symbols_to_fetch:
                try:
                    req = OptionSnapshotRequest(symbol_or_symbols=symbols_to_fetch)
                    fetched = await asyncio.to_thread(
                        self.data_client.get_option_snapshot, req
                    )
                    # Cache and merge fetched results
                    for sym, snapshot in fetched.items():
                        snapshots[sym] = snapshot
                        # Cache the raw snapshot for future use
                        self._greeks_cache.set(sym, snapshot)
                except APIError as e:
                    self.logger.warning("Could not fetch option snapshots: %s", e)

            # Group positions by underlying + expiration
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for pos_data in options_positions:
                pos = pos_data["raw_position"]
                parsed = pos_data["parsed"]
                key = f"{parsed['underlying']}_{parsed['expiration']}"

                if key not in grouped:
                    grouped[key] = []

                # Build leg data
                leg = {
                    "symbol": pos.symbol,
                    "underlying": parsed["underlying"],
                    "expiration": parsed["expiration"],
                    "strike": parsed["strike"],
                    "contract_type": parsed["contract_type"],
                    "quantity": int(pos.qty),
                    "side": "long" if float(pos.qty) > 0 else "short",
                    "entry_price": float(pos.avg_entry_price),
                    "current_price": float(pos.current_price) if pos.current_price else None,
                    "market_value": float(pos.market_value) if pos.market_value else None,
                    "unrealized_pnl": float(pos.unrealized_pl) if pos.unrealized_pl else None,
                    "unrealized_pnl_pct": float(pos.unrealized_plpc) if pos.unrealized_plpc else None,
                }

                # Add Greeks from snapshot (handle both cached dict and API object)
                snapshot = snapshots.get(pos.symbol)
                if snapshot:
                    if isinstance(snapshot, dict):
                        # Cached dict from get_options_chain
                        leg["iv"] = snapshot.get("iv")
                        leg["delta"] = snapshot.get("delta")
                        leg["gamma"] = snapshot.get("gamma")
                        leg["theta"] = snapshot.get("theta")
                        leg["vega"] = snapshot.get("vega")
                        leg["bid"] = snapshot.get("bid")
                        leg["ask"] = snapshot.get("ask")
                    else:
                        # API snapshot object
                        leg["iv"] = snapshot.implied_volatility
                        if snapshot.greeks:
                            leg["delta"] = snapshot.greeks.delta
                            leg["gamma"] = snapshot.greeks.gamma
                            leg["theta"] = snapshot.greeks.theta
                            leg["vega"] = snapshot.greeks.vega
                        if snapshot.latest_quote:
                            leg["bid"] = snapshot.latest_quote.bid_price
                            leg["ask"] = snapshot.latest_quote.ask_price

                grouped[key].append(leg)

            # Build position results
            positions = []
            total_pnl = 0.0

            for key, legs in grouped.items():
                underlying_sym, expiration = key.split("_", 1)

                # Detect strategy type
                strategy_type = self._detect_strategy_type(legs)

                # Calculate P&L metrics
                pnl_metrics = self._calculate_pnl_metrics(legs, strategy_type)
                total_pnl += pnl_metrics["unrealized_pnl"]

                # Calculate position Greeks (sum across legs)
                position_delta = sum(
                    (leg.get("delta", 0) or 0) * leg["quantity"]
                    for leg in legs
                )
                position_gamma = sum(
                    (leg.get("gamma", 0) or 0) * leg["quantity"]
                    for leg in legs
                )
                position_theta = sum(
                    (leg.get("theta", 0) or 0) * leg["quantity"]
                    for leg in legs
                )
                position_vega = sum(
                    (leg.get("vega", 0) or 0) * leg["quantity"]
                    for leg in legs
                )

                positions.append({
                    "position_id": key,
                    "underlying": underlying_sym,
                    "expiration": expiration,
                    "strategy_type": strategy_type,
                    "legs": legs,
                    # P&L metrics
                    "entry_credit": pnl_metrics["entry_credit"],
                    "current_value": pnl_metrics["current_value"],
                    "current_pnl": pnl_metrics["unrealized_pnl"],
                    "max_profit": pnl_metrics["max_profit"],
                    "max_loss": pnl_metrics["max_loss"],
                    "current_pnl_pct": pnl_metrics["current_pnl_pct"],
                    "pnl_vs_risk": pnl_metrics["pnl_vs_risk"],
                    "time_value_remaining_pct": pnl_metrics["time_value_remaining_pct"],
                    # Greeks
                    "position_delta": round(position_delta, 4),
                    "position_gamma": round(position_gamma, 4),
                    "position_theta": round(position_theta, 4),
                    "position_vega": round(position_vega, 4),
                })

            return {
                "positions": positions,
                "total_positions": len(positions),
                "total_pnl": round(total_pnl, 2),
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Get options positions failed: {exc}"
            ) from exc

    def _detect_strategy_type(self, legs: List[Dict[str, Any]]) -> str:
        """Detect the strategy type from leg structure.

        Args:
            legs: List of leg dicts with contract_type, strike, side.

        Returns:
            Strategy type string: "iron_butterfly", "iron_condor",
            "vertical", "straddle", "strangle", "single", or "custom".
        """
        if len(legs) == 1:
            return "single"

        if len(legs) == 2:
            # Check for vertical spread, straddle, or strangle
            types = set(leg["contract_type"] for leg in legs)
            strikes = set(leg["strike"] for leg in legs)

            if len(types) == 1:
                # Same type = vertical spread
                return "vertical"
            elif len(strikes) == 1:
                # Same strike, different types = straddle
                return "straddle"
            else:
                # Different strikes, different types = strangle
                return "strangle"

        if len(legs) == 4:
            # Check for iron butterfly or iron condor
            puts = [leg for leg in legs if leg["contract_type"] == "put"]
            calls = [leg for leg in legs if leg["contract_type"] == "call"]

            if len(puts) == 2 and len(calls) == 2:
                put_strikes = sorted([p["strike"] for p in puts])
                call_strikes = sorted([c["strike"] for c in calls])

                # Iron Butterfly: short strikes are equal
                short_put = max(put_strikes)  # Higher put strike is typically short
                short_call = min(call_strikes)  # Lower call strike is typically short

                if short_put == short_call:
                    return "iron_butterfly"
                else:
                    return "iron_condor"

        return "custom"

    def _calculate_pnl_metrics(
        self,
        legs: List[Dict[str, Any]],
        strategy_type: str,
    ) -> Dict[str, Any]:
        """Calculate P&L metrics for a position.

        Args:
            legs: List of leg dicts with entry_price, current_price, side, strike.
            strategy_type: Strategy type from _detect_strategy_type.

        Returns:
            Dictionary with:
            - entry_credit: Initial premium collected (for credit spreads)
            - current_value: Current position value
            - unrealized_pnl: Unrealized P&L in USD
            - max_profit: Maximum possible profit
            - max_loss: Maximum possible loss
            - current_pnl_pct: P&L as % of max profit
            - pnl_vs_risk: P&L as % of max risk (loss)
            - time_value_remaining_pct: % of entry credit remaining
        """
        # Calculate entry value (credit collected for credit spreads)
        # Short legs contribute positive credit, long legs are costs
        entry_credit = 0.0
        current_value = 0.0
        quantity = 1  # Default

        for leg in legs:
            qty = abs(leg["quantity"])
            quantity = max(quantity, qty)
            entry_price = leg["entry_price"] * qty * 100
            current_price = (leg.get("current_price") or leg["entry_price"]) * qty * 100

            if leg["side"] == "short":
                # Short = credit received
                entry_credit += entry_price
                current_value += current_price
            else:
                # Long = debit paid
                entry_credit -= entry_price
                current_value -= current_price

        # For credit spreads, P&L = entry_credit - current_value
        # (we want current_value to go to 0 for max profit)
        unrealized_pnl = entry_credit - current_value

        # Calculate max_profit and max_loss based on strategy
        max_profit = 0.0
        max_loss = 0.0

        if strategy_type in ("iron_butterfly", "iron_condor"):
            # Max profit = entry credit (positions expire worthless)
            max_profit = entry_credit

            # Max loss = wing_width - entry_credit
            # Determine wing width from strikes
            puts = [leg for leg in legs if leg["contract_type"] == "put"]
            calls = [leg for leg in legs if leg["contract_type"] == "call"]

            if len(puts) >= 2 and len(calls) >= 2:
                put_strikes = sorted([p["strike"] for p in puts])
                call_strikes = sorted([c["strike"] for c in calls])

                # Wing width is distance from short to long strike
                put_wing = put_strikes[1] - put_strikes[0]  # Higher - lower
                call_wing = call_strikes[1] - call_strikes[0]  # Higher - lower
                wing_width = max(put_wing, call_wing)

                max_loss = (wing_width * 100 * quantity) - entry_credit

        elif strategy_type == "vertical":
            # Vertical spread
            strikes = sorted([leg["strike"] for leg in legs])
            width = strikes[1] - strikes[0]
            short_legs = [leg for leg in legs if leg["side"] == "short"]

            if short_legs:
                # Credit spread
                max_profit = entry_credit
                max_loss = (width * 100 * quantity) - entry_credit
            else:
                # Debit spread
                max_profit = (width * 100 * quantity) + entry_credit  # entry_credit is negative
                max_loss = abs(entry_credit)

        elif strategy_type in ("straddle", "strangle"):
            # For short straddle/strangle, max profit is premium collected
            short_legs = [leg for leg in legs if leg["side"] == "short"]
            if short_legs:
                max_profit = entry_credit
                max_loss = float("inf")  # Unlimited loss potential
            else:
                # Long straddle/strangle - max loss is premium paid
                max_profit = float("inf")
                max_loss = abs(entry_credit)

        elif strategy_type == "single":
            leg = legs[0]
            if leg["side"] == "short":
                max_profit = leg["entry_price"] * abs(leg["quantity"]) * 100
                max_loss = float("inf") if leg["contract_type"] == "call" else (
                    leg["strike"] * abs(leg["quantity"]) * 100 - max_profit
                )
            else:
                max_loss = leg["entry_price"] * abs(leg["quantity"]) * 100
                max_profit = float("inf")

        else:
            # Custom strategy - estimate from current values
            max_profit = max(entry_credit, 0) if entry_credit > 0 else 0
            max_loss = abs(entry_credit) if entry_credit < 0 else 0

        # Calculate percentages (avoid division by zero)
        current_pnl_pct = 0.0
        if max_profit > 0 and max_profit != float("inf"):
            current_pnl_pct = (unrealized_pnl / max_profit) * 100

        pnl_vs_risk = 0.0
        if max_loss > 0 and max_loss != float("inf"):
            pnl_vs_risk = (unrealized_pnl / max_loss) * 100

        time_value_remaining_pct = 100.0
        if entry_credit > 0:
            time_value_remaining_pct = (current_value / entry_credit) * 100

        return {
            "entry_credit": round(entry_credit, 2),
            "current_value": round(current_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "max_profit": round(max_profit, 2) if max_profit != float("inf") else None,
            "max_loss": round(max_loss, 2) if max_loss != float("inf") else None,
            "current_pnl_pct": round(current_pnl_pct, 2),
            "pnl_vs_risk": round(pnl_vs_risk, 2),
            "time_value_remaining_pct": round(time_value_remaining_pct, 2),
        }

    @tool_schema(CloseOptionsPositionInput)
    async def close_options_position(
        self,
        position_id: str,
        order_type: str = "market",
        limit_credit: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Close an existing multi-leg options position.

        Closes all legs of a position atomically using a reverse MLEG order.
        For credit spreads (Iron Butterfly/Condor), closing means buying back
        shorts and selling longs.

        Args:
            position_id: Position ID in format 'UNDERLYING_EXPIRATION'.
            order_type: 'market' for immediate close, 'limit' for target price.
            limit_credit: For limit orders, target net credit to receive.

        Returns:
            Dictionary with:
            - order_id: Close order ID
            - status: Order status
            - position_id: Position that was closed
            - realized_pnl: Estimated realized P&L
            - legs_closed: Number of legs in the close order

        Raises:
            AlpacaOptionsError: If position not found or close fails.
        """
        try:
            # Get current positions
            positions_result = await self.get_options_positions()
            positions = positions_result.get("positions", [])

            # Find the target position
            target_position = None
            for pos in positions:
                if pos["position_id"] == position_id:
                    target_position = pos
                    break

            if not target_position:
                raise AlpacaOptionsError(
                    f"Position '{position_id}' not found. "
                    f"Available positions: {[p['position_id'] for p in positions]}"
                )

            legs = target_position["legs"]
            if not legs:
                raise AlpacaOptionsError(
                    f"Position '{position_id}' has no legs to close."
                )

            # Calculate entry value for P&L
            entry_value = sum(
                leg["entry_price"] * abs(leg["quantity"]) * 100
                * (1 if leg["side"] == "long" else -1)
                for leg in legs
            )

            # Calculate current value for estimated P&L
            current_value = sum(
                (leg.get("current_price") or leg["entry_price"])
                * abs(leg["quantity"]) * 100
                * (1 if leg["side"] == "long" else -1)
                for leg in legs
            )

            estimated_pnl = current_value - entry_value

            # Build reverse order - flip sides
            close_legs = []
            for leg in legs:
                # Reverse: long -> sell, short -> buy
                close_side = OrderSide.SELL if leg["side"] == "long" else OrderSide.BUY
                close_legs.append(
                    OptionLegRequest(
                        symbol=leg["symbol"],
                        side=close_side,
                        ratio_qty=abs(leg["quantity"]),
                    )
                )

            # Create order request
            if order_type.lower() == "limit":
                if limit_credit is None:
                    raise AlpacaOptionsError(
                        "limit_credit is required for limit orders"
                    )
                order_request = LimitOrderRequest(
                    qty=1,  # MLEG uses qty=1, ratio in legs
                    limit_price=limit_credit,
                    order_class=OrderClass.MLEG,
                    time_in_force=TimeInForce.DAY,
                    legs=close_legs,
                )
            else:
                order_request = MarketOrderRequest(
                    qty=1,
                    order_class=OrderClass.MLEG,
                    time_in_force=TimeInForce.DAY,
                    legs=close_legs,
                )

            self.logger.info(
                "Closing position %s with %d legs, order_type=%s",
                position_id,
                len(close_legs),
                order_type,
            )

            # Submit close order
            order = await asyncio.to_thread(
                self.trading_client.submit_order, order_request
            )

            # Invalidate Greeks cache for this underlying after order placement
            self._greeks_cache.invalidate_by_underlying(target_position["underlying"])

            # Calculate realized P&L percentages
            max_profit = target_position.get("max_profit")
            max_loss = target_position.get("max_loss")
            realized_pnl = target_position.get("current_pnl", estimated_pnl)

            realized_pnl_pct = 0.0
            if max_profit and max_profit > 0:
                realized_pnl_pct = (realized_pnl / max_profit) * 100

            realized_vs_risk = 0.0
            if max_loss and max_loss > 0:
                realized_vs_risk = (realized_pnl / max_loss) * 100

            return {
                "order_id": str(order.id),
                "status": str(order.status),
                "position_id": position_id,
                "underlying": target_position["underlying"],
                "expiration": target_position["expiration"],
                "strategy_type": target_position["strategy_type"],
                "order_type": order_type,
                "limit_credit": limit_credit,
                "legs_closed": len(close_legs),
                # P&L metrics
                "entry_credit": target_position.get("entry_credit", round(abs(entry_value), 2)),
                "close_value": round(abs(current_value), 2),
                "realized_pnl": round(realized_pnl, 2),
                "max_profit": max_profit,
                "max_loss": max_loss,
                "realized_pnl_pct": round(realized_pnl_pct, 2),
                "realized_vs_risk": round(realized_vs_risk, 2),
                "paper": self.paper,
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Close options position failed: {exc}"
            ) from exc

    # =========================================================================
    # RISK ANALYSIS TOOLS
    # =========================================================================

    @tool_schema(AnalyzeOptionsPortfolioRiskInput)
    async def analyze_options_portfolio_risk(
        self,
        include_greeks: bool = True,
        group_by_expiration: bool = True,
        group_by_underlying: bool = True,
    ) -> Dict[str, Any]:
        """Analyze aggregate risk metrics for the entire options portfolio.

        Calculates portfolio-level Greeks exposure, premium at risk, and
        concentration metrics. Used by Risk Analyst to assess overall
        options risk profile.

        Args:
            include_greeks: Include aggregate Greeks (delta, gamma, theta, vega).
            group_by_expiration: Group positions by expiration date bucket.
            group_by_underlying: Show concentration by underlying symbol.

        Returns:
            Dictionary with:
            - total_positions: Number of options positions
            - total_premium_at_risk: Sum of position values
            - aggregate_greeks: Net delta, gamma, theta, vega
            - by_expiration: Positions grouped by expiration bucket
            - by_underlying: Concentration by underlying
            - risk_flags: Any risk limit violations

        Raises:
            AlpacaOptionsError: If API call fails.
        """
        try:
            # Get all options positions
            positions_data = await self.get_options_positions()
            positions = positions_data.get("positions", [])

            if not positions:
                return {
                    "total_positions": 0,
                    "total_premium_at_risk": 0.0,
                    "aggregate_greeks": {
                        "delta": 0.0,
                        "gamma": 0.0,
                        "theta": 0.0,
                        "vega": 0.0,
                    },
                    "by_expiration": {},
                    "by_underlying": {},
                    "risk_flags": [],
                }

            # Calculate aggregates
            total_premium = 0.0
            total_delta = 0.0
            total_gamma = 0.0
            total_theta = 0.0
            total_vega = 0.0

            by_expiration: Dict[str, Dict[str, Any]] = {}
            by_underlying: Dict[str, Dict[str, Any]] = {}
            risk_flags = []

            for pos in positions:
                underlying = pos.get("underlying", "UNKNOWN")
                expiration = pos.get("expiration", "UNKNOWN")

                # Sum position-level metrics
                position_value = abs(sum(
                    leg.get("market_value", 0) or 0
                    for leg in pos.get("legs", [])
                ))
                total_premium += position_value

                if include_greeks:
                    total_delta += pos.get("position_delta", 0) or 0
                    total_gamma += pos.get("position_gamma", 0) or 0
                    total_theta += pos.get("position_theta", 0) or 0
                    total_vega += pos.get("position_vega", 0) or 0

                # Group by expiration
                if group_by_expiration:
                    if expiration not in by_expiration:
                        by_expiration[expiration] = {
                            "positions": 0,
                            "premium_at_risk": 0.0,
                            "delta": 0.0,
                        }
                    by_expiration[expiration]["positions"] += 1
                    by_expiration[expiration]["premium_at_risk"] += position_value
                    by_expiration[expiration]["delta"] += pos.get("position_delta", 0) or 0

                # Group by underlying
                if group_by_underlying:
                    if underlying not in by_underlying:
                        by_underlying[underlying] = {
                            "positions": 0,
                            "premium_at_risk": 0.0,
                            "delta": 0.0,
                        }
                    by_underlying[underlying]["positions"] += 1
                    by_underlying[underlying]["premium_at_risk"] += position_value
                    by_underlying[underlying]["delta"] += pos.get("position_delta", 0) or 0

            # Check for risk flags
            # Flag 1: High single-underlying concentration (>50%)
            for underlying, data in by_underlying.items():
                if total_premium > 0:
                    concentration = data["premium_at_risk"] / total_premium
                    if concentration > 0.5:
                        risk_flags.append(
                            f"HIGH_CONCENTRATION: {underlying} is "
                            f"{concentration:.0%} of options portfolio"
                        )

            # Flag 2: High absolute delta (directional risk)
            if abs(total_delta) > 100:
                risk_flags.append(
                    f"HIGH_DELTA: Net delta of {total_delta:.1f} indicates "
                    "significant directional exposure"
                )

            # Flag 3: High negative theta (time decay)
            if total_theta < -50:
                risk_flags.append(
                    f"HIGH_THETA_DECAY: Daily theta decay of "
                    f"${abs(total_theta):.2f}"
                )

            return {
                "total_positions": len(positions),
                "total_premium_at_risk": round(total_premium, 2),
                "aggregate_greeks": {
                    "delta": round(total_delta, 4),
                    "gamma": round(total_gamma, 4),
                    "theta": round(total_theta, 4),
                    "vega": round(total_vega, 4),
                } if include_greeks else None,
                "by_expiration": {
                    exp: {
                        "positions": data["positions"],
                        "premium_at_risk": round(data["premium_at_risk"], 2),
                        "delta": round(data["delta"], 4),
                    }
                    for exp, data in sorted(by_expiration.items())
                } if group_by_expiration else None,
                "by_underlying": {
                    und: {
                        "positions": data["positions"],
                        "premium_at_risk": round(data["premium_at_risk"], 2),
                        "delta": round(data["delta"], 4),
                        "concentration_pct": round(
                            data["premium_at_risk"] / total_premium * 100, 1
                        ) if total_premium > 0 else 0,
                    }
                    for und, data in sorted(by_underlying.items())
                } if group_by_underlying else None,
                "risk_flags": risk_flags,
                "paper": self.paper,
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Analyze options portfolio risk failed: {exc}"
            ) from exc

    @tool_schema(StressTestOptionsPositionsInput)
    async def stress_test_options_positions(
        self,
        underlying_move_pct: float = 5.0,
        iv_change_pct: float = 20.0,
        position_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Stress test options positions under hypothetical market scenarios.

        Calculates estimated P&L impact for underlying price moves and
        implied volatility changes. Uses first-order Greeks approximation.

        Args:
            underlying_move_pct: Hypothetical price move (e.g., 5.0 for ±5%).
            iv_change_pct: Hypothetical IV change (e.g., 20.0 for ±20%).
            position_id: Specific position to test. None tests all positions.

        Returns:
            Dictionary with:
            - scenarios: List of scenario results
            - worst_case_pnl: Worst scenario P&L
            - best_case_pnl: Best scenario P&L
            - most_likely_impact: Middle scenario estimate

        Raises:
            AlpacaOptionsError: If API call fails.
        """
        try:
            # Get positions
            positions_data = await self.get_options_positions(
                underlying=position_id.split("_")[0] if position_id else None
            )
            positions = positions_data.get("positions", [])

            # Filter to specific position if requested
            if position_id:
                positions = [
                    p for p in positions
                    if p.get("position_id") == position_id
                ]
                if not positions:
                    raise AlpacaOptionsError(
                        f"Position {position_id} not found"
                    )

            if not positions:
                return {
                    "scenarios": [],
                    "worst_case_pnl": 0.0,
                    "best_case_pnl": 0.0,
                    "most_likely_impact": 0.0,
                    "positions_tested": 0,
                }

            # Define scenarios
            scenarios = [
                {
                    "name": f"underlying_up_{underlying_move_pct}pct",
                    "underlying_change": underlying_move_pct / 100,
                    "iv_change": 0,
                },
                {
                    "name": f"underlying_down_{underlying_move_pct}pct",
                    "underlying_change": -underlying_move_pct / 100,
                    "iv_change": 0,
                },
                {
                    "name": f"iv_up_{iv_change_pct}pct",
                    "underlying_change": 0,
                    "iv_change": iv_change_pct / 100,
                },
                {
                    "name": f"iv_down_{iv_change_pct}pct",
                    "underlying_change": 0,
                    "iv_change": -iv_change_pct / 100,
                },
                {
                    "name": f"crash_down_{underlying_move_pct}pct_iv_up_{iv_change_pct}pct",
                    "underlying_change": -underlying_move_pct / 100,
                    "iv_change": iv_change_pct / 100,
                },
                {
                    "name": f"rally_up_{underlying_move_pct}pct_iv_down_{iv_change_pct}pct",
                    "underlying_change": underlying_move_pct / 100,
                    "iv_change": -iv_change_pct / 100,
                },
            ]

            scenario_results = []

            for scenario in scenarios:
                total_pnl = 0.0
                position_impacts = []

                for pos in positions:
                    # Get position Greeks
                    delta = pos.get("position_delta", 0) or 0
                    gamma = pos.get("position_gamma", 0) or 0
                    vega = pos.get("position_vega", 0) or 0

                    # Estimate P&L using Greeks
                    # Delta P&L: delta * underlying_change * 100 (per contract)
                    # Gamma P&L: 0.5 * gamma * (underlying_change)^2 * 100
                    # Vega P&L: vega * IV_change (IV in decimal)

                    # Get underlying price for scaling
                    legs = pos.get("legs", [])
                    underlying_price = 100.0  # Default if not available
                    if legs:
                        # Use strike as proxy if we don't have underlying price
                        underlying_price = legs[0].get("strike", 100.0)

                    price_change = underlying_price * scenario["underlying_change"]

                    # First-order approximation
                    delta_pnl = delta * price_change * 100
                    gamma_pnl = 0.5 * gamma * (price_change ** 2) * 100
                    vega_pnl = vega * scenario["iv_change"] * 100

                    position_pnl = delta_pnl + gamma_pnl + vega_pnl
                    total_pnl += position_pnl

                    position_impacts.append({
                        "position_id": pos.get("position_id"),
                        "underlying": pos.get("underlying"),
                        "estimated_pnl": round(position_pnl, 2),
                        "delta_impact": round(delta_pnl, 2),
                        "gamma_impact": round(gamma_pnl, 2),
                        "vega_impact": round(vega_pnl, 2),
                    })

                scenario_results.append({
                    "scenario": scenario["name"],
                    "underlying_change_pct": scenario["underlying_change"] * 100,
                    "iv_change_pct": scenario["iv_change"] * 100,
                    "total_estimated_pnl": round(total_pnl, 2),
                    "position_impacts": position_impacts,
                })

            # Find worst/best cases
            pnls = [s["total_estimated_pnl"] for s in scenario_results]
            worst_case = min(pnls)
            best_case = max(pnls)
            most_likely = sum(pnls) / len(pnls) if pnls else 0

            return {
                "scenarios": scenario_results,
                "worst_case_pnl": round(worst_case, 2),
                "best_case_pnl": round(best_case, 2),
                "most_likely_impact": round(most_likely, 2),
                "positions_tested": len(positions),
                "underlying_move_tested": underlying_move_pct,
                "iv_change_tested": iv_change_pct,
                "paper": self.paper,
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Stress test options positions failed: {exc}"
            ) from exc

    @tool_schema(GetPositionGreeksInput)
    async def get_position_greeks(
        self,
        position_id: str,
    ) -> Dict[str, Any]:
        """Get current Greeks for a specific options position.

        Retrieves delta, gamma, theta, vega aggregated across all legs
        of the specified position.

        Args:
            position_id: Position ID in format 'UNDERLYING_EXPIRATION'.

        Returns:
            Dictionary with:
            - position_id: The position identifier
            - underlying: Underlying symbol
            - expiration: Expiration date
            - strategy_type: Strategy type (iron_butterfly, iron_condor, etc.)
            - aggregate_greeks: Position-level Greeks
            - leg_greeks: Per-leg Greeks breakdown
            - current_value: Current market value
            - unrealized_pnl: Unrealized P&L

        Raises:
            AlpacaOptionsError: If position not found or API call fails.
        """
        try:
            # Get positions filtered by underlying
            underlying = position_id.split("_")[0] if "_" in position_id else None
            positions_data = await self.get_options_positions(underlying=underlying)
            positions = positions_data.get("positions", [])

            # Find the specific position
            target_position = None
            for pos in positions:
                if pos.get("position_id") == position_id:
                    target_position = pos
                    break

            if not target_position:
                raise AlpacaOptionsError(
                    f"Position {position_id} not found"
                )

            # Extract leg-level Greeks
            leg_greeks = []
            for leg in target_position.get("legs", []):
                leg_greeks.append({
                    "symbol": leg.get("symbol"),
                    "strike": leg.get("strike"),
                    "contract_type": leg.get("contract_type"),
                    "side": leg.get("side"),
                    "quantity": leg.get("quantity"),
                    "delta": leg.get("delta"),
                    "gamma": leg.get("gamma"),
                    "theta": leg.get("theta"),
                    "vega": leg.get("vega"),
                    "iv": leg.get("iv"),
                    "current_price": leg.get("current_price"),
                })

            # Calculate current value and P&L
            current_value = sum(
                (leg.get("market_value", 0) or 0)
                for leg in target_position.get("legs", [])
            )
            unrealized_pnl = target_position.get("current_pnl", 0)

            return {
                "position_id": position_id,
                "underlying": target_position.get("underlying"),
                "expiration": target_position.get("expiration"),
                "strategy_type": target_position.get("strategy_type"),
                "aggregate_greeks": {
                    "delta": target_position.get("position_delta"),
                    "gamma": target_position.get("position_gamma"),
                    "theta": target_position.get("position_theta"),
                    "vega": target_position.get("position_vega"),
                },
                "leg_greeks": leg_greeks,
                "current_value": round(current_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "paper": self.paper,
            }

        except APIError as exc:
            raise AlpacaOptionsError(
                f"Get position greeks failed: {exc}"
            ) from exc

    async def cleanup(self) -> None:
        """Clean up client connections and cache."""
        self._trading_client = None
        self._data_client = None
        self._greeks_cache.clear()
        self.logger.debug("AlpacaOptionsToolkit clients and cache cleaned up")
