"""Abstract backend interface for IBKR connections.

Defines the contract that both TWSBackend and PortalBackend must implement.
The IBKRToolkit delegates all operations to whichever backend is configured.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from navconfig.logging import logging

from .models import (
    AccountSummary,
    BarData,
    ContractSpec,
    IBKRConfig,
    OrderRequest,
    OrderStatus,
    Position,
    Quote,
)


class IBKRBackend(ABC):
    """Abstract base class for IBKR connection backends.

    Subclasses must implement all abstract methods to provide a complete
    IBKR integration via either TWS API or Client Portal REST API.
    """

    def __init__(self, config: IBKRConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    # ── Connection ───────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to IBKR."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection gracefully."""

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if currently connected to IBKR."""

    # ── Market Data ──────────────────────────────────────────────

    @abstractmethod
    async def get_quote(self, contract: ContractSpec) -> Quote:
        """Get real-time quote snapshot for a contract."""

    @abstractmethod
    async def get_historical_bars(
        self,
        contract: ContractSpec,
        duration: str,
        bar_size: str,
    ) -> list[BarData]:
        """Get historical OHLCV bars for a contract."""

    @abstractmethod
    async def get_options_chain(
        self, symbol: str, expiry: Optional[str] = None
    ) -> list[dict]:
        """Get options chain for an underlying symbol."""

    @abstractmethod
    async def search_contracts(
        self, pattern: str, sec_type: str = "STK"
    ) -> list[dict]:
        """Search for contracts matching a pattern."""

    @abstractmethod
    async def run_scanner(
        self, scan_code: str, num_results: int = 25
    ) -> list[dict]:
        """Run an IBKR market scanner."""

    # ── Order Management ─────────────────────────────────────────

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderStatus:
        """Place a new order."""

    @abstractmethod
    async def modify_order(self, order_id: int, **changes) -> OrderStatus:
        """Modify an existing open order."""

    @abstractmethod
    async def cancel_order(self, order_id: int) -> dict:
        """Cancel an open order."""

    @abstractmethod
    async def get_open_orders(self) -> list[OrderStatus]:
        """Get all currently open orders."""

    # ── Account & Portfolio ──────────────────────────────────────

    @abstractmethod
    async def get_account_summary(self) -> AccountSummary:
        """Get account summary information."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all current positions."""

    @abstractmethod
    async def get_pnl(self) -> dict:
        """Get daily P&L breakdown."""

    @abstractmethod
    async def get_trades(self, days: int = 1) -> list[dict]:
        """Get recent trade executions."""

    # ── Info ─────────────────────────────────────────────────────

    @abstractmethod
    async def get_news(
        self, symbol: Optional[str] = None, num_articles: int = 5
    ) -> list[dict]:
        """Get market news, optionally filtered by symbol."""

    @abstractmethod
    async def get_fundamentals(self, symbol: str) -> dict:
        """Get fundamental data for a symbol."""
