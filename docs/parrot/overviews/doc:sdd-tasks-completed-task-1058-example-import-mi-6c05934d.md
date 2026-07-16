---
type: Wiki Overview
title: 'TASK-1058: Update Example Imports from orchestration to flows'
id: doc:sdd-tasks-completed-task-1058-example-import-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 17 example files contain 24 import lines referencing `parrot.bots.orchestration`.
  Most
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.agents
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
---

# TASK-1058: Update Example Imports from orchestration to flows

**Feature**: FEAT-155 — Final Migration: Remove bots/orchestration, Consolidate into bots/flows
**Spec**: `sdd/specs/migration-orchestration-to-flows.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

17 example files contain 24 import lines referencing `parrot.bots.orchestration`. Most
are crew examples importing `AgentCrew` or `OrchestratorAgent`. Some decision workflow
examples import `AgentsFlow` and `decision_node` from orchestration, which was never
correct — those must be repointed to `parrot.bots.flow` (singular).

Implements: Spec §3 Module 3 (Example Import Migration).

---

## Scope

- Update all 24 import lines across 17 example files
- Crew examples: repoint to `parrot.bots.flows` (plural)
- Decision workflow examples: repoint to `parrot.bots.flow` (singular — the AgentsFlow engine)
- Fix `execution_memory_demo.py` which has both `AgentsFlow` and `ResultRetrievalTool` imports

**NOT in scope**: updating handler imports (TASK-1056), updating tests (TASK-1057),
deleting orchestration directory (TASK-1059), modifying example logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/crew/crew_flows.py` | MODIFY | Line 12: `orchestration.AgentCrew, FlowContext` → `flows` |
| `examples/crew/crew_loop.py` | MODIFY | Line 4: `orchestration.crew.AgentCrew` → `flows.crew` |
| `examples/crew/crew_nav_qa.py` | MODIFY | Line 3: `orchestration.AgentCrew, FlowContext` → `flows` |
| `examples/crew/crew_qa.py` | MODIFY | Line 17: `orchestration.crew.AgentCrew` → `flows.crew` |
| `examples/crew/market_researcher.py` | MODIFY | Line 3: `orchestration.AgentCrew` → `flows` |
| `examples/crew/orchestation_test.py` | MODIFY | Line 8: `orchestration.agent.OrchestratorAgent` → `flows.agents` |
| `examples/crew/orchestrator_example.py` | MODIFY | Line 8: same |
| `examples/crew/reproduce_orchestrator.py` | MODIFY | Line 9: same |
| `examples/crew/simple.py` | MODIFY | Lines 9,11: two import lines |
| `examples/crew/test_agenttool.py` | MODIFY | Line 7: `orchestration.agent.OrchestratorAgent` → `flows.agents` |
| `examples/crew/workday_jira_db_orchestrator.py` | MODIFY | Line 15: same |
| `examples/crew/a2a_orchestrator_example.py` | MODIFY | Line 21: `orchestration.A2AOrchestratorAgent` → `flows` |
| `examples/decision_simple_working.py` | MODIFY | Lines 9,10: `orchestration.AgentsFlow` → `flow.AgentsFlow` + `decision_node` |
| `examples/decision_workflow_example.py` | MODIFY | Lines 17,18: same |
| `examples/decision_workflow_simple_test.py` | MODIFY | Lines 8,9: same |
| `examples/execution_memory_demo.py` | MODIFY | Lines 13,141: `AgentsFlow` → `flow`; `tools` → `flows` |
| `examples/orchestration/messaging.py` | MODIFY | Lines 121,237: `orchestration.agent.OrchestratorAgent` → `flows.agents` |
| `examples/tool/o365.py` | MODIFY | Line 519: same |
| `examples/tools/agenttool.py` | MODIFY | Line 131: same |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Crew imports (plural "flows")
from parrot.bots.flows.crew import AgentCrew         # verified: flows/crew/__init__.py:6
from parrot.bots.flows import AgentCrew, FlowContext  # verified: flows/__init__.py:54,20
from parrot.bots.flows.agents import OrchestratorAgent  # verified: flows/agents/__init__.py:17
from parrot.bots.flows import A2AOrchestratorAgent   # verified: flows/__init__.py:59
from parrot.bots.flows import ResultRetrievalTool    # verified: flows/__init__.py:68
from parrot.bots.flows.core import FlowContext       # verified: flows/core/__init__.py

# AgentsFlow imports (singular "flow")
from parrot.bots.flow import AgentsFlow              # verified: flow/__init__.py:4
from parrot.bots.flow.decision_node import (         # verified: flow/__init__.py:10-21
    DecisionFlowNode,
    DecisionMode,
    DecisionType,
    DecisionNodeConfig,
    DecisionResult,
    BinaryDecision,
    ApprovalDecision,
    MultiChoiceDecision,
    EscalationPolicy,
    VoteWeight,
)
```

### Does NOT Exist

- ~~`parrot.bots.orchestration.AgentsFlow`~~ — was never exported from orchestration; lives at `parrot.bots.flow`
- ~~`parrot.bots.orchestration.decision_node`~~ — never existed in orchestration; lives at `parrot.bots.flow.decision_node`
- ~~`parrot.bots.orchestration.tools.ResultRetrievalTool`~~ — never existed; use `parrot.bots.flows.ResultRetrievalTool`
- ~~`parrot.bots.flows.AgentsFlow`~~ — AgentsFlow is in `parrot.bots.flow` (singular), NOT `flows` (plural)

---

## Implementation Notes

### Import Replacements by Category

**Category A: Crew examples** (most common)
```python
# OrchestratorAgent
# OLD: from parrot.bots.orchestration.agent import OrchestratorAgent
# NEW: from parrot.bots.flows.agents import OrchestratorAgent

# AgentCrew (from crew module)
# OLD: from parrot.bots.orchestration.crew import AgentCrew
# NEW: from parrot.bots.flows.crew import AgentCrew

# AgentCrew + FlowContext (from package)
# OLD: from parrot.bots.orchestration import AgentCrew, FlowContext
# NEW: from parrot.bots.flows import AgentCrew, FlowContext

# A2AOrchestratorAgent
# OLD: from parrot.bots.orchestration import A2AOrchestratorAgent
# NEW: from parrot.bots.flows import A2AOrchestratorAgent

# AgentCrew + FlowContext + OrchestratorAgent (simple.py — two lines)
# OLD: from parrot.bots.orchestration.crew import AgentCrew, FlowContext
#      from parrot.bots.orchestration.agent import OrchestratorAgent
# NEW: from parrot.bots.flows.crew import AgentCrew
#      from parrot.bots.flows.core import FlowContext
#      from parrot.bots.flows.agents import OrchestratorAgent
```

**Category B: Decision workflow examples** (import from singular `flow`)
```python
# AgentsFlow
# OLD: from parrot.bots.orchestration import AgentsFlow
# NEW: from parrot.bots.flow import AgentsFlow

# decision_node
# OLD: from parrot.bots.orchestration.decision_node import (...)
# NEW: from parrot.bots.flow.decision_node import (...)
```

**Category C: Mixed (execution_memory_demo.py)**
```python
# OLD: from parrot.bots.orchestration import AgentsFlow
# NEW: from parrot.bots.flow import AgentsFlow
# OLD: from parrot.bots.orchestration.tools import ResultRetrievalTool
# NEW: from parrot.bots.flows import ResultRetrievalTool
```

### Key Constraints

- Do NOT change example logic — only import lines
- **Critical distinction**: `parrot.bots.flows` (plural) for crew/agents/primitives vs
  `parrot.bots.flow` (singular) for AgentsFlow/decision_node. These are different modules.
- Some examples may have other issues (e.g., using deprecated APIs). Ignore those — only fix imports.

---

## Acceptance Criteria

- [ ] No example file contains `from parrot.bots.orchestration`
- [ ] No example file contains `import parrot.bots.orchestration`
- [ ] Decision workflow examples import from `parrot.bots.flow` (singular)
- [ ] Crew examples import from `parrot.bots.flows` (plural)
- [ ] `grep -rn 'parrot.bots.orchestration' examples/` returns nothing

---

## Test Specification

No automated tests for examples. Manual verification:

```bash
# Verify no remaining orchestration references
grep -rn 'parrot.bots.orchestration' examples/

# Spot-check a few imports resolve
python -c "from parrot.bots.flows.crew import AgentCrew; print('OK')"
python -c "from parrot.bots.flows.agents import OrchestratorAgent; print('OK')"
python -c "from parrot.bots.flow import AgentsFlow; print('OK')"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migration-orchestration-to-flows.spec.md` for full context
2. **Check dependencies** — none required
3. **Verify the Codebase Contract** — especially the `flow` vs `flows` distinction
4. **Update status** in `sdd/tasks/index/migration-orchestration-to-flows.json` → `"in-progress"`
5. **Implement** the import replacements file by file, following the category map above
6. **Verify** all acceptance criteria are met (especially the grep check)
7. **Move this file** to `sdd/tasks/completed/TASK-1058-example-import-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-05-11
**Notes**: Updated 12 example files. Several files in the spec list had no orchestration
references (decision_simple_working.py, decision_workflow_example.py, decision_workflow_simple_test.py,
execution_memory_demo.py, orchestration/messaging.py, crew_nav_qa.py, crew_qa.py) — already clean.
simple.py: split "AgentCrew, FlowContext" into two separate import lines as per spec pattern.

**Deviations from spec**: none
