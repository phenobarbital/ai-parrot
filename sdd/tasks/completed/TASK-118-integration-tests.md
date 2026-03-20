# TASK-118: Research Memory Integration Tests

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-114, TASK-115, TASK-116, TASK-117
**Assigned-to**: claude-session

---

## Context

This task creates integration tests that verify the complete flow: research crews with deduplication, analysts with pull model, and the full research-to-deliberation pipeline.

Reference: Spec Section 4 "Integration Tests"

---

## Scope

- Integration test: Research crew deduplication flow
- Integration test: Analyst pull model flow
- Integration test: Cross-pollination between analysts
- Integration test: Full research → analyst → deliberation pipeline
- Integration test: Cleanup on startup

**NOT in scope**:
- Unit tests (TASK-117)
- Performance tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_research_memory_integration.py` | CREATE | All integration tests |

---

## Implementation Notes

### Test Structure

```python
# tests/test_research_memory_integration.py
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

from parrot.finance.research.memory import (
    FileResearchMemory,
    ResearchDocument,
    set_research_memory,
    get_research_memory,
)
from parrot.finance.research.memory.tools import (
    check_research_exists,
    store_research,
    get_latest_research,
)
from parrot.finance.research.service import FinanceResearchService
from parrot.finance.swarm import CommitteeDeliberation

from tests.fixtures.research_memory import *


class TestResearchCrewDeduplication:
    """Test that research crews skip when research exists."""

    @pytest.mark.asyncio
    async def test_crew_skips_when_exists(self, populated_memory):
        """Crew should skip execution when research exists for period."""
        set_research_memory(populated_memory)

        # Check exists returns True
        result = await check_research_exists("research_crew_macro", "2026-03-03")
        assert result["exists"] is True
        assert "already completed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_crew_proceeds_when_missing(self, started_memory):
        """Crew should proceed when no research exists."""
        set_research_memory(started_memory)

        result = await check_research_exists("research_crew_macro", "2026-03-03")
        assert result["exists"] is False
        assert "proceed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_store_then_skip(self, started_memory, sample_briefing):
        """After storing, subsequent check should return exists=True."""
        set_research_memory(started_memory)

        # First check - should not exist
        result1 = await check_research_exists("research_crew_macro")
        assert result1["exists"] is False

        # Store research
        await store_research(
            briefing=sample_briefing.model_dump(),
            crew_id="research_crew_macro",
            domain="macro",
        )

        # Second check - should exist
        result2 = await check_research_exists(
            "research_crew_macro",
            result1["period_key"]
        )
        assert result2["exists"] is True


class TestAnalystPullModel:
    """Test that analysts can pull research from collective memory."""

    @pytest.mark.asyncio
    async def test_analyst_gets_latest_research(self, populated_memory):
        """Analyst can retrieve latest research for their domain."""
        set_research_memory(populated_memory)

        result = await get_latest_research("macro")
        assert "error" not in result
        assert result["domain"] == "macro"
        assert "briefing" in result

    @pytest.mark.asyncio
    async def test_analyst_gets_empty_domain(self, started_memory):
        """Analyst gets error dict for empty domain."""
        set_research_memory(started_memory)

        result = await get_latest_research("sentiment")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_analyst_gets_history_for_comparison(self, started_memory):
        """Analyst can retrieve multiple periods for comparison."""
        set_research_memory(started_memory)

        # Store 3 documents
        for i in range(3):
            doc = create_document_with_date(f"2026-03-0{i+1}")
            await started_memory.store(doc)

        from parrot.finance.research.memory.tools import get_research_history
        result = await get_research_history("macro", last_n=2)

        assert len(result) == 2
        # Newest first
        assert result[0]["period_key"] > result[1]["period_key"]


class TestCrossPollination:
    """Test that analysts can access research from other domains."""

    @pytest.mark.asyncio
    async def test_cross_domain_access(self, populated_memory):
        """Analyst can access research from multiple domains."""
        set_research_memory(populated_memory)

        from parrot.finance.research.memory.tools import get_cross_domain_research
        result = await get_cross_domain_research(["macro", "crypto"])

        assert "macro" in result
        assert "crypto" in result
        assert "error" not in result["macro"]
        assert "error" not in result["crypto"]

    @pytest.mark.asyncio
    async def test_cross_domain_partial(self, started_memory, sample_document):
        """Cross-domain works even if some domains are empty."""
        set_research_memory(started_memory)
        await started_memory.store(sample_document)  # Only macro

        from parrot.finance.research.memory.tools import get_cross_domain_research
        result = await get_cross_domain_research(["macro", "sentiment"])

        assert "error" not in result["macro"]
        assert "error" in result["sentiment"]


class TestFullPipeline:
    """Test the complete research → deliberation flow."""

    @pytest.mark.asyncio
    async def test_research_to_deliberation(self, started_memory, sample_briefing):
        """Full flow: store research → analysts pull → deliberation."""
        set_research_memory(started_memory)

        # 1. Store research for all domains
        for domain in ["macro", "equity", "crypto", "sentiment", "risk"]:
            await store_research(
                briefing=sample_briefing.model_dump(),
                crew_id=f"research_crew_{domain}",
                domain=domain,
            )

        # Wait for fire-and-forget
        await asyncio.sleep(0.3)

        # 2. Verify all domains have research
        for domain in ["macro", "equity", "crypto", "sentiment", "risk"]:
            result = await get_latest_research(domain)
            assert "error" not in result, f"Missing research for {domain}"

        # 3. Cross-pollination works
        from parrot.finance.research.memory.tools import get_cross_domain_research
        cross = await get_cross_domain_research(["macro", "sentiment", "risk"])
        assert len(cross) == 3
        assert all("error" not in v for v in cross.values())


class TestCleanupOnStartup:
    """Test that cleanup runs before cache warmup."""

    @pytest.mark.asyncio
    async def test_cleanup_archives_old(self, tmp_path):
        """Old documents are archived during startup."""
        memory = FileResearchMemory(
            base_path=str(tmp_path / "memory"),
            warmup_on_init=False,
        )
        await memory.start()

        # Store old document (> 7 days)
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        old_doc = create_document_with_date(old_date)
        await memory.store(old_doc)
        await asyncio.sleep(0.3)  # Wait for persist

        # Run cleanup
        archived = await memory.cleanup(retention_days=7)
        assert archived == 1

        # Check moved to _historical
        historical = memory.base_path / "_historical"
        assert historical.exists()

        await memory.stop()

    @pytest.mark.asyncio
    async def test_cleanup_removes_from_cache(self, tmp_path):
        """Archived documents are removed from cache."""
        memory = FileResearchMemory(
            base_path=str(tmp_path / "memory"),
            warmup_on_init=False,
        )
        await memory.start()

        # Store old document
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        old_doc = create_document_with_date(old_date)
        await memory.store(old_doc)

        # Verify in cache
        cache_key = (old_doc.crew_id, old_doc.period_key)
        assert cache_key in memory._cache

        # Cleanup
        await memory.cleanup(retention_days=7)

        # Verify removed from cache
        assert cache_key not in memory._cache

        await memory.stop()


class TestServiceIntegration:
    """Test FinanceResearchService with collective memory."""

    @pytest.mark.asyncio
    async def test_service_starts_with_memory(self, mock_bot_manager, tmp_path):
        """Service initializes memory correctly."""
        service = FinanceResearchService(
            bot_manager=mock_bot_manager,
            memory_base_path=str(tmp_path / "memory"),
        )

        await service.start()

        # Memory should be accessible
        memory = get_research_memory()
        assert memory is not None
        assert memory.base_path.exists()

        await service.stop()

    @pytest.mark.asyncio
    async def test_service_schedules_from_config(self, mock_bot_manager, tmp_path):
        """Service builds heartbeats from schedule config."""
        service = FinanceResearchService(
            bot_manager=mock_bot_manager,
            memory_base_path=str(tmp_path / "memory"),
        )

        # Check heartbeats match DEFAULT_RESEARCH_SCHEDULES
        from parrot.finance.research.memory.schemas import DEFAULT_RESEARCH_SCHEDULES
        assert len(service._heartbeats) == len(DEFAULT_RESEARCH_SCHEDULES)
```

---

## Acceptance Criteria

- [ ] Deduplication flow integration test passes
- [ ] Analyst pull model integration test passes
- [ ] Cross-pollination integration test passes
- [ ] Full pipeline integration test passes
- [ ] Cleanup on startup integration test passes
- [ ] Service integration test passes
- [ ] All tests run: `pytest tests/test_research_memory_integration.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — All implementation tasks must be complete
2. **Update status** → `"in-progress"`
3. **Create** integration test file with comprehensive scenarios
4. **Run tests**: `pytest tests/test_research_memory_integration.py -v`
5. **Verify** all acceptance criteria
6. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**:
- Created `tests/test_research_memory_integration.py` with 26 comprehensive integration tests
- Test categories:
  - Research Crew Deduplication (5 tests): check_research_exists, store_research flows
  - Analyst Pull Model (5 tests): get_latest_research, get_research_history
  - Cross-Pollination (4 tests): get_cross_domain_research across multiple domains
  - Full Pipeline (3 tests): end-to-end research → analyst retrieval flow
  - Cleanup on Startup (4 tests): archival, cache removal, retention
  - Schedule Configuration (3 tests): crew/domain/schedule mapping
  - Memory Instance Management (2 tests): set/get global memory
- All 142 research memory tests passing (schemas, abstract, audit, tools, file, integration)
- Linting clean (ruff check passes)
