"""
Parrot Finance Research — Autonomous Research Agent Layer
==========================================================

This module bridges the existing AgentService runtime with the
finance research crews, providing:

    - ``FinanceResearchService``: AgentService subclass with pre-configured
      heartbeats for all 5 research crews (macro, equity, crypto,
      sentiment, risk) and automatic tool registration.

    - ``FileResearchMemory``: Filesystem-based collective memory for
      research documents with in-memory cache and fire-and-forget writes.

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
    │       │              FileResearchMemory       │
    │       │                   │       │          │
    │       │            File Write   Cache        │
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
        memory=service.memory,
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
    CREW_PROMPTS,
)
from .trigger import (
    DeliberationTrigger,
    TriggerMode,
    CycleResult,
    DEFAULT_STALENESS_WINDOWS,
)
from .memory import (
    # Abstract base class
    ResearchMemory,
    # Implementation
    FileResearchMemory,
    # Models
    ResearchDocument,
    ResearchScheduleConfig,
    AuditEvent,
    # Functions
    generate_period_key,
    set_research_memory,
    get_research_memory,
    # Constants
    DEFAULT_RESEARCH_SCHEDULES,
    ALL_CREW_IDS,
    ALL_DOMAINS,
    DOMAIN_TO_CREW,
    # Tools
    check_research_exists,
    store_research,
    get_latest_research,
    get_research_history,
    get_cross_domain_research,
)

__all__ = [
    # Service
    "FinanceResearchService",
    "configure_research_tools",
    "CREW_PROMPTS",
    # Store (legacy, still available for parsing)
    "ResearchBriefingStore",
    "ResearchOutputParser",
    # Trigger
    "DeliberationTrigger",
    "TriggerMode",
    "CycleResult",
    "DEFAULT_STALENESS_WINDOWS",
    # Memory
    "ResearchMemory",
    "FileResearchMemory",
    "ResearchDocument",
    "ResearchScheduleConfig",
    "AuditEvent",
    "generate_period_key",
    "set_research_memory",
    "get_research_memory",
    "DEFAULT_RESEARCH_SCHEDULES",
    "ALL_CREW_IDS",
    "ALL_DOMAINS",
    "DOMAIN_TO_CREW",
    # Tools
    "check_research_exists",
    "store_research",
    "get_latest_research",
    "get_research_history",
    "get_cross_domain_research",
]