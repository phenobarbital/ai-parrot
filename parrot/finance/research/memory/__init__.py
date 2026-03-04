"""
Research Memory Package
========================

Collective memory system for Finance Research + Analyst.

This package provides:
- ResearchMemory: Abstract base class for memory implementations
- FileResearchMemory: Filesystem-based implementation with in-memory cache
- ResearchDocument: Storage unit for research briefings
- ResearchScheduleConfig: Per-crew scheduling configuration
- AuditEvent: Audit trail event model
- DEFAULT_RESEARCH_SCHEDULES: Pre-configured schedules for all 5 crews
- generate_period_key(): Helper for ISO period key generation

Tools:
- set_research_memory / get_research_memory: Global instance management
- check_research_exists: Crew deduplication check
- store_research: Crew storage
- get_latest_research: Analyst query
- get_research_history: Analyst query
- get_cross_domain_research: Analyst cross-pollination

Usage:
    from parrot.finance.research.memory import (
        ResearchMemory,
        FileResearchMemory,
        ResearchDocument,
        ResearchScheduleConfig,
        AuditEvent,
        DEFAULT_RESEARCH_SCHEDULES,
        generate_period_key,
        # Tools
        set_research_memory,
        check_research_exists,
        get_latest_research,
    )
"""
from parrot.finance.research.memory.abstract import ResearchMemory
from parrot.finance.research.memory.file import FileResearchMemory
from parrot.finance.research.memory.schemas import (
    # Models
    ResearchDocument,
    ResearchScheduleConfig,
    AuditEvent,
    # Type aliases
    PeriodGranularity,
    AuditEventType,
    # Functions
    generate_period_key,
    parse_period_key_date,
    # Constants
    DEFAULT_RESEARCH_SCHEDULES,
    ALL_CREW_IDS,
    ALL_DOMAINS,
    DOMAIN_TO_CREW,
)
from parrot.finance.research.memory.tools import (
    # Instance management
    set_research_memory,
    get_research_memory,
    # Crew tools
    check_research_exists,
    store_research,
    # Analyst tools
    get_latest_research,
    get_research_history,
    get_cross_domain_research,
)


__all__ = [
    # Abstract base class
    "ResearchMemory",
    # Implementations
    "FileResearchMemory",
    # Models
    "ResearchDocument",
    "ResearchScheduleConfig",
    "AuditEvent",
    # Type aliases
    "PeriodGranularity",
    "AuditEventType",
    # Functions
    "generate_period_key",
    "parse_period_key_date",
    # Constants
    "DEFAULT_RESEARCH_SCHEDULES",
    "ALL_CREW_IDS",
    "ALL_DOMAINS",
    "DOMAIN_TO_CREW",
    # Tools - Instance management
    "set_research_memory",
    "get_research_memory",
    # Tools - Crew (deduplication)
    "check_research_exists",
    "store_research",
    # Tools - Analyst (query)
    "get_latest_research",
    "get_research_history",
    "get_cross_domain_research",
]
