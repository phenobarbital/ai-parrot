---
type: Wiki Overview
title: 'TASK-982: Update `flows/__init__.py` exports'
id: doc:sdd-tasks-completed-task-982-update-flows-init-exports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from .crew import AgentCrew, CrewAgentNode
relates_to:
- concept: mod:parrot.bots.flows
  rel: mentions
---

# TASK-982: Update `flows/__init__.py` exports

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-979, TASK-980, TASK-981
**Assigned-to**: unassigned

---

## Context

> Spec Module 7. The top-level `flows/__init__.py` currently only re-exports
> core primitives. After all modules have been moved, it must also export
> `AgentCrew`, `CrewAgentNode`, `NodeResult`, and the agent classes from their
> new sub-packages.

---

## Scope

- Update `packages/ai-parrot/src/parrot/bots/flows/__init__.py`:
  - Add exports for `AgentCrew`, `CrewAgentNode` from `.crew`
  - Add export for `NodeResult` from `.core.result`
  - Add exports for `OrchestratorAgent`, `A2AOrchestratorAgent`,
    `HRAgentFactory` from `.agents`
  - Add export for `ResultRetrievalTool` from `.tools`
  - Update `__all__` list
- Verify `orchestration/` is left in place (NOT deleted)

**NOT in scope**: Modifying any other file. Fixing consumers. Deleting
`orchestration/`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | MODIFY | Add new exports |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Current flows/__init__.py (verified: 75 lines)
# Already exports from .core: AgentLike, AgentRef, ..., FlowResult, FlowContext, etc.
# New imports to add:

from .crew import AgentCrew, CrewAgentNode
from .core.result import NodeResult
from .agents import (
    OrchestratorAgent,
    A2AOrchestratorAgent,
    ListAvailableA2AAgentsTool,
    HRAgentFactory,
)
from .tools import ResultRetrievalTool
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/__init__.py:1-74
# Current __all__ list includes 24 core symbols.
# Append new symbols to __all__.
```

### Does NOT Exist
- ~~`parrot.bots.flows.AgentCrew`~~ — will exist after this task
- ~~`parrot.bots.flows.OrchestratorAgent`~~ — will exist after this task

---

## Implementation Notes

### Pattern to Follow
```python
# Append to existing flows/__init__.py, after the core imports:

# Crew sub-package
from .crew import AgentCrew, CrewAgentNode

# Node-level result model
from .core.result import NodeResult

# Agent classes
from .agents import (
    OrchestratorAgent,
    A2AOrchestratorAgent,
    ListAvailableA2AAgentsTool,
    HRAgentFactory,
)

# Tools
from .tools import ResultRetrievalTool

# Update __all__:
__all__ = [
    # ... existing entries ...
    # Crew
    "AgentCrew",
    "CrewAgentNode",
    # Result
    "NodeResult",
    # Agents
    "OrchestratorAgent",
    "A2AOrchestratorAgent",
    "ListAvailableA2AAgentsTool",
    "HRAgentFactory",
    # Tools
    "ResultRetrievalTool",
]
```

### Key Constraints
- Keep all existing exports intact — this is additive only
- Import order: core imports first (existing), then crew, agents, tools
- `orchestration/` directory must remain untouched
- `orchestration/__init__.py` is NOT modified

### References in Codebase
- `parrot/bots/flows/__init__.py` — file to modify
- `parrot/bots/orchestration/__init__.py` — verify it still exists

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows import AgentCrew` works
- [ ] `from parrot.bots.flows import CrewAgentNode` works
- [ ] `from parrot.bots.flows import NodeResult` works
- [ ] `from parrot.bots.flows import OrchestratorAgent` works
- [ ] `from parrot.bots.flows import A2AOrchestratorAgent` works
- [ ] `from parrot.bots.flows import ResultRetrievalTool` works
- [ ] All previously-exported symbols still work (no regressions)
- [ ] `parrot/bots/orchestration/` directory still exists (NOT deleted)
- [ ] `parrot/bots/orchestration/__init__.py` is NOT modified

---

## Test Specification

```python
# tests/unit/test_flows_exports.py
import pytest


class TestFlowsTopLevelExports:
    def test_core_exports_still_work(self):
        from parrot.bots.flows import (
            AgentLike, FlowStatus, AgentTaskMachine,
            Node, AgentNode, FlowResult, FlowContext,
            FlowTransition, ExecutionMemory,
        )

    def test_crew_exports(self):
        from parrot.bots.flows import AgentCrew, CrewAgentNode
        assert AgentCrew is not None
        assert CrewAgentNode is not None

    def test_node_result_export(self):
        from parrot.bots.flows import NodeResult
        assert NodeResult is not None

    def test_agent_exports(self):
        from parrot.bots.flows import OrchestratorAgent, A2AOrchestratorAgent
        assert OrchestratorAgent is not None

    def test_tool_export(self):
        from parrot.bots.flows import ResultRetrievalTool
        assert ResultRetrievalTool is not None

    def test_orchestration_dir_exists(self):
        import pathlib
        orch = pathlib.Path("packages/ai-parrot/src/parrot/bots/orchestration/__init__.py")
        assert orch.exists(), "orchestration/ should NOT be deleted"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-979, TASK-980, TASK-981 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — read `flows/__init__.py` to confirm current exports
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-982-update-flows-init-exports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker agent (FEAT-143 session)
**Date**: 2026-05-04
**Notes**: Updated `flows/__init__.py` to add imports from `.crew` (AgentCrew,
CrewAgentNode), `.agents` (OrchestratorAgent, A2AOrchestratorAgent,
ListAvailableA2AAgentsTool, HRAgentFactory), and `.tools` (ResultRetrievalTool).
All previously-exported symbols unchanged. `orchestration/` directory untouched.
Module docstring updated to document the new exports. Total `__all__` size: 30 symbols.

**Deviations from spec**: none
