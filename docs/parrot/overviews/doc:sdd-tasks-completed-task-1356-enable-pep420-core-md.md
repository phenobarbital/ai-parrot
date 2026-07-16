---
type: Wiki Overview
title: 'TASK-1356: Enable PEP 420 namespace merging in core outputs package'
id: doc:sdd-tasks-completed-task-1356-enable-pep420-core-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'from pkgutil import extend_path # stdlib, no install needed'
relates_to:
- concept: mod:parrot.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.version
  rel: mentions
---

# TASK-1356: Enable PEP 420 namespace merging in core outputs package

**Feature**: FEAT-200 — Extract outputs/formats to ai-parrot-visualizations
**Spec**: `sdd/proposals/ai-parrot-visualizations.proposal.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

> Adds `pkgutil.extend_path()` calls to the core's `__init__.py` files
> so Python merges `parrot.outputs.formats` from both the host (ai-parrot)
> and the satellite (ai-parrot-visualizations) packages. This is the same
> pattern already used at `parrot/embeddings/__init__.py` (line 1-2).
> Without this, `import_module('.matplotlib', 'parrot.outputs.formats')`
> would only search the core's directory.

---

## Scope

- Add `extend_path()` to `packages/ai-parrot/src/parrot/outputs/__init__.py`
- Add `extend_path()` to `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
- Verify `packages/ai-parrot/src/parrot/__init__.py` already has `extend_path()` (confirmed at line 9)
- Remove the debug `print()` statement in `register_renderer` (line 25 of `formats/__init__.py`)

**NOT in scope**: Moving renderer files (TASK-1357/1358), changing the `get_renderer` switch logic, modifying `pyproject.toml`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/__init__.py` | MODIFY | Add `extend_path()` at top |
| `packages/ai-parrot/src/parrot/outputs/formats/__init__.py` | MODIFY | Add `extend_path()` at top, remove debug print |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pkgutil import extend_path  # stdlib, no install needed
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/__init__.py:9
from pkgutil import extend_path  # ALREADY present — do NOT duplicate

# packages/ai-parrot/src/parrot/embeddings/__init__.py:1-2
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)  # reference pattern

# packages/ai-parrot/src/parrot/outputs/__init__.py (current state — lines 1-43)
# Line 1: """Output formatters for AI-Parrot..."""
# Line 24: from ..models.outputs import OutputMode, OutputType
# Line 25-30: from .formatter import (OutputFormatter, OutputRetryConfig, ...)
# Line 31: from .formats import RenderResult, RenderError
# NO extend_path present

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py (current state)
# Line 1: import contextlib
# Line 2: from typing import Protocol, Dict, Type, Any, Optional
# Line 3: from importlib import import_module
# Line 4: from ...models.outputs import OutputMode
# Line 17: def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None):
# Line 25: print(':::: Registering renderer for mode:', mode)  ← REMOVE this debug print
# Line 33: def get_renderer(mode: OutputMode) -> Type[Renderer]:
# NO extend_path present
```

### Does NOT Exist
- ~~`extend_path` in `outputs/__init__.py`~~ — not present; this task adds it
- ~~`extend_path` in `outputs/formats/__init__.py`~~ — not present; this task adds it

---

## Implementation Notes

### Pattern to Follow
```python
# Add these two lines at the very top of each __init__.py,
# BEFORE any other imports:
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

### Key Constraints
- `extend_path()` MUST be the first executable statement (before any other imports)
- The existing imports, registry, and `get_renderer` logic remain unchanged
- Keep existing docstring in `outputs/__init__.py` (move extend_path after the docstring)

### References in Codebase
- `packages/ai-parrot/src/parrot/embeddings/__init__.py:1-2` — exact pattern to replicate
- `packages/ai-parrot/src/parrot/stores/__init__.py:1-2` — same pattern (second reference)

---

## Acceptance Criteria

- [ ] `parrot/outputs/__init__.py` has `extend_path()` as first executable statement
- [ ] `parrot/outputs/formats/__init__.py` has `extend_path()` as first executable statement
- [ ] Debug `print` on line 25 of `formats/__init__.py` is removed
- [ ] All existing imports from `parrot.outputs` still work: `from parrot.outputs import OutputFormatter, OutputMode`
- [ ] All existing imports from `parrot.outputs.formats` still work: `from parrot.outputs.formats import get_renderer, register_renderer, RenderResult`
- [ ] `pytest packages/ai-parrot/tests/outputs/ -v` passes (if tests exist)

---

## Test Specification

```python
# Quick smoke test
import parrot.outputs
import parrot.outputs.formats

# Verify extend_path worked
assert hasattr(parrot.outputs, '__path__')
assert len(parrot.outputs.__path__) >= 1

assert hasattr(parrot.outputs.formats, '__path__')
assert len(parrot.outputs.formats.__path__) >= 1

# Verify registry still works
from parrot.outputs.formats import get_renderer, RENDERERS, register_renderer
from parrot.outputs import OutputFormatter, OutputMode
```

---

## Agent Instructions

When you pick up this task:

1. **Read the reference** at `parrot/embeddings/__init__.py:1-2`
2. **Modify** `outputs/__init__.py` — add extend_path after docstring, before imports
3. **Modify** `formats/__init__.py` — add extend_path at top, remove debug print
4. **Run tests** to verify nothing broke
5. **Commit** with message: `sdd: enable PEP 420 extend_path for outputs namespace (TASK-1356)`

---

## Completion Note

Implemented by sdd-worker on 2026-05-28.

- Added `extend_path()` to `parrot/outputs/__init__.py` (after docstring, before imports)
- Added `extend_path()` to `parrot/outputs/formats/__init__.py` (before all other imports)
- Removed debug `print()` on line 25 of `formats/__init__.py`
- Verified `__path__` merges both core and satellite directories ✅
- Verified `parrot.outputs.formats.version.__version__` is now discoverable ✅

PEP 420 namespace merging confirmed working — both paths appear in `__path__`:
- `.../ai-parrot/src/parrot/outputs/formats`
- `.../ai-parrot-visualizations/src/parrot/outputs/formats`
