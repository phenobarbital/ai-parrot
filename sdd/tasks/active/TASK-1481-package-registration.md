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

*(Agent fills this in when done)*
