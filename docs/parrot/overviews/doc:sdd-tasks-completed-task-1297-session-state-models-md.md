---
type: Wiki Overview
title: 'TASK-1297: Session State Models'
id: doc:sdd-tasks-completed-task-1297-session-state-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The collaborative session orchestrator needs Pydantic models to track session
  lifecycle,
relates_to:
- concept: mod:parrot.integrations.matrix.crew
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.session_models
  rel: mentions
---

# TASK-1297: Session State Models

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The collaborative session orchestrator needs Pydantic models to track session lifecycle,
per-agent round results, and overall session state. These are pure data models with no
Matrix I/O, making them independently testable.

Implements Spec Module 3.

---

## Scope

- Create `parrot/integrations/matrix/crew/session_models.py` with:
  - `SessionPhase` enum: CREATED, INVESTIGATING, CROSS_POLLINATING, SYNTHESIZING, COMPLETED, FAILED
  - `AgentRoundResult` model: agent_name, display_name, mxid, round_number, result_text, event_id, timestamp
  - `CollaborativeSessionState` model: session_id, room_id, question, phase, current_round, max_rounds, agent_results, started_at, completed_at, final_synthesis
- Export models from `crew/__init__.py`.
- Write unit tests for model creation, serialization, and phase transitions.

**NOT in scope**: Session orchestration logic, Matrix messaging, config.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/matrix/crew/session_models.py` | CREATE | Pydantic data models |
| `parrot/integrations/matrix/crew/__init__.py` | MODIFY | Add exports |
| `tests/test_matrix_session_models.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field
from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional
```

### Existing Signatures to Use
```python
# parrot/integrations/matrix/crew/__init__.py:1-40
# Current exports — add new models alongside existing ones:
# MatrixCrewConfig, MatrixCrewAgentEntry, MatrixCrewRegistry, MatrixAgentCard,
# MatrixCoordinator, MatrixCrewAgentWrapper, MatrixCrewTransport,
# parse_mention, format_reply, build_pill
```

### Does NOT Exist
- ~~`SessionPhase`~~ — this is what we're creating
- ~~`AgentRoundResult`~~ — this is what we're creating
- ~~`CollaborativeSessionState`~~ — this is what we're creating
- ~~`parrot/integrations/matrix/crew/session_models.py`~~ — file does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
class SessionPhase(str, Enum):
    CREATED = "created"
    INVESTIGATING = "investigating"
    CROSS_POLLINATING = "cross_pollinating"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"

class AgentRoundResult(BaseModel):
    agent_name: str
    display_name: str
    mxid: str
    round_number: int
    result_text: str
    event_id: str
    timestamp: datetime

class CollaborativeSessionState(BaseModel):
    session_id: str
    room_id: str
    question: str
    phase: SessionPhase = SessionPhase.CREATED
    current_round: int = 0
    max_rounds: int = 1
    agent_results: Dict[str, List[AgentRoundResult]] = Field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    final_synthesis: Optional[str] = None
```

### Key Constraints
- Pure Pydantic models — no async, no I/O.
- `AgentRoundResult.event_id` stores the Matrix event ID for reply-to threading.
- `agent_results` is keyed by agent_name with a list of results per round.

### References in Codebase
- `parrot/integrations/matrix/crew/registry.py:14` — `MatrixAgentCard` as pattern for agent data models

---

## Acceptance Criteria

- [ ] `SessionPhase` enum has all 6 values
- [ ] `AgentRoundResult` model validates and serializes correctly
- [ ] `CollaborativeSessionState` model validates and serializes correctly
- [ ] Models exported from `parrot.integrations.matrix.crew`
- [ ] All tests pass: `pytest tests/test_matrix_session_models.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/matrix/crew/session_models.py`

---

## Test Specification

```python
import pytest
from datetime import datetime, timezone
from parrot.integrations.matrix.crew.session_models import (
    SessionPhase, AgentRoundResult, CollaborativeSessionState,
)


class TestSessionPhase:
    def test_enum_values(self):
        assert SessionPhase.CREATED == "created"
        assert SessionPhase.INVESTIGATING == "investigating"
        assert SessionPhase.COMPLETED == "completed"


class TestAgentRoundResult:
    def test_creation(self):
        result = AgentRoundResult(
            agent_name="analyst",
            display_name="Financial Analyst",
            mxid="@analyst:server",
            round_number=1,
            result_text="Analysis complete",
            event_id="$event123",
            timestamp=datetime.now(timezone.utc),
        )
        assert result.agent_name == "analyst"

    def test_serialization(self):
        result = AgentRoundResult(...)
        data = result.model_dump()
        assert "event_id" in data


class TestCollaborativeSessionState:
    def test_defaults(self):
        state = CollaborativeSessionState(
            session_id="sess-1", room_id="!room:server", question="test?"
        )
        assert state.phase == SessionPhase.CREATED
        assert state.current_round == 0
        assert state.agent_results == {}
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `crew/__init__.py` exports
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1297-session-state-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
