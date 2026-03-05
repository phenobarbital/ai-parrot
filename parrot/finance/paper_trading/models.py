"""
Paper Trading Data Models
=========================

Pydantic models for paper-trading mode configuration, simulated orders,
positions, and fills. Used by VirtualPortfolio and toolkit enhancements.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# =============================================================================
# EXECUTION MODE
# =============================================================================


class ExecutionMode(str, Enum):
    """
    Execution environment mode.

    - LIVE: Real trading with real funds
    - PAPER: Platform-native paper trading (Alpaca paper, IBKR paper, Binance testnet)
    - DRY_RUN: Local simulation only (no API calls for orders)
    """

    LIVE = "live"
    PAPER = "paper"
    DRY_RUN = "dry_run"


# =============================================================================
# CONFIGURATION
# =============================================================================


class PaperTradingConfig(BaseModel):
    """
    Global paper-trading configuration.

    Controls execution mode and simulation parameters for all toolkits.
    """

    mode: ExecutionMode = Field(
        default=ExecutionMode.PAPER,
        description="Execution mode for all toolkits",
    )
    simulate_slippage_bps: int = Field(
        default=0,
        description="Basis points of slippage to simulate (0 = no simulation)",
        ge=0,
        le=100,
    )
    simulate_fill_delay_ms: int = Field(
        default=0,
        description="Milliseconds of fill delay to simulate (0 = instant)",
        ge=0,
        le=5000,
    )
    fail_on_live_in_dev: bool = Field(
        default=True,
        description="Raise error if mode=LIVE in development environment",
    )

    class Config:
        use_enum_values = False


# =============================================================================
# SIMULATED POSITION
# =============================================================================


class SimulatedPosition(BaseModel):
    """
    Virtual position tracked in dry-run mode.

    Represents an open position in the virtual portfolio.
    """

    symbol: str = Field(..., description="Ticker or trading pair symbol")
    platform: str = Field(..., description="Platform identifier (alpaca, binance, etc.)")
    side: Literal["long", "short"] = Field(..., description="Position side")
    quantity: Decimal = Field(..., description="Number of shares/contracts/units", gt=0)
    avg_entry_price: Decimal = Field(..., description="Average entry price", gt=0)
    current_price: Optional[Decimal] = Field(
        default=None, description="Latest market price"
    )
    unrealized_pnl: Optional[Decimal] = Field(
        default=None, description="Unrealized profit/loss"
    )
    opened_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When position was opened",
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp",
    )

    def calculate_unrealized_pnl(self) -> Decimal:
        """Calculate unrealized P&L based on current price."""
        if self.current_price is None:
            return Decimal("0")
        price_diff = self.current_price - self.avg_entry_price
        if self.side == "short":
            price_diff = -price_diff
        return price_diff * self.quantity

    def update_price(self, price: Decimal) -> None:
        """Update current price and recalculate P&L."""
        self.current_price = price
        self.unrealized_pnl = self.calculate_unrealized_pnl()
        self.last_updated = datetime.now(timezone.utc)

    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat(),
        }


# =============================================================================
# SIMULATED ORDER
# =============================================================================


class SimulatedOrder(BaseModel):
    """
    Virtual order in dry-run mode.

    Represents an order submitted to the virtual portfolio.
    """

    order_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique order identifier",
    )
    symbol: str = Field(..., description="Ticker or trading pair symbol")
    platform: str = Field(..., description="Platform identifier")
    side: Literal["buy", "sell"] = Field(..., description="Order side")
    order_type: Literal["limit", "market", "stop", "stop_limit"] = Field(
        ..., description="Order type"
    )
    quantity: Decimal = Field(..., description="Order quantity", gt=0)
    limit_price: Optional[Decimal] = Field(
        default=None, description="Limit price for limit/stop_limit orders", gt=0
    )
    stop_price: Optional[Decimal] = Field(
        default=None, description="Stop trigger price for stop/stop_limit orders", gt=0
    )
    status: Literal["pending", "filled", "cancelled", "rejected"] = Field(
        default="pending", description="Order status"
    )
    filled_quantity: Decimal = Field(
        default=Decimal("0"), description="Quantity filled so far"
    )
    filled_price: Optional[Decimal] = Field(
        default=None, description="Average fill price"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Order creation timestamp",
    )
    filled_at: Optional[datetime] = Field(
        default=None, description="When order was filled"
    )
    rejected_reason: Optional[str] = Field(
        default=None, description="Reason for rejection if rejected"
    )

    def is_fillable_at_price(self, market_price: Decimal) -> bool:
        """Check if order can be filled at given market price."""
        if self.status != "pending":
            return False

        if self.order_type == "market":
            return True

        if self.order_type == "limit":
            if self.limit_price is None:
                return False
            # Buy limit fills when market <= limit
            if self.side == "buy":
                return market_price <= self.limit_price
            # Sell limit fills when market >= limit
            return market_price >= self.limit_price

        if self.order_type == "stop":
            if self.stop_price is None:
                return False
            # Buy stop triggers when market >= stop
            if self.side == "buy":
                return market_price >= self.stop_price
            # Sell stop triggers when market <= stop
            return market_price <= self.stop_price

        if self.order_type == "stop_limit":
            if self.stop_price is None or self.limit_price is None:
                return False
            # First check stop trigger
            stop_triggered = (
                (self.side == "buy" and market_price >= self.stop_price)
                or (self.side == "sell" and market_price <= self.stop_price)
            )
            if not stop_triggered:
                return False
            # Then check limit
            if self.side == "buy":
                return market_price <= self.limit_price
            return market_price >= self.limit_price

        return False

    def fill(
        self,
        price: Decimal,
        quantity: Optional[Decimal] = None,
        slippage_bps: int = 0,
    ) -> None:
        """Fill the order at given price with optional slippage."""
        fill_qty = quantity if quantity is not None else self.quantity

        # Apply slippage
        if slippage_bps > 0:
            slippage_factor = Decimal(slippage_bps) / Decimal("10000")
            if self.side == "buy":
                price = price * (Decimal("1") + slippage_factor)
            else:
                price = price * (Decimal("1") - slippage_factor)

        self.filled_quantity = fill_qty
        self.filled_price = price
        self.status = "filled"
        self.filled_at = datetime.now(timezone.utc)

    def cancel(self) -> bool:
        """Cancel the order if pending."""
        if self.status == "pending":
            self.status = "cancelled"
            return True
        return False

    def reject(self, reason: str) -> None:
        """Reject the order with a reason."""
        self.status = "rejected"
        self.rejected_reason = reason

    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat(),
        }


# =============================================================================
# SIMULATED FILL
# =============================================================================


class SimulatedFill(BaseModel):
    """
    Fill record for a simulated order.

    Immutable record of an execution event.
    """

    fill_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique fill identifier",
    )
    order_id: str = Field(..., description="Parent order ID")
    symbol: str = Field(..., description="Ticker or trading pair symbol")
    platform: str = Field(..., description="Platform identifier")
    side: Literal["buy", "sell"] = Field(..., description="Trade side")
    quantity: Decimal = Field(..., description="Fill quantity", gt=0)
    price: Decimal = Field(..., description="Fill price", gt=0)
    slippage_bps: int = Field(
        default=0, description="Slippage applied in basis points", ge=0
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Fill timestamp",
    )

    @property
    def notional_value(self) -> Decimal:
        """Calculate notional value of the fill."""
        return self.quantity * self.price

    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat(),
        }


# =============================================================================
# VIRTUAL PORTFOLIO STATE
# =============================================================================


class VirtualPortfolioState(BaseModel):
    """
    Snapshot of the virtual portfolio.

    Complete state of the paper trading portfolio at a point in time.
    """

    cash_balance: Decimal = Field(
        default=Decimal("100000"),
        description="Available cash balance",
    )
    initial_cash: Decimal = Field(
        default=Decimal("100000"),
        description="Starting cash balance",
    )
    positions: list[SimulatedPosition] = Field(
        default_factory=list,
        description="Open positions",
    )
    pending_orders: list[SimulatedOrder] = Field(
        default_factory=list,
        description="Orders awaiting execution",
    )
    filled_orders: list[SimulatedOrder] = Field(
        default_factory=list,
        description="Completed orders",
    )
    fills: list[SimulatedFill] = Field(
        default_factory=list,
        description="Execution records",
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last state update timestamp",
    )

    @property
    def total_position_value(self) -> Decimal:
        """Calculate total value of all positions."""
        total = Decimal("0")
        for pos in self.positions:
            if pos.current_price is not None:
                total += pos.quantity * pos.current_price
        return total

    @property
    def total_equity(self) -> Decimal:
        """Calculate total portfolio equity (cash + positions)."""
        return self.cash_balance + self.total_position_value

    @property
    def total_unrealized_pnl(self) -> Decimal:
        """Calculate total unrealized P&L across all positions."""
        total = Decimal("0")
        for pos in self.positions:
            if pos.unrealized_pnl is not None:
                total += pos.unrealized_pnl
        return total

    @property
    def total_realized_pnl(self) -> Decimal:
        """Calculate total realized P&L from closed positions."""
        return self.total_equity - self.initial_cash - self.total_unrealized_pnl

    class Config:
        json_encoders = {
            Decimal: str,
            datetime: lambda v: v.isoformat(),
        }


# =============================================================================
# SIMULATION DETAILS (for execution reports)
# =============================================================================


class SimulationDetails(BaseModel):
    """
    Details about simulation parameters applied to an execution.

    Attached to ExecutionReportOutput when is_simulated=True.
    """

    slippage_applied_bps: int = Field(
        default=0, description="Slippage applied in basis points"
    )
    fill_delay_applied_ms: int = Field(
        default=0, description="Fill delay applied in milliseconds"
    )
    virtual_portfolio_id: Optional[str] = Field(
        default=None, description="ID of the virtual portfolio used"
    )
    simulation_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When simulation was performed",
    )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
