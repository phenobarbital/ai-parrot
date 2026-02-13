"""
Parrot Finance Research — Autonomous Research Agent Layer
==========================================================

This module bridges the existing AgentService runtime with the
finance research crews, providing:

    - ``FinanceResearchService``: AgentService subclass with pre-configured
      heartbeats for all 5 research crews (macro, equity, crypto,
      sentiment, risk) and automatic tool registration.

    - ``ResearchBriefingStore``: Redis-backed persistence for structured
      research briefings with pub/sub events for downstream consumers.

    - ``ResearchOutputParser``: Parses raw LLM output from research crews
      into validated ``ResearchBriefing`` dataclasses.

    - ``DeliberationTrigger``: Monitors briefing freshness and auto-triggers
      the full deliberation → execution pipeline when quorum is met.

    - ``configure_research_tools``: Attaches domain-specific toolkits
      to each crew agent via BotManager.

Architecture::

    ┌─────────────────────────────────────────────┐
    │        FinanceResearchService                │
    │        (extends AgentService)                │
    │                                              │
    │  HeartbeatScheduler ──→ crew.ask(prompt)     │
    │       │                       │              │
    │       │               _process_task()        │
    │       │                 (override)           │
    │       │                       │              │
    │       │              ResearchOutputParser     │
    │       │                       │              │
    │       │              ResearchBriefingStore    │
    │       │                   │       │          │
    │       │            Redis SET   PUBLISH       │
    └───────┼───────────────────┼───────┼──────────┘
            │                   │       │
            ▼                   │       ▼
    APScheduler cron            │  DeliberationTrigger
                                │       │
                                │  check_freshness()
                                │       │
                                │  quorum ≥ 4/5 ?
                                │       │
                                └──▶ run_trading_pipeline()

Usage::

    from parrot.finance.research import (
        FinanceResearchService,
        DeliberationTrigger,
    )

    # Start research service
    service = FinanceResearchService(bot_manager=my_bot_manager)
    await service.start()

    # Start trigger (auto-fires pipeline on quorum)
    trigger = DeliberationTrigger(
        briefing_store=service.briefing_store,
        redis=service._redis,
        mode="quorum",
    )
    await trigger.start()

    # Or trigger manually
    result = await trigger.force_trigger()

    # Shutdown
    await trigger.stop()
    await service.stop()
"""

from .briefing_store import ResearchBriefingStore, ResearchOutputParser
from .service import (
    FinanceResearchService,
    configure_research_tools,
    DEFAULT_HEARTBEATS,
    CREW_PROMPTS,
)
from .trigger import (
    DeliberationTrigger,
    TriggerMode,
    CycleResult,
    DEFAULT_STALENESS_WINDOWS,
)

__all__ = [
    # Service
    "FinanceResearchService",
    "configure_research_tools",
    "DEFAULT_HEARTBEATS",
    "CREW_PROMPTS",
    # Store
    "ResearchBriefingStore",
    "ResearchOutputParser",
    # Trigger
    "DeliberationTrigger",
    "TriggerMode",
    "CycleResult",
    "DEFAULT_STALENESS_WINDOWS",
]