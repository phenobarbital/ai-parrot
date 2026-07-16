---
type: Wiki Overview
title: 'TASK-1057: Update Test Imports from orchestration to flows'
id: doc:sdd-tasks-completed-task-1057-test-import-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 15 test files contain 27+ import lines referencing `parrot.bots.orchestration`.
  This task
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
---

# TASK-1057: Update Test Imports from orchestration to flows

**Feature**: FEAT-155 — Final Migration: Remove bots/orchestration, Consolidate into bots/flows
**Spec**: `sdd/specs/migration-orchestration-to-flows.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

15 test files contain 27+ import lines referencing `parrot.bots.orchestration`. This task
updates all of them to use the canonical `parrot.bots.flows` paths. One test
(`test_execution_memory_integration.py`) has already-broken imports that need fixing.
Two test files in `test_flow_primitives/` have backward-compat tests that explicitly test
orchestration imports — those tests must be updated or removed.

Implements: Spec §3 Module 2 (Test Import Migration).

---

## Scope

- Update all 27+ import lines across 15 test files
- Fix broken imports in `test_execution_memory_integration.py` (lines 15-16)
- Update or remove backward-compat tests in `test_flow_primitives/test_init_reexports.py`
  (lines 103-118: `test_agent_crew_still_importable` and `TestDeadCodeRemoved`)
- Remove `test_agent_task_removed_from_crew` in `test_flow_primitives/test_contract.py` (line 431-434)
- Handle `_CrewAgentNode` → `CrewAgentNode` rename in `test_agentnode_execute.py`
- Handle `AgentNode` alias → `CrewAgentNode` in `test_crew_final_regression.py`
- Handle `import parrot.bots.orchestration.crew as crew` module import patterns

**NOT in scope**: updating handler imports (TASK-1056), updating examples (TASK-1058),
deleting orchestration directory (TASK-1059), modifying test logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_agent_crew_examples.py` | MODIFY | Line 35: `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `tests/test_crew_parallel_regression.py` | MODIFY | Line 14: same |
| `tests/test_crew_flow_regression.py` | MODIFY | Line 13: same |
| `tests/test_crew_loop_regression.py` | MODIFY | Line 18: same |
| `tests/test_crew_sequential_regression.py` | MODIFY | Line 13: same |
| `tests/test_agentnode_execute.py` | MODIFY | Line 19: `_CrewAgentNode` → `CrewAgentNode` from `flows.crew` |
| `tests/test_orchestrator_agent.py` | MODIFY | Line 23: `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `tests/test_crew_final_regression.py` | MODIFY | 12 import lines across multiple test methods |
| `tests/test_execution_memory_integration.py` | MODIFY | Lines 15-16: fix broken imports |
| `tests/test_flow_primitives/test_init_reexports.py` | MODIFY | Remove/update backward-compat tests (lines 102-118) |
| `tests/test_flow_primitives/test_contract.py` | MODIFY | Remove `test_agent_task_removed_from_crew` (lines 431-434) |

All paths relative to `packages/ai-parrot/`.

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# AgentCrew — most common replacement
from parrot.bots.flows.crew import AgentCrew       # verified: flows/crew/__init__.py:6
from parrot.bots.flows.crew import CrewAgentNode   # verified: flows/crew/__init__.py:5

# Core types (FlowContext, AgentRef, etc.)
from parrot.bots.flows.core import FlowContext     # verified: flows/core/__init__.py
from parrot.bots.flows.core import AgentRef        # verified: flows/core/__init__.py

# Orchestrator agent
from parrot.bots.flows.agents import OrchestratorAgent  # verified: flows/agents/__init__.py:17

# Storage (for test_execution_memory_integration.py)
from parrot.bots.flows.core.storage import ExecutionMemory  # verified: flows/core/storage/__init__.py:12

# Tools (for test_execution_memory_integration.py)
from parrot.bots.flows import ResultRetrievalTool  # verified: flows/__init__.py:68

# Module-level import pattern (for test_crew_final_regression.py)
from parrot.bots.flows import crew as crew_pkg     # verified: flows/crew/__init__.py
import parrot.bots.flows.crew.crew as crew         # verified: flows/crew/crew.py exists
```

### Does NOT Exist

- ~~`parrot.bots.orchestration.storage`~~ — never existed as a source module; use `flows.core.storage`
- ~~`parrot.bots.orchestration.tools`~~ — never existed as a source module; use `flows.tools` or `flows.ResultRetrievalTool`
- ~~`parrot.bots.flows.crew._CrewAgentNode`~~ — private name; use `CrewAgentNode`
- ~~`parrot.bots.flows.crew.AgentNode`~~ — old alias; use `CrewAgentNode`
- ~~`parrot.bots.orchestration.crew.AgentTask`~~ — dead code, removed in FEAT-134

---

## Implementation Notes

### Import Replacements — Complete Map

```python
# Pattern 1: Simple AgentCrew import (most common)
# OLD: from parrot.bots.orchestration.crew import AgentCrew
# NEW: from parrot.bots.flows.crew import AgentCrew

# Pattern 2: Multiple symbols from crew
# OLD: from parrot.bots.orchestration.crew import AgentNode, _CrewAgentNode
# NEW: from parrot.bots.flows.crew import CrewAgentNode
# Note: AgentNode was an alias for _CrewAgentNode; both become CrewAgentNode

# Pattern 3: FlowContext from crew (re-exported)
# OLD: from parrot.bots.orchestration.crew import FlowContext
# NEW: from parrot.bots.flows.core import FlowContext

# Pattern 4: AgentRef from crew (re-exported)
# OLD: from parrot.bots.orchestration.crew import AgentRef
# NEW: from parrot.bots.flows.core import AgentRef

# Pattern 5: Module import
# OLD: from parrot.bots.orchestration import crew
# NEW: from parrot.bots.flows.crew import crew as crew_mod
# OR:  import parrot.bots.flows.crew.crew as crew

# Pattern 6: OrchestratorAgent
# OLD: from parrot.bots.orchestration.agent import OrchestratorAgent
# NEW: from parrot.bots.flows.agents import OrchestratorAgent

# Pattern 7: Broken storage/tools (test_execution_memory_integration.py)
# OLD: from parrot.bots.orchestration.storage import ExecutionMemory  ← BROKEN
# NEW: from parrot.bots.flows.core.storage import ExecutionMemory
# OLD: from parrot.bots.orchestration.tools import ResultRetrievalTool  ← BROKEN
# NEW: from parrot.bots.flows import ResultRetrievalTool

# Pattern 8: Aliased import
# OLD: from parrot.bots.orchestration.crew import AgentCrew as OrchAgentCrew
# NEW: from parrot.bots.flows.crew import AgentCrew as OrchAgentCrew
```

### Backward-Compat Tests to Handle

In `test_flow_primitives/test_init_reexports.py`:
- **`test_agent_crew_still_importable`** (line 102-104): This test verifies the old
  orchestration path works. Remove it or change to test the flows path.
- **`TestDeadCodeRemoved`** class (lines 107-118): Tests that `AgentTask` was removed
  from `orchestration.crew`. Remove the entire class — `orchestration.crew` won't exist.

In `test_flow_primitives/test_contract.py`:
- **`test_agent_task_removed_from_crew`** (lines 431-434): Same — remove it.

### Key Constraints

- Do NOT change test logic — only import lines
- When replacing `AgentNode` or `_CrewAgentNode`, also update any variable names or
  assertions that reference the old class name
- For `test_crew_final_regression.py` which has imports inside test methods, update
  each method's local import independently

---

## Acceptance Criteria

- [ ] No test file contains `from parrot.bots.orchestration`
- [ ] No test file contains `import parrot.bots.orchestration`
- [ ] `test_execution_memory_integration.py` imports resolve (no longer broken)
- [ ] `_CrewAgentNode` references replaced with `CrewAgentNode`
- [ ] Backward-compat tests for orchestration imports removed
- [ ] All tests pass: `pytest packages/ai-parrot/tests/ -v --timeout=60 -x`
- [ ] `grep -rn 'parrot.bots.orchestration' packages/ai-parrot/tests/` returns nothing

---

## Test Specification

No new tests. Verification that existing tests pass after import rewrite:

```bash
pytest packages/ai-parrot/tests/test_agent_crew_examples.py \
       packages/ai-parrot/tests/test_crew_parallel_regression.py \
       packages/ai-parrot/tests/test_crew_flow_regression.py \
       packages/ai-parrot/tests/test_crew_loop_regression.py \
       packages/ai-parrot/tests/test_crew_sequential_regression.py \
       packages/ai-parrot/tests/test_agentnode_execute.py \
       packages/ai-parrot/tests/test_orchestrator_agent.py \
       packages/ai-parrot/tests/test_crew_final_regression.py \
       packages/ai-parrot/tests/test_execution_memory_integration.py \
       packages/ai-parrot/tests/test_flow_primitives/ \
       -v --timeout=60 -x
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migration-orchestration-to-flows.spec.md` for full context
2. **Check dependencies** — none required
3. **Verify the Codebase Contract** — confirm all new import paths work before changing test files
4. **Update status** in `sdd/tasks/index/migration-orchestration-to-flows.json` → `"in-progress"`
5. **Implement** the import replacements file by file, following the pattern map above
6. **Verify** all acceptance criteria are met (especially the grep check)
7. **Move this file** to `sdd/tasks/completed/TASK-1057-test-import-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-05-11
**Notes**: Updated all 11 test files. Also updated test_bot_cleanup_lifecycle.py (not in spec
list but had sys.modules stubs for orchestration — removed to satisfy grep acceptance check).
test_orchestrator_agent.py: updated import + all @patch paths to flows.agents.orchestrator.
test_crew_final_regression.py: rewrote TestBackwardCompatImports/TestDeadCodeRemoved/TestModuleExports
to use flows paths; removed test_flows_agentcrew_is_same_class_as_orchestration.

**Deviations from spec**: test_bot_cleanup_lifecycle.py added (had sys.modules stubs for
orchestration that would fail the grep acceptance check)
