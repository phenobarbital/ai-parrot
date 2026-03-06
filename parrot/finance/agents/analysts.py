"""
Analyst Agents
==============

Analyst agents with research query tools for pull-based research access.

Each analyst:
1. Has query tools to pull research from collective memory
2. Can access their primary domain's research
3. Can cross-pollinate by accessing other domains' research
4. Can compare current vs historical research
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
from parrot.finance.research.memory import (
    get_latest_research,
    get_research_history,
    get_cross_domain_research,
)
from parrot.finance.schemas import InvestmentPolicyStatement


def _get_query_tools() -> list:
    """Get the query tools for analyst agents.

    Returns:
        List containing research query tools for pulling from collective memory.
    """
    return [get_latest_research, get_research_history, get_cross_domain_research]


def _get_prediction_market_tools() -> list:
    """Get prediction market tools (Polymarket + Kalshi probability signals).

    Returns:
        List of prediction market tools, or empty list if toolkit unavailable.
    """
    try:
        from parrot.tools.prediction_market import PredictionMarketToolkit
        return PredictionMarketToolkit().get_tools()
    except Exception:
        return []


def _apply_ips(base_prompt: str, ips: InvestmentPolicyStatement | None) -> str:
    """Append IPS block to a system prompt when provided.

    Args:
        base_prompt: The static baseline system prompt constant.
        ips: Optional investment policy statement to inject.

    Returns:
        Unmodified ``base_prompt`` when ``ips`` is None or produces no block;
        otherwise ``base_prompt`` with the ``<investment_policy>`` block appended.
    """
    if ips is None:
        return base_prompt
    block = ips.to_prompt_block()
    if not block:
        return base_prompt
    return base_prompt + "\n\n" + block


def create_macro_analyst(
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    """Macroeconomic analyst - big picture analysis.

    Args:
        tools: Additional tools to provide. Query tools are
            always included automatically.
        ips: Optional investment policy statement injected into the system prompt.

    Returns:
        Agent configured for macro analysis with query tools.
    """
    all_tools = _get_query_tools() + _get_prediction_market_tools() + (tools or [])
    return Agent(
        name="Macro Analyst",
        agent_id="macro_analyst",
        llm=MODEL_RECOMMENDATIONS["macro_analyst"]["model"],
        system_prompt=_apply_ips(ANALYST_MACRO, ips),
        tools=all_tools,
        use_tools=True,
        instructions=(
            "Analyze macroeconomic conditions and translate them into "
            "actionable market views across all asset classes."
        ),
    )


def create_equity_analyst(
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    """Equity and ETF analyst - fundamental and technical analysis.

    Args:
        tools: Additional tools to provide. Query tools are
            always included automatically.
        ips: Optional investment policy statement injected into the system prompt.

    Returns:
        Agent configured for equity analysis with query tools.
    """
    all_tools = _get_query_tools() + _get_prediction_market_tools() + (tools or [])
    return Agent(
        name="Equity & ETF Analyst",
        agent_id="equity_analyst",
        llm=MODEL_RECOMMENDATIONS["equity_analyst"]["model"],
        system_prompt=_apply_ips(ANALYST_EQUITY, ips),
        tools=all_tools,
        use_tools=True,
        instructions=(
            "Identify specific stock and ETF opportunities based on "
            "fundamental analysis, technical signals, and sector dynamics."
        ),
    )


def create_crypto_analyst(
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    """Crypto and DeFi analyst - on-chain analysis.

    Args:
        tools: Additional tools to provide. Query tools are
            always included automatically.
        ips: Optional investment policy statement injected into the system prompt.

    Returns:
        Agent configured for crypto analysis with query tools.
    """
    all_tools = _get_query_tools() + _get_prediction_market_tools() + (tools or [])
    return Agent(
        name="Crypto & DeFi Analyst",
        agent_id="crypto_analyst",
        llm=MODEL_RECOMMENDATIONS["crypto_analyst"]["model"],
        system_prompt=_apply_ips(ANALYST_CRYPTO, ips),
        tools=all_tools,
        use_tools=True,
        instructions=(
            "Analyze cryptocurrency markets using on-chain data, tokenomics, "
            "and market microstructure."
        ),
    )


def create_sentiment_analyst(
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    """Sentiment and flow analyst - market psychology.

    Args:
        tools: Additional tools to provide. Query tools are
            always included automatically.
        ips: Optional investment policy statement injected into the system prompt.

    Returns:
        Agent configured for sentiment analysis with query tools.
    """
    all_tools = _get_query_tools() + _get_prediction_market_tools() + (tools or [])
    return Agent(
        name="Sentiment & Flow Analyst",
        agent_id="sentiment_analyst",
        llm=MODEL_RECOMMENDATIONS["sentiment_analyst"]["model"],
        system_prompt=_apply_ips(ANALYST_SENTIMENT, ips),
        tools=all_tools,
        use_tools=True,
        instructions=(
            "Read the market's mood and positioning. Detect when the crowd "
            "is too bullish, too bearish, or about to shift."
        ),
    )


def create_risk_analyst(
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    """Risk and quantitative analyst - portfolio risk management.

    Args:
        tools: Additional tools to provide. Query tools are
            always included automatically.
        ips: Optional investment policy statement injected into the system prompt.

    Returns:
        Agent configured for risk analysis with query tools.
    """
    all_tools = _get_query_tools() + _get_prediction_market_tools() + (tools or [])
    return Agent(
        name="Risk & Quantitative Analyst",
        agent_id="risk_analyst",
        llm=MODEL_RECOMMENDATIONS["risk_analyst"]["model"],
        system_prompt=_apply_ips(ANALYST_RISK, ips),
        tools=all_tools,
        use_tools=True,
        instructions=(
            "Assess and quantify the risks of opportunities, ensure the "
            "portfolio remains within safe parameters."
        ),
    )


def create_all_analysts(
    additional_tools: dict[str, list] | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> dict[str, Agent]:
    """Create all analyst agents with query tools.

    Args:
        additional_tools: Optional dict mapping analyst domain to additional tools.
            Example: {"macro": [fred_tool], "crypto": [binance_tool]}
        ips: Optional investment policy statement injected into every analyst's
            system prompt.

    Returns:
        Dict mapping domain name to Agent instance.
    """
    additional_tools = additional_tools or {}
    return {
        "macro": create_macro_analyst(additional_tools.get("macro"), ips=ips),
        "equity": create_equity_analyst(additional_tools.get("equity"), ips=ips),
        "crypto": create_crypto_analyst(additional_tools.get("crypto"), ips=ips),
        "sentiment": create_sentiment_analyst(additional_tools.get("sentiment"), ips=ips),
        "risk": create_risk_analyst(additional_tools.get("risk"), ips=ips),
    }


def create_analyst(
    analyst_id: str,
    domain: str,
    tools: list | None = None,
    ips: InvestmentPolicyStatement | None = None,
) -> Agent:
    """Create a single analyst by analyst_id.

    Args:
        analyst_id: Full analyst identifier (e.g., "macro_analyst")
        domain: Analysis domain (e.g., "macro")
        tools: Additional tools to provide.
        ips: Optional investment policy statement injected into the system prompt.

    Returns:
        Agent configured for the specified domain.

    Raises:
        ValueError: If analyst_id is not recognized.
    """
    creators = {
        "macro_analyst": create_macro_analyst,
        "equity_analyst": create_equity_analyst,
        "crypto_analyst": create_crypto_analyst,
        "sentiment_analyst": create_sentiment_analyst,
        "risk_analyst": create_risk_analyst,
    }
    if analyst_id not in creators:
        raise ValueError(
            f"Unknown analyst_id: {analyst_id}. "
            f"Valid options: {list(creators.keys())}"
        )
    return creators[analyst_id](tools, ips=ips)
