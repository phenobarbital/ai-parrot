# TASK-109: Research Memory Data Models

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This task implements the Pydantic data models for the Collective Research Memory system. These models define the schema for research documents, schedule configurations, and audit events that form the foundation of the new filesystem-based research storage.

Reference: Spec Section 2 "Data Models"

---

## Scope

- Implement `ResearchDocument` model with id, crew_id, domain, period_key, briefing, metadata
- Implement `ResearchScheduleConfig` model with cron_expression, period_granularity, staleness_hours
- Implement `AuditEvent` model with event_type, timestamp, crew_id, period_key, domain, actor, details
- Define `DEFAULT_RESEARCH_SCHEDULES` dict with configurations for all 5 research crews
- Add helper function `generate_period_key(granularity: str) -> str` for ISO period key generation

**NOT in scope**:
- Abstract memory interface (TASK-110)
- File memory implementation (TASK-111)
- Tools implementation (TASK-113)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/research/memory/__init__.py` | CREATE | Package init with exports |
| `parrot/finance/research/memory/schemas.py` | CREATE | All Pydantic models and schedule configs |

---

## Implementation Notes

### Pattern to Follow

```python
# Reference: parrot/finance/schemas.py
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field
from parrot.finance.schemas import ResearchBriefing


class ResearchDocument(BaseModel):
    """A research document stored in collective memory."""

    id: str = Field(description="Unique document ID (UUID)")
    crew_id: str = Field(description="Research crew identifier")
    domain: str = Field(description="Research domain: macro, equity, crypto, sentiment, risk")
    period_key: str = Field(description="Period identifier in ISO format")
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    briefing: ResearchBriefing
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_daily(self) -> bool:
        return "T" not in self.period_key
```

### Period Key Generation

```python
def generate_period_key(granularity: str) -> str:
    """Generate period key based on granularity.

    Args:
        granularity: One of "daily", "4h", "6h", "hourly"

    Returns:
        ISO format period key: "2026-03-03" or "2026-03-03T14:00:00"
    """
    now = datetime.now(timezone.utc)

    if granularity == "daily":
        return now.strftime("%Y-%m-%d")
    elif granularity == "4h":
        hour = (now.hour // 4) * 4
        return now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
    # ... etc
```

### Default Schedules

```python
DEFAULT_RESEARCH_SCHEDULES: dict[str, ResearchScheduleConfig] = {
    "research_crew_macro": ResearchScheduleConfig(
        crew_id="research_crew_macro",
        cron_expression="0 6,14 * * *",      # 2x/day
        period_granularity="daily",
        staleness_hours=24,
    ),
    "research_crew_crypto": ResearchScheduleConfig(
        crew_id="research_crew_crypto",
        cron_expression="0 */4 * * *",       # Every 4 hours
        period_granularity="4h",
        staleness_hours=4,
    ),
    # ... etc for all 5 crews
}
```

### Key Constraints

- Use `str | None` syntax (Python 3.10+)
- All fields must have `Field()` with description
- Import `ResearchBriefing` from `parrot.finance.schemas`
- Period key format: ISO 8601 (`2026-03-03` or `2026-03-03T14:00:00`)

### References in Codebase

- `parrot/finance/schemas.py` — `ResearchBriefing`, `ResearchItem` dataclasses
- `parrot/memory/abstract.py` — `ConversationTurn` pattern for dataclass structure

---

## Acceptance Criteria

- [ ] `ResearchDocument` model implemented with all fields from spec
- [ ] `ResearchScheduleConfig` model implemented
- [ ] `AuditEvent` model implemented
- [ ] `DEFAULT_RESEARCH_SCHEDULES` dict with configs for all 5 crews
- [ ] `generate_period_key()` helper function works for all granularities
- [ ] No linting errors: `ruff check parrot/finance/research/memory/`
- [ ] Models importable: `from parrot.finance.research.memory.schemas import ResearchDocument`

---

## Test Specification

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
from parrot.finance.schemas import ResearchBriefing


class TestResearchDocument:
    def test_minimal_document(self):
        """Create document with required fields."""
        briefing = ResearchBriefing(
            id="b123",
            analyst_id="macro_analyst",
            domain="macro",
            generated_at=datetime.now(timezone.utc),
            research_items=[],
            portfolio_snapshot={},
        )
        doc = ResearchDocument(
            id="doc123",
            crew_id="research_crew_macro",
            domain="macro",
            period_key="2026-03-03",
            briefing=briefing,
        )
        assert doc.is_daily is True
        assert doc.domain == "macro"

    def test_hourly_period_key(self):
        """Hourly period key is not daily."""
        briefing = ResearchBriefing(...)
        doc = ResearchDocument(
            id="doc456",
            crew_id="research_crew_crypto",
            domain="crypto",
            period_key="2026-03-03T14:00:00",
            briefing=briefing,
        )
        assert doc.is_daily is False


class TestGeneratePeriodKey:
    def test_daily_granularity(self):
        key = generate_period_key("daily")
        assert "T" not in key
        assert len(key) == 10  # YYYY-MM-DD

    def test_4h_granularity(self):
        key = generate_period_key("4h")
        assert "T" in key

    def test_invalid_granularity(self):
        with pytest.raises(ValueError):
            generate_period_key("invalid")


class TestDefaultSchedules:
    def test_all_crews_configured(self):
        assert len(DEFAULT_RESEARCH_SCHEDULES) == 5
        assert "research_crew_macro" in DEFAULT_RESEARCH_SCHEDULES
        assert "research_crew_crypto" in DEFAULT_RESEARCH_SCHEDULES

    def test_crypto_is_4h(self):
        config = DEFAULT_RESEARCH_SCHEDULES["research_crew_crypto"]
        assert config.period_granularity == "4h"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/finance-research-collective-memory.spec.md` for full model definitions
2. **Check dependencies** — none for this task
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** all models in `parrot/finance/research/memory/schemas.py`
5. **Run tests**: `pytest tests/test_research_memory_schemas.py -v`
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-109-research-memory-schemas.md`
8. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**: Implemented all data models in `parrot/finance/research/memory/schemas.py` with comprehensive tests (35 tests, all passing). Models include `ResearchDocument`, `ResearchScheduleConfig`, `AuditEvent`, `generate_period_key()`, `parse_period_key_date()`, and `DEFAULT_RESEARCH_SCHEDULES` for all 5 research crews. Package exports correctly set up in `__init__.py`.
