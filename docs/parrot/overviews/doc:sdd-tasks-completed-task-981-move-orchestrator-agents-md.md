---
type: Wiki Overview
title: 'TASK-981: Create `flows/agents/` package and move orchestrator agents'
id: doc:sdd-tasks-completed-task-981-move-orchestrator-agents-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (update relative imports for new package depth)
relates_to:
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.agents.a2a_orchestrator
  rel: mentions
- concept: mod:parrot.bots.flows.agents.hr
  rel: mentions
- concept: mod:parrot.bots.flows.agents.orchestrator
  rel: mentions
---

# TASK-981: Create `flows/agents/` package and move orchestrator agents

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-979
**Assigned-to**: unassigned

---

## Context

> Spec Module 6. Three agent classes live in `orchestration/`:
> `OrchestratorAgent`, `A2AOrchestratorAgent`, and the HR agents
> (`HRAgentFactory`, `RAGHRAgent`, `EmployeeDataAgent`). They must be moved
> to `flows/agents/` so the entire orchestration surface lives under `flows/`.
> The old files in `orchestration/` are NOT deleted.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/agents/` package
- Create `agents/__init__.py` exporting all public classes
- Move `orchestration/agent.py` → `flows/agents/orchestrator.py`
  (update relative imports for new package depth)
- Move `orchestration/a2a_orchestrator.py` → `flows/agents/a2a_orchestrator.py`
  (update relative imports; update internal ref `.agent.OrchestratorAgent`
  → `.orchestrator.OrchestratorAgent`)
- Move `orchestration/hr.py` → `flows/agents/hr.py`
  (update relative imports; update internal refs to `AgentCrew`)
- Do NOT delete files in `orchestration/` — they stay untouched

**NOT in scope**: Modifying any consumer that imports from `orchestration/`.
Modifying `orchestration/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/agents/__init__.py` | CREATE | Exports public classes |
| `packages/ai-parrot/src/parrot/bots/flows/agents/orchestrator.py` | CREATE | `OrchestratorAgent` (moved) |
| `packages/ai-parrot/src/parrot/bots/flows/agents/a2a_orchestrator.py` | CREATE | `A2AOrchestratorAgent` (moved) |
| `packages/ai-parrot/src/parrot/bots/flows/agents/hr.py` | CREATE | HR agent classes (moved) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# orchestration/agent.py imports (verified: line 1-8):
from typing import Dict, List, Any, Optional, Union, Callable
from ..agent import BasicAgent                    # → ../../agent → ...agent
from ..abstract import AbstractBot                # → ...abstract
from ...tools.agent import AgentContext, AgentTool # → ....tools.agent
from ...registry import agent_registry            # → ....registry
from ...models.responses import AIMessage         # → ....models.responses
from ...models.crew import AgentResult            # → ....models.crew

# NEW paths from flows/agents/orchestrator.py:
from ...agent import BasicAgent
from ...abstract import AbstractBot
from ....tools.agent import AgentContext, AgentTool
from ....registry import agent_registry
from ....models.responses import AIMessage
from ....models.crew import AgentResult

# orchestration/a2a_orchestrator.py imports (verified: line 1-14):
from ...tools.abstract import AbstractTool, AbstractToolArgsSchema
from ...a2a.mixin import A2AClientMixin
from ...a2a.client import A2AClient, A2AAgentConnection
from .agent import OrchestratorAgent  # → .orchestrator

# NEW paths from flows/agents/a2a_orchestrator.py:
from ....tools.abstract import AbstractTool, AbstractToolArgsSchema
from ....a2a.mixin import A2AClientMixin
from ....a2a.client import A2AClient, A2AAgentConnection
from .orchestrator import OrchestratorAgent

# orchestration/hr.py imports (verified: line 1-10):
from ..agent import BasicAgent
from .agent import OrchestratorAgent
from .crew import AgentCrew
from ...tools.abstract import AbstractTool
from ...tools.manager import ToolManager
from ...stores.abstract import AbstractStore

# NEW paths from flows/agents/hr.py:
from ...agent import BasicAgent
from .orchestrator import OrchestratorAgent
from ..crew import AgentCrew
from ....tools.abstract import AbstractTool
from ....tools.manager import ToolManager
from ....stores.abstract import AbstractStore
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/orchestration/agent.py:10
class OrchestratorAgent(BasicAgent):
    def __init__(self, name="OrchestratorAgent", orchestration_prompt=None,
                 agent_names=None, **kwargs): ...

# packages/ai-parrot/src/parrot/bots/orchestration/a2a_orchestrator.py:~60
class A2AOrchestratorAgent(OrchestratorAgent, A2AClientMixin): ...

# packages/ai-parrot/src/parrot/bots/orchestration/hr.py:13
class HRAgentFactory: ...
```

### Does NOT Exist
- ~~`parrot.bots.flows.agents`~~ — does not exist yet (this task creates it)
- ~~`parrot.bots.flows.agents.orchestrator`~~ — does not exist yet
- ~~`parrot.bots.flows.agents.hr`~~ — does not exist yet

---

## Implementation Notes

### Import Path Recalculation

From `flows/agents/orchestrator.py`, the package depth changes. Old relative
imports from `orchestration/agent.py` that used `..` (2 levels up to `bots/`)
now need `...` (3 levels: `agents/` → `flows/` → `bots/`).

Pattern:
- `orchestration/` is 1 level deep under `bots/`
- `flows/agents/` is 2 levels deep under `bots/`
- So add one extra `.` to every relative import that targets `bots/` or above

### `hr.py` imports `AgentCrew`

The old `hr.py` does `from .crew import AgentCrew`. In the new location
(`flows/agents/hr.py`), this becomes `from ..crew import AgentCrew`
(one level up to `flows/`, then into `crew/`).

### Key Constraints
- Keep all class signatures identical (no API changes)
- `a2a_orchestrator.py` references `.agent.OrchestratorAgent` — update to
  `.orchestrator.OrchestratorAgent`
- Do NOT modify any file in `orchestration/`

### References in Codebase
- `parrot/bots/orchestration/agent.py` — source for `OrchestratorAgent`
- `parrot/bots/orchestration/a2a_orchestrator.py` — source for `A2AOrchestratorAgent`
- `parrot/bots/orchestration/hr.py` — source for HR agents

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.agents import OrchestratorAgent` works
- [ ] `from parrot.bots.flows.agents import A2AOrchestratorAgent` works
- [ ] `from parrot.bots.flows.agents import ListAvailableA2AAgentsTool` works
- [ ] `from parrot.bots.flows.agents import HRAgentFactory` works
- [ ] `from parrot.bots.flows.agents.orchestrator import OrchestratorAgent` works
- [ ] `from parrot.bots.flows.agents.a2a_orchestrator import A2AOrchestratorAgent` works
- [ ] `from parrot.bots.flows.agents.hr import HRAgentFactory, RAGHRAgent, EmployeeDataAgent` works
- [ ] Files in `orchestration/` are NOT modified
- [ ] All class signatures are preserved

---

## Test Specification

```python
# tests/unit/test_flows_agents_import.py
import pytest


class TestFlowsAgentsImport:
    def test_orchestrator_import(self):
        from parrot.bots.flows.agents import OrchestratorAgent
        assert OrchestratorAgent is not None

    def test_a2a_orchestrator_import(self):
        from parrot.bots.flows.agents import A2AOrchestratorAgent
        assert A2AOrchestratorAgent is not None

    def test_a2a_tool_import(self):
        from parrot.bots.flows.agents import ListAvailableA2AAgentsTool
        assert ListAvailableA2AAgentsTool is not None

    def test_hr_factory_import(self):
        from parrot.bots.flows.agents import HRAgentFactory
        assert HRAgentFactory is not None

    def test_orchestrator_inherits_basic_agent(self):
        from parrot.bots.flows.agents import OrchestratorAgent
        from parrot.bots.agent import BasicAgent
        assert issubclass(OrchestratorAgent, BasicAgent)

    def test_a2a_inherits_orchestrator(self):
        from parrot.bots.flows.agents import A2AOrchestratorAgent, OrchestratorAgent
        assert issubclass(A2AOrchestratorAgent, OrchestratorAgent)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-979 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm the three source files still exist in `orchestration/`
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-981-move-orchestrator-agents.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (FEAT-143 session)
**Date**: 2026-05-04
**Notes**: Created `flows/agents/` package with four files:
`__init__.py` (exports all public classes), `orchestrator.py` (`OrchestratorAgent`
moved from `orchestration/agent.py` with import paths updated for 2-level depth;
`_init_execution_memory` updated to canonical `..core.storage.memory`),
`a2a_orchestrator.py` (`A2AOrchestratorAgent` + `ListAvailableA2AAgentsTool`;
`.agent.OrchestratorAgent` → `.orchestrator.OrchestratorAgent`),
`hr.py` (`HRAgentFactory`, `RAGHRAgent`, `EmployeeDataAgent`; `AgentCrew`
imported from `..crew` flows package). Files in `orchestration/` untouched.

**Deviations from spec**: none
