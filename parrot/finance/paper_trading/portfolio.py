"""
Virtual Portfolio Engine
========================

Local simulation engine for DRY_RUN mode.
Tracks virtual positions, generates simulated fills, and calculates P&L.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from navconfig.logging import logging

from .models import (
    SimulatedFill,
    SimulatedOrder,
    SimulatedPosition,
    VirtualPortfolioState,
)


class VirtualPortfolio:
    """
    Local simulation engine for dry-run mode.

    Provides paper trading simulation without any external API calls.
    Tracks orders, positions, fills, and cash balance.

    Thread-safe via asyncio locks for concurrent order placement.

    Usage:
        portfolio = VirtualPortfolio(initial_cash=Decimal("100000"))

        # Place a market order (fills immediately)
        order = SimulatedOrder(
            symbol="AAPL",
            platform="alpaca",
            side="buy",
            order_type="market",
            quantity=Decimal("10"),
        )
        await portfolio.place_order(order, current_price=Decimal("150.00"))

        # Place a limit order (fills when price crosses)
        limit_order = SimulatedOrder(
            symbol="AAPL",
            platform="alpaca",
            side="sell",
            order_type="limit",
            quantity=Decimal("10"),
            limit_price=Decimal("160.00"),
        )
        await portfolio.place_order(limit_order)

        # Update prices to trigger limit fills
        await portfolio.update_prices({"AAPL": Decimal("165.00")})
    """

    def __init__(
        self,
        initial_cash: Decimal = Decimal("100000"),
        slippage_bps: int = 0,
        fill_delay_ms: int = 0,
        portfolio_id: Optional[str] = None,
    ):
        """
        Initialize the virtual portfolio.

        Args:
            initial_cash: Starting cash balance
            slippage_bps: Basis points of slippage to apply to fills (0-100)
            fill_delay_ms: Milliseconds of delay before fills (0-5000)
            portfolio_id: Optional identifier for this portfolio
        """
        self._id = portfolio_id or str(uuid.uuid4())
        self._initial_cash = initial_cash
        self._cash_balance = initial_cash
        self._slippage_bps = slippage_bps
        self._fill_delay_ms = fill_delay_ms

        # State storage
        self._positions: dict[str, SimulatedPosition] = {}  # symbol -> position
        self._pending_orders: dict[str, SimulatedOrder] = {}  # order_id -> order
        self._filled_orders: list[SimulatedOrder] = []
        self._fills: list[SimulatedFill] = []

        # Current prices for limit order evaluation
        self._current_prices: dict[str, Decimal] = {}

        # Thread safety
        self._lock = asyncio.Lock()

        self._logger = logging.getLogger("VirtualPortfolio")

    @property
    def id(self) -> str:
        """Portfolio identifier."""
        return self._id

    @property
    def cash_balance(self) -> Decimal:
        """Current cash balance."""
        return self._cash_balance

    @property
    def slippage_bps(self) -> int:
        """Slippage in basis points."""
        return self._slippage_bps

    @property
    def fill_delay_ms(self) -> int:
        """Fill delay in milliseconds."""
        return self._fill_delay_ms

    # =========================================================================
    # ORDER MANAGEMENT
    # =========================================================================

    async def place_order(
        self,
        order: SimulatedOrder,
        current_price: Optional[Decimal] = None,
    ) -> SimulatedOrder:
        """
        Submit an order to the virtual portfolio.

        For market orders, fills immediately at current_price (or stored price).
        For limit/stop orders, adds to pending and fills when price crosses.

        Args:
            order: The order to place
            current_price: Current market price (required for market orders)

        Returns:
            The order with updated status

        Raises:
            ValueError: If market order without current_price
        """
        async with self._lock:
            # Store current price if provided
            if current_price is not None:
                self._current_prices[order.symbol] = current_price

            # Get price for evaluation
            price = current_price or self._current_prices.get(order.symbol)

            # Market orders require a price
            if order.order_type == "market":
                if price is None:
                    order.reject("Market order requires current_price")
                    self._logger.warning(
                        f"Order {order.order_id} rejected: no price for market order"
                    )
                    return order

                # Apply fill delay if configured
                if self._fill_delay_ms > 0:
                    await asyncio.sleep(self._fill_delay_ms / 1000.0)

                # Fill immediately
                await self._fill_order(order, price)
                return order

            # Limit/stop orders: check if immediately fillable
            if price is not None and order.is_fillable_at_price(price):
                # Apply fill delay if configured
                if self._fill_delay_ms > 0:
                    await asyncio.sleep(self._fill_delay_ms / 1000.0)

                await self._fill_order(order, price)
                return order

            # Not immediately fillable - add to pending
            self._pending_orders[order.order_id] = order
            self._logger.info(
                f"Order {order.order_id} pending: {order.side} {order.quantity} "
                f"{order.symbol} @ {order.limit_price or order.stop_price}"
            )
            return order

    async def _fill_order(
        self,
        order: SimulatedOrder,
        price: Decimal,
    ) -> None:
        """
        Fill an order at the given price.

        Updates cash balance, creates/updates position, and records fill.
        """
        # Apply slippage to fill price
        fill_price = self._apply_slippage(price, order.side)

        # Calculate notional value
        notional = order.quantity * fill_price

        # Check cash for buys
        if order.side == "buy" and notional > self._cash_balance:
            order.reject(
                f"Insufficient cash: need {notional}, have {self._cash_balance}"
            )
            self._logger.warning(
                f"Order {order.order_id} rejected: insufficient cash"
            )
            return

        # Fill the order (slippage already applied to fill_price)
        order.fill(fill_price, slippage_bps=0)

        # Update cash balance
        if order.side == "buy":
            self._cash_balance -= notional
        else:
            self._cash_balance += notional

        # Create fill record
        fill = SimulatedFill(
            order_id=order.order_id,
            symbol=order.symbol,
            platform=order.platform,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            slippage_bps=self._slippage_bps,
        )
        self._fills.append(fill)

        # Update position
        await self._update_position_from_fill(fill)

        # Move from pending to filled
        self._pending_orders.pop(order.order_id, None)
        self._filled_orders.append(order)

        self._logger.info(
            f"Order {order.order_id} filled: {order.side} {order.quantity} "
            f"{order.symbol} @ {fill_price}"
        )

    def _apply_slippage(self, price: Decimal, side: str) -> Decimal:
        """Apply slippage to a price based on order side."""
        if self._slippage_bps == 0:
            return price

        slippage_factor = Decimal(self._slippage_bps) / Decimal("10000")
        if side == "buy":
            # Buys fill at slightly higher price
            return price * (Decimal("1") + slippage_factor)
        else:
            # Sells fill at slightly lower price
            return price * (Decimal("1") - slippage_factor)

    async def _update_position_from_fill(self, fill: SimulatedFill) -> None:
        """Update or create position based on fill."""
        symbol = fill.symbol
        existing = self._positions.get(symbol)

        if fill.side == "buy":
            if existing is None:
                # New long position
                self._positions[symbol] = SimulatedPosition(
                    symbol=symbol,
                    platform=fill.platform,
                    side="long",
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    current_price=fill.price,
                )
            elif existing.side == "long":
                # Add to long position (average cost)
                total_qty = existing.quantity + fill.quantity
                total_cost = (
                    existing.quantity * existing.avg_entry_price
                    + fill.quantity * fill.price
                )
                existing.quantity = total_qty
                existing.avg_entry_price = total_cost / total_qty
                existing.last_updated = datetime.now(timezone.utc)
            else:
                # Reduce short position
                if fill.quantity >= existing.quantity:
                    # Close short, potentially go long
                    remaining = fill.quantity - existing.quantity
                    if remaining > Decimal("0"):
                        self._positions[symbol] = SimulatedPosition(
                            symbol=symbol,
                            platform=fill.platform,
                            side="long",
                            quantity=remaining,
                            avg_entry_price=fill.price,
                            current_price=fill.price,
                        )
                    else:
                        del self._positions[symbol]
                else:
                    existing.quantity -= fill.quantity
                    existing.last_updated = datetime.now(timezone.utc)

        else:  # sell
            if existing is None:
                # New short position
                self._positions[symbol] = SimulatedPosition(
                    symbol=symbol,
                    platform=fill.platform,
                    side="short",
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    current_price=fill.price,
                )
            elif existing.side == "short":
                # Add to short position
                total_qty = existing.quantity + fill.quantity
                total_cost = (
                    existing.quantity * existing.avg_entry_price
                    + fill.quantity * fill.price
                )
                existing.quantity = total_qty
                existing.avg_entry_price = total_cost / total_qty
                existing.last_updated = datetime.now(timezone.utc)
            else:
                # Reduce long position
                if fill.quantity >= existing.quantity:
                    # Close long, potentially go short
                    remaining = fill.quantity - existing.quantity
                    if remaining > Decimal("0"):
                        self._positions[symbol] = SimulatedPosition(
                            symbol=symbol,
                            platform=fill.platform,
                            side="short",
                            quantity=remaining,
                            avg_entry_price=fill.price,
                            current_price=fill.price,
                        )
                    else:
                        del self._positions[symbol]
                else:
                    existing.quantity -= fill.quantity
                    existing.last_updated = datetime.now(timezone.utc)

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a pending order.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if cancelled, False if not found or already filled
        """
        async with self._lock:
            order = self._pending_orders.get(order_id)
            if order is None:
                return False

            if order.cancel():
                del self._pending_orders[order_id]
                self._logger.info(f"Order {order_id} cancelled")
                return True

            return False

    # =========================================================================
    # PRICE UPDATES
    # =========================================================================

    async def update_prices(self, prices: dict[str, Decimal]) -> list[SimulatedOrder]:
        """
        Update current prices and trigger limit order fills.

        Args:
            prices: Dict of symbol -> current price

        Returns:
            List of orders that were filled
        """
        filled_orders = []

        async with self._lock:
            # Update stored prices
            self._current_prices.update(prices)

            # Update position prices
            for symbol, price in prices.items():
                if symbol in self._positions:
                    self._positions[symbol].update_price(price)

            # Check pending orders for fills
            orders_to_fill = []
            for order_id, order in list(self._pending_orders.items()):
                price = prices.get(order.symbol)
                if price is not None and order.is_fillable_at_price(price):
                    orders_to_fill.append((order, price))

            # Fill orders outside the iteration
            for order, price in orders_to_fill:
                # Apply fill delay if configured
                if self._fill_delay_ms > 0:
                    await asyncio.sleep(self._fill_delay_ms / 1000.0)

                await self._fill_order(order, price)
                filled_orders.append(order)

        return filled_orders

    # =========================================================================
    # QUERIES
    # =========================================================================

    def get_positions(self) -> list[SimulatedPosition]:
        """Get all current positions."""
        return list(self._positions.values())

    def get_position(self, symbol: str) -> Optional[SimulatedPosition]:
        """Get position for a specific symbol."""
        return self._positions.get(symbol)

    def get_open_orders(self) -> list[SimulatedOrder]:
        """Get all pending orders."""
        return list(self._pending_orders.values())

    def get_order(self, order_id: str) -> Optional[SimulatedOrder]:
        """Get an order by ID (pending or filled)."""
        if order_id in self._pending_orders:
            return self._pending_orders[order_id]
        for order in self._filled_orders:
            if order.order_id == order_id:
                return order
        return None

    def get_fills(self, since: Optional[datetime] = None) -> list[SimulatedFill]:
        """
        Get fill history.

        Args:
            since: Optional datetime to filter fills after

        Returns:
            List of fills, optionally filtered by time
        """
        if since is None:
            return list(self._fills)
        return [f for f in self._fills if f.timestamp >= since]

    def get_state(self) -> VirtualPortfolioState:
        """Get complete portfolio snapshot."""
        return VirtualPortfolioState(
            cash_balance=self._cash_balance,
            initial_cash=self._initial_cash,
            positions=list(self._positions.values()),
            pending_orders=list(self._pending_orders.values()),
            filled_orders=list(self._filled_orders),
            fills=list(self._fills),
            last_updated=datetime.now(timezone.utc),
        )

    # =========================================================================
    # MANAGEMENT
    # =========================================================================

    async def reset(self) -> None:
        """Reset portfolio to initial state."""
        async with self._lock:
            self._cash_balance = self._initial_cash
            self._positions.clear()
            self._pending_orders.clear()
            self._filled_orders.clear()
            self._fills.clear()
            self._current_prices.clear()
            self._logger.info(f"Portfolio {self._id} reset to initial state")

    def get_current_price(self, symbol: str) -> Optional[Decimal]:
        """Get the last known price for a symbol."""
        return self._current_prices.get(symbol)

    def set_slippage(self, slippage_bps: int) -> None:
        """Update slippage setting."""
        if 0 <= slippage_bps <= 100:
            self._slippage_bps = slippage_bps

    def set_fill_delay(self, delay_ms: int) -> None:
        """Update fill delay setting."""
        if 0 <= delay_ms <= 5000:
            self._fill_delay_ms = delay_ms

    # =========================================================================
    # SUMMARY
    # =========================================================================

    def summary(self) -> dict:
        """Get a summary of portfolio state."""
        state = self.get_state()
        return {
            "portfolio_id": self._id,
            "cash_balance": str(self._cash_balance),
            "initial_cash": str(self._initial_cash),
            "total_equity": str(state.total_equity),
            "total_unrealized_pnl": str(state.total_unrealized_pnl),
            "position_count": len(self._positions),
            "pending_orders": len(self._pending_orders),
            "filled_orders": len(self._filled_orders),
            "total_fills": len(self._fills),
        }
