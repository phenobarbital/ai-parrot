"""
Analyst Agents
"""
from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    ANALYST_MACRO,
    ANALYST_EQUITY,
    ANALYST_CRYPTO,
    ANALYST_SENTIMENT,
    ANALYST_RISK,
    MODEL_RECOMMENDATIONS,
)


def create_macro_analyst() -> Agent:
    """Macroeconomic analyst - big picture analysis."""
    return Agent(
        name="Macro Analyst",
        agent_id="macro_analyst",
        llm=MODEL_RECOMMENDATIONS["macro_analyst"]["model"],
        system_prompt=ANALYST_MACRO,
        use_tools=True,
        instructions=(
            "Analyze macroeconomic conditions and translate them into "
            "actionable market views across all asset classes."
        ),
    )


def create_equity_analyst() -> Agent:
    """Equity and ETF analyst - fundamental and technical analysis."""
    return Agent(
        name="Equity & ETF Analyst",
        agent_id="equity_analyst",
        llm=MODEL_RECOMMENDATIONS["equity_analyst"]["model"],
        system_prompt=ANALYST_EQUITY,
        use_tools=True,
        instructions=(
            "Identify specific stock and ETF opportunities based on "
            "fundamental analysis, technical signals, and sector dynamics."
        ),
    )


def create_crypto_analyst() -> Agent:
    """Crypto and DeFi analyst - on-chain analysis."""
    return Agent(
        name="Crypto & DeFi Analyst",
        agent_id="crypto_analyst",
        llm=MODEL_RECOMMENDATIONS["crypto_analyst"]["model"],
        system_prompt=ANALYST_CRYPTO,
        use_tools=True,
        instructions=(
            "Analyze cryptocurrency markets using on-chain data, tokenomics, "
            "and market microstructure."
        ),
    )


def create_sentiment_analyst() -> Agent:
    """Sentiment and flow analyst - market psychology."""
    return Agent(
        name="Sentiment & Flow Analyst",
        agent_id="sentiment_analyst",
        llm=MODEL_RECOMMENDATIONS["sentiment_analyst"]["model"],
        system_prompt=ANALYST_SENTIMENT,
        use_tools=True,
        instructions=(
            "Read the market's mood and positioning. Detect when the crowd "
            "is too bullish, too bearish, or about to shift."
        ),
    )


def create_risk_analyst() -> Agent:
    """Risk and quantitative analyst - portfolio risk management."""
    return Agent(
        name="Risk & Quantitative Analyst",
        agent_id="risk_analyst",
        llm=MODEL_RECOMMENDATIONS["risk_analyst"]["model"],
        system_prompt=ANALYST_RISK,
        use_tools=True,
        instructions=(
            "Assess and quantify the risks of opportunities, ensure the "
            "portfolio remains within safe parameters."
        ),
    )


def create_all_analysts() -> dict[str, Agent]:
    """Create all analyst agents."""
    return {
        "macro": create_macro_analyst(),
        "equity": create_equity_analyst(),
        "crypto": create_crypto_analyst(),
        "sentiment": create_sentiment_analyst(),
        "risk": create_risk_analyst(),
    }
