---
type: Wiki Overview
title: 'TASK-1350: Matrix Channel Extraction + Hook Implementation'
id: doc:sdd-tasks-completed-task-1350-matrix-extraction-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Move the Matrix channel integration (18 Python files, ~392 KB) from
relates_to:
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
- concept: mod:parrot.integrations.matrix
  rel: mentions
- concept: mod:parrot.integrations.matrix.client
  rel: mentions
- concept: mod:parrot.integrations.matrix.hook
  rel: mentions
---

# TASK-1350: Matrix Channel Extraction + Hook Implementation

**Feature**: FEAT-202 — ai-parrot-integrations
**Spec**: `sdd/specs/ai-parrot-integrations.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1345, TASK-1343
**Assigned-to**: unassigned

---

## Context

Move the Matrix channel integration (18 Python files, ~392 KB) from
`parrot/integrations/matrix/` to the satellite package. Matrix is the
most actively developed channel (matrix-collaborative-crew, FEAT-195
already merged). This task also creates the concrete `MatrixHook`
implementation in the satellite that self-registers with the
`HookRegistry` created in TASK-1343.

Implements **Spec Modules 6 + 11** (hook implementation side).

---

## Scope

- Move `packages/ai-parrot/src/parrot/integrations/matrix/` →
  `packages/ai-parrot-integrations/src/parrot/integrations/matrix/`
  (18 files, byte-identical).
- Create `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py`
  — the concrete `MatrixHook` implementation (moved from
  `parrot/core/hooks/matrix.py`, adapted to use `HookRegistry.register()`).
- Remove `parrot/core/hooks/matrix.py` from core (the interface and
  registry stay — created in TASK-1343).
- Move related tests:
  - `packages/ai-parrot/tests/test_matrix_*.py` (all matrix test files)
- Verify PEP 420 resolution for `MatrixClientWrapper` imports.

**NOT in scope**: Changing matrix-collaborative-crew logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/` | CREATE (move) | 18 Python files |
| `packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py` | CREATE | MatrixHook adapted from core |
| `packages/ai-parrot-integrations/tests/test_matrix_*.py` | CREATE (move) | Matrix tests |
| `packages/ai-parrot/src/parrot/integrations/matrix/` | DELETE | Removed from core |
| `packages/ai-parrot/src/parrot/core/hooks/matrix.py` | DELETE | Hook moved to satellite |
| `packages/ai-parrot/tests/test_matrix_*.py` | DELETE | Tests moved |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Core hook to relocate:
# parrot/core/hooks/matrix.py:10-11,14
from .base import BaseHook                         # line 10
from .models import HookType, MatrixHookConfig     # line 11
class MatrixHook(BaseHook):                        # line 14

# Dynamic import inside MatrixHook (line 63):
from parrot.integrations.matrix.client import MatrixClientWrapper

# After TASK-1343, HookRegistry exists:
from parrot.core.hooks.base import HookRegistry    # created by TASK-1343

# Matrix consumer in core:
# parrot/core/hooks/matrix.py is the ONLY core file importing from matrix
```

### Does NOT Exist

- ~~`parrot.integrations.matrix.hook`~~ — does NOT exist yet; this task creates it
- ~~`parrot.integrations.matrix.MatrixBot`~~ — the class is `MatrixClientWrapper`

---

## Implementation Notes

### Pattern to Follow — Hook Self-Registration

```python
# packages/ai-parrot-integrations/src/parrot/integrations/matrix/hook.py
from parrot.core.hooks.base import BaseHook, HookRegistry
from parrot.core.hooks.models import HookType, MatrixHookConfig

class MatrixHook(BaseHook):
    """Matrix message listener — relocated from core."""
    # ... same implementation as core/hooks/matrix.py ...
    # but import MatrixClientWrapper locally (same package now)

# Auto-register on import
HookRegistry.register("matrix", MatrixHook)
```

### Key Constraints

- Matrix is actively developed — move byte-identical, no refactoring.
- `MatrixHookConfig` stays in `parrot/core/hooks/models.py` (core) for
  backward compat — the hook in satellite imports it from there.
- The old `parrot/core/hooks/matrix.py` must be deleted AFTER the new
  hook is in place (same commit).
- Multiple test files (test_matrix_appservice, test_matrix_crew,
  test_matrix_hook, test_matrix_transport, etc.) — move all.

---

## Acceptance Criteria

- [ ] All 18 matrix Python files present in satellite
- [ ] `MatrixHook` in satellite auto-registers with `HookRegistry`
- [ ] `parrot/core/hooks/matrix.py` deleted from core
- [ ] `from parrot.integrations.matrix.client import MatrixClientWrapper` works
- [ ] All matrix tests pass in satellite
- [ ] No linting errors

---

## Completion Note

*(Agent fills this in when done)*
