# TASK-113: Research Memory Tools

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-111
**Assigned-to**: claude-session

---

## Context

This task implements the tools that research crews and analysts use to interact with the collective memory. Crews use deduplication tools; analysts use query tools.

Reference: Spec Section 2 "New Public Interfaces" - Tools section

---

## Scope

**Crew Tools (Deduplication)**:
- `check_research_exists(crew_id, period_key)` — Check if research already exists
- `store_research(briefing, crew_id, domain)` — Store completed research

**Analyst Tools (Query)**:
- `get_latest_research(domain)` — Get most recent research for domain
- `get_research_history(domain, last_n)` — Get N recent documents
- `get_cross_domain_research(domains)` — Get latest from multiple domains

**NOT in scope**:
- Memory implementation (TASK-111)
- Service integration (TASK-114)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/research/memory/tools.py` | CREATE | All 5 research memory tools |
| `parrot/finance/research/memory/__init__.py` | MODIFY | Export tools |

---

## Implementation Notes

### Tool Pattern

```python
# parrot/finance/research/memory/tools.py
from typing import Any
import uuid
from datetime import datetime, timezone

from parrot.tools import tool
from parrot.finance.schemas import ResearchBriefing

from .file import FileResearchMemory
from .schemas import ResearchDocument, generate_period_key, DEFAULT_RESEARCH_SCHEDULES


# Global memory instance (injected at service startup)
_memory: FileResearchMemory | None = None


def set_research_memory(memory: FileResearchMemory) -> None:
    """Set the global research memory instance."""
    global _memory
    _memory = memory


def get_research_memory() -> FileResearchMemory:
    """Get the global research memory instance."""
    if _memory is None:
        raise RuntimeError("Research memory not initialized. Call set_research_memory() first.")
    return _memory
```

### Crew Tools

```python
@tool
async def check_research_exists(crew_id: str, period_key: str | None = None) -> dict[str, Any]:
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


@tool
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

    # Parse briefing
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
        metadata={"sources": []},  # Could extract from briefing
    )

    doc_id = await memory.store(document)

    return {
        "success": True,
        "document_id": doc_id,
        "period_key": period_key,
    }
```

### Analyst Tools

```python
@tool
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


@tool
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


@tool
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
```

### Key Constraints

- Use `@tool` decorator from `parrot.tools`
- All tools must be `async`
- Tools use a global `_memory` instance (set at service startup)
- Return dicts (not Pydantic models) for LLM compatibility
- Include comprehensive docstrings for LLM tool descriptions
- Handle missing research gracefully with error dicts

### References in Codebase

- `parrot/tools/finnhub.py` — Tool pattern example
- `parrot/tools/alpaca/` — Toolkit pattern example
- `parrot/tools/__init__.py` — `@tool` decorator import

---

## Acceptance Criteria

- [x] All 5 tools implemented with `@tool` decorator
- [x] Tools use global `_memory` instance via `get_research_memory()`
- [x] `check_research_exists` auto-generates period_key from schedule config
- [x] `store_research` creates `ResearchDocument` and stores
- [x] `get_latest_research` returns latest document or error dict
- [x] `get_research_history` returns list of N documents
- [x] `get_cross_domain_research` returns dict of domain -> document
- [x] All tools have comprehensive docstrings
- [x] No linting errors

---

## Test Specification

```python
# tests/test_research_memory_tools.py
import pytest
from parrot.finance.research.memory.tools import (
    check_research_exists,
    store_research,
    get_latest_research,
    get_research_history,
    get_cross_domain_research,
    set_research_memory,
)


@pytest.fixture
async def setup_memory(temp_memory):
    await temp_memory.start()
    set_research_memory(temp_memory)
    yield temp_memory


class TestCheckResearchExists:
    @pytest.mark.asyncio
    async def test_returns_false_when_missing(self, setup_memory):
        result = await check_research_exists("research_crew_macro", "2026-03-03")
        assert result["exists"] is False
        assert result["document_id"] is None

    @pytest.mark.asyncio
    async def test_returns_true_when_present(self, setup_memory, sample_document):
        await setup_memory.store(sample_document)
        result = await check_research_exists(
            sample_document.crew_id,
            sample_document.period_key
        )
        assert result["exists"] is True
        assert result["document_id"] == sample_document.id


class TestStoreResearch:
    @pytest.mark.asyncio
    async def test_stores_and_returns_id(self, setup_memory):
        result = await store_research(
            briefing={"id": "b123", "analyst_id": "macro_analyst", ...},
            crew_id="research_crew_macro",
            domain="macro",
        )
        assert result["success"] is True
        assert result["document_id"] is not None


class TestGetLatestResearch:
    @pytest.mark.asyncio
    async def test_returns_document(self, setup_memory, sample_document):
        await setup_memory.store(sample_document)
        result = await get_latest_research("macro")
        assert "error" not in result
        assert result["domain"] == "macro"

    @pytest.mark.asyncio
    async def test_returns_error_when_missing(self, setup_memory):
        result = await get_latest_research("nonexistent")
        assert "error" in result


class TestGetCrossDomainResearch:
    @pytest.mark.asyncio
    async def test_returns_multiple_domains(self, setup_memory):
        # Store macro and sentiment
        await setup_memory.store(create_document("macro"))
        await setup_memory.store(create_document("sentiment"))

        result = await get_cross_domain_research(["macro", "sentiment"])
        assert "macro" in result
        assert "sentiment" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-111 must be complete
2. **Update status** → `"in-progress"`
3. **Implement** tools in `parrot/finance/research/memory/tools.py`
4. **Run tests**: `pytest tests/test_research_memory_tools.py -v`
5. **Verify** all acceptance criteria
6. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**: Implemented all 5 research memory tools using @tool() decorator pattern:
- **Crew tools**: `check_research_exists` (deduplication check with auto-period generation), `store_research` (persists briefing to collective memory)
- **Analyst tools**: `get_latest_research`, `get_research_history`, `get_cross_domain_research` (cross-pollination support)
- Global instance management via `set_research_memory()` / `get_research_memory()`
- All tools return dicts for LLM compatibility with comprehensive docstrings
- 18 tests passing including integration tests for full crew→analyst workflow
