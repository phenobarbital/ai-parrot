---
type: Wiki Overview
title: 'TASK-1481: Package Registration & Init'
id: doc:sdd-tasks-completed-task-1481-package-registration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements spec §3 Module 7. Wires up the package exports and registers
relates_to:
- concept: mod:parrot_tools.computer
  rel: mentions
- concept: mod:parrot_tools.computer.models
  rel: mentions
- concept: mod:parrot_tools.computer.toolkit
  rel: mentions
- concept: mod:parrot_tools.scraping.toolkit
  rel: mentions
---

# TASK-1481: Package Registration & Init

**Feature**: FEAT-227 — Computer-Use Agent
**Spec**: `sdd/specs/computer-use-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1475, TASK-1476, TASK-1477, TASK-1478
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 7. Wires up the package exports and registers
ComputerInteractionToolkit in the TOOL_REGISTRY for discovery by agents.

---

## Scope

- Update `packages/ai-parrot-tools/src/parrot_tools/computer/__init__.py` with all public exports
- Register `ComputerInteractionToolkit` in `TOOL_REGISTRY` at `parrot_tools/__init__.py`
- Verify imports work end-to-end

**NOT in scope**: implementation of any component (all done in prior tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/computer/__init__.py` | MODIFY | Add all public exports |
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | MODIFY | Add TOOL_REGISTRY entry |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# parrot_tools/__init__.py — TOOL_REGISTRY pattern:
TOOL_REGISTRY = {  # line 12
    "web_scraping": "parrot_tools.scraping.toolkit.WebScrapingToolkit",  # line 63
    # Add: "computer_interaction": "parrot_tools.computer.toolkit.ComputerInteractionToolkit"
}
```

### Does NOT Exist
- ~~`TOOL_REGISTRY["computer"]`~~ — does not exist yet
- ~~`parrot_tools.computer`~~ package exports — empty until this task

---

## Acceptance Criteria

- [ ] `from parrot_tools.computer import ComputerInteractionToolkit, ComputerAgent, AsyncComputerBackend` works
- [ ] `from parrot_tools.computer.models import EnvState, ComputerTask, LoopResult` works
- [ ] `TOOL_REGISTRY["computer_interaction"]` resolves to `ComputerInteractionToolkit`
- [ ] No circular import issues

---

## Completion Note

Added `"computer_interaction": "parrot_tools.computer.toolkit.ComputerInteractionToolkit"` to `TOOL_REGISTRY` in `parrot_tools/__init__.py`. The `computer/__init__.py` already exported all required public symbols (models via direct import, heavy components via `__getattr__` lazy loader). Verified `TOOL_REGISTRY["computer_interaction"]` resolves correctly and all 96 computer unit tests pass.
