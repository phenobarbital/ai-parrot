"""
Research Crews
"""
from parrot.bots.agent import Agent
from parrot.finance.prompts import (
    RESEARCH_CREW_MACRO,
    RESEARCH_CREW_EQUITY,
    RESEARCH_CREW_CRYPTO,
    RESEARCH_CREW_SENTIMENT,
    RESEARCH_CREW_RISK,
    MODEL_RECOMMENDATIONS,
)

def create_macro_research_crew() -> Agent:
    """Research crew for macroeconomic data collection."""
    return Agent(
        name="Macro Research Crew",
        agent_id="research_crew_macro",
        llm=MODEL_RECOMMENDATIONS["research_crew_macro"]["model"],
        system_prompt=RESEARCH_CREW_MACRO,
        use_tools=True,
        instructions="Collect and summarize macroeconomic data and news.",
    )


def create_equity_research_crew() -> Agent:
    """Research crew for equity and ETF data collection."""
    return Agent(
        name="Equity Research Crew",
        agent_id="research_crew_equity",
        llm=MODEL_RECOMMENDATIONS["research_crew_equity"]["model"],
        system_prompt=RESEARCH_CREW_EQUITY,
        use_tools=True,
        instructions="Collect and summarize stock market data and earnings reports.",
    )


def create_crypto_research_crew() -> Agent:
    """Research crew for cryptocurrency data collection."""
    return Agent(
        name="Crypto Research Crew",
        agent_id="research_crew_crypto",
        llm=MODEL_RECOMMENDATIONS["research_crew_crypto"]["model"],
        system_prompt=RESEARCH_CREW_CRYPTO,
        use_tools=True,
        instructions="Collect and summarize crypto market data and on-chain metrics.",
    )


def create_sentiment_research_crew() -> Agent:
    """Research crew for sentiment and flow data collection."""
    return Agent(
        name="Sentiment Research Crew",
        agent_id="research_crew_sentiment",
        llm=MODEL_RECOMMENDATIONS["research_crew_sentiment"]["model"],
        system_prompt=RESEARCH_CREW_SENTIMENT,
        use_tools=True,
        instructions="Collect and summarize market sentiment and flow data.",
    )


def create_risk_research_crew() -> Agent:
    """Research crew for risk metrics calculation."""
    return Agent(
        name="Risk Research Crew",
        agent_id="research_crew_risk",
        llm=MODEL_RECOMMENDATIONS["research_crew_risk"]["model"],
        system_prompt=RESEARCH_CREW_RISK,
        use_tools=True,
        instructions="Calculate and monitor portfolio risk metrics.",
    )


def create_all_research_crews() -> dict[str, Agent]:
    """Create all research crew agents."""
    return {
        "macro": create_macro_research_crew(),
        "equity": create_equity_research_crew(),
        "crypto": create_crypto_research_crew(),
        "sentiment": create_sentiment_research_crew(),
        "risk": create_risk_research_crew(),
    }
