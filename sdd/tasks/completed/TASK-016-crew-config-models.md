# TASK-016: Configuration & Data Models

**Feature**: FEAT-010 — TelegramCrewTransport
**Spec**: `sdd/specs/telegram-crew-transport.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

This task implements Module 1 from the spec. The configuration models are the foundation for the entire crew transport system — every other module depends on loading and validating config correctly.

Implements spec Section 3, Module 1.

---

## Scope

- Implement `TelegramCrewConfig` Pydantic model with all fields from spec
- Implement `CrewAgentEntry` Pydantic model
- Add `from_yaml(path)` classmethod on `TelegramCrewConfig` for YAML loading with env var substitution
- Add sensible defaults and validators (e.g., `max_message_length` capped at 4096)

**NOT in scope**: AgentCard/AgentSkill models (TASK-017), registry logic, transport logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/telegram/crew/__init__.py` | CREATE | Empty init (will be populated in TASK-024) |
| `parrot/integrations/telegram/crew/config.py` | CREATE | TelegramCrewConfig + CrewAgentEntry models |
| `tests/test_telegram_crew/test_config.py` | CREATE | Unit tests for config models |

---

## Implementation Notes

### Pattern to Follow
```python
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import yaml
import os

class CrewAgentEntry(BaseModel):
    chatbot_id: str
    bot_token: str
    username: str
    skills: List[dict] = []
    tags: List[str] = []
    accepts_files: List[str] = []
    emits_files: List[str] = []
    system_prompt_override: Optional[str] = None

class TelegramCrewConfig(BaseModel):
    group_id: int
    coordinator_token: str
    coordinator_username: str
    hitl_user_ids: List[int] = []
    agents: Dict[str, CrewAgentEntry] = {}
    announce_on_join: bool = True
    update_pinned_registry: bool = True
    reply_to_sender: bool = True
    silent_tool_calls: bool = True
    typing_indicator: bool = True
    max_message_length: int = 4000
    temp_dir: str = "/tmp/parrot_crew"
    max_file_size_mb: int = 50
    allowed_mime_types: List[str] = [
        "text/csv", "application/json", "text/plain",
        "image/png", "image/jpeg", "application/pdf",
        "application/vnd.apache.parquet",
    ]

    @classmethod
    def from_yaml(cls, path: str) -> "TelegramCrewConfig":
        ...
```

### Key Constraints
- Use Pydantic v2 `BaseModel`
- YAML loading should support `${ENV_VAR}` substitution pattern
- All fields must have type hints and sensible defaults
- Use `logging.getLogger(__name__)`

### References in Codebase
- `parrot/integrations/telegram/settings.py` — existing Telegram config patterns
- `parrot/settings.py` — project-wide settings pattern

---

## Acceptance Criteria

- [ ] `TelegramCrewConfig` can be constructed from a dict with all fields
- [ ] `CrewAgentEntry` validates correctly
- [ ] `TelegramCrewConfig.from_yaml()` loads from a YAML file
- [ ] Environment variable substitution works in YAML values
- [ ] All tests pass: `pytest tests/test_telegram_crew/test_config.py -v`
- [ ] Import works: `from parrot.integrations.telegram.crew.config import TelegramCrewConfig`

---

## Test Specification

```python
# tests/test_telegram_crew/test_config.py
import pytest
from parrot.integrations.telegram.crew.config import (
    TelegramCrewConfig, CrewAgentEntry,
)


class TestCrewAgentEntry:
    def test_creation(self):
        entry = CrewAgentEntry(
            chatbot_id="agent1",
            bot_token="fake:token",
            username="agent1_bot",
        )
        assert entry.chatbot_id == "agent1"
        assert entry.skills == []

    def test_with_all_fields(self):
        entry = CrewAgentEntry(
            chatbot_id="agent1",
            bot_token="fake:token",
            username="agent1_bot",
            skills=[{"name": "echo", "description": "Echoes input"}],
            tags=["test"],
            accepts_files=["csv"],
            emits_files=["json"],
            system_prompt_override="Custom prompt",
        )
        assert len(entry.skills) == 1


class TestTelegramCrewConfig:
    def test_from_dict(self):
        config = TelegramCrewConfig(
            group_id=-1001234567890,
            coordinator_token="fake:coordinator",
            coordinator_username="coord_bot",
        )
        assert config.group_id == -1001234567890
        assert config.max_message_length == 4000

    def test_with_agents(self):
        config = TelegramCrewConfig(
            group_id=-100123,
            coordinator_token="fake:token",
            coordinator_username="coord_bot",
            agents={
                "TestAgent": CrewAgentEntry(
                    chatbot_id="test",
                    bot_token="fake:agent",
                    username="test_bot",
                )
            },
        )
        assert "TestAgent" in config.agents

    def test_from_yaml(self, tmp_path):
        yaml_content = """
group_id: -1001234567890
coordinator_token: "fake:coordinator"
coordinator_username: "coord_bot"
agents:
  TestAgent:
    chatbot_id: "test"
    bot_token: "fake:agent"
    username: "test_bot"
"""
        yaml_file = tmp_path / "crew.yaml"
        yaml_file.write_text(yaml_content)
        config = TelegramCrewConfig.from_yaml(str(yaml_file))
        assert config.group_id == -1001234567890
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/telegram-crew-transport.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-016-crew-config-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented `TelegramCrewConfig` and `CrewAgentEntry` Pydantic v2 models with YAML loading and `${ENV_VAR}` substitution. Added `max_message_length` validator (capped at 4096). All 14 unit tests pass. Created crew package with empty `__init__.py`.

**Deviations from spec**: none
