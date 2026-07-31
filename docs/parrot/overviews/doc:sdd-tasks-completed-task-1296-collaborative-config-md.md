---
type: Wiki Overview
title: 'TASK-1296: Collaborative Config Extension'
id: doc:sdd-tasks-completed-task-1296-collaborative-config-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The collaborative session needs YAML configuration for trigger command, round
  count,
relates_to:
- concept: mod:parrot.integrations.matrix.crew.config
  rel: mentions
---

# TASK-1296: Collaborative Config Extension

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The collaborative session needs YAML configuration for trigger command, round count,
timeouts, summarizer agent, and verbosity. This task adds a `CollaborativeConfig`
Pydantic model and integrates it as an optional field on the existing `MatrixCrewConfig`.

Implements Spec Module 2.

---

## Scope

- Create `CollaborativeConfig` Pydantic model with fields: `command_prefix`,
  `max_rounds`, `agent_timeout`, `session_timeout`, `summarizer_agent`,
  `session_verbosity`, `include_chat_context`.
- Add `collaborative: Optional[CollaborativeConfig] = None` field to `MatrixCrewConfig`.
- Ensure backward compatibility: configs without `collaborative:` section still load.
- Write unit tests for config loading, defaults, and YAML round-trip.

**NOT in scope**: Session orchestration, transport routing changes, reply-to support.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/matrix/crew/config.py` | MODIFY | Add `CollaborativeConfig` model and field on `MatrixCrewConfig` |
| `tests/test_matrix_collaborative_config.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.config import MatrixCrewConfig, MatrixCrewAgentEntry
from pydantic import BaseModel, Field
```

### Existing Signatures to Use
```python
# parrot/integrations/matrix/crew/config.py:91
class MatrixCrewConfig(BaseModel):
    homeserver_url: str
    server_name: str
    as_token: str
    hs_token: str
    bot_mxid: str
    general_room_id: str
    agents: Dict[str, MatrixCrewAgentEntry] = {}
    appservice_port: int = 8449
    pinned_registry: bool = True
    typing_indicator: bool = True
    streaming: bool = True
    unaddressed_agent: Optional[str] = None
    max_message_length: int = 4096

    @classmethod
    def from_yaml(cls, path: str) -> "MatrixCrewConfig":  # line 140
```

### Does NOT Exist
- ~~`MatrixCrewConfig.collaborative`~~ — this is what we're adding
- ~~`CollaborativeConfig`~~ — this is what we're creating

---

## Implementation Notes

### Pattern to Follow
```python
class CollaborativeConfig(BaseModel):
    command_prefix: str = Field(default="!investigate")
    max_rounds: int = Field(default=1, ge=1, le=10)
    agent_timeout: float = Field(default=120.0)
    session_timeout: float = Field(default=600.0)
    summarizer_agent: Optional[str] = Field(default=None)
    session_verbosity: str = Field(default="full")
    include_chat_context: bool = Field(default=True)

# Add to MatrixCrewConfig:
collaborative: Optional[CollaborativeConfig] = Field(
    default=None, description="Collaborative session configuration"
)
```

### Key Constraints
- `CollaborativeConfig` is `Optional` on `MatrixCrewConfig` — existing YAMLs without
  this section must continue loading without errors.
- `from_yaml()` already calls `_walk_and_substitute()` for env vars — no changes
  needed for the loader itself.

### References in Codebase
- `parrot/integrations/matrix/crew/config.py:57` — `MatrixCrewAgentEntry` pattern
- `parrot/integrations/matrix/crew/config.py:140` — `from_yaml()` classmethod

---

## Acceptance Criteria

- [ ] `CollaborativeConfig` model exists with all specified fields and defaults
- [ ] `MatrixCrewConfig.collaborative` field is optional (None by default)
- [ ] Existing YAML configs without `collaborative:` load without errors
- [ ] YAML config with `collaborative:` section loads correctly
- [ ] Environment variable substitution works in collaborative fields
- [ ] All tests pass: `pytest tests/test_matrix_collaborative_config.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/matrix/crew/config.py`

---

## Test Specification

```python
import pytest
from parrot.integrations.matrix.crew.config import MatrixCrewConfig, CollaborativeConfig


class TestCollaborativeConfig:
    def test_defaults(self):
        config = CollaborativeConfig()
        assert config.command_prefix == "!investigate"
        assert config.max_rounds == 1
        assert config.agent_timeout == 120.0
        assert config.summarizer_agent is None
        assert config.session_verbosity == "full"

    def test_max_rounds_validation(self):
        with pytest.raises(Exception):
            CollaborativeConfig(max_rounds=0)
        with pytest.raises(Exception):
            CollaborativeConfig(max_rounds=11)


class TestMatrixCrewConfigBackwardCompat:
    def test_loads_without_collaborative(self):
        """Existing config without collaborative: section loads fine."""
        config = MatrixCrewConfig(
            homeserver_url="http://localhost:8008",
            server_name="test.local",
            as_token="test", hs_token="test",
            bot_mxid="@bot:test.local",
            general_room_id="!room:test.local",
        )
        assert config.collaborative is None

    def test_loads_with_collaborative(self):
        """Config with collaborative: section loads and validates."""
        config = MatrixCrewConfig(
            homeserver_url="http://localhost:8008",
            server_name="test.local",
            as_token="test", hs_token="test",
            bot_mxid="@bot:test.local",
            general_room_id="!room:test.local",
            collaborative={"max_rounds": 3, "summarizer_agent": "summarizer"},
        )
        assert config.collaborative.max_rounds == 3
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm signatures still match
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1296-collaborative-config.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
