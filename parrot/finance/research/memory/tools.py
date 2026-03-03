"""
Research Memory Tools
======================

Tools for research crews and analysts to interact with collective memory.

Crew Tools (Deduplication):
- check_research_exists: Check if research already exists for a period
- store_research: Store completed research to collective memory

Analyst Tools (Query):
- get_latest_research: Get most recent research for a domain
- get_research_history: Get N recent documents for a domain
- get_cross_domain_research: Get latest from multiple domains
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from parrot.tools import tool
from parrot.finance.schemas import ResearchBriefing

from .abstract import ResearchMemory
from .schemas import (
    ResearchDocument,
    generate_period_key,
    DEFAULT_RESEARCH_SCHEDULES,
)


# =============================================================================
# GLOBAL MEMORY INSTANCE
# =============================================================================


_memory: ResearchMemory | None = None


def set_research_memory(memory: ResearchMemory) -> None:
    """Set the global research memory instance.

    Call this at service startup to inject the memory implementation.

    Args:
        memory: A ResearchMemory implementation (e.g., FileResearchMemory)
    """
    global _memory
    _memory = memory


def get_research_memory() -> ResearchMemory:
    """Get the global research memory instance.

    Returns:
        The configured ResearchMemory instance.

    Raises:
        RuntimeError: If set_research_memory() was not called first.
    """
    if _memory is None:
        raise RuntimeError(
            "Research memory not initialized. Call set_research_memory() first."
        )
    return _memory


# =============================================================================
# CREW TOOLS (DEDUPLICATION)
# =============================================================================


@tool()
async def check_research_exists(
    crew_id: str,
    period_key: str | None = None,
) -> dict[str, Any]:
    """Check if research already exists for this crew and period.

    Use this BEFORE executing research to avoid duplicate work.
    If research exists, skip execution and return early.

    Args:
        crew_id: The research crew identifier (e.g., "research_crew_macro")
        period_key: The period in ISO format. If not provided, uses current period
                    based on the crew's schedule configuration.

    Returns:
        A dict with:
        - exists (bool): Whether research exists for this period
        - message (str): Human-readable status message
        - document_id (str | None): ID of existing document if found
        - period_key (str): The period key that was checked

    Example:
        >>> result = await check_research_exists("research_crew_macro")
        >>> if result["exists"]:
        >>>     return "Research already completed for today"
    """
    memory = get_research_memory()

    # Generate period key if not provided
    if period_key is None:
        config = DEFAULT_RESEARCH_SCHEDULES.get(crew_id)
        granularity = config.period_granularity if config else "daily"
        period_key = generate_period_key(granularity)

    exists = await memory.exists(crew_id, period_key)

    if exists:
        doc = await memory.get(crew_id, period_key)
        return {
            "exists": True,
            "message": f"Research already completed for {crew_id} period {period_key}",
            "document_id": doc.id if doc else None,
            "period_key": period_key,
        }

    return {
        "exists": False,
        "message": f"No research found for {crew_id} period {period_key}. Proceed with execution.",
        "document_id": None,
        "period_key": period_key,
    }


@tool()
async def store_research(
    briefing: dict[str, Any],
    crew_id: str,
    domain: str,
) -> dict[str, Any]:
    """Store a completed research briefing in collective memory.

    Call this after completing research to persist the results.
    Other analysts can then retrieve this research.

    Args:
        briefing: The research briefing content as a dict (ResearchBriefing structure)
        crew_id: The research crew identifier (e.g., "research_crew_macro")
        domain: The research domain (macro, equity, crypto, sentiment, risk)

    Returns:
        A dict with:
        - success (bool): Whether storage succeeded
        - document_id (str): The stored document's ID
        - period_key (str): The period key used for storage

    Example:
        >>> result = await store_research(
        ...     briefing=my_briefing_dict,
        ...     crew_id="research_crew_macro",
        ...     domain="macro"
        ... )
        >>> print(f"Stored as {result['document_id']}")
    """
    memory = get_research_memory()

    # Parse briefing - handle both dict and ResearchBriefing
    if isinstance(briefing, dict):
        research_briefing = ResearchBriefing(**briefing)
    else:
        research_briefing = briefing

    # Generate period key
    config = DEFAULT_RESEARCH_SCHEDULES.get(crew_id)
    granularity = config.period_granularity if config else "daily"
    period_key = generate_period_key(granularity)

    # Create document
    document = ResearchDocument(
        id=uuid.uuid4().hex,
        crew_id=crew_id,
        domain=domain,
        period_key=period_key,
        generated_at=datetime.now(timezone.utc),
        briefing=research_briefing,
        metadata={"sources": []},
    )

    doc_id = await memory.store(document)

    return {
        "success": True,
        "document_id": doc_id,
        "period_key": period_key,
    }


# =============================================================================
# ANALYST TOOLS (QUERY)
# =============================================================================


@tool()
async def get_latest_research(domain: str) -> dict[str, Any]:
    """Get the most recent research for a domain.

    Use this to pull the latest research from collective memory.
    This is the primary way analysts access research data.

    Args:
        domain: The research domain (macro, equity, crypto, sentiment, risk)

    Returns:
        The ResearchDocument as a dict, or an error dict if not found.
        Includes: id, crew_id, domain, period_key, generated_at, briefing, metadata

    Example:
        >>> result = await get_latest_research("macro")
        >>> if "error" not in result:
        >>>     briefing = result["briefing"]
    """
    memory = get_research_memory()

    doc = await memory.get_latest(domain)

    if doc is None:
        return {
            "error": f"No research found for domain '{domain}'",
            "domain": domain,
        }

    return doc.model_dump(mode="json")


@tool()
async def get_research_history(
    domain: str,
    last_n: int = 2,
) -> list[dict[str, Any]]:
    """Get recent research history for a domain.

    Useful for comparing current research with previous periods.
    Returns documents ordered by date descending (newest first).

    Args:
        domain: The research domain (macro, equity, crypto, sentiment, risk)
        last_n: Number of recent documents to retrieve (default: 2)

    Returns:
        List of ResearchDocument dicts ordered by date descending.
        Empty list if no documents found.

    Example:
        >>> history = await get_research_history("macro", last_n=3)
        >>> current = history[0] if history else None
        >>> previous = history[1] if len(history) > 1 else None
    """
    memory = get_research_memory()

    docs = await memory.get_history(domain, last_n=last_n)

    return [doc.model_dump(mode="json") for doc in docs]


@tool()
async def get_cross_domain_research(
    domains: list[str],
) -> dict[str, dict[str, Any]]:
    """Get the latest research from multiple domains.

    Use this for cross-pollination analysis across different research areas.
    Returns a dict mapping each domain to its latest research.

    Args:
        domains: List of domains to query (e.g., ["macro", "sentiment"])

    Returns:
        Dict mapping domain -> latest ResearchDocument dict.
        Domains without research will have an error dict as value.

    Example:
        >>> research = await get_cross_domain_research(["macro", "sentiment"])
        >>> macro_data = research.get("macro", {})
        >>> sentiment_data = research.get("sentiment", {})
    """
    memory = get_research_memory()

    result = {}
    for domain in domains:
        doc = await memory.get_latest(domain)
        if doc:
            result[domain] = doc.model_dump(mode="json")
        else:
            result[domain] = {"error": f"No research found for domain '{domain}'"}

    return result


# =============================================================================
# EXPORTS
# =============================================================================


__all__ = [
    # Instance management
    "set_research_memory",
    "get_research_memory",
    # Crew tools
    "check_research_exists",
    "store_research",
    # Analyst tools
    "get_latest_research",
    "get_research_history",
    "get_cross_domain_research",
]
