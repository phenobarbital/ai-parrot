"""Factory functions to wire write toolkits into executor agents and the orchestrator."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Type
from navconfig.logging import logging

from ..schemas import (
    AssetClass,
    Platform,
    Capability,
    AgentCapabilityProfile,
    ExecutorConstraints,
)
from .alpaca_write import AlpacaWriteToolkit
from .binance_write import BinanceWriteToolkit
from .bybit_write import BybitWriteToolkit
from .kraken_write import KrakenWriteToolkit
from .ibkr_write import IBKRWriteToolkit

logger = logging.getLogger("finance.execution_integration")


# =============================================================================
# Toolkit factories
# =============================================================================

def create_alpaca_write_toolkit(**kwargs) -> AlpacaWriteToolkit:
    """Create an AlpacaWriteToolkit with default (navconfig) settings."""
    return AlpacaWriteToolkit(**kwargs)


def create_binance_write_toolkit(**kwargs) -> BinanceWriteToolkit:
    """Create a BinanceWriteToolkit with default settings."""
    return BinanceWriteToolkit(**kwargs)


def create_bybit_write_toolkit(**kwargs) -> BybitWriteToolkit:
    """Create a BybitWriteToolkit with default settings."""
    return BybitWriteToolkit(**kwargs)


def create_kraken_write_toolkit(**kwargs) -> KrakenWriteToolkit:
    """Create a KrakenWriteToolkit with default settings."""
    return KrakenWriteToolkit(**kwargs)


def create_ibkr_write_toolkit(**kwargs) -> IBKRWriteToolkit:
    """Create an IBKRWriteToolkit with default settings."""
    return IBKRWriteToolkit(**kwargs)


# =============================================================================
# Executor capability profiles
# =============================================================================

STOCK_EXECUTOR_PROFILE = AgentCapabilityProfile(
    agent_id="stock_executor",
    role="stock_executor",
    capabilities={
        Capability.READ_MARKET_DATA,
        Capability.READ_PORTFOLIO,
        Capability.PLACE_ORDER_STOCK,
        Capability.CANCEL_ORDER,
        Capability.MODIFY_ORDER,
        Capability.SET_STOP_LOSS,
        Capability.SET_TAKE_PROFIT,
        Capability.CLOSE_POSITION,
    },
    platforms=[Platform.ALPACA, Platform.IBKR],
    asset_classes=[AssetClass.STOCK, AssetClass.ETF],
    constraints=ExecutorConstraints(
        max_order_value_usd=50_000,
        max_daily_trades=100,
        max_order_pct=10.0,
        allowed_order_types=["limit", "stop", "stop_limit", "trailing_stop"],
    ),
)

CRYPTO_EXECUTOR_PROFILE = AgentCapabilityProfile(
    agent_id="crypto_executor",
    role="crypto_executor",
    capabilities={
        Capability.READ_MARKET_DATA,
        Capability.READ_PORTFOLIO,
        Capability.PLACE_ORDER_CRYPTO,
        Capability.CANCEL_ORDER,
        Capability.MODIFY_ORDER,
        Capability.SET_STOP_LOSS,
        Capability.SET_TAKE_PROFIT,
        Capability.CLOSE_POSITION,
    },
    platforms=[Platform.BINANCE, Platform.BYBIT, Platform.KRAKEN],
    asset_classes=[AssetClass.CRYPTO],
    constraints=ExecutorConstraints(
        max_order_value_usd=25_000,
        max_daily_trades=200,
        max_order_pct=8.0,
        allowed_order_types=["limit", "stop_limit", "stop_market"],
    ),
)


# =============================================================================
# Routing map
# =============================================================================

PLATFORM_ROUTING = {
    # STOCK/ETF routing: Alpaca primary, IBKR fallback
    AssetClass.STOCK: [Platform.ALPACA, Platform.IBKR],
    AssetClass.ETF: [Platform.ALPACA, Platform.IBKR],
    # CRYPTO routing: Binance primary, Bybit + Kraken fallbacks
    AssetClass.CRYPTO: [Platform.BINANCE, Platform.BYBIT, Platform.KRAKEN],
}


def get_routing_for_asset(asset_class: AssetClass) -> List[Platform]:
    """Return the platform priority list for a given asset class."""
    return PLATFORM_ROUTING.get(asset_class, [])


# =============================================================================
# Agent factories
# =============================================================================

def create_stock_executor_toolkits() -> Dict[Platform, Any]:
    """Create toolkit instances for the stock executor."""
    toolkits: Dict[Platform, Any] = {}
    try:
        toolkits[Platform.ALPACA] = create_alpaca_write_toolkit()
        logger.info("AlpacaWriteToolkit created for stock_executor.")
    except Exception as exc:
        logger.warning(f"AlpacaWriteToolkit init failed: {exc}")
    try:
        toolkits[Platform.IBKR] = create_ibkr_write_toolkit()
        logger.info("IBKRWriteToolkit created for stock_executor (fallback).")
    except Exception as exc:
        logger.warning(f"IBKRWriteToolkit init failed: {exc}")
    return toolkits


def create_crypto_executor_toolkits() -> Dict[Platform, Any]:
    """Create toolkit instances for the crypto executor."""
    toolkits: Dict[Platform, Any] = {}
    try:
        toolkits[Platform.BINANCE] = create_binance_write_toolkit()
        logger.info("BinanceWriteToolkit created for crypto_executor.")
    except Exception as exc:
        logger.warning(f"BinanceWriteToolkit init failed: {exc}")
    try:
        toolkits[Platform.BYBIT] = create_bybit_write_toolkit()
        logger.info("BybitWriteToolkit created for crypto_executor (fallback).")
    except Exception as exc:
        logger.warning(f"BybitWriteToolkit init failed: {exc}")
    try:
        toolkits[Platform.KRAKEN] = create_kraken_write_toolkit()
        logger.info("KrakenWriteToolkit created for crypto_executor (fallback).")
    except Exception as exc:
        logger.warning(f"KrakenWriteToolkit init failed: {exc}")
    return toolkits


def create_all_executor_toolkits() -> Dict[str, Dict[Platform, Any]]:
    """Create all executor toolkit sets."""
    return {
        "stock_executor": create_stock_executor_toolkits(),
        "crypto_executor": create_crypto_executor_toolkits(),
    }


# =============================================================================
# Orchestrator factory
# =============================================================================

def create_full_execution_orchestrator(
    agent_class: Optional[Type] = None,
    custom_stock_profile: Optional[AgentCapabilityProfile] = None,
    custom_crypto_profile: Optional[AgentCapabilityProfile] = None,
) -> Dict[str, Any]:
    """Create a complete execution orchestrator configuration.

    Returns a dict with:
        - toolkits: {executor_id: {Platform: toolkit_instance}}
        - profiles: {executor_id: AgentCapabilityProfile}
        - routing: {AssetClass: [Platform, ...]}
    """
    toolkits = create_all_executor_toolkits()
    profiles = {
        "stock_executor": custom_stock_profile or STOCK_EXECUTOR_PROFILE,
        "crypto_executor": custom_crypto_profile or CRYPTO_EXECUTOR_PROFILE,
    }
    routing = dict(PLATFORM_ROUTING)

    logger.info(
        f"Execution orchestrator ready. "
        f"Stock platforms: {[str(p) for p in toolkits.get('stock_executor', {})]}, "
        f"Crypto platforms: {[str(p) for p in toolkits.get('crypto_executor', {})]}"
    )

    return {
        "toolkits": toolkits,
        "profiles": profiles,
        "routing": routing,
    }
