---
type: Wiki Overview
title: 'TASK-1060: Relocate crew definition models to parrot/models/'
id: doc:sdd-tasks-completed-task-1060-relocate-crew-definition-models-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The definition models (`ExecutionMode`, `AgentDefinition`, `FlowRelation`,
relates_to:
- concept: mod:parrot.handlers.crew.models
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.crew_definition
  rel: mentions
---

# TASK-1060: Relocate crew definition models to parrot/models/

**Feature**: FEAT-156 — AgentCrew.from_definition classmethod
**Spec**: `sdd/proposals/agentcrew-from-definition.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The definition models (`ExecutionMode`, `AgentDefinition`, `FlowRelation`,
`CrewDefinition`) currently live in `parrot/handlers/crew/models.py` — the HTTP
handler layer. However, they are imported by `manager/manager.py`,
`autonomous/orchestrator.py`, and `handlers/crew/redis_persistence.py`, proving
they are not HTTP-specific. Moving them to `parrot/models/` establishes them as
core data models, which is a prerequisite for `AgentCrew.from_definition()` to
import them without a circular handler → bots dependency.

---

## Scope

- Create `parrot/models/crew_definition.py` with `ExecutionMode`, `AgentDefinition`,
  `FlowRelation`, and `CrewDefinition` (moved from `handlers/crew/models.py`).
- Add re-exports in `handlers/crew/models.py` so existing imports continue to work.
- Add exports in `parrot/models/__init__.py`.
- Update direct importers to use the new canonical path (optional — re-exports
  guarantee backward compat, but updating is cleaner).

**NOT in scope**:
- Job-related models (`CrewJob`, `CrewQueryRequest`, `CrewJobResponse`, etc.) —
  these are genuinely HTTP-specific and stay in `handlers/crew/models.py`.
- The `AgentCrew.from_definition()` method itself (TASK-1061).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/crew_definition.py` | CREATE | New home for definition models |
| `packages/ai-parrot/src/parrot/models/__init__.py` | MODIFY | Add exports for new models |
| `packages/ai-parrot/src/parrot/handlers/crew/models.py` | MODIFY | Replace definitions with re-exports |
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Update import path (line 61) |
| `packages/ai-parrot/src/parrot/autonomous/orchestrator.py` | MODIFY | Update import path (line 37) |
| `packages/ai-parrot/src/parrot/handlers/crew/execution_handler.py` | MODIFY | Update import path (line 8-11) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current imports to migrate FROM:
from ..handlers.crew.models import CrewDefinition, ExecutionMode  # manager/manager.py:61
from ..handlers.crew.models import CrewDefinition  # autonomous/orchestrator.py:37
from parrot.handlers.crew.models import JobStatus, ExecutionMode  # execution_handler.py:8-11
from .models import CrewDefinition, ExecutionMode  # handlers/crew/handler.py:17
from .models import CrewDefinition  # handlers/crew/redis_persistence.py:13
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/handlers/crew/models.py:14
class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    FLOW = "flow"
    LOOP = "loop"

# packages/ai-parrot/src/parrot/handlers/crew/models.py:31
class AgentDefinition(BaseModel):
    agent_id: str
    agent_class: str = Field(default="BaseAgent")
    name: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    tools: List[str] = Field(default_factory=list)
    system_prompt: Optional[str] = None

# packages/ai-parrot/src/parrot/handlers/crew/models.py:56
class FlowRelation(BaseModel):
    source: Union[str, List[str]]
    target: Union[str, List[str]]

# packages/ai-parrot/src/parrot/handlers/crew/models.py:66
class CrewDefinition(BaseModel):
    crew_id: str
    tenant: str = Field(default="global")
    name: str
    description: Optional[str] = None
    execution_mode: ExecutionMode = Field(default=ExecutionMode.SEQUENTIAL)
    agents: List[AgentDefinition]
    flow_relations: List[FlowRelation] = Field(default_factory=list)
    shared_tools: List[str] = Field(default_factory=list)
    max_parallel_tasks: int = Field(default=10)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
```

### Does NOT Exist
- ~~`parrot.models.crew_definition`~~ — does not exist yet (this task creates it)
- ~~`CrewDefinition.from_definition`~~ — no factory methods on CrewDefinition

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same pattern as parrot/models/crew.py
# which contains CrewResult, AgentExecutionInfo, etc.
# Pure data models with no imports from parrot/bots/ or parrot/handlers/
```

### Key Constraints
- The new module must NOT import from `parrot/bots/` or `parrot/handlers/` — models are pure data.
- Re-exports in `handlers/crew/models.py` must be exact: same names, same public API.
- `JobStatus`, `CrewJob`, `CrewQueryRequest`, `CrewJobResponse`, `CrewJobStatusResponse`,
  `CrewListResponse` stay in `handlers/crew/models.py`.

---

## Acceptance Criteria

- [ ] `from parrot.models.crew_definition import CrewDefinition, AgentDefinition, FlowRelation, ExecutionMode` works
- [ ] `from parrot.models import CrewDefinition, AgentDefinition, FlowRelation, ExecutionMode` works
- [ ] `from parrot.handlers.crew.models import CrewDefinition, ExecutionMode` still works (re-exports)
- [ ] No circular imports: `python -c "from parrot.models.crew_definition import CrewDefinition"`
- [ ] All existing tests pass: `pytest tests/ -x -q`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/models/crew_definition.py`

---

## Test Specification

```python
# tests/unit/test_crew_definition_models.py
import pytest
from parrot.models.crew_definition import (
    ExecutionMode, AgentDefinition, FlowRelation, CrewDefinition
)


class TestModelRelocation:
    def test_execution_mode_values(self):
        assert ExecutionMode.SEQUENTIAL == "sequential"
        assert ExecutionMode.PARALLEL == "parallel"
        assert ExecutionMode.FLOW == "flow"
        assert ExecutionMode.LOOP == "loop"

    def test_agent_definition_defaults(self):
        ad = AgentDefinition(agent_id="test-agent")
        assert ad.agent_class == "BaseAgent"
        assert ad.config == {}
        assert ad.tools == []

    def test_crew_definition_roundtrip(self):
        cd = CrewDefinition(
            name="test-crew",
            agents=[AgentDefinition(agent_id="a1")],
        )
        data = cd.model_dump()
        cd2 = CrewDefinition(**data)
        assert cd2.name == "test-crew"

    def test_backward_compat_import(self):
        from parrot.handlers.crew.models import CrewDefinition as CD
        assert CD is CrewDefinition


class TestFlowRelation:
    def test_single_source_target(self):
        fr = FlowRelation(source="agent-a", target="agent-b")
        assert fr.source == "agent-a"

    def test_list_source_target(self):
        fr = FlowRelation(source=["a", "b"], target=["c"])
        assert isinstance(fr.source, list)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has none
3. **Verify the Codebase Contract** — confirm all imports and signatures listed above
4. **Update status** in `sdd/tasks/index/FEAT-156.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1060-relocate-crew-definition-models.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-11
**Notes**: Created `parrot/models/crew_definition.py` with `ExecutionMode`, `AgentDefinition`,
`FlowRelation`, and `CrewDefinition` copied verbatim from `handlers/crew/models.py`.
Updated `handlers/crew/models.py` to re-export the 4 classes and keep `JobStatus`,
`CrewJob`, `CrewQueryRequest`, `CrewJobResponse`, `CrewJobStatusResponse`, `CrewListResponse`
in place. Updated `parrot/models/__init__.py` to add imports and `__all__` entries.
Updated `manager/manager.py`, `autonomous/orchestrator.py`, and
`handlers/crew/execution_handler.py` to import from the new canonical path.
All 9 unit tests pass.

**Deviations from spec**: none
