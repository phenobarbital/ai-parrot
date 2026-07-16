---
type: Wiki Overview
title: 'TASK-1063: Define CrewHookCallback type alias'
id: doc:sdd-tasks-completed-task-1063-crew-hook-type-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task defines the `CrewHookCallback` type alias used by the hook registration
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.models
  rel: mentions
- concept: mod:parrot.models.crew
  rel: mentions
---

# TASK-1063: Define CrewHookCallback type alias

**Feature**: FEAT-157 — AgentCrew Lifecycle Hooks
**Spec**: `sdd/specs/agentcrew-hooks.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This task defines the `CrewHookCallback` type alias used by the hook registration
and dispatch system in AgentCrew. It implements Module 1 from the spec (§3).

The type follows the same pattern as the existing `ActionCallback` type alias
but is more specific — it documents the exact `(crew_name, result)` signature
rather than using `Callable[..., ...]`.

---

## Scope

- Define `CrewHookCallback` type alias in `parrot/bots/flows/core/types.py`
- Add `CrewHookCallback` to the `__init__.py` re-exports in `flows/core/` and `flows/`

**NOT in scope**: Hook registration methods, dispatch logic, or tests (those are TASK-1064 and TASK-1065).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/types.py` | MODIFY | Add `CrewHookCallback` type alias |
| `packages/ai-parrot/src/parrot/bots/flows/core/__init__.py` | MODIFY | Add `CrewHookCallback` to imports and `__all__` |
| `packages/ai-parrot/src/parrot/bots/flows/__init__.py` | MODIFY | Add `CrewHookCallback` to imports and `__all__` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# packages/ai-parrot/src/parrot/bots/flows/core/types.py — already imported:
from typing import Any, Awaitable, Callable, Dict, Protocol, Union  # verified: types.py:12-19
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/flows/core/types.py:27
ActionCallback = Callable[..., Union[None, Awaitable[None]]]

# packages/ai-parrot/src/parrot/bots/flows/core/__init__.py:22,56
# ActionCallback is imported at line 22 and in __all__ at line 56

# packages/ai-parrot/src/parrot/bots/flows/__init__.py:26,76
# ActionCallback is imported at line 26 and in __all__ at line 76
```

### Does NOT Exist

- ~~`CrewHookCallback`~~ — does not exist yet; this task creates it
- ~~`HookCallback`~~ — no such type alias exists anywhere

---

## Implementation Notes

### Pattern to Follow

Add the type alias right after `ActionCallback` (line 27-28 of types.py):

```python
# After line 28 in types.py:
CrewHookCallback = Callable[[str, Any], Union[None, Awaitable[None]]]
"""Callback type for crew-level lifecycle hooks (on_complete, on_error).

Signature: (crew_name: str, result: CrewResult) -> None
The second parameter is typed as Any to avoid circular imports with
parrot.models.crew.CrewResult.
"""
```

**Why `Any` instead of `CrewResult`**: The `types.py` module is deliberately
import-cycle-free (see module docstring line 7). Importing `CrewResult` from
`parrot.models.crew` would introduce a cycle. Use `Any` for the type alias;
the docstring documents the actual expected type.

### Key Constraints

- Do NOT add any imports from `parrot.bots.*` or `parrot.models.*` — the types
  module must remain cycle-free.
- Add `CrewHookCallback` to both `__init__.py` re-exports next to `ActionCallback`.

---

## Acceptance Criteria

- [ ] `CrewHookCallback` type alias defined in `types.py`
- [ ] Type alias exported from `parrot.bots.flows.core` and `parrot.bots.flows`
- [ ] No circular import introduced
- [ ] `python -c "from parrot.bots.flows.core.types import CrewHookCallback; print(CrewHookCallback)"` succeeds

---

## Test Specification

No dedicated test file — this is a type alias. Verification is via import check
in the acceptance criteria above.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/agentcrew-hooks.spec.md` for full context
2. **Check dependencies** — none for this task
3. **Verify the Codebase Contract** — confirm `ActionCallback` is still at types.py:27
4. **Implement** the type alias and __init__.py exports
5. **Verify** the import works from a Python shell
6. **Update status** in per-spec index → `"in-progress"` / `"done"`
7. **Move this file** to `sdd/tasks/completed/`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-11
**Notes**: Added `CrewHookCallback = Callable[[str, Any], Union[None, Awaitable[None]]]`
to `types.py` after `ActionCallback`, with full docstring explaining the
`(crew_name, result)` signature, the `Any` usage for cycle-safety, ordering
guarantees, and exception behaviour. Re-exported from both `flows/core/__init__.py`
and `flows/__init__.py` alongside `ActionCallback`.

**Deviations from spec**: none
