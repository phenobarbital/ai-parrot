"""
Trading Swarm - Agent Definitions
==================================

Definiciones de todos los agentes del sistema de trading autónomo.

Arquitectura de 6 capas:
    CAPA 1 - Research Crews (5 crews)
    CAPA 2 - Analistas (5 analistas especializados)
    CAPA 3 - Deliberación (CIO/Árbitro)
    CAPA 4 - Redacción (Secretary)
    CAPA 5 - Ejecución (4 ejecutores por plataforma)
    CAPA 6 - Monitoreo (Portfolio Manager + Performance Tracker)

Total: 18 agentes
"""

from .research import (
    create_macro_research_crew,
    create_equity_research_crew,
    create_crypto_research_crew,
    create_sentiment_research_crew,
    create_risk_research_crew,
    create_all_research_crews,
)
from .analysts import (
    create_macro_analyst,
    create_equity_analyst,
    create_crypto_analyst,
    create_sentiment_analyst,
    create_risk_analyst,
    create_all_analysts,
)
from .deliberation import (
    create_cio,
    create_secretary,
    create_all_deliberation_agents,
)
from .executors import (
    create_stock_executor,
    create_crypto_executor_binance,
    create_crypto_executor_kraken,
    create_general_executor,
    create_all_executors,
)
from .monitoring import (
    create_portfolio_manager,
    create_all_monitoring_agents,
)
from .performance_tracker import create_performance_tracker

from parrot.bots.agent import Agent


def create_all_agents() -> dict[str, dict[str, Agent]]:
    """
    Create all agents in the Trading Swarm system.

    Returns:
        Dictionary organized by layer:
        {
            "research_crews": {...},
            "analysts": {...},
            "deliberation": {...},
            "executors": {...},
            "monitoring": {...}
        }
    """
    return {
        "research_crews": create_all_research_crews(),
        "analysts": create_all_analysts(),
        "deliberation": create_all_deliberation_agents(),
        "executors": create_all_executors(),
        "monitoring": create_all_monitoring_agents(),
    }


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

__all__ = [
    # Research Crews
    "create_macro_research_crew",
    "create_equity_research_crew",
    "create_crypto_research_crew",
    "create_sentiment_research_crew",
    "create_risk_research_crew",
    # Analysts
    "create_macro_analyst",
    "create_equity_analyst",
    "create_crypto_analyst",
    "create_sentiment_analyst",
    "create_risk_analyst",
    # Deliberation
    "create_cio",
    "create_secretary",
    # Executors
    "create_stock_executor",
    "create_crypto_executor_binance",
    "create_crypto_executor_kraken",
    "create_general_executor",
    # Monitoring
    "create_portfolio_manager",
    "create_performance_tracker",
    # Factory functions
    "create_all_research_crews",
    "create_all_analysts",
    "create_all_deliberation_agents",
    "create_all_executors",
    "create_all_monitoring_agents",
    "create_all_agents",
]
