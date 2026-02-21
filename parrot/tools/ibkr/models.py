"""Pydantic data models for the IBKR Trading Toolkit.

Defines configuration, market data, order, position, and account models
used throughout the IBKR toolkit. All monetary/price fields use Decimal
for precision. Field descriptions serve as LLM tool parameter descriptions.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field


class IBKRConfig(BaseModel):
    """Configuration for IBKR connection."""

    backend: Literal["tws", "portal"] = Field(
        "tws", description="Connection backend: 'tws' for TWS API, 'portal' for Client Portal REST API."
    )
    host: str = Field("127.0.0.1", description="TWS/Gateway host address.")
    port: int = Field(7497, description="TWS port (7497=paper trading, 7496=live trading).")
    client_id: int = Field(1, description="Client ID for TWS connection.")
    portal_url: Optional[str] = Field(
        None, description="Client Portal Gateway URL (required for portal backend)."
    )
    readonly: bool = Field(
        False, description="Read-only mode — disables order placement and modification."
    )


class RiskConfig(BaseModel):
    """Risk management guardrails for agent-driven trading."""

    max_order_qty: int = Field(
        100, description="Maximum shares/contracts per single order."
    )
    max_order_value: Decimal = Field(
        Decimal("50000"), description="Maximum notional value per single order."
    )
    max_position_value: Decimal = Field(
        Decimal("200000"), description="Maximum total position value per symbol."
    )
    daily_loss_limit: Decimal = Field(
        Decimal("5000"), description="Maximum daily realized + unrealized loss before trading halt."
    )
    require_confirmation: bool = Field(
        True, description="Require human confirmation callback before order execution."
    )


class ContractSpec(BaseModel):
    """Unified contract specification for IBKR instruments."""

    symbol: str = Field(..., description="Ticker symbol (e.g. AAPL, ES, BTC).")
    sec_type: str = Field(
        "STK", description="Security type: STK, OPT, FUT, CASH, CRYPTO."
    )
    exchange: str = Field(
        "SMART", description="Exchange (e.g. SMART, NYSE, GLOBEX, CBOE)."
    )
    currency: str = Field("USD", description="Currency.")


class Quote(BaseModel):
    """Real-time quote data for a contract."""

    symbol: str = Field(..., description="Ticker symbol.")
    last: Optional[Decimal] = Field(None, description="Last traded price.")
    bid: Optional[Decimal] = Field(None, description="Current bid price.")
    ask: Optional[Decimal] = Field(None, description="Current ask price.")
    volume: Optional[int] = Field(None, description="Trading volume.")
    timestamp: Optional[datetime] = Field(None, description="Quote timestamp.")


class BarData(BaseModel):
    """Historical OHLCV bar."""

    timestamp: datetime = Field(..., description="Bar timestamp.")
    open: Decimal = Field(..., description="Opening price.")
    high: Decimal = Field(..., description="High price.")
    low: Decimal = Field(..., description="Low price.")
    close: Decimal = Field(..., description="Closing price.")
    volume: int = Field(..., description="Bar volume.")


class OrderRequest(BaseModel):
    """Order placement request with validation."""

    symbol: str = Field(..., description="Ticker symbol.")
    action: Literal["BUY", "SELL"] = Field(
        ..., description="Order action: BUY or SELL."
    )
    quantity: int = Field(..., gt=0, description="Order quantity (must be > 0).")
    order_type: Literal["MKT", "LMT", "STP", "STP_LMT"] = Field(
        "LMT", description="Order type: MKT, LMT, STP, or STP_LMT."
    )
    limit_price: Optional[Decimal] = Field(
        None, description="Limit price (required for LMT and STP_LMT orders)."
    )
    stop_price: Optional[Decimal] = Field(
        None, description="Stop trigger price (required for STP and STP_LMT orders)."
    )
    tif: Literal["DAY", "GTC", "IOC", "FOK"] = Field(
        "DAY", description="Time in force: DAY, GTC, IOC, or FOK."
    )


class OrderStatus(BaseModel):
    """Order status response from IBKR."""

    order_id: int = Field(..., description="IBKR order ID.")
    symbol: str = Field(..., description="Ticker symbol.")
    action: str = Field(..., description="Order action (BUY/SELL).")
    quantity: int = Field(..., description="Total order quantity.")
    filled: int = Field(0, description="Quantity filled.")
    remaining: int = Field(0, description="Quantity remaining.")
    avg_fill_price: Optional[Decimal] = Field(
        None, description="Average fill price."
    )
    status: str = Field(..., description="Order status (e.g. Submitted, Filled, Cancelled).")
    timestamp: Optional[datetime] = Field(None, description="Status update timestamp.")


class Position(BaseModel):
    """Account position for a single instrument."""

    symbol: str = Field(..., description="Ticker symbol.")
    quantity: int = Field(..., description="Position size (negative for short).")
    avg_cost: Decimal = Field(..., description="Average cost basis per share.")
    market_value: Optional[Decimal] = Field(None, description="Current market value.")
    unrealized_pnl: Optional[Decimal] = Field(None, description="Unrealized P&L.")
    realized_pnl: Optional[Decimal] = Field(None, description="Realized P&L.")


class AccountSummary(BaseModel):
    """Account summary information."""

    account_id: str = Field(..., description="IBKR account ID.")
    net_liquidation: Decimal = Field(..., description="Net liquidation value.")
    total_cash: Decimal = Field(..., description="Total cash balance.")
    buying_power: Decimal = Field(..., description="Available buying power.")
    gross_position_value: Decimal = Field(..., description="Gross position value.")
    unrealized_pnl: Decimal = Field(..., description="Total unrealized P&L.")
    realized_pnl: Decimal = Field(..., description="Total realized P&L.")
