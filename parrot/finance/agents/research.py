"""
Research Crews
==============

Research crew agents with deduplication support.

Each crew:
1. Checks if research exists for current period before executing
2. Executes research only if no existing research found
3. Stores research to collective memory after completion

The deduplication tools (`check_research_exists`, `store_research`) are
automatically added to each crew and the prompts include instructions
on how to use them.
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
from parrot.finance.research.memory import (
    check_research_exists,
    store_research,
)


def _get_dedup_tools() -> list:
    """Get the deduplication tools for research crews.

    Returns:
        List containing check_research_exists and store_research tools.
    """
    return [check_research_exists, store_research]

def create_macro_research_crew(tools: list | None = None) -> Agent:
    """Research crew for macroeconomic data collection.

    Args:
        tools: Additional tools to provide. Deduplication tools are
            always included automatically.

    Returns:
        Agent configured for macro research with deduplication.
    """
    all_tools = _get_dedup_tools() + (tools or [])
    return Agent(
        name="Macro Research Crew",
        agent_id="research_crew_macro",
        llm=MODEL_RECOMMENDATIONS["research_crew_macro"]["model"],
        system_prompt=RESEARCH_CREW_MACRO,
        tools=all_tools,
        use_tools=True,
        instructions="Collect and summarize macroeconomic data and news.",
    )


def create_equity_research_crew(tools: list | None = None) -> Agent:
    """Research crew for equity and ETF data collection.

    Args:
        tools: Additional tools to provide. Deduplication tools are
            always included automatically.

    Returns:
        Agent configured for equity research with deduplication.
    """
    all_tools = _get_dedup_tools() + (tools or [])
    return Agent(
        name="Equity Research Crew",
        agent_id="research_crew_equity",
        llm=MODEL_RECOMMENDATIONS["research_crew_equity"]["model"],
        system_prompt=RESEARCH_CREW_EQUITY,
        tools=all_tools,
        use_tools=True,
        instructions="Collect and summarize stock market data and earnings reports.",
    )


def create_crypto_research_crew(tools: list | None = None) -> Agent:
    """Research crew for cryptocurrency data collection.

    Args:
        tools: Additional tools to provide. Deduplication tools are
            always included automatically.

    Returns:
        Agent configured for crypto research with deduplication.
    """
    all_tools = _get_dedup_tools() + (tools or [])
    return Agent(
        name="Crypto Research Crew",
        agent_id="research_crew_crypto",
        llm=MODEL_RECOMMENDATIONS["research_crew_crypto"]["model"],
        system_prompt=RESEARCH_CREW_CRYPTO,
        tools=all_tools,
        use_tools=True,
        instructions="Collect and summarize crypto market data and on-chain metrics.",
    )


def create_sentiment_research_crew(tools: list | None = None) -> Agent:
    """Research crew for sentiment and flow data collection.

    Args:
        tools: Additional tools to provide. Deduplication tools are
            always included automatically.

    Returns:
        Agent configured for sentiment research with deduplication.
    """
    all_tools = _get_dedup_tools() + (tools or [])
    return Agent(
        name="Sentiment Research Crew",
        agent_id="research_crew_sentiment",
        llm=MODEL_RECOMMENDATIONS["research_crew_sentiment"]["model"],
        system_prompt=RESEARCH_CREW_SENTIMENT,
        tools=all_tools,
        use_tools=True,
        instructions="Collect and summarize market sentiment and flow data.",
    )


def create_risk_research_crew(tools: list | None = None) -> Agent:
    """Research crew for risk metrics calculation.

    Args:
        tools: Additional tools to provide. Deduplication tools are
            always included automatically.

    Returns:
        Agent configured for risk research with deduplication.
    """
    all_tools = _get_dedup_tools() + (tools or [])
    return Agent(
        name="Risk Research Crew",
        agent_id="research_crew_risk",
        llm=MODEL_RECOMMENDATIONS["research_crew_risk"]["model"],
        system_prompt=RESEARCH_CREW_RISK,
        tools=all_tools,
        use_tools=True,
        instructions="Calculate and monitor portfolio risk metrics.",
    )


def create_all_research_crews(
    additional_tools: dict[str, list] | None = None,
) -> dict[str, Agent]:
    """Create all research crew agents with deduplication tools.

    Args:
        additional_tools: Optional dict mapping crew domain to additional tools.
            Example: {"macro": [fred_tool], "crypto": [binance_tool]}

    Returns:
        Dict mapping domain name to Agent instance.
    """
    additional_tools = additional_tools or {}
    return {
        "macro": create_macro_research_crew(additional_tools.get("macro")),
        "equity": create_equity_research_crew(additional_tools.get("equity")),
        "crypto": create_crypto_research_crew(additional_tools.get("crypto")),
        "sentiment": create_sentiment_research_crew(additional_tools.get("sentiment")),
        "risk": create_risk_research_crew(additional_tools.get("risk")),
    }


def create_research_crew(
    crew_id: str,
    domain: str,
    tools: list | None = None,
) -> Agent:
    """Create a single research crew by crew_id.

    Args:
        crew_id: Full crew identifier (e.g., "research_crew_macro")
        domain: Research domain (e.g., "macro")
        tools: Additional tools to provide.

    Returns:
        Agent configured for the specified domain.

    Raises:
        ValueError: If crew_id is not recognized.
    """
    creators = {
        "research_crew_macro": create_macro_research_crew,
        "research_crew_equity": create_equity_research_crew,
        "research_crew_crypto": create_crypto_research_crew,
        "research_crew_sentiment": create_sentiment_research_crew,
        "research_crew_risk": create_risk_research_crew,
    }
    if crew_id not in creators:
        raise ValueError(
            f"Unknown crew_id: {crew_id}. "
            f"Valid options: {list(creators.keys())}"
        )
    return creators[crew_id](tools)
