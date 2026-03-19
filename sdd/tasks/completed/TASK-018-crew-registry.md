# TASK-018: CrewRegistry

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-017
**Assigned-to**: claude-session

---

## Context

This task implements Module 3 from the spec. The `CrewRegistry` is the thread-safe in-memory registry that tracks all active agents in the crew. It provides CRUD operations and resolution by username or agent name.

Implements spec Section 3, Module 3.

---

## Scope

- Implement `CrewRegistry` class with in-memory storage
- Implement `register(card: AgentCard)` — adds agent to registry
- Implement `unregister(username: str)` — removes agent, returns removed card
- Implement `update_status(username, status, current_task=None)` — updates agent status
- Implement `get(username: str)` — returns card or None
- Implement `list_active()` — returns list of cards excluding offline agents
- Implement `resolve(name_or_username: str)` — resolves by @username or agent_name (case-insensitive)
- Ensure thread safety using `asyncio.Lock`

**NOT in scope**: Persistence to Redis/DB, coordinator bot logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/registry.py` | CREATE | CrewRegistry implementation |
| `tests/test_telegram_crew/test_registry.py` | CREATE | Unit tests including thread safety |

---

## Implementation Notes

### Pattern to Follow
```python
import asyncio
from typing import Dict, List, Optional
from .agent_card import AgentCard

class CrewRegistry:
    def __init__(self):
        self._agents: Dict[str, AgentCard] = {}  # keyed by username
        self._lock = asyncio.Lock()
        self.logger = logging.getLogger(__name__)
```

### Key Constraints
- Use `asyncio.Lock` for all mutating operations
- `resolve()` must support both `@username` and `agent_name` lookup (case-insensitive for names)
- `list_active()` excludes agents with status `"offline"`
- `update_status()` must also update `last_seen` timestamp
- Use `logging.getLogger(__name__)`

### References in Codebase
- `parrot/integrations/telegram/bot_manager.py` — existing registry pattern for bots

---

## Acceptance Criteria

- [ ] Register and unregister agents correctly
- [ ] Status transitions work (ready/busy/offline)
- [ ] `resolve()` works by username and by agent name (case-insensitive)
- [ ] `list_active()` excludes offline agents
- [ ] Thread safety verified with concurrent operations
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_registry.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.registry import CrewRegistry`

---

## Test Specification

```python
# tests/test_telegram_crew/test_registry.py
import pytest
import asyncio
from datetime import datetime, timezone
from parrot.integrations.telegram.crew.registry import CrewRegistry
from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill


@pytest.fixture
def registry():
    return CrewRegistry()


@pytest.fixture
def sample_card():
    return AgentCard(
        agent_id="agent1",
        agent_name="DataAgent",
        telegram_username="data_bot",
        telegram_user_id=111,
        model="gpt-4",
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestCrewRegistry:
    @pytest.mark.asyncio
    async def test_register_unregister(self, registry, sample_card):
        await registry.register(sample_card)
        assert registry.get("data_bot") is not None
        removed = await registry.unregister("data_bot")
        assert removed.agent_id == "agent1"
        assert registry.get("data_bot") is None

    @pytest.mark.asyncio
    async def test_update_status(self, registry, sample_card):
        await registry.register(sample_card)
        await registry.update_status("data_bot", "busy", "processing Q2")
        card = registry.get("data_bot")
        assert card.status == "busy"
        assert card.current_task == "processing Q2"

    def test_resolve_by_username(self, registry, sample_card):
        # sync register for test setup
        registry._agents["data_bot"] = sample_card
        assert registry.resolve("data_bot") is not None
        assert registry.resolve("@data_bot") is not None

    def test_resolve_by_name(self, registry, sample_card):
        registry._agents["data_bot"] = sample_card
        assert registry.resolve("DataAgent") is not None
        assert registry.resolve("dataagent") is not None

    @pytest.mark.asyncio
    async def test_list_active(self, registry, sample_card):
        await registry.register(sample_card)
        active = registry.list_active()
        assert len(active) == 1
        await registry.update_status("data_bot", "offline")
        active = registry.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_thread_safety(self, registry):
        cards = [
            AgentCard(
                agent_id=f"agent_{i}",
                agent_name=f"Agent{i}",
                telegram_username=f"bot_{i}",
                telegram_user_id=i,
                model="test",
                joined_at=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
            )
            for i in range(10)
        ]
        await asyncio.gather(*[registry.register(c) for c in cards])
        assert len(registry.list_active()) == 10
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-017 (AgentCard) is in `sdd/tasks/completed/`
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-018-crew-registry.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `CrewRegistry` with asyncio.Lock-based thread safety. All CRUD operations (register, unregister, update_status, get, list_active, resolve) working. Resolution supports @username and case-insensitive agent_name lookup. update_status also updates last_seen timestamp. All 16 unit tests pass including concurrent register/unregister.

**Deviations from spec**: none
