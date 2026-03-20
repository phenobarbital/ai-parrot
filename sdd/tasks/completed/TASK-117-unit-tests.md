# TASK-117: Research Memory Unit Tests

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-109, TASK-110, TASK-111, TASK-112, TASK-113
**Assigned-to**: claude-session

---

## Context

This task creates comprehensive unit tests for all research memory components: schemas, abstract interface, file implementation, audit trail, and tools.

Reference: Spec Section 4 "Test Specification"

---

## Scope

- Unit tests for `ResearchDocument`, `ResearchScheduleConfig`, `AuditEvent` models
- Unit tests for `generate_period_key()` helper
- Unit tests for `FileResearchMemory` core operations
- Unit tests for audit trail logging
- Unit tests for cleanup/archival
- Unit tests for all 5 research memory tools
- Fixtures for sample documents and temporary memory

**NOT in scope**:
- Integration tests (TASK-118)
- Service-level tests

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_research_memory_schemas.py` | CREATE | Schema model tests |
| `tests/test_research_memory_file.py` | CREATE | File memory tests |
| `tests/test_research_memory_audit.py` | CREATE | Audit trail tests |
| `tests/test_research_memory_tools.py` | CREATE | Tool tests |
| `tests/fixtures/research_memory.py` | CREATE | Shared fixtures |

---

## Implementation Notes

### Shared Fixtures

```python
# tests/fixtures/research_memory.py
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from parrot.finance.research.memory.schemas import ResearchDocument
from parrot.finance.research.memory.file import FileResearchMemory
from parrot.finance.schemas import ResearchBriefing, ResearchItem


@pytest.fixture
def sample_briefing() -> ResearchBriefing:
    """Sample research briefing."""
    return ResearchBriefing(
        id="briefing-123",
        analyst_id="macro_analyst",
        domain="macro",
        generated_at=datetime.now(timezone.utc),
        research_items=[
            ResearchItem(
                title="GDP Growth Estimate",
                description="Q1 GDP growth estimated at 2.3%",
                timestamp=datetime.now(timezone.utc),
                source="FRED",
                relevance_score=0.9,
                assets_mentioned=["SPY", "QQQ"],
                sentiment="bullish",
                data_points={"gdp_growth": 2.3},
            ),
        ],
        portfolio_snapshot={},
    )


@pytest.fixture
def sample_document(sample_briefing) -> ResearchDocument:
    """Sample research document."""
    return ResearchDocument(
        id="doc-123",
        crew_id="research_crew_macro",
        domain="macro",
        period_key="2026-03-03",
        generated_at=datetime.now(timezone.utc),
        briefing=sample_briefing,
        metadata={"sources": ["FRED"]},
    )


@pytest.fixture
def temp_memory(tmp_path) -> FileResearchMemory:
    """Temporary file research memory for testing."""
    return FileResearchMemory(
        base_path=str(tmp_path / "research_memory"),
        cache_max_size=10,
        warmup_on_init=False,
    )


@pytest.fixture
async def started_memory(temp_memory) -> FileResearchMemory:
    """Memory that has been started."""
    await temp_memory.start()
    yield temp_memory
    await temp_memory.stop()


@pytest.fixture
async def populated_memory(started_memory, sample_document) -> FileResearchMemory:
    """Memory pre-populated with sample documents."""
    import asyncio

    # Add documents for multiple domains
    for domain in ["macro", "equity", "crypto"]:
        doc = ResearchDocument(
            id=f"doc-{domain}",
            crew_id=f"research_crew_{domain}",
            domain=domain,
            period_key="2026-03-03",
            generated_at=datetime.now(timezone.utc),
            briefing=sample_document.briefing,
        )
        await started_memory.store(doc)

    # Wait for fire-and-forget writes
    await asyncio.sleep(0.2)

    return started_memory


def create_document_with_date(date_str: str, domain: str = "macro") -> ResearchDocument:
    """Helper to create document with specific date."""
    return ResearchDocument(
        id=f"doc-{date_str}",
        crew_id=f"research_crew_{domain}",
        domain=domain,
        period_key=date_str,
        generated_at=datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc),
        briefing=ResearchBriefing(
            id="b",
            analyst_id=f"{domain}_analyst",
            domain=domain,
            generated_at=datetime.now(timezone.utc),
            research_items=[],
            portfolio_snapshot={},
        ),
    )
```

### Schema Tests

```python
# tests/test_research_memory_schemas.py
import pytest
from datetime import datetime, timezone
from parrot.finance.research.memory.schemas import (
    ResearchDocument,
    ResearchScheduleConfig,
    AuditEvent,
    DEFAULT_RESEARCH_SCHEDULES,
    generate_period_key,
)


class TestResearchDocument:
    def test_minimal_document(self, sample_briefing):
        doc = ResearchDocument(
            id="doc123",
            crew_id="research_crew_macro",
            domain="macro",
            period_key="2026-03-03",
            briefing=sample_briefing,
        )
        assert doc.is_daily is True
        assert doc.domain == "macro"

    def test_hourly_period_key(self, sample_briefing):
        doc = ResearchDocument(
            id="doc456",
            crew_id="research_crew_crypto",
            domain="crypto",
            period_key="2026-03-03T14:00:00",
            briefing=sample_briefing,
        )
        assert doc.is_daily is False

    def test_generated_at_default(self, sample_briefing):
        doc = ResearchDocument(
            id="doc789",
            crew_id="research_crew_macro",
            domain="macro",
            period_key="2026-03-03",
            briefing=sample_briefing,
        )
        assert doc.generated_at is not None


class TestResearchScheduleConfig:
    def test_required_fields(self):
        config = ResearchScheduleConfig(
            crew_id="research_crew_macro",
            cron_expression="0 6 * * *",
        )
        assert config.period_granularity == "daily"
        assert config.staleness_hours == 24


class TestDefaultSchedules:
    def test_all_crews_configured(self):
        assert len(DEFAULT_RESEARCH_SCHEDULES) == 5
        expected_crews = [
            "research_crew_macro",
            "research_crew_equity",
            "research_crew_crypto",
            "research_crew_sentiment",
            "research_crew_risk",
        ]
        for crew in expected_crews:
            assert crew in DEFAULT_RESEARCH_SCHEDULES

    def test_crypto_is_4h(self):
        config = DEFAULT_RESEARCH_SCHEDULES["research_crew_crypto"]
        assert config.period_granularity == "4h"
        assert config.staleness_hours == 4


class TestGeneratePeriodKey:
    def test_daily_granularity(self):
        key = generate_period_key("daily")
        assert "T" not in key
        assert len(key) == 10

    def test_4h_granularity(self):
        key = generate_period_key("4h")
        assert "T" in key

    def test_hourly_granularity(self):
        key = generate_period_key("hourly")
        assert "T" in key
        assert ":00:00" in key

    def test_invalid_granularity(self):
        with pytest.raises(ValueError):
            generate_period_key("invalid")
```

### File Memory Tests

```python
# tests/test_research_memory_file.py
import pytest
import asyncio
from pathlib import Path

from tests.fixtures.research_memory import *


class TestFileResearchMemoryBasic:
    @pytest.mark.asyncio
    async def test_start_creates_directories(self, temp_memory):
        await temp_memory.start()

        assert temp_memory.base_path.exists()
        assert (temp_memory.base_path / "macro").exists()
        assert (temp_memory.base_path / "_audit_log").exists()

        await temp_memory.stop()

    @pytest.mark.asyncio
    async def test_store_and_get(self, started_memory, sample_document):
        doc_id = await started_memory.store(sample_document)

        result = await started_memory.get(
            sample_document.crew_id,
            sample_document.period_key
        )
        assert result is not None
        assert result.id == doc_id

    @pytest.mark.asyncio
    async def test_exists_true(self, started_memory, sample_document):
        await started_memory.store(sample_document)

        exists = await started_memory.exists(
            sample_document.crew_id,
            sample_document.period_key
        )
        assert exists is True

    @pytest.mark.asyncio
    async def test_exists_false(self, started_memory):
        exists = await started_memory.exists("nonexistent", "2026-03-03")
        assert exists is False

    @pytest.mark.asyncio
    async def test_get_latest(self, populated_memory):
        result = await populated_memory.get_latest("macro")
        assert result is not None
        assert result.domain == "macro"

    @pytest.mark.asyncio
    async def test_get_history(self, started_memory):
        # Store multiple documents
        for i in range(3):
            doc = create_document_with_date(f"2026-03-0{i+1}")
            await started_memory.store(doc)

        history = await started_memory.get_history("macro", last_n=2)
        assert len(history) == 2
        # Should be ordered newest first
        assert history[0].period_key > history[1].period_key


class TestFileResearchMemoryCache:
    @pytest.mark.asyncio
    async def test_cache_hit(self, started_memory, sample_document):
        await started_memory.store(sample_document)

        # First get populates cache
        result1 = await started_memory.get(
            sample_document.crew_id,
            sample_document.period_key
        )

        # Second get should hit cache (same object)
        result2 = await started_memory.get(
            sample_document.crew_id,
            sample_document.period_key
        )

        assert result1 is result2  # Same object from cache

    @pytest.mark.asyncio
    async def test_lru_eviction(self, started_memory):
        # Store more documents than cache_max_size (10)
        for i in range(15):
            doc = create_document_with_date(f"2026-03-{i+1:02d}")
            await started_memory.store(doc)

        # Cache should be at max size
        assert len(started_memory._cache) == 10

    @pytest.mark.asyncio
    async def test_fire_and_forget_persists(self, started_memory, sample_document):
        await started_memory.store(sample_document)

        # Wait for fire-and-forget
        await asyncio.sleep(0.3)

        # Check file exists
        path = started_memory._get_file_path(
            sample_document.domain,
            sample_document.crew_id,
            sample_document.period_key
        )
        assert path.exists()
```

### Tool Tests

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

from tests.fixtures.research_memory import *


@pytest.fixture
async def setup_memory(started_memory):
    set_research_memory(started_memory)
    yield started_memory


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
    async def test_stores_and_returns_id(self, setup_memory, sample_briefing):
        result = await store_research(
            briefing=sample_briefing.model_dump(),
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


class TestGetResearchHistory:
    @pytest.mark.asyncio
    async def test_returns_history(self, setup_memory):
        # Store multiple documents
        for i in range(3):
            doc = create_document_with_date(f"2026-03-0{i+1}")
            await setup_memory.store(doc)

        result = await get_research_history("macro", last_n=2)
        assert len(result) == 2


class TestGetCrossDomainResearch:
    @pytest.mark.asyncio
    async def test_returns_multiple_domains(self, populated_memory):
        set_research_memory(populated_memory)

        result = await get_cross_domain_research(["macro", "crypto"])
        assert "macro" in result
        assert "crypto" in result
        assert "error" not in result["macro"]
```

---

## Acceptance Criteria

- [ ] All schema tests pass
- [ ] All file memory tests pass
- [ ] All tool tests pass
- [ ] Tests cover edge cases (missing data, cache eviction, etc.)
- [ ] Shared fixtures work across test files
- [ ] Coverage > 80% for memory module
- [ ] All tests run: `pytest tests/test_research_memory*.py -v`

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — Core implementation tasks must be complete
2. **Update status** → `"in-progress"`
3. **Create** test files with comprehensive coverage
4. **Run tests**: `pytest tests/test_research_memory*.py -v`
5. **Check coverage**: `pytest --cov=parrot.finance.research.memory`
6. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**:
- Created `tests/test_research_memory_file.py` with 28 comprehensive tests
- Tests cover all FileResearchMemory operations:
  - Basic operations: start, stop, store, get, exists (7 tests)
  - Latest and history retrieval (6 tests)
  - Cache behavior: hits, LRU eviction, on-store caching (3 tests)
  - Persistence: fire-and-forget, restart survival, JSON format (3 tests)
  - Query operations: all domains, filtered, since filter (3 tests)
  - Initialization options: defaults, cache size, debug mode, warmup (4 tests)
  - Multi-domain operations: isolation, cross-domain storage (2 tests)
- All 116 research memory tests passing (schemas, abstract, audit, tools, file)
- Linting clean (ruff check passes)
