---
type: Wiki Overview
title: 'TASK-977: Extract `CrewAgentNode` to `flows/crew/nodes.py`'
id: doc:sdd-tasks-completed-task-977-extract-crewagentnode-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from ..core.node import AgentNode as _CoreAgentNode
relates_to:
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.nodes
  rel: mentions
---

# TASK-977: Extract `CrewAgentNode` to `flows/crew/nodes.py`

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-976
**Assigned-to**: unassigned

---

## Context

> Spec Module 1. The `_CrewAgentNode` dataclass is currently defined inline
> in `orchestration/crew.py` (lines 72-144). It must be extracted to its own
> module so it can be reused by other flow engines and imported cleanly by the
> moved `AgentCrew`. The public name changes from `_CrewAgentNode` to
> `CrewAgentNode`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/crew/` package
  - `__init__.py` (initially exports `CrewAgentNode` only; `AgentCrew` added in TASK-979)
  - `nodes.py` containing `CrewAgentNode`
- Copy `_CrewAgentNode` from `orchestration/crew.py:72-144` to `flows/crew/nodes.py`
- Rename to `CrewAgentNode` (public name)
- Update imports to use relative paths within the new location
- Do NOT modify `orchestration/crew.py` — it stays untouched

**NOT in scope**: Moving `AgentCrew`, updating imports in `crew.py`, creating
`flows/agents/` package, or modifying any consumer.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/__init__.py` | CREATE | Package init, exports `CrewAgentNode` |
| `packages/ai-parrot/src/parrot/bots/flows/crew/nodes.py` | CREATE | `CrewAgentNode` dataclass |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Core AgentNode to subclass (verified: flows/core/node.py:143-242)
from ..core.node import AgentNode as _CoreAgentNode

# FlowContext for execute_in_context (verified: flows/core/context.py:26)
from ..core.context import FlowContext

# Standard library
from dataclasses import dataclass
from typing import Any, Dict, Optional
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/core/node.py:143-242
@dataclass
class AgentNode(Node):
    agent: AgentLike
    node_id: str
    dependencies: Set[str] = field(default_factory=set)
    successors: Set[str] = field(default_factory=set)
    fsm: Optional[AgentTaskMachine] = field(default=None)
    @property
    def name(self) -> str: ...
    async def execute(self, prompt: str, *, timeout: Optional[float] = None, **ctx) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/bots/orchestration/crew.py:72-144
# Source to copy (rename _CrewAgentNode → CrewAgentNode):
@dataclass
class _CrewAgentNode(_CoreAgentNode):
    def _format_prompt(self, input_data: Dict[str, Any]) -> str: ...   # line 84
    async def execute_in_context(self, context: FlowContext, timeout: Optional[float] = None) -> Any: ...  # line 115
```

### Does NOT Exist
- ~~`parrot.bots.flows.crew`~~ — does not exist yet (this task creates it)
- ~~`CrewAgentNode`~~ — does not exist as a public name (currently `_CrewAgentNode`)
- ~~`parrot.bots.flows.crew.crew`~~ — does not exist yet (TASK-979)

---

## Implementation Notes

### Pattern to Follow
```python
# flows/crew/nodes.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ..core.node import AgentNode as _CoreAgentNode
from ..core.context import FlowContext


@dataclass
class CrewAgentNode(_CoreAgentNode):
    """Crew-specific node wrapping an agent with dependency metadata."""

    def _format_prompt(self, input_data: Dict[str, Any]) -> str:
        # Copy verbatim from orchestration/crew.py:84-113
        ...

    async def execute_in_context(
        self, context: FlowContext, timeout: Optional[float] = None
    ) -> Any:
        # Copy verbatim from orchestration/crew.py:115-139
        ...
```

```python
# flows/crew/__init__.py
from .nodes import CrewAgentNode

__all__ = ["CrewAgentNode"]
```

### Key Constraints
- `CrewAgentNode` MUST be a `@dataclass` that inherits from `_CoreAgentNode` (which is `AgentNode`)
- `execute_in_context` calls `context.get_input_for_agent()` — this is a backward-compat alias that works on `FlowContext`
- Do NOT add `AgentCrew` to `__init__.py` yet — that happens in TASK-979

### References in Codebase
- `parrot/bots/orchestration/crew.py:72-144` — source code to extract
- `parrot/bots/flows/core/node.py:143-242` — parent class `AgentNode`

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.crew.nodes import CrewAgentNode` works
- [ ] `from parrot.bots.flows.crew import CrewAgentNode` works
- [ ] `CrewAgentNode` is a subclass of `parrot.bots.flows.core.node.AgentNode`
- [ ] `CrewAgentNode` has `_format_prompt()` and `execute_in_context()` methods
- [ ] `flows/crew/__init__.py` only exports `CrewAgentNode` (not `AgentCrew` yet)

---

## Test Specification

```python
# tests/unit/test_crew_agent_node.py
import pytest
from unittest.mock import AsyncMock, Mock
from parrot.bots.flows.crew.nodes import CrewAgentNode
from parrot.bots.flows.core.node import AgentNode
from parrot.bots.flows.core.context import FlowContext


class TestCrewAgentNode:
    def test_import(self):
        from parrot.bots.flows.crew import CrewAgentNode as CAN
        assert CAN is CrewAgentNode

    def test_inherits_agent_node(self):
        assert issubclass(CrewAgentNode, AgentNode)

    def test_format_prompt_task_only(self):
        agent = Mock()
        agent.name = "test"
        node = CrewAgentNode(agent=agent, node_id="n1")
        result = node._format_prompt({"task": "hello"})
        assert result == "hello"

    def test_format_prompt_with_dependencies(self):
        agent = Mock()
        agent.name = "test"
        node = CrewAgentNode(agent=agent, node_id="n1")
        result = node._format_prompt({
            "task": "hello",
            "dependencies": {"dep1": "result1"}
        })
        assert "hello" in result
        assert "dep1" in result

    @pytest.mark.asyncio
    async def test_execute_in_context(self):
        agent = AsyncMock()
        agent.name = "test_agent"
        agent.ask = AsyncMock(return_value=Mock(content="result", output="result"))
        node = CrewAgentNode(agent=agent, node_id="n1")
        ctx = FlowContext(initial_task="do something")
        result = await node.execute_in_context(ctx)
        assert result is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-976 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `_CrewAgentNode` is still at `crew.py:72-144`
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-977-extract-crewagentnode.md`
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
**Notes**: Created `flows/crew/` package with `nodes.py` containing `CrewAgentNode` (renamed from `_CrewAgentNode`). Copied `_format_prompt()` and `execute_in_context()` methods verbatim from `orchestration/crew.py:84-139`. Updated imports to use relative paths within the new location (`from ..core.node import AgentNode as _CoreAgentNode`, `from ..core.context import FlowContext`). `crew/__init__.py` exports only `CrewAgentNode` — `AgentCrew` will be added in TASK-979. `orchestration/crew.py` was not modified.

**Deviations from spec**: none
