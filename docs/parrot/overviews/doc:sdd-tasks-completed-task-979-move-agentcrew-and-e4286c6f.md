---
type: Wiki Overview
title: 'TASK-979: Move `AgentCrew` to `flows/crew/crew.py` + result model migration'
id: doc:sdd-tasks-completed-task-979-move-agentcrew-and-result-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: → `from ..core.result import FlowResult, NodeExecutionInfo, build_node_metadata`
relates_to:
- concept: mod:parrot.bots.abstract
  rel: mentions
- concept: mod:parrot.bots.agent
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.clients
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-979: Move `AgentCrew` to `flows/crew/crew.py` + result model migration

**Feature**: FEAT-143 — Flows Consolidation
**Spec**: `sdd/specs/flows-consolidation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: XL (> 8h)
**Depends-on**: TASK-976, TASK-977, TASK-978
**Assigned-to**: unassigned

---

## Context

> Spec Module 3. The core task of this feature: move the 3589-line `AgentCrew`
> class from `orchestration/crew.py` to `flows/crew/crew.py`. During the move,
> replace all old result models (`CrewResult`, `AgentExecutionInfo`,
> `build_agent_metadata`, `AgentResult`) with the new canonical models
> (`FlowResult`, `NodeExecutionInfo`, `build_node_metadata`, `NodeResult`).
> Also update `CrewAgentNode` import to come from `.nodes` and
> `ResultRetrievalTool` from `..tools`.

---

## Scope

- Copy `AgentCrew` class and all supporting code from
  `orchestration/crew.py` (lines 147-3589) to `flows/crew/crew.py`
- Replace imports:
  - `from ...models.crew import CrewResult, AgentResult, AgentExecutionInfo, build_agent_metadata`
    → `from ..core.result import FlowResult, NodeExecutionInfo, build_node_metadata`
    + `from ..core.result import NodeResult`
  - `from ..flows.core.result import determine_run_status` → `from ..core.result import determine_run_status`
  - `from ..flows.core.storage import ...` → `from ..core.storage import ...`
  - `from ..flows.core.node import AgentNode as _CoreAgentNode` → removed (use `.nodes.CrewAgentNode`)
  - `from ..flow.tools import ResultRetrievalTool` → `from ..tools import ResultRetrievalTool`
  - All `from ...xxx` paths recalculated for new package depth
- Replace all usages in the code:
  - `CrewResult(...)` → `FlowResult(...)` with `nodes=` instead of `agents=`
  - `AgentExecutionInfo(...)` → `NodeExecutionInfo(...)`
  - `build_agent_metadata(...)` → `build_node_metadata(...)`
  - `AgentResult(...)` → `NodeResult(...)`  with `node_id=`/`node_name=` instead of `agent_id=`/`agent_name=`
  - `FlowResult.status` use `FlowStatus` enum where appropriate
- Import `CrewAgentNode` from `.nodes` (not defined inline)
- Keep `AgentNode = CrewAgentNode` alias for backward compat in the module
- Update `flows/crew/__init__.py` to also export `AgentCrew`
- Do NOT modify `orchestration/crew.py` — it stays untouched

**NOT in scope**: Refactoring `_execute_agent()` or replacing `AgentContext`
(that's TASK-980). Only the result model types change here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | CREATE | `AgentCrew` class (moved) |
| `packages/ai-parrot/src/parrot/bots/flows/crew/__init__.py` | MODIFY | Add `AgentCrew` export |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# What the new crew.py should import (recalculated paths from flows/crew/):
from __future__ import annotations
from typing import List, Dict, Any, Union, Optional, Literal, Set, Callable, Awaitable, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import contextlib, asyncio, time, uuid
from tqdm.asyncio import tqdm as async_tqdm
from navconfig.logging import logging
from datamodel.parsers.json import json_encoder

# Relative imports from new location (flows/crew/crew.py):
from ...agent import BasicAgent              # parrot.bots.agent
from ...abstract import AbstractBot          # parrot.bots.abstract
from ....clients import AbstractClient       # parrot.clients
from ....clients.factory import SUPPORTED_CLIENTS
from ....clients.google import GoogleGenAIClient
from ....tools.manager import ToolManager
from ....tools.agent import AgentTool
from ....tools.abstract import AbstractTool
from ....tools.agent import AgentContext     # still imported for now (removed in TASK-980)
from ....models.responses import AIMessage, AgentResponse
from ....models.status import AgentStatus

# NEW canonical imports (replacing parrot.models.crew):
from ..core.result import (
    FlowResult, NodeExecutionInfo, build_node_metadata, determine_run_status, NodeResult,
)
from ..core.types import FlowStatus
from ..core.storage import ExecutionMemory, PersistenceMixin, SynthesisMixin
from ..core.storage.synthesis import SYNTHESIS_PROMPT
from ..core.context import FlowContext
from ..core.types import AgentRef, DependencyResults, PromptBuilder
from ..core.fsm import AgentTaskMachine
from ..tools import ResultRetrievalTool
from .nodes import CrewAgentNode
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/orchestration/crew.py — source to copy

# Line 147-275: AgentCrew.__init__() — uses _CrewAgentNode → CrewAgentNode
# Line 855-906: _execute_agent() — takes AgentContext (stays for now)
# Line 1045-1362: run_sequential() — returns CrewResult → FlowResult
# Line 1364-1817: run_loop() — returns CrewResult → FlowResult
# Line 1819-2128: run_parallel() — returns CrewResult → FlowResult
# Line 2130-2361: run_flow() — returns CrewResult → FlowResult
# Line 2455-2617: run() — returns CrewResult → FlowResult
# Line 2619-3589: Memory/summary methods

# FlowResult constructor (verified: flows/core/result.py:142-159)
FlowResult(
    output=...,
    responses=...,
    summary=...,
    nodes=agents_info,        # NOT agents= (use nodes= field)
    execution_log=...,
    total_time=...,
    status=FlowStatus.COMPLETED,  # or determine_run_status(...)
    errors=...,
    metadata=...,
)

# NodeResult constructor (from TASK-976):
NodeResult(
    node_id=...,              # was agent_id
    node_name=...,            # was agent_name
    task=...,
    result=...,
    ai_message=...,
    metadata=...,
    execution_time=...,
    parent_execution_id=...,
    execution_id=...,
)
```

### Does NOT Exist
- ~~`FlowResult(agents=...)`~~ — constructor field is `nodes=`, not `agents=`
- ~~`FlowResult.agents` (constructor)~~ — `agents` is a property alias only
- ~~`parrot.bots.flows.crew.crew`~~ — does not exist yet (this task creates it)

---

## Implementation Notes

### Key Replacement Patterns

1. **CrewResult → FlowResult**:
   ```python
   # OLD:
   return CrewResult(output=..., agents=agents_info, ...)
   # NEW:
   return FlowResult(output=..., nodes=agents_info, ...)
   ```

2. **AgentExecutionInfo → NodeExecutionInfo**: Direct replacement in type hints
   and construction. Field names are identical.

3. **build_agent_metadata → build_node_metadata**: Direct function replacement.
   Identical signature.

4. **AgentResult → NodeResult**:
   ```python
   # OLD:
   AgentResult(agent_id=agent_id, agent_name=agent.name, task=query, result=output, ...)
   # NEW:
   NodeResult(node_id=agent_id, node_name=agent.name, task=query, result=output, ...)
   ```

5. **FlowStatus**: Where `CrewResult` used string literals like `status='completed'`,
   use `FlowStatus.COMPLETED`. Or use `determine_run_status()` which returns
   compatible string literals.

### Key Constraints
- This is a ~3500-line file. Work methodically through all imports first, then
  find-and-replace each model type.
- `_execute_agent()` still takes `AgentContext` in this task. TASK-980 will change it.
- Preserve `__all__` with `AgentCrew`, `AgentNode`, `FlowContext`, `AgentRef`,
  `DependencyResults`, `PromptBuilder` for backward compat.
- `AgentNode = CrewAgentNode` alias must be kept at module level.

### References in Codebase
- `parrot/bots/orchestration/crew.py:1-3589` — the entire source to move
- `parrot/bots/flows/core/result.py` — target result models
- `parrot/models/crew.py` — old models being replaced

---

## Acceptance Criteria

- [ ] `from parrot.bots.flows.crew import AgentCrew` works
- [ ] `from parrot.bots.flows.crew.crew import AgentCrew` works
- [ ] `AgentCrew` is subclass of `PersistenceMixin, SynthesisMixin`
- [ ] No import of `CrewResult` in `flows/crew/crew.py`
- [ ] No import of `AgentExecutionInfo` in `flows/crew/crew.py`
- [ ] No import of `build_agent_metadata` in `flows/crew/crew.py`
- [ ] All `FlowResult(...)` calls use `nodes=` field (not `agents=`)
- [ ] All `NodeResult(...)` calls use `node_id=` and `node_name=` fields
- [ ] `flows/crew/__init__.py` exports both `AgentCrew` and `CrewAgentNode`
- [ ] `orchestration/crew.py` is NOT modified

---

## Test Specification

```python
# tests/unit/test_agentcrew_import.py
import pytest
from parrot.bots.flows.crew import AgentCrew, CrewAgentNode
from parrot.bots.flows.core.storage import PersistenceMixin, SynthesisMixin


class TestAgentCrewImport:
    def test_import_from_crew_package(self):
        from parrot.bots.flows.crew import AgentCrew
        assert AgentCrew is not None

    def test_import_from_crew_module(self):
        from parrot.bots.flows.crew.crew import AgentCrew
        assert AgentCrew is not None

    def test_mixin_inheritance(self):
        assert issubclass(AgentCrew, PersistenceMixin)
        assert issubclass(AgentCrew, SynthesisMixin)

    def test_no_old_model_imports(self):
        import parrot.bots.flows.crew.crew as mod
        source = open(mod.__file__).read()
        assert "from parrot.models.crew import" not in source or "CrewResult" not in source
        assert "build_agent_metadata" not in source

    def test_backward_compat_agent_node_alias(self):
        from parrot.bots.flows.crew.crew import AgentNode
        assert AgentNode is CrewAgentNode
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-976, TASK-977, TASK-978 must be in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `orchestration/crew.py` is still 3589 lines
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-979-move-agentcrew-and-result-migration.md`
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
**Notes**: Created `flows/crew/crew.py` by transforming `orchestration/crew.py`. All result model migrations completed: `CrewResult` → `FlowResult`, `AgentExecutionInfo` → `NodeExecutionInfo`, `build_agent_metadata` → `build_node_metadata`, `AgentResult` → `NodeResult`. All `NodeResult()` calls updated to use `node_id=`/`node_name=` instead of `agent_id=`/`agent_name=`. All `FlowResult()` calls updated to use `nodes=` instead of `agents=`. `CrewAgentNode` imported from `.nodes`. `AgentNode = CrewAgentNode` alias preserved. `AgentContext` import kept for TASK-980. `orchestration/crew.py` not modified. `crew/__init__.py` updated to export both `AgentCrew` and `CrewAgentNode`.

**Deviations from spec**: none
