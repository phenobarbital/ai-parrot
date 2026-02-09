"""
Monitoring Agents
"""
from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    PORTFOLIO_MANAGER,
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
from parrot.finance.agents.performance_tracker import create_performance_tracker


def create_portfolio_manager() -> Agent:
    """Portfolio manager - enforces stop-loss and take-profit rules."""
    # Can close positions on ALL platforms but cannot open new ones
    capabilities = AgentCapabilityProfile(
        agent_id="portfolio_manager",
        role="portfolio_manager",
        capabilities={
            Capability.READ_MARKET_DATA,
            Capability.READ_PORTFOLIO,
            Capability.CLOSE_POSITION,
            Capability.SET_STOP_LOSS,
            Capability.SET_TAKE_PROFIT,
            Capability.CANCEL_ORDER,
            Capability.SEND_MESSAGE,
        },
        platforms=[Platform.ALPACA, Platform.BINANCE, Platform.KRAKEN],
        asset_classes=[AssetClass.STOCK, AssetClass.ETF, AssetClass.CRYPTO],
        constraints=ExecutorConstraints(
            max_order_pct=0.0,  # Cannot open positions
            max_order_value_usd=0.0,
            allowed_order_types=[],
            max_daily_trades=100,  # Can close many positions
            max_daily_volume_usd=999999.0,
            max_positions=999,
            max_exposure_pct=100.0,
            max_asset_class_exposure_pct=100.0,
            min_consensus=ConsensusLevel.DIVIDED,  # No consensus needed for mechanical rules
            max_daily_loss_pct=5.0,
            max_drawdown_pct=15.0,
        ),
    )

    agent = Agent(
        name="Portfolio Manager",
        agent_id="portfolio_manager",
        llm=MODEL_RECOMMENDATIONS["portfolio_manager"]["model"],
        system_prompt=PORTFOLIO_MANAGER,
        use_tools=True,
        instructions=(
            "Monitor all open positions and execute mechanical exit rules. "
            "Protect the portfolio by enforcing stop-losses and take-profits."
        ),
    )
    agent.capabilities = capabilities
    return agent


def create_all_monitoring_agents() -> dict[str, Agent]:
    """Create all monitoring agents."""
    return {
        "portfolio_manager": create_portfolio_manager(),
        "performance_tracker": create_performance_tracker(),
    }
