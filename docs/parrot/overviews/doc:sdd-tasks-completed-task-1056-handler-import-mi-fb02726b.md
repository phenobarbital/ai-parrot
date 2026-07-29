---
type: Wiki Overview
title: 'TASK-1056: Update Handler Imports from orchestration to flows'
id: doc:sdd-tasks-completed-task-1056-handler-import-migration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The handler layer is production code serving REST endpoints for AgentCrew
  management.
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows.crew
  rel: mentions
- concept: mod:parrot.bots.flows.crew.crew
  rel: mentions
- concept: mod:parrot.handlers.crew.execution_handler
  rel: mentions
- concept: mod:parrot.handlers.crew.handler
  rel: mentions
---

# TASK-1056: Update Handler Imports from orchestration to flows

**Feature**: FEAT-155 — Final Migration: Remove bots/orchestration, Consolidate into bots/flows
**Spec**: `sdd/specs/migration-orchestration-to-flows.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The handler layer is production code serving REST endpoints for AgentCrew management.
Two handler files still import `AgentCrew` from the legacy `parrot.bots.orchestration.crew`
path. This task repoints them to the canonical `parrot.bots.flows.crew` module.

This is the lowest-risk task (only 2 import lines to change) and has no dependencies,
making it a good starting point.

Implements: Spec §3 Module 1 (Handler Import Migration).

---

## Scope

- Update the import in `handler.py` line 18
- Update the import in `execution_handler.py` line 7
- Verify both handlers still function (import succeeds)

**NOT in scope**: modifying handler logic, updating tests, updating examples.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/crew/handler.py` | MODIFY | Change import on line 18 |
| `packages/ai-parrot/src/parrot/handlers/crew/execution_handler.py` | MODIFY | Change import on line 7 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# NEW canonical import — use this
from parrot.bots.flows.crew import AgentCrew  # verified: flows/crew/__init__.py:6

# OLD import to replace
# from parrot.bots.orchestration.crew import AgentCrew  ← DELETE this
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/handlers/crew/handler.py:18
# OLD: from parrot.bots.orchestration.crew import AgentCrew
# NEW: from parrot.bots.flows.crew import AgentCrew

# packages/ai-parrot/src/parrot/handlers/crew/execution_handler.py:7
# OLD: from parrot.bots.orchestration.crew import AgentCrew
# NEW: from parrot.bots.flows.crew import AgentCrew
```

### Does NOT Exist

- ~~`parrot.bots.orchestration.crew`~~ — will be deleted in TASK-1059; do NOT import from it
- ~~`parrot.bots.flows.crew.crew.AgentCrew`~~ — use `parrot.bots.flows.crew.AgentCrew` (the `__init__.py` re-exports)

---

## Implementation Notes

### Pattern to Follow

Each file needs exactly one line changed. The import is a simple find-and-replace:

```python
# Before:
from parrot.bots.orchestration.crew import AgentCrew

# After:
from parrot.bots.flows.crew import AgentCrew
```

### Key Constraints

- Do NOT change any handler logic — only the import line
- The `AgentCrew` class from `flows.crew` is the same class (migrated in FEAT-137)

---

## Acceptance Criteria

- [ ] `handler.py` imports `AgentCrew` from `parrot.bots.flows.crew`
- [ ] `execution_handler.py` imports `AgentCrew` from `parrot.bots.flows.crew`
- [ ] No remaining `from parrot.bots.orchestration` in either handler file
- [ ] `python -c "from parrot.handlers.crew.handler import CrewHandler"` succeeds

---

## Test Specification

No new tests needed. Verification is that existing handler imports resolve:

```python
# Quick smoke test
def test_handler_import():
    from parrot.handlers.crew.handler import CrewHandler
    assert CrewHandler is not None

def test_execution_handler_import():
    from parrot.handlers.crew.execution_handler import CrewExecutionHandler
    assert CrewExecutionHandler is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/migration-orchestration-to-flows.spec.md` for full context
2. **Check dependencies** — none required
3. **Verify the Codebase Contract** — confirm `from parrot.bots.flows.crew import AgentCrew` works
4. **Update status** in `sdd/tasks/index/migration-orchestration-to-flows.json` → `"in-progress"`
5. **Implement** the two import line changes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1056-handler-import-migration.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-05-11
**Notes**: Updated 2 handler files — exact import lines changed as specified.

**Deviations from spec**: none
