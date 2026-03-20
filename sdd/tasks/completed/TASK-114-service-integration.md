# TASK-114: Service Integration

**Feature**: FEAT-010
**Spec**: `sdd/specs/finance-research-collective-memory.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-111, TASK-112, TASK-113
**Assigned-to**: claude-session

---

## Context

This task integrates `FileResearchMemory` into `FinanceResearchService`, replacing the Redis-based `ResearchBriefingStore`. Also updates `DeliberationTrigger` to use the new memory.

Reference: Spec Section 3 "Module 5: Service Integration"

---

## Scope

- Modify `FinanceResearchService` to use `FileResearchMemory` instead of `ResearchBriefingStore`
- Initialize memory at service startup with `set_research_memory()`
- Update schedule configurations to use `ResearchScheduleConfig`
- Modify `DeliberationTrigger` to check memory freshness instead of Redis
- Remove Redis dependency from service (for briefing storage)

**NOT in scope**:
- Crew integration (TASK-115)
- Analyst integration (TASK-116)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/finance/research/service.py` | MODIFY | Replace briefing store with memory |
| `parrot/finance/research/trigger.py` | MODIFY | Use memory for freshness checks |
| `parrot/finance/research/__init__.py` | MODIFY | Update exports |

---

## Implementation Notes

### Service Modifications

```python
# parrot/finance/research/service.py
from parrot.finance.research.memory import (
    FileResearchMemory,
    set_research_memory,
    DEFAULT_RESEARCH_SCHEDULES,
)

class FinanceResearchService(AgentService):
    """Research service with collective memory storage."""

    def __init__(
        self,
        bot_manager: BotManager,
        memory_base_path: str = "./research_memory",
        max_workers: int = 5,
        heartbeats: list[HeartbeatConfig] | None = None,
    ):
        # Build heartbeats from DEFAULT_RESEARCH_SCHEDULES if not provided
        if heartbeats is None:
            heartbeats = self._build_heartbeats_from_schedules()

        super().__init__(
            bot_manager=bot_manager,
            max_workers=max_workers,
            heartbeats=heartbeats,
        )

        # Initialize collective memory
        self._memory = FileResearchMemory(
            base_path=memory_base_path,
            cache_max_size=100,
            warmup_on_init=True,
        )

    async def start(self) -> None:
        """Start service with memory initialization."""
        # Initialize memory
        await self._memory.start()

        # Set global memory for tools
        set_research_memory(self._memory)

        # Start parent service (heartbeats, etc.)
        await super().start()

        self.logger.info("FinanceResearchService started with collective memory")

    async def stop(self) -> None:
        """Stop service gracefully."""
        await super().stop()
        await self._memory.stop()

    def _build_heartbeats_from_schedules(self) -> list[HeartbeatConfig]:
        """Build HeartbeatConfig list from DEFAULT_RESEARCH_SCHEDULES."""
        heartbeats = []
        for crew_id, config in DEFAULT_RESEARCH_SCHEDULES.items():
            heartbeats.append(HeartbeatConfig(
                agent_name=crew_id,
                cron_expression=config.cron_expression,
                prompt_template=CREW_PROMPTS.get(crew_id, "Execute research."),
                delivery=DeliveryConfig(channel=DeliveryChannel.LOG),
                metadata={
                    "domain": config.crew_id.replace("research_crew_", ""),
                    "type": "research_crew",
                    "period_granularity": config.period_granularity,
                },
            ))
        return heartbeats

    @property
    def memory(self) -> FileResearchMemory:
        """Access the collective memory store."""
        return self._memory
```

### Remove Redis Briefing Store Usage

```python
# In _process_task, replace:
# await self.briefing_store.store_briefing(crew_id, briefing)

# With:
from .memory.schemas import ResearchDocument
from .memory import set_research_memory

# ... in _process_task:
# The crew itself will call store_research tool, OR we can do it here:
if result.success and "briefing" in result.output:
    document = ResearchDocument(
        id=uuid.uuid4().hex,
        crew_id=crew_id,
        domain=domain,
        period_key=generate_period_key(config.period_granularity),
        briefing=parsed_briefing,
    )
    await self._memory.store(document)
```

### Trigger Modifications

```python
# parrot/finance/research/trigger.py
from parrot.finance.research.memory import FileResearchMemory


class DeliberationTrigger:
    """Monitor research freshness and trigger deliberation."""

    def __init__(
        self,
        memory: FileResearchMemory,
        # Remove: redis: aioredis.Redis,
        # Remove: briefing_store: ResearchBriefingStore,
        mode: TriggerMode = TriggerMode.QUORUM,
        quorum_threshold: int = 4,
        staleness_windows: dict[str, timedelta] | None = None,
        # ...
    ):
        self.memory = memory
        # ... rest unchanged

    async def check_freshness(self) -> dict[str, bool]:
        """Check which domains have fresh research."""
        now = datetime.now(timezone.utc)
        freshness = {}

        for domain in ["macro", "equity", "crypto", "sentiment", "risk"]:
            doc = await self.memory.get_latest(domain)
            if doc is None:
                freshness[domain] = False
                continue

            window = self.staleness_windows.get(domain, timedelta(hours=8))
            age = now - doc.generated_at
            freshness[domain] = age <= window

        return freshness

    async def _fetch_briefings(self) -> dict[str, ResearchBriefing]:
        """Fetch all fresh briefings for deliberation."""
        briefings = {}
        for domain in ["macro", "equity", "crypto", "sentiment", "risk"]:
            doc = await self.memory.get_latest(domain)
            if doc:
                briefings[domain] = doc.briefing
        return briefings
```

### Key Constraints

- Remove Redis briefing dependencies entirely
- Keep Redis only if used for other purposes (distributed lock, etc.)
- Initialize memory BEFORE starting heartbeats
- Set global memory for tools via `set_research_memory()`
- Maintain backward compatibility with existing service API

### References in Codebase

- `parrot/finance/research/service.py` — Current implementation
- `parrot/finance/research/trigger.py` — Current implementation
- `parrot/finance/research/briefing_store.py` — To be replaced

---

## Acceptance Criteria

- [x] `FinanceResearchService` uses `FileResearchMemory` instead of `ResearchBriefingStore`
- [x] Memory initialized at service `start()` with `set_research_memory()`
- [x] Heartbeats built from `DEFAULT_RESEARCH_SCHEDULES`
- [x] `DeliberationTrigger` uses memory for freshness checks
- [x] No Redis dependency for briefing storage
- [x] Service `stop()` calls `memory.stop()`
- [x] Existing service tests still pass (with modifications)

---

## Test Specification

```python
# tests/test_finance_research_service.py
import pytest
from parrot.finance.research.service import FinanceResearchService
from parrot.finance.research.memory import get_research_memory


class TestFinanceResearchService:
    @pytest.mark.asyncio
    async def test_service_starts_with_memory(self, bot_manager, tmp_path):
        service = FinanceResearchService(
            bot_manager=bot_manager,
            memory_base_path=str(tmp_path / "memory"),
        )
        await service.start()

        # Memory should be accessible
        memory = get_research_memory()
        assert memory is not None

        await service.stop()

    @pytest.mark.asyncio
    async def test_schedules_from_config(self, bot_manager, tmp_path):
        service = FinanceResearchService(
            bot_manager=bot_manager,
            memory_base_path=str(tmp_path / "memory"),
        )

        # Check heartbeats match DEFAULT_RESEARCH_SCHEDULES
        assert len(service._heartbeats) == 5
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-111, TASK-112, TASK-113 must be complete
2. **Update status** → `"in-progress"`
3. **Read current** `service.py` and `trigger.py` to understand existing code
4. **Modify** to use `FileResearchMemory`
5. **Run tests**: `pytest tests/test_finance_research_service.py -v`
6. **Verify** existing service tests still pass
7. **Move to completed** and update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-03
**Notes**:
- Modified `FinanceResearchService` to use `FileResearchMemory` instead of `ResearchBriefingStore`
- Service now initializes memory at startup before starting AgentService base class
- Global memory set via `set_research_memory()` for tool access
- `_build_heartbeats_from_schedules()` method builds heartbeats from `DEFAULT_RESEARCH_SCHEDULES`
- `_process_task()` now stores `ResearchDocument` to memory with proper period keys
- `DeliberationTrigger` now accepts `ResearchMemory` and uses polling instead of Redis pub/sub
- `check_freshness()` method queries memory's `get_latest()` for each domain
- `_fetch_briefings()` retrieves briefings from memory for pipeline execution
- Redis kept only for distributed locking and debounce tracking
- All 117 research memory tests passing + 16 research runner tests passing
