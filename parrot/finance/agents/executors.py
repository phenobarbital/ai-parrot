"""
Executor Agents
"""
from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    EXECUTOR_STOCK,
    EXECUTOR_CRYPTO,
    EXECUTOR_GENERAL,
    MODEL_RECOMMENDATIONS,
)
from parrot.finance.schemas import (
    Platform,
    AssetClass,
    Capability,
    AgentCapabilityProfile,
    ExecutorConstraints,
    ConsensusLevel,
)


def create_stock_executor() -> Agent:
    """Stock execution agent for Alpaca platform."""
    # Define capabilities
    capabilities = AgentCapabilityProfile(
        agent_id="stock_executor",
        role="stock_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.PLACE_ORDER_STOCK,
            Capability.CANCEL_ORDER,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.SEND_MESSAGE,
        },
        platforms=[Platform.ALPACA],
        asset_classes=[AssetClass.STOCK, AssetClass.ETF],
        constraints=ExecutorConstraints(
            max_order_pct=2.0,
            max_order_value_usd=500.0,
            allowed_order_types=["limit"],
            max_daily_trades=10,
            max_daily_volume_usd=2000.0,
            max_positions=10,
            max_exposure_pct=70.0,
            max_asset_class_exposure_pct=40.0,
            min_consensus=ConsensusLevel.MAJORITY,
            max_daily_loss_pct=5.0,
            max_drawdown_pct=15.0,
        ),
    )

    agent = Agent(
        name="Stock Executor (Alpaca)",
        agent_id="stock_executor",
        llm=MODEL_RECOMMENDATIONS["stock_executor"]["model"],
        system_prompt=EXECUTOR_STOCK,
        use_tools=True,
        instructions=(
            "Execute trading orders on Alpaca for stocks and ETFs. "
            "Verify constraints and enforce safety rules."
        ),
    )
    # Attach capability profile as metadata
    agent.capabilities = capabilities
    return agent


def create_crypto_executor_binance() -> Agent:
    """Crypto execution agent for Binance platform."""
    # Define capabilities with more conservative crypto constraints
    capabilities = AgentCapabilityProfile(
        agent_id="crypto_executor_binance",
        role="crypto_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.PLACE_ORDER_CRYPTO,
            Capability.CANCEL_ORDER,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.SEND_MESSAGE,
        },
        platforms=[Platform.BINANCE],
        asset_classes=[AssetClass.CRYPTO],
        constraints=ExecutorConstraints(
            max_order_pct=1.5,  # More conservative for crypto
            max_order_value_usd=300.0,
            allowed_order_types=["limit"],
            max_daily_trades=8,
            max_daily_volume_usd=1500.0,
            max_positions=8,
            max_exposure_pct=60.0,
            max_asset_class_exposure_pct=30.0,  # Lower crypto exposure
            min_consensus=ConsensusLevel.STRONG_MAJORITY,  # Higher consensus required
            max_daily_loss_pct=4.0,
            max_drawdown_pct=12.0,
        ),
    )

    agent = Agent(
        name="Crypto Executor (Binance)",
        agent_id="crypto_executor_binance",
        llm=MODEL_RECOMMENDATIONS["crypto_executor"]["model"],
        system_prompt=EXECUTOR_CRYPTO,
        use_tools=True,
        instructions=(
            "Execute crypto trading orders on Binance. "
            "Extra caution for high-volatility crypto environment."
        ),
    )
    agent.capabilities = capabilities
    return agent


def create_crypto_executor_kraken() -> Agent:
    """Crypto execution agent for Kraken platform."""
    capabilities = AgentCapabilityProfile(
        agent_id="crypto_executor_kraken",
        role="crypto_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.PLACE_ORDER_CRYPTO,
            Capability.CANCEL_ORDER,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.SEND_MESSAGE,
        },
        platforms=[Platform.KRAKEN],
        asset_classes=[AssetClass.CRYPTO],
        constraints=ExecutorConstraints(
            max_order_pct=1.5,
            max_order_value_usd=300.0,
            allowed_order_types=["limit"],
            max_daily_trades=8,
            max_daily_volume_usd=1500.0,
            max_positions=8,
            max_exposure_pct=60.0,
            max_asset_class_exposure_pct=30.0,
            min_consensus=ConsensusLevel.STRONG_MAJORITY,
            max_daily_loss_pct=4.0,
            max_drawdown_pct=12.0,
        ),
    )

    agent = Agent(
        name="Crypto Executor (Kraken)",
        agent_id="crypto_executor_kraken",
        llm=MODEL_RECOMMENDATIONS["crypto_executor"]["model"],
        system_prompt=EXECUTOR_CRYPTO,
        use_tools=True,
        instructions=(
            "Execute crypto trading orders on Kraken. "
            "Extra caution for high-volatility crypto environment."
        ),
    )
    agent.capabilities = capabilities
    return agent


def create_general_executor() -> Agent:
    """General executor for cross-platform coordination."""
    capabilities = AgentCapabilityProfile(
        agent_id="general_executor",
        role="general_executor",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.SEND_MESSAGE,
        },
        platforms=[],  # No direct platform access
        asset_classes=[],
        constraints=None,  # No execution constraints (read-only)
    )

    agent = Agent(
        name="General Executor",
        agent_id="general_executor",
        llm=MODEL_RECOMMENDATIONS["stock_executor"]["model"],
        system_prompt=EXECUTOR_GENERAL,
        use_tools=True,
        instructions=(
            "Route orders to the appropriate platform-specific executor "
            "based on asset class and platform availability."
        ),
    )
    agent.capabilities = capabilities
    return agent


def create_all_executors() -> dict[str, Agent]:
    """Create all executor agents."""
    return {
        "stock": create_stock_executor(),
        "crypto_binance": create_crypto_executor_binance(),
        "crypto_kraken": create_crypto_executor_kraken(),
        "general": create_general_executor(),
    }
