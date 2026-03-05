"""
Paper Trading Module
====================

Provides paper-trading and dry-run execution modes for the finance module.
Enables safe testing of trading strategies without real capital.

Components:
    - ExecutionMode: Enum for LIVE, PAPER, DRY_RUN modes
    - PaperTradingConfig: Configuration for paper trading behavior
    - PaperTradingMixin: Mixin class for toolkit paper-trading awareness
    - SimulatedOrder/Position/Fill: Data models for virtual execution
    - VirtualPortfolioState: Complete portfolio snapshot
    - VirtualPortfolio: Local simulation engine for DRY_RUN mode

Example:
    >>> from parrot.finance.paper_trading import (
    ...     ExecutionMode,
    ...     PaperTradingConfig,
    ...     VirtualPortfolio,
    ... )
    >>> config = PaperTradingConfig(
    ...     mode=ExecutionMode.DRY_RUN,
    ...     simulate_slippage_bps=10,
    ... )
    >>> portfolio = VirtualPortfolio(slippage_bps=config.simulate_slippage_bps)
"""

from .mixin import PaperTradingMixin
from .models import (
    ExecutionMode,
    PaperTradingConfig,
    SimulatedFill,
    SimulatedOrder,
    SimulatedPosition,
    SimulationDetails,
    VirtualPortfolioState,
)
from .portfolio import VirtualPortfolio

__all__ = [
    # Enums and config
    "ExecutionMode",
    "PaperTradingConfig",
    # Mixin for toolkits
    "PaperTradingMixin",
    # Data models
    "SimulatedFill",
    "SimulatedOrder",
    "SimulatedPosition",
    "SimulationDetails",
    "VirtualPortfolioState",
    # Portfolio engine
    "VirtualPortfolio",
]
