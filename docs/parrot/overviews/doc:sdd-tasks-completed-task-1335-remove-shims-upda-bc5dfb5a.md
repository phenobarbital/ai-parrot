---
type: Wiki Overview
title: 'TASK-1335: Remove hook shims and update entry points'
id: doc:sdd-tasks-completed-task-1335-remove-shims-update-entrypoints-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After the package move (TASK-1333), the old backward-compatibility shims
  at
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.cli
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.brokers
  rel: mentions
---

# TASK-1335: Remove hook shims and update entry points

**Feature**: FEAT-196 — Fix Parrot Transport
**Spec**: `sdd/specs/fix-parrot-transport.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1333
**Assigned-to**: unassigned

---

## Context

After the package move (TASK-1333), the old backward-compatibility shims at
`parrot/autonomous/hooks/` are no longer needed (the only code that used them
via submodule imports — `hook.py` — is being fixed in TASK-1334). This task
removes the shim directory, updates the `parrot-fs` console script entry point
in `pyproject.toml`, and cleans up the root-level bytecode directory.

Implements: Spec Module 3 (Remove Shims & Update Entry Points).

---

## Scope

- Delete `packages/ai-parrot/src/parrot/autonomous/hooks/` entirely (shim `__init__.py` +
  `brokers/__init__.py` + `brokers/` directory)
- Update `packages/ai-parrot/pyproject.toml` line 103:
  `parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"` (was `parrot.transport.filesystem.cli:main`)
- Delete root-level `parrot/transport/` directory (contains only `__pycache__` bytecode files)
- Verify old `packages/ai-parrot/src/parrot/transport/` was already removed by TASK-1333

**NOT in scope**:
- Moving the transport package (TASK-1333, already done)
- Fixing hook.py imports (TASK-1334)
- Updating test imports (TASK-1336)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/autonomous/hooks/__init__.py` | DELETE | Remove backward-compat shim |
| `packages/ai-parrot/src/parrot/autonomous/hooks/brokers/__init__.py` | DELETE | Remove broker shim |
| `packages/ai-parrot/src/parrot/autonomous/hooks/brokers/` | DELETE | Remove empty broker directory |
| `packages/ai-parrot/src/parrot/autonomous/hooks/` | DELETE | Remove entire shim directory |
| `packages/ai-parrot/pyproject.toml` | MODIFY | Update `parrot-fs` entry point (line 103) |
| `parrot/transport/` | DELETE | Remove root-level bytecode directory |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# The shim files being deleted contain:
# packages/ai-parrot/src/parrot/autonomous/hooks/__init__.py:
from parrot.core.hooks import *  # noqa: F401, F403
from parrot.core.hooks import __all__  # noqa: F401

# packages/ai-parrot/src/parrot/autonomous/hooks/brokers/__init__.py:
# (re-exports from parrot.core.hooks.brokers)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/pyproject.toml line 103 (current):
# parrot-fs = "parrot.transport.filesystem.cli:main"
#
# Must become:
# parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"
```

### Does NOT Exist
- ~~`parrot.autonomous.hooks.base`~~ — module file does not exist (only the `__init__.py` shim)
- ~~`parrot.autonomous.hooks.models`~~ — module file does not exist
- ~~Source files in `parrot/transport/` at repo root~~ — only `__pycache__` bytecode; no `.py` source files

---

## Implementation Notes

### Deletion sequence
```bash
# 1. Remove the shim directory
git rm -r packages/ai-parrot/src/parrot/autonomous/hooks/

# 2. Update pyproject.toml entry point
# Change line 103 from:
#   parrot-fs = "parrot.transport.filesystem.cli:main"
# To:
#   parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"

# 3. Clean up root-level bytecode (not tracked by git, use rm)
rm -rf parrot/transport/
```

### Key Constraints
- The `parrot/autonomous/hooks/` directory contains ONLY shim files — no production logic.
  All real hook code lives in `parrot/core/hooks/`.
- The root-level `parrot/transport/` is NOT tracked by git (only `__pycache__` bytecode).
  Use `rm -rf`, not `git rm`.
- After this task, `parrot.autonomous.hooks` will raise `ModuleNotFoundError` — this is
  intentional (clean break). Test files referencing it are fixed in TASK-1336.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/autonomous/hooks/` directory does not exist
- [ ] `pyproject.toml` line 103 reads `parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"`
- [ ] Root-level `parrot/transport/` directory does not exist
- [ ] `import parrot.autonomous.hooks` raises `ModuleNotFoundError` (expected — shims removed)
- [ ] `parrot.core.hooks` still works: `from parrot.core.hooks import BaseHook, HookManager`

---

## Test Specification

```python
# Verify shims are gone (clean break):
def test_old_shim_removed():
    import pytest
    with pytest.raises(ModuleNotFoundError):
        import parrot.autonomous.hooks

# Verify core hooks still work:
def test_core_hooks_unaffected():
    from parrot.core.hooks import BaseHook, HookManager, HookEvent
    assert BaseHook is not None
    assert HookManager is not None

# Verify entry point (check pyproject.toml content):
def test_entrypoint_updated():
    from pathlib import Path
    toml = Path("packages/ai-parrot/pyproject.toml").read_text()
    assert "parrot.autonomous.transport.filesystem.cli:main" in toml
    assert "parrot.transport.filesystem.cli:main" not in toml
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fix-parrot-transport.spec.md` for full context
2. **Check dependencies** — TASK-1333 must be completed
3. **Verify the Codebase Contract** — confirm `parrot/autonomous/hooks/` still exists and still only contains shim files
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** the deletions and pyproject.toml update
6. **Verify** all acceptance criteria
7. **Move this file** to `sdd/tasks/completed/TASK-1335-remove-shims-update-entrypoints.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-28
**Notes**: Removed `parrot/autonomous/hooks/__init__.py` and `parrot/autonomous/hooks/brokers/__init__.py`
via `git rm -r`. Updated pyproject.toml line 103 from `parrot.transport.filesystem.cli:main` to
`parrot.autonomous.transport.filesystem.cli:main`. The root-level `parrot/transport/` bytecode directory
was already absent from the worktree (never committed to git) — no action needed.

**Deviations from spec**: none
