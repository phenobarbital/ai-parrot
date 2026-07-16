---
type: Wiki Overview
title: 'TASK-1308: flows/flow/ subpackage skeleton (L1 — Module 1)'
id: doc:sdd-tasks-completed-task-1308-agentsflow-migration-subpackage-skeleton-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This is Layer 1 of the AgentsFlow migration (FEAT-196). The current
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.flow
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
---

# TASK-1308: flows/flow/ subpackage skeleton (L1 — Module 1)

**Feature**: FEAT-196 — AgentsFlow Migration
**Spec**: `sdd/specs/agentsflow-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is Layer 1 of the AgentsFlow migration (FEAT-196). The current
`parrot/bots/flows/flow.py` is a single file containing the `AgentsFlow` class.
This task converts it into a proper subpackage `parrot/bots/flows/flow/` that
mirrors the existing `parrot/bots/flows/crew/` subpackage layout.

Implements §3 Module 1 of the spec. All subsequent tasks depend on this one.

---

## Scope

- Create `packages/ai-parrot/src/parrot/bots/flows/flow/` directory (subpackage)
- Create `packages/ai-parrot/src/parrot/bots/flows/flow/__init__.py` — re-exports
  `AgentsFlow`, `NODE_REGISTRY`, `register_node`, `CompletionEvent`
- Move the content of `packages/ai-parrot/src/parrot/bots/flows/flow.py` →
  `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` verbatim (no
  behavioural changes at this stage)
- Delete `packages/ai-parrot/src/parrot/bots/flows/flow.py` (the single file)
- Update `packages/ai-parrot/src/parrot/bots/flows/__init__.py` to import from
  `.flow` subpackage (already imports `from .flow import AgentsFlow, ...` — verify
  this still resolves after the conversion)
- Write a smoke test: `from parrot.bots.flows.flow import AgentsFlow` succeeds;
  `from parrot.bots.flows import AgentsFlow` still resolves

**NOT in scope**: changing any imports inside `flow.py` (the legacy
`parrot.bots.flow.*` imports stay — L4/TASK-1312 fixes those). Not moving
any other files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/flow/__init__.py` | CREATE | Subpackage init — re-exports AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | CREATE | Verbatim copy of current flows/flow.py (AgentsFlow class body unchanged) |
| `packages/ai-parrot/src/parrot/bots/flows/flow.py` | DELETE | Single-file replaced by subpackage |
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | VERIFY | `from .flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent` still resolves |
| `packages/ai-parrot/tests/bots/flows/test_subpackage_import.py` | CREATE | Smoke test for subpackage import |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Current single-file (to be moved verbatim):
# packages/ai-parrot/src/parrot/bots/flows/flow.py — full file

# flows/__init__.py currently imports (verified line ~79):
from .flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent

# crew/ subpackage mirrors (reference for new flow/__init__.py):
# packages/ai-parrot/src/parrot/bots/flows/crew/__init__.py
from .nodes import CrewAgentNode
from .crew import AgentCrew
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/flow.py (current)
# Module-level symbols to re-export from new flow/__init__.py:
NODE_REGISTRY: Dict[str, Type[Node]]          # module-level dict
def register_node(name: str) -> Callable:      # decorator factory
@dataclass
class CompletionEvent: ...                     # dataclass
class AgentsFlow(PersistenceMixin): ...        # line ~133 (class body unchanged)
```

### Does NOT Exist

- ~~`parrot.bots.flows.flow.AgentsFlow`~~ as a file import (before this task — it's
  a single-file `flow.py`, not a package)
- ~~`parrot.bots.flows.flow.flow.py`~~ before this task runs

---

## Implementation Notes

### Pattern to Follow

Mirror `parrot/bots/flows/crew/`:

```
crew/
├── __init__.py      # from .nodes import CrewAgentNode; from .crew import AgentCrew
├── crew.py          # class AgentCrew(...)
└── nodes.py         # class CrewAgentNode(...)
```

New structure:

```
flow/
├── __init__.py      # from .flow import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent
└── flow.py          # verbatim copy of current flows/flow.py
```

### Key Constraints

- Do NOT modify the content of `flow.py` in this task. Verbatim move only.
- The `parrot.bots.flows.__init__.py` line `from .flow import AgentsFlow, NODE_REGISTRY,
  register_node, CompletionEvent` must still work after this task (it will, because
  `flow/__init__.py` re-exports those names).
- After this task, `from parrot.bots.flows.flow import AgentsFlow` must work.
- After this task, `from parrot.bots.flows.flow.flow import AgentsFlow` must also work.

### References in Codebase

- `packages/ai-parrot/src/parrot/bots/flows/crew/__init__.py` — mirror this layout
- `packages/ai-parrot/src/parrot/bots/flows/flow.py` — source file to move

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/bots/flows/flow/` directory exists with
  `__init__.py` and `flow.py`
- [ ] `packages/ai-parrot/src/parrot/bots/flows/flow.py` (single file) is deleted
- [ ] `from parrot.bots.flows.flow import AgentsFlow` resolves
- [ ] `from parrot.bots.flows import AgentsFlow, NODE_REGISTRY, register_node, CompletionEvent`
  all resolve
- [ ] Smoke test passes: `pytest packages/ai-parrot/tests/bots/flows/test_subpackage_import.py -v`
- [ ] `ruff check packages/ai-parrot/src/parrot/bots/flows/flow/`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/flows/test_subpackage_import.py
import pytest


def test_subpackage_import_agentsflow():
    """AgentsFlow is importable from the new subpackage path."""
    from parrot.bots.flows.flow import AgentsFlow  # noqa: PLC0415
    assert AgentsFlow is not None


def test_subpackage_import_registry():
    """NODE_REGISTRY, register_node, CompletionEvent are importable from subpackage."""
    from parrot.bots.flows.flow import NODE_REGISTRY, register_node, CompletionEvent  # noqa: PLC0415
    assert isinstance(NODE_REGISTRY, dict)
    assert callable(register_node)
    assert CompletionEvent is not None


def test_flows_root_still_exports_agentsflow():
    """parrot.bots.flows still exports AgentsFlow after subpackage conversion."""
    from parrot.bots.flows import AgentsFlow  # noqa: PLC0415
    assert AgentsFlow is not None


def test_subpackage_flow_module_accessible():
    """Inner flow.flow module is directly accessible."""
    from parrot.bots.flows.flow.flow import AgentsFlow  # noqa: PLC0415
    assert AgentsFlow is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentsflow-migration.spec.md` for full context
2. **Check dependencies** — none; this is the first task
3. **Verify the Codebase Contract** — confirm `flow.py` content and `crew/__init__.py` structure
4. **Implement** following the scope above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/`
7. **Update index** → `"done"` in `sdd/tasks/index/agentsflow-migration.json`
8. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
