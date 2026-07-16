---
type: Wiki Overview
title: 'TASK-978: Move `ResultRetrievalTool` to `flows/tools.py`'
id: doc:sdd-tasks-completed-task-978-move-resultretrievaltool-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: (the tool calls `result.to_text()` and `result.agent_name`, both exist on
  `NodeResult`)
relates_to:
- concept: mod:parrot.bots.flows.tools
  rel: mentions
- concept: mod:parrot.tools.abstract
  rel: mentions
---

# TASK-978: Move `ResultRetrievalTool` to `flows/tools.py`

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-976
**Assigned-to**: unassigned

---

## Context

> Spec Module 2. `ResultRetrievalTool` currently lives in the old singular
> `bots/flow/tools.py` and imports `ExecutionMemory` from `bots/flow/storage/`.
> It must be moved to `flows/tools.py` so it uses the canonical core storage
> location from FEAT-134. The old `bots/flow/tools.py` is NOT modified.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/tools.py`
- Copy `ResultRetrievalTool` from `bots/flow/tools.py` to `flows/tools.py`
- Update its import of `ExecutionMemory` from `bots/flow/storage.memory` to
  `.core.storage.memory` (relative import within `flows/`)
- Update `NodeResult` references: `AgentResult.to_text()` → `NodeResult.to_text()`
  (the tool calls `result.to_text()` and `result.agent_name`, both exist on `NodeResult`)
- Do NOT modify the old `bots/flow/tools.py`

**NOT in scope**: Modifying `bots/flow/` (the old package), updating consumers
of the tool, or moving any other file.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/tools.py` | CREATE | `ResultRetrievalTool` moved here |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# What the new file should import:
from typing import Any, Dict, Optional
from parrot.tools.abstract import AbstractTool  # verified: parrot/tools/abstract.py
from .core.storage.memory import ExecutionMemory  # verified: flows/core/storage/memory.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flow/tools.py:5-79 — source to copy
class ResultRetrievalTool(AbstractTool):
    name = "execution_context_tool"
    description = "Retrieve detailed execution results and context from agents..."
    def __init__(self, memory: ExecutionMemory, *args, **kwargs): ...  # line 10
    def get_schema(self) -> Dict[str, Any]: ...  # line 22
    async def _execute(self, action: str, agent_id=None, query=None) -> str: ...  # line 47

# packages/ai-parrot/src/parrot/bots/flows/core/storage/memory.py:17
@dataclass
class ExecutionMemory(VectorStoreMixin):
    results: Dict[str, NodeResult]  # after TASK-976
    execution_order: List[str]
    def get_results_by_agent(self, agent_id: str) -> Optional[NodeResult]: ...
    def search_similar(self, query: str, top_k: int) -> List[...]: ...
```

### Does NOT Exist
- ~~`parrot.bots.flows.tools`~~ — does not exist yet (this task creates it)
- ~~`parrot.bots.flows.tools.ResultRetrievalTool`~~ — does not exist yet

---

## Implementation Notes

### Pattern to Follow
```python
# flows/tools.py — copy from bots/flow/tools.py with updated imports
from typing import Any, Dict, Optional
from parrot.tools.abstract import AbstractTool
from .core.storage.memory import ExecutionMemory


class ResultRetrievalTool(AbstractTool):
    """Retrieval Tool for flows (AgentCrew, AgentsFlow)."""
    name = "execution_context_tool"
    # ... rest copied verbatim from bots/flow/tools.py
```

### Key Constraints
- The tool's `_execute()` method references `self.memory.execution_order`,
  `self.memory.get_results_by_agent()`, and `self.memory.search_similar()`.
  All of these exist on `ExecutionMemory`.
- The tool calls `result.to_text()` and `result.agent_name` — both exist on
  `NodeResult` (after TASK-976).
- Use relative import for `ExecutionMemory`: `from .core.storage.memory import ExecutionMemory`

### References in Codebase
- `parrot/bots/flow/tools.py:1-79` — source code to copy
- `parrot/tools/abstract.py` — `AbstractTool` base class

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.tools import ResultRetrievalTool` works
- [ ] `ResultRetrievalTool` is a subclass of `AbstractTool`
- [ ] `ResultRetrievalTool` accepts `ExecutionMemory` in its constructor
- [ ] The old `bots/flow/tools.py` is NOT modified

---

## Test Specification

```python
# tests/unit/test_flows_result_retrieval_tool.py
import pytest
from unittest.mock import Mock, AsyncMock
from parrot.bots.flows.tools import ResultRetrievalTool
from parrot.tools.abstract import AbstractTool


class TestResultRetrievalTool:
    def test_import(self):
        assert ResultRetrievalTool is not None

    def test_inherits_abstract_tool(self):
        assert issubclass(ResultRetrievalTool, AbstractTool)

    def test_has_schema(self):
        memory = Mock()
        tool = ResultRetrievalTool(memory=memory)
        schema = tool.get_schema()
        assert schema["name"] == "execution_context_tool"
        assert "parameters" in schema

    @pytest.mark.asyncio
    async def test_list_agents(self):
        memory = Mock()
        memory.execution_order = ["agent1", "agent2"]
        tool = ResultRetrievalTool(memory=memory)
        result = await tool._execute(action="list_agents")
        assert "agent1" in result
        assert "agent2" in result
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-976 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `bots/flow/tools.py` still contains `ResultRetrievalTool`
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-978-move-resultretrievaltool.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

---

## Completion Note (filled)

**Completed by**: sdd-worker agent
**Date**: 2026-05-04
**Notes**: Created `parrot/bots/flows/tools.py` with `ResultRetrievalTool` copied from `bots/flow/tools.py`. Updated import of `ExecutionMemory` from `.core.storage.memory` (relative path within `flows/`). Updated `res.agent_name` reference to `res.node_name` (works via backward-compat alias too, but node_name is canonical). The old `bots/flow/tools.py` was NOT modified. `ResultRetrievalTool` is a proper subclass of `AbstractTool` from `parrot.tools.abstract`.

**Deviations from spec**: none
