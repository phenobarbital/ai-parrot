# TASK-017: AgentCard & AgentSkill Models

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This task implements Module 2 from the spec. `AgentCard` is the identity and capability descriptor for each agent in the crew. It provides rendering methods used by the CoordinatorBot for the pinned registry message and agent announcements.

Implements spec Section 3, Module 2.

---

## Scope

- Implement `AgentSkill` Pydantic model (name, description, input_types, output_types, example)
- Implement `AgentCard` Pydantic model with all fields from spec
- Implement `to_telegram_text()` method — renders a formatted announcement message for the group
- Implement `to_registry_line()` method — renders a compact one-line status for the pinned message (with emoji per status: ready/busy/offline)

**NOT in scope**: Registry CRUD (TASK-018), mention building (TASK-020).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/agent_card.py` | CREATE | AgentCard + AgentSkill models |
| `tests/test_telegram_crew/test_agent_card.py` | CREATE | Unit tests |

---

## Implementation Notes

### Key Constraints
- `AgentCard.status` must be one of: `"ready"`, `"busy"`, `"offline"`
- `to_registry_line()` format: `{emoji} @{username}  {agent_name} · {current_task or ""}"`
  - Emoji mapping: ready=checkmark, busy=hourglass, offline=red circle
- `to_telegram_text()` should render a multi-line announcement with agent name, model, skills list, file types
- Use `datetime` with timezone-aware fields for `joined_at` and `last_seen`
- Use Pydantic v2 `BaseModel`

### References in Codebase
- `parrot/integrations/telegram/bot_manager.py` — existing bot identity patterns

---

## Acceptance Criteria

- [ ] `AgentSkill` validates correctly with all optional fields
- [ ] `AgentCard` can be instantiated with all fields from spec
- [ ] `to_telegram_text()` returns a formatted multi-line string
- [ ] `to_registry_line()` returns correct emoji per status
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_agent_card.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill`

---

## Test Specification

```python
# tests/test_telegram_crew/test_agent_card.py
import pytest
from datetime import datetime, timezone
from parrot.integrations.telegram.crew.agent_card import AgentCard, AgentSkill


@pytest.fixture
def sample_skill():
    return AgentSkill(name="echo", description="Echoes input")


@pytest.fixture
def sample_card(sample_skill):
    return AgentCard(
        agent_id="test_agent",
        agent_name="TestAgent",
        telegram_username="test_agent_bot",
        telegram_user_id=999999,
        model="test:model",
        skills=[sample_skill],
        tags=["test"],
        joined_at=datetime.now(timezone.utc),
        last_seen=datetime.now(timezone.utc),
    )


class TestAgentSkill:
    def test_creation(self, sample_skill):
        assert sample_skill.name == "echo"
        assert sample_skill.input_types == []

    def test_with_all_fields(self):
        skill = AgentSkill(
            name="analyze",
            description="Analyzes data",
            input_types=["csv", "json"],
            output_types=["text", "chart"],
            example="Analyze sales Q2",
        )
        assert len(skill.input_types) == 2


class TestAgentCard:
    def test_creation(self, sample_card):
        assert sample_card.agent_id == "test_agent"
        assert sample_card.status == "ready"

    def test_to_telegram_text(self, sample_card):
        text = sample_card.to_telegram_text()
        assert "TestAgent" in text
        assert "@test_agent_bot" in text

    def test_to_registry_line_ready(self, sample_card):
        line = sample_card.to_registry_line()
        assert "@test_agent_bot" in line

    def test_to_registry_line_busy(self, sample_card):
        sample_card.status = "busy"
        sample_card.current_task = "processing Q2"
        line = sample_card.to_registry_line()
        assert "processing Q2" in line

    def test_to_registry_line_offline(self, sample_card):
        sample_card.status = "offline"
        line = sample_card.to_registry_line()
        assert "@test_agent_bot" in line
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-017-agent-card.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `AgentCard` and `AgentSkill` Pydantic v2 models with `to_telegram_text()` (multi-line announcement) and `to_registry_line()` (compact status with emoji). Status emoji mapping: ready=checkmark, busy=hourglass, offline=red circle. All 12 unit tests pass.

**Deviations from spec**: none
