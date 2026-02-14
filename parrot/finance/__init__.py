"""
Parrot Finance — Autonomous Trading Agent Council
==================================================

A multi-agent deliberation system for algorithmic trading decisions.

Architecture:
    Layer 1: Research Crews (5 crews, cron-driven data collection)
    Layer 2: Analyst Committee (5 specialized analysts)
    Layer 3: CIO Deliberation (multi-round contradiction detection)
    Layer 4: Secretary (Investment Memo synthesis)
    Layer 5: Executors (platform-specific: Alpaca, Binance, Kraken)
    Layer 6: Monitoring (Portfolio Manager + Performance Tracker)

Public APIs:
    - run_full_cycle: Main entry point for deliberation → orders
    - memo_to_orders: Convert InvestmentMemo to TradingOrders
    - create_all_agents: Factory for all 18 agents
    - CommitteeDeliberation: Deliberation orchestrator
    - ExecutionOrchestrator: Order execution orchestrator

Schemas:
    - TradingOrder, InvestmentMemo, AnalystReport, etc.
    - AgentCapabilityProfile, ExecutorConstraints
    - Platform, AssetClass, ConsensusLevel enums

Example:
    >>> from parrot.finance import run_full_cycle
    >>> from parrot.bots import Agent
    >>>
    >>> memo, orders = await run_full_cycle(
    ...     agent_class=Agent,
    ...     briefings=my_briefings,
    ...     portfolio=my_portfolio,
    ...     constraints=my_constraints,
    ... )
"""

# Main orchestrators
from .swarm import (
    CommitteeDeliberation,
    run_full_cycle,
    memo_to_orders,
)

from .execution import (
    ExecutionOrchestrator,
    OrderQueue,
)

# Agent factories
from .agents import (
    create_all_agents,
    # Research crews
    create_macro_research_crew,
    create_equity_research_crew,
    create_crypto_research_crew,
    create_sentiment_research_crew,
    create_risk_research_crew,
    create_all_research_crews,
    # Analysts
    create_macro_analyst,
    create_equity_analyst,
    create_crypto_analyst,
    create_sentiment_analyst,
    create_risk_analyst,
    create_all_analysts,
    # Deliberation
    create_cio,
    create_secretary,
    # Executors
    create_stock_executor,
    create_crypto_executor_binance,
    create_crypto_executor_kraken,
    create_general_executor,
    # Monitoring
    create_portfolio_manager,
    create_performance_tracker,
)

# Core schemas
from .schemas import (
    # Orders & Execution
    TradingOrder,
    OrderStatus,
    OrderStatusChange,
    # Memos & Recommendations
    InvestmentMemo,
    MemoRecommendation,
    # Research & Analysis
    ResearchItem,
    ResearchBriefing,
    AnalystReport,
    AnalystRecommendation,
    # Deliberation
    DeliberationRound,
    RevisionRequest,
    # Portfolio
    PortfolioSnapshot,
    Position,
    # Constraints & Capabilities
    ExecutorConstraints,
    AgentCapabilityProfile,
    # Routing
    OrderRouter,
    # Enums
    Platform,
    AssetClass,
    Signal,
    ConsensusLevel,
    TimeHorizon,
    MessageType,
    Capability,
    # Message Bus
    MessageBus,
    AgentMessage,
)

# Pydantic output models (for structured LLM outputs)
from .swarm import (
    AnalystReportOutput,
    RiskAnalystReportOutput,
    CIOAssessmentOutput,
    InvestmentMemoOutput,
    MemoRecommendationOutput,
)

from .execution import (
    ExecutionReportOutput,
    PortfolioManagerOutput,
)

# Research-only runner (lazy — avoid RuntimeWarning with `python -m`)
# from .research_runner import run_research_only

# Telegram notification
from .telegram_notify import format_memo_markdown, send_memo_to_telegram

# FSM state machines
from .fsm import (
    OrderStateMachine,
    PipelineStateMachine,
    PipelinePhase,
    transition_order,
)

# Anti-hallucination guards
from .guards import (
    DeterministicGuard,
    ExecutionMandate,
    GuardResult,
    GuardViolation,
    ViolationType,
    SafeToolWrapper,
    wrap_tools_with_guards,
    create_mandate_from_order,
    ExecutionAuditEntry,
)

__all__ = [
    # Orchestrators
    "CommitteeDeliberation",
    "ExecutionOrchestrator",
    "run_full_cycle",
    "memo_to_orders",
    # Agent factories
    "create_all_agents",
    "create_macro_research_crew",
    "create_equity_research_crew",
    "create_crypto_research_crew",
    "create_sentiment_research_crew",
    "create_risk_research_crew",
    "create_all_research_crews",
    "create_macro_analyst",
    "create_equity_analyst",
    "create_crypto_analyst",
    "create_sentiment_analyst",
    "create_risk_analyst",
    "create_all_analysts",
    "create_cio",
    "create_secretary",
    "create_stock_executor",
    "create_crypto_executor_binance",
    "create_crypto_executor_kraken",
    "create_general_executor",
    "create_portfolio_manager",
    "create_performance_tracker",
    # Schemas
    "TradingOrder",
    "OrderStatus",
    "OrderStatusChange",
    "OrderQueue",
    "InvestmentMemo",
    "MemoRecommendation",
    "ResearchItem",
    "ResearchBriefing",
    "AnalystReport",
    "AnalystRecommendation",
    "DeliberationRound",
    "RevisionRequest",
    "PortfolioSnapshot",
    "Position",
    "ExecutorConstraints",
    "AgentCapabilityProfile",
    "OrderRouter",
    "Platform",
    "AssetClass",
    "Signal",
    "ConsensusLevel",
    "TimeHorizon",
    "MessageType",
    "Capability",
    "MessageBus",
    "AgentMessage",
    # Output models
    "AnalystReportOutput",
    "RiskAnalystReportOutput",
    "CIOAssessmentOutput",
    "InvestmentMemoOutput",
    "MemoRecommendationOutput",
    "ExecutionReportOutput",
    "PortfolioManagerOutput",
    # FSM
    "OrderStateMachine",
    "PipelineStateMachine",
    "PipelinePhase",
    "transition_order",
    # Research-only runner
    "run_research_only",
    # Telegram notification
    "format_memo_markdown",
    "send_memo_to_telegram",
    # Guards
    "DeterministicGuard",
    "ExecutionMandate",
    "GuardResult",
    "GuardViolation",
    "ViolationType",
    "SafeToolWrapper",
    "wrap_tools_with_guards",
    "create_mandate_from_order",
    "ExecutionAuditEntry",
]


def __getattr__(name: str):
    """Lazy imports for modules that conflict with ``python -m`` execution."""
    if name == "run_research_only":
        from .research_runner import run_research_only
        return run_research_only
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
