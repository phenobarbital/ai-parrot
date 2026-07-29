---
type: Wiki Overview
title: 'Feature Specification: Final Migration — Remove `bots/orchestration`, Consolidate
  into `bots/flows`'
id: doc:sdd-specs-migration-orchestration-to-flows-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-134 (flow-primitives) and FEAT-137 (agentcrew-primitives) moved all
  orchestration
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.agents.orchestrator
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.storage
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.bots.flows.tools
  rel: mentions
- concept: mod:parrot.handlers.crew
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Final Migration — Remove `bots/orchestration`, Consolidate into `bots/flows`

**Feature ID**: FEAT-155
**Date**: 2026-05-11
**Author**: Jesus
**Status**: implemented
**Target version**: next minor
**Proposal**: `sdd/proposals/migration-orchestration-to-flows.proposal.md`
**Prior specs**: FEAT-134 (flow-primitives), FEAT-137 (agentcrew-primitives) — both completed

> **Note (FEAT-196, 2026-05-28)**: `parrot.bots.flow` (singular) has been deleted.
> References to it in this spec are historical.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-134 (flow-primitives) and FEAT-137 (agentcrew-primitives) moved all orchestration
code to `parrot.bots.flows` — core primitives, AgentCrew, OrchestratorAgent,
A2AOrchestratorAgent, and HR agents. The old `parrot.bots.orchestration` directory was
left in place to avoid breaking consumers, but it now contains **~4,900 lines of
duplicate code** across 5 Python files.

The situation is worse than simple duplication: `orchestration/crew.py` is a **divergent
hybrid** — it imports core types from `flows.core` but keeps its own `AgentCrew`
implementation using the old `CrewResult` model, while the canonical `flows/crew/crew.py`
uses the new `FlowResult` model. One test file (`test_execution_memory_integration.py`)
already has **broken imports** referencing non-existent modules. Several example files
import `AgentsFlow` from `orchestration`, which was never exported there.

This is the final cleanup phase: delete `orchestration/` entirely, update all in-tree
imports (handlers, tests, examples) to use `parrot.bots.flows`, and clean up stale
bytecache.

### Goals

- Delete all files in `packages/ai-parrot/src/parrot/bots/orchestration/` (7 files, ~4,900 lines)
- Update 2 handler files to import from `parrot.bots.flows`
- Update 15 test files (27+ import lines) to import from `parrot.bots.flows`
- Fix 1 already-broken test (`test_execution_memory_integration.py`)
- Update 17 example files (24 import lines) to import from `parrot.bots.flows` or `parrot.bots.flow`
- Clean up stale `__pycache__` directories under the installed `parrot/bots/orchestration/` path
- Delete the empty `orchestration/` directory tree

### Non-Goals (explicitly out of scope)

- Modifying `parrot.bots.flow` (singular) — the AgentsFlow/FSM engine is a separate module, not part of this migration.
- Modifying `parrot.bots.flows.core/`, `flows/crew/`, or `flows/agents/` — already canonical, no changes needed.
- Deprecating `parrot.models.crew.CrewResult` — that model stays for now. Backward compat was handled in FEAT-137.
  *(Rejected alternative: keeping orchestration/ as a deprecation stub — resolved in proposal review.)*
- Changing handler logic — only import paths change, not behavior.
- Modifying `parrot.bots.__init__` — it does not re-export orchestration symbols.

---

## 2. Architectural Design

### Overview

This is a pure delete-and-repoint migration. No new code is written. The canonical
modules already exist in `parrot.bots.flows`:

```
parrot.bots.flows/
  __init__.py          ← master re-export hub (30+ symbols)
  agents/
    orchestrator.py    ← OrchestratorAgent (canonical)
    a2a_orchestrator.py ← A2AOrchestratorAgent (canonical)
    hr.py              ← HRAgentFactory, RAGHRAgent, EmployeeDataAgent (canonical)
  crew/
    crew.py            ← AgentCrew (canonical, uses FlowResult)
    nodes.py           ← CrewAgentNode (was _CrewAgentNode)
  core/                ← shared primitives
  tools.py             ← ResultRetrievalTool
```

Every consumer that currently imports from `parrot.bots.orchestration` gets repointed
to the equivalent symbol from `parrot.bots.flows` (or its sub-packages).

### Import Mapping

| Old import | New import |
|---|---|
| `from parrot.bots.orchestration.crew import AgentCrew` | `from parrot.bots.flows.crew import AgentCrew` |
| `from parrot.bots.orchestration.crew import AgentNode` | `from parrot.bots.flows.crew import CrewAgentNode` |
| `from parrot.bots.orchestration.crew import _CrewAgentNode` | `from parrot.bots.flows.crew import CrewAgentNode` |
| `from parrot.bots.orchestration.crew import FlowContext` | `from parrot.bots.flows.core import FlowContext` |
| `from parrot.bots.orchestration.crew import AgentRef` | `from parrot.bots.flows.core import AgentRef` |
| `from parrot.bots.orchestration import AgentCrew` | `from parrot.bots.flows import AgentCrew` |
| `from parrot.bots.orchestration import AgentCrew, FlowContext` | `from parrot.bots.flows import AgentCrew, FlowContext` |
| `from parrot.bots.orchestration.agent import OrchestratorAgent` | `from parrot.bots.flows.agents import OrchestratorAgent` |
| `from parrot.bots.orchestration import A2AOrchestratorAgent` | `from parrot.bots.flows import A2AOrchestratorAgent` |
| `from parrot.bots.orchestration import OrchestratorAgent` | `from parrot.bots.flows import OrchestratorAgent` |
| `from parrot.bots.orchestration.storage import ExecutionMemory` | `from parrot.bots.flows.core.storage import ExecutionMemory` |
| `from parrot.bots.orchestration.tools import ResultRetrievalTool` | `from parrot.bots.flows import ResultRetrievalTool` |
| `import parrot.bots.orchestration.crew as crew` | `import parrot.bots.flows.crew.crew as crew` |
| `from parrot.bots.orchestration import AgentsFlow` | `from parrot.bots.flow import AgentsFlow` |
| `from parrot.bots.orchestration.decision_node import ...` | `from parrot.bots.flow.decision_node import ...` |
| `from parrot.bots.orchestration import crew` | `from parrot.bots.flows import crew` *(or inline)* |

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.bots.flows` | import target | All consumers repointed here |
| `parrot.bots.flow` | import target | Decision workflow examples repointed here |
| `parrot.handlers.crew` | import update | Production handlers, 2 files |
| `parrot.models.crew` | unchanged | `CrewResult` model stays in place |
| `parrot.bots.__init__` | unchanged | Does not export orchestration |

### Data Models

No new data models. `FlowResult` (from `flows.core.result`) replaces `CrewResult` as the
return type for consumers that switch from `orchestration/crew.py` to `flows/crew/crew.py`.
FEAT-137 ensured backward compatibility.

---

## 3. Module Breakdown

### Module 1: Handler Import Migration
- **Files**:
  - `packages/ai-parrot/src/parrot/handlers/crew/handler.py` (line 18)
  - `packages/ai-parrot/src/parrot/handlers/crew/execution_handler.py` (line 7)
- **Responsibility**: Update import lines from `orchestration.crew` to `flows.crew`
- **Depends on**: None

### Module 2: Test Import Migration
- **Files**: 15 test files with 27+ import lines (see §6 Codebase Contract for full list)
- **Responsibility**: Update all test imports from `orchestration` to `flows`. Fix broken test
  `test_execution_memory_integration.py`. Update backward-compat tests in `test_flow_primitives/`
  to either test the new import paths or be removed (they tested orchestration imports).
- **Depends on**: None

### Module 3: Example Import Migration
- **Files**: 17 example files with 24 import lines (see §6 Codebase Contract for full list)
- **Responsibility**: Update all example imports. Note that decision workflow examples
  (`AgentsFlow`, `decision_node`) must import from `parrot.bots.flow` (singular), not `flows`.
- **Depends on**: None

### Module 4: Delete `orchestration/` Directory & Cleanup
- **Path**: `packages/ai-parrot/src/parrot/bots/orchestration/`
- **Responsibility**: Delete all files (`__init__.py`, `crew.py`, `agent.py`,
  `a2a_orchestrator.py`, `hr.py`, `verify.py`, `README.md`), remove the directory,
  and clean up stale `__pycache__` in the installed `parrot/bots/orchestration/` path.
- **Depends on**: Module 1, Module 2, Module 3

---

## 4. Test Specification

### Verification Strategy

This migration is mechanical — the primary test is that all existing tests still pass
after the import rewrite. No new test logic is needed.

### Tests to Update

| Test File | Current Import | New Import |
|---|---|---|
| `test_agent_crew_examples.py:35` | `orchestration.crew.AgentCrew` | `flows.crew.AgentCrew` |
| `test_crew_parallel_regression.py:14` | `orchestration.crew.AgentCrew` | `flows.crew.AgentCrew` |
| `test_crew_flow_regression.py:13` | `orchestration.crew.AgentCrew` | `flows.crew.AgentCrew` |
| `test_crew_loop_regression.py:18` | `orchestration.crew.AgentCrew` | `flows.crew.AgentCrew` |
| `test_crew_sequential_regression.py:13` | `orchestration.crew.AgentCrew` | `flows.crew.AgentCrew` |
| `test_agentnode_execute.py:19` | `orchestration.crew._CrewAgentNode` | `flows.crew.CrewAgentNode` |
| `test_orchestrator_agent.py:23` | `orchestration.agent.OrchestratorAgent` | `flows.agents.OrchestratorAgent` |
| `test_crew_final_regression.py` | 12 import lines from `orchestration` | Repoint all to `flows` |
| `test_execution_memory_integration.py:15-16` | `orchestration.storage.ExecutionMemory`, `orchestration.tools.ResultRetrievalTool` | `flows.core.storage.ExecutionMemory`, `flows.ResultRetrievalTool` |

### Tests to Update/Remove (Backward Compat)

| Test File | Lines | Action |
|---|---|---|
| `test_flow_primitives/test_init_reexports.py:102-118` | `test_agent_crew_still_importable`, `TestDeadCodeRemoved` | Remove these tests (they test that orchestration/ is importable) |
| `test_flow_primitives/test_contract.py:431-434` | `test_agent_task_removed_from_crew` | Remove (tests orchestration.crew module attribute) |

### Validation Command

```bash
pytest packages/ai-parrot/tests/ -v --timeout=60 -x
```

---

## 5. Acceptance Criteria

- [x] All orchestration source files have canonical equivalents in flows/ (verified in proposal)
- [ ] `packages/ai-parrot/src/parrot/bots/orchestration/` directory no longer exists
- [ ] `parrot/bots/orchestration/` installed path has no stale `__pycache__` files
- [ ] All handler imports updated: `from parrot.bots.flows.crew import AgentCrew`
- [ ] All test imports updated: no test file contains `from parrot.bots.orchestration`
- [ ] Broken test `test_execution_memory_integration.py` fixed to use correct imports
- [ ] Backward-compat tests that tested orchestration imports updated or removed
- [ ] All example imports updated: no example file contains `from parrot.bots.orchestration`
- [ ] Decision workflow examples import from `parrot.bots.flow` (not orchestration)
- [ ] `pytest packages/ai-parrot/tests/ -v --timeout=60` passes (no import errors)
- [ ] No remaining `from parrot.bots.orchestration` anywhere in the codebase (`grep -r` confirms)

---

## 6. Codebase Contract

### Verified Imports (canonical paths — use these)

```python
# AgentCrew and CrewAgentNode
from parrot.bots.flows.crew import AgentCrew      # verified: flows/crew/__init__.py:6
from parrot.bots.flows.crew import CrewAgentNode   # verified: flows/crew/__init__.py:5

# Orchestrator agents
from parrot.bots.flows.agents import OrchestratorAgent        # verified: flows/agents/__init__.py:17
from parrot.bots.flows.agents import A2AOrchestratorAgent     # verified: flows/agents/__init__.py:19
from parrot.bots.flows.agents import ListAvailableA2AAgentsTool  # verified: flows/agents/__init__.py:20
from parrot.bots.flows.agents import HRAgentFactory           # verified: flows/agents/__init__.py:23
from parrot.bots.flows.agents import RAGHRAgent               # verified: flows/agents/__init__.py:23
from parrot.bots.flows.agents import EmployeeDataAgent        # verified: flows/agents/__init__.py:23

# Core types
from parrot.bots.flows.core import FlowContext    # verified: flows/core/__init__.py
from parrot.bots.flows.core import AgentRef       # verified: flows/core/__init__.py
from parrot.bots.flows.core import FlowResult     # verified: flows/core/__init__.py

# Storage
from parrot.bots.flows.core.storage import ExecutionMemory   # verified: flows/core/storage/__init__.py:12
from parrot.bots.flows.core.storage import PersistenceMixin  # verified: flows/core/storage/__init__.py:14

# Tools
from parrot.bots.flows import ResultRetrievalTool   # verified: flows/__init__.py:68

# Master re-export hub (also valid for any of the above)
from parrot.bots.flows import AgentCrew, FlowContext, OrchestratorAgent  # verified: flows/__init__.py

# AgentsFlow and decision_node (singular flow module — NOT flows)
from parrot.bots.flow import AgentsFlow           # verified: flow/__init__.py:4
from parrot.bots.flow.decision_node import DecisionFlowNode  # verified: flow/__init__.py:11
```

### Files to Delete

All paths relative to `packages/ai-parrot/src/parrot/bots/orchestration/`:

| File | Lines | Content |
|---|---|---|
| `__init__.py` | 4 | Re-exports (will break after other files deleted) |
| `crew.py` | 3615 | Divergent AgentCrew (hybrid, uses old CrewResult) |
| `agent.py` | 334 | Duplicate OrchestratorAgent |
| `a2a_orchestrator.py` | 308 | Duplicate A2AOrchestratorAgent |
| `hr.py` | 434 | Duplicate HRAgentFactory/RAGHRAgent/EmployeeDataAgent |
| `verify.py` | 203 | Standalone FSM verification script (not imported) |
| `README.md` | 464 | Documentation |

### Consumer Files to Update — Handlers

| File | Line | Old Import | New Import |
|---|---|---|---|
| `src/parrot/handlers/crew/handler.py` | 18 | `from parrot.bots.orchestration.crew import AgentCrew` | `from parrot.bots.flows.crew import AgentCrew` |
| `src/parrot/handlers/crew/execution_handler.py` | 7 | `from parrot.bots.orchestration.crew import AgentCrew` | `from parrot.bots.flows.crew import AgentCrew` |

### Consumer Files to Update — Tests

| File | Line(s) | Import(s) to Replace |
|---|---|---|
| `tests/test_agent_crew_examples.py` | 35 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `tests/test_crew_parallel_regression.py` | 14 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `tests/test_crew_flow_regression.py` | 13 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `tests/test_crew_loop_regression.py` | 18 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `tests/test_crew_sequential_regression.py` | 13 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `tests/test_agentnode_execute.py` | 19 | `orchestration.crew._CrewAgentNode` → `flows.crew.CrewAgentNode` |
| `tests/test_orchestrator_agent.py` | 23 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `tests/test_crew_final_regression.py` | 25,29,37,42,47,51,83,105,146,150,164,182 | Multiple: `AgentNode`→`CrewAgentNode`, `FlowContext`, `AgentRef`, `AgentCrew`, `crew` module |
| `tests/test_execution_memory_integration.py` | 15,16 | `orchestration.storage.ExecutionMemory` → `flows.core.storage.ExecutionMemory`; `orchestration.tools.ResultRetrievalTool` → `flows.ResultRetrievalTool` |
| `tests/test_flow_primitives/test_init_reexports.py` | 103,109,115 | Remove `test_agent_crew_still_importable` and `TestDeadCodeRemoved` class |
| `tests/test_flow_primitives/test_contract.py` | 433 | Remove `test_agent_task_removed_from_crew` test |

### Consumer Files to Update — Examples

| File | Line(s) | Import(s) to Replace |
|---|---|---|
| `examples/crew/crew_flows.py` | 12 | `orchestration.AgentCrew, FlowContext` → `flows.AgentCrew, FlowContext` |
| `examples/crew/crew_loop.py` | 4 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `examples/crew/crew_nav_qa.py` | 3 | `orchestration.AgentCrew, FlowContext` → `flows.AgentCrew, FlowContext` |
| `examples/crew/crew_qa.py` | 17 | `orchestration.crew.AgentCrew` → `flows.crew.AgentCrew` |
| `examples/crew/market_researcher.py` | 3 | `orchestration.AgentCrew` → `flows.AgentCrew` |
| `examples/crew/orchestation_test.py` | 8 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/crew/orchestrator_example.py` | 8 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/crew/reproduce_orchestrator.py` | 9 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/crew/simple.py` | 9,11 | `orchestration.crew.AgentCrew, FlowContext` + `orchestration.agent.OrchestratorAgent` → `flows.crew.AgentCrew` + `flows.core.FlowContext` + `flows.agents.OrchestratorAgent` |
| `examples/crew/test_agenttool.py` | 7 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/crew/workday_jira_db_orchestrator.py` | 15 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/crew/a2a_orchestrator_example.py` | 21 | `orchestration.A2AOrchestratorAgent` → `flows.A2AOrchestratorAgent` |
| `examples/decision_simple_working.py` | 9,10 | `orchestration.AgentsFlow` → `flow.AgentsFlow`; `orchestration.decision_node` → `flow.decision_node` |
| `examples/decision_workflow_example.py` | 17,18 | Same as above |
| `examples/decision_workflow_simple_test.py` | 8,9 | Same as above |
| `examples/execution_memory_demo.py` | 13,141 | `orchestration.AgentsFlow` → `flow.AgentsFlow`; `orchestration.tools.ResultRetrievalTool` → `flows.ResultRetrievalTool` |
| `examples/orchestration/messaging.py` | 121,237 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/tool/o365.py` | 519 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |
| `examples/tools/agenttool.py` | 131 | `orchestration.agent.OrchestratorAgent` → `flows.agents.OrchestratorAgent` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.bots.orchestration.storage`~~ — removed; use `parrot.bots.flows.core.storage`
- ~~`parrot.bots.orchestration.tools`~~ — removed; use `parrot.bots.flows.tools`
- ~~`parrot.bots.orchestration.crew.AgentTask`~~ — dead code, removed in FEAT-134
- ~~`parrot.bots.orchestration.decision_node`~~ — never existed here; lives at `parrot.bots.flow.decision_node`
- ~~`parrot.bots.orchestration.AgentsFlow`~~ — never exported from orchestration; lives at `parrot.bots.flow.AgentsFlow`
- ~~`parrot.bots.flows.crew._CrewAgentNode`~~ — private name was in old crew; canonical name is `CrewAgentNode`
- ~~`parrot.bots.flows.crew.AgentNode`~~ — old alias from orchestration/crew.py; use `CrewAgentNode`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Import from the most specific sub-package (e.g., `from parrot.bots.flows.crew import AgentCrew`)
  rather than the master hub when the consumer only needs one symbol.
- The `flows/agents/orchestrator.py` header convention: docstring notes "Moved from
  `parrot.bots.orchestration.agent` to `parrot.bots.flows.agents.orchestrator` (FEAT-143)."

### Known Risks / Gotchas

- **Stale bytecache.** The installed `parrot/bots/orchestration/__pycache__/` has `.pyc` files.
  After deleting source files, Python may still import from bytecache.
  *Mitigation*: Delete `parrot/bots/orchestration/` entirely from the installed path
  (`rm -rf parrot/bots/orchestration/`), then reinstall (`uv pip install -e packages/ai-parrot`).

- **`_CrewAgentNode` → `CrewAgentNode` rename.** Test `test_agentnode_execute.py` imports the
  private name. Replace with the public `CrewAgentNode` and verify the test still works.

- **Decision workflow examples.** These import `AgentsFlow` and `decision_node` from
  `parrot.bots.orchestration`, which was never correct. The correct module is
  `parrot.bots.flow` (singular). These examples were likely already broken.

- **`import parrot.bots.orchestration.crew as crew` pattern.** Some tests (`test_crew_final_regression.py`,
  `test_flow_primitives/test_contract.py`) import the crew *module* object, not just symbols.
  Replace with `import parrot.bots.flows.crew.crew as crew` or restructure the test to
  import specific symbols.

### External Dependencies

None — no new packages required.

---

## 8. Open Questions

> All questions resolved during proposal phase.

- [x] **Should orchestration/ be kept as a deprecation stub?** — *Resolved in proposal*: Delete entirely. All in-tree imports will be updated; external consumers read the changelog.
- [x] **Should CrewResult backward-compat aliases be added to FlowResult?** — *Resolved in proposal*: Already handled in FEAT-137. Trust the agentcrew-primitives migration.
- [x] **Are agent classes already moved to flows/agents/?** — *Resolved in proposal*: Yes, confirmed. `orchestrator.py`, `a2a_orchestrator.py`, and `hr.py` all exist in `flows/agents/`.
- [x] **Is AgentCrew already in flows/crew/?** — *Resolved in proposal*: Yes. `flows/crew/crew.py` is canonical with new result models.
- [x] **Does flows/__init__.py export everything consumers need?** — *Resolved in proposal*: Yes, 30+ symbols exported.

---

## Worktree Strategy

- **Isolation unit**: per-spec (single worktree, all tasks sequential)
- **Rationale**: All 4 modules touch different file sets but Module 4 (delete) depends on
  Modules 1-3. Sequential execution in one worktree is simplest.
- **Cross-feature dependencies**: None. FEAT-134 and FEAT-137 are already completed and merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-11 | Claude (Opus 4.6) | Initial draft from FEAT-155 proposal |
