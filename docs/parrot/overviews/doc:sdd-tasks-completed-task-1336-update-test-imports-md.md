---
type: Wiki Overview
title: 'TASK-1336: Update all test imports to new paths'
id: doc:sdd-tasks-completed-task-1336-update-test-imports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After the package move (TASK-1333), hook import fix (TASK-1334), and shim
  removal
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.transport
  rel: mentions
- concept: mod:parrot.autonomous.transport.base
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.channel
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.config
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.feed
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.hook
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.inbox
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.registry
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.reservation
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.transport
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.file_watchdog
  rel: mentions
- concept: mod:parrot.core.hooks.manager
  rel: mentions
- concept: mod:parrot.core.hooks.matrix
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
- concept: mod:parrot.core.hooks.scheduler
  rel: mentions
---

# TASK-1336: Update all test imports to new paths

**Feature**: FEAT-196 — Fix Parrot Transport
**Spec**: `sdd/specs/fix-parrot-transport.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1333, TASK-1334, TASK-1335
**Assigned-to**: unassigned

---

## Context

After the package move (TASK-1333), hook import fix (TASK-1334), and shim removal
(TASK-1335), all test files still reference the old import paths. This task updates
every test file to use the new canonical paths and removes the backward-compat shim
test that's now expected to fail.

Implements: Spec Module 4 (Update All Test Imports).

---

## Scope

Two categories of import updates:

**Category 1: Transport imports** (`parrot.transport.*` → `parrot.autonomous.transport.*`):
- `tests/transport/test_abstract_transport.py`
- `tests/transport/filesystem/test_imports.py`
- `tests/transport/filesystem/conftest.py`
- `tests/transport/filesystem/test_channel.py`
- `tests/transport/filesystem/test_registry.py`
- `tests/transport/filesystem/test_config.py`
- `tests/transport/filesystem/test_feed.py`
- `tests/transport/filesystem/test_inbox.py`
- `tests/transport/filesystem/test_reservation.py`
- `tests/transport/filesystem/test_integration.py`
- `tests/transport/filesystem/test_hook.py`

**Category 2: Hook imports** (`parrot.autonomous.hooks.*` → `parrot.core.hooks.*`):
- `tests/test_hooks.py`
- `tests/test_matrix_hook.py`
- `tests/transport/filesystem/test_imports.py` (line 37)
- `tests/transport/filesystem/test_hook.py` (lines 8, 186)
- `tests/transport/filesystem/test_integration.py` (line 8)

**Category 3: Remove backward-compat shim test**:
- `tests/core/hooks/test_imports.py` — remove `test_backward_compat_shim` method (lines 102-106)

**Category 4: Update test_imports.py** to verify new paths:
- `tests/transport/filesystem/test_imports.py` — update all assertions to match new import paths

**NOT in scope**:
- Moving the transport package (TASK-1333)
- Fixing hook.py imports (TASK-1334)
- Removing shims (TASK-1335)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/transport/test_abstract_transport.py` | MODIFY | `parrot.transport.base` → `parrot.autonomous.transport.base` |
| `packages/ai-parrot/tests/transport/filesystem/test_imports.py` | MODIFY | All import paths updated + hook model import fixed |
| `packages/ai-parrot/tests/transport/filesystem/conftest.py` | MODIFY | `parrot.transport.filesystem.*` → `parrot.autonomous.transport.filesystem.*` |
| `packages/ai-parrot/tests/transport/filesystem/test_channel.py` | MODIFY | Transport import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_registry.py` | MODIFY | Transport import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_config.py` | MODIFY | Transport import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_feed.py` | MODIFY | Transport import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_inbox.py` | MODIFY | Transport import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_reservation.py` | MODIFY | Transport import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_integration.py` | MODIFY | Transport + hook import paths |
| `packages/ai-parrot/tests/transport/filesystem/test_hook.py` | MODIFY | Transport + hook import paths |
| `packages/ai-parrot/tests/test_hooks.py` | MODIFY | `parrot.autonomous.hooks.*` → `parrot.core.hooks.*` |
| `packages/ai-parrot/tests/test_matrix_hook.py` | MODIFY | `parrot.autonomous.hooks.*` → `parrot.core.hooks.*` |
| `packages/ai-parrot/tests/core/hooks/test_imports.py` | MODIFY | Remove `test_backward_compat_shim` method |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# NEW canonical transport imports (use these in all tests):
from parrot.autonomous.transport import AbstractTransport  # after move
from parrot.autonomous.transport.base import AbstractTransport  # explicit module
from parrot.autonomous.transport.filesystem import FilesystemTransport
from parrot.autonomous.transport.filesystem import FilesystemTransportConfig
from parrot.autonomous.transport.filesystem import FilesystemHook
from parrot.autonomous.transport.filesystem.config import FilesystemTransportConfig
from parrot.autonomous.transport.filesystem.transport import FilesystemTransport
from parrot.autonomous.transport.filesystem.hook import FilesystemHook
from parrot.autonomous.transport.filesystem.feed import ActivityFeed
from parrot.autonomous.transport.filesystem.channel import ChannelManager
from parrot.autonomous.transport.filesystem.registry import AgentRegistry
from parrot.autonomous.transport.filesystem.inbox import InboxManager
from parrot.autonomous.transport.filesystem.reservation import ReservationManager

# NEW canonical hook imports (use these in all tests):
from parrot.core.hooks.base import BaseHook              # packages/ai-parrot/src/parrot/core/hooks/base.py:12
from parrot.core.hooks.models import HookType            # in __all__
from parrot.core.hooks.models import HookEvent           # in __all__
from parrot.core.hooks.models import FilesystemHookConfig  # NOT in __all__, import from models directly
from parrot.core.hooks.models import SchedulerHookConfig   # in __all__
from parrot.core.hooks.models import FileWatchdogHookConfig  # in __all__
from parrot.core.hooks.models import MatrixHookConfig    # in __all__
from parrot.core.hooks.manager import HookManager        # packages/ai-parrot/src/parrot/core/hooks/manager.py
from parrot.core.hooks.scheduler import SchedulerHook    # lazy import in core/hooks
from parrot.core.hooks.file_watchdog import FileWatchdogHook  # lazy import in core/hooks
from parrot.core.hooks.matrix import MatrixHook          # lazy import in core/hooks
```

### Does NOT Exist
- ~~`parrot.transport`~~ — package no longer exists after TASK-1333
- ~~`parrot.autonomous.hooks`~~ — shim directory deleted in TASK-1335
- ~~`parrot.autonomous.hooks.base`~~ — never existed as a module file
- ~~`parrot.autonomous.hooks.models`~~ — never existed as a module file
- ~~`parrot.autonomous.hooks.scheduler`~~ — never existed as a module file
- ~~`parrot.autonomous.hooks.file_watchdog`~~ — never existed as a module file
- ~~`parrot.autonomous.hooks.matrix`~~ — never existed as a module file
- ~~`parrot.autonomous.hooks.manager`~~ — never existed as a module file

---

## Implementation Notes

### Systematic replacement approach

Use `sed` or manual edits. The replacements are mechanical:

**Transport replacements** (in test files under `tests/transport/`):
```
from parrot.transport.   →  from parrot.autonomous.transport.
import parrot.transport.  →  import parrot.autonomous.transport.
```

**Hook replacements** (in `tests/test_hooks.py`, `tests/test_matrix_hook.py`, and some transport tests):
```
from parrot.autonomous.hooks.base      →  from parrot.core.hooks.base
from parrot.autonomous.hooks.models    →  from parrot.core.hooks.models
from parrot.autonomous.hooks.manager   →  from parrot.core.hooks.manager
from parrot.autonomous.hooks.scheduler →  from parrot.core.hooks.scheduler
from parrot.autonomous.hooks.file_watchdog →  from parrot.core.hooks.file_watchdog
from parrot.autonomous.hooks.matrix    →  from parrot.core.hooks.matrix
from parrot.autonomous.hooks import    →  from parrot.core.hooks import
```

### Special cases

1. **`test_imports.py`** — this file tests import paths as assertions.
   Update the docstrings and import targets:
   - `"parrot.transport.base"` → `"parrot.autonomous.transport.base"`
   - `"parrot.transport"` → `"parrot.autonomous.transport"`
   - `from parrot.autonomous.hooks.models import FilesystemHookConfig` → `from parrot.core.hooks.models import FilesystemHookConfig`
   - Also update the `import parrot.transport.filesystem as pkg` → `import parrot.autonomous.transport.filesystem as pkg`

2. **`test_imports.py` line 37** (`test_hook_config_from_models`):
   ```python
   # BEFORE:
   from parrot.autonomous.hooks.models import FilesystemHookConfig
   # AFTER:
   from parrot.core.hooks.models import FilesystemHookConfig
   ```
   Also update the docstring to reflect the new import path.

3. **`tests/core/hooks/test_imports.py`** — remove `test_backward_compat_shim` method (lines 102-106):
   ```python
   # REMOVE THIS:
   def test_backward_compat_shim(self):
       """parrot.autonomous.hooks re-exports everything from parrot.core.hooks."""
       from parrot.autonomous.hooks import BaseHook, HookManager, HookEvent  # noqa: F401
       assert BaseHook is not None
   ```

### Key Constraints
- `FilesystemHookConfig` must be imported from `parrot.core.hooks.models` (NOT from
  `parrot.core.hooks`) because it's not in `__all__`
- The `SchedulerHook`, `FileWatchdogHook`, `MatrixHook` classes are lazily imported
  in `core/hooks/__init__.py` — can be imported from either `parrot.core.hooks` or
  their specific modules

---

## Acceptance Criteria

- [ ] All transport tests pass: `pytest packages/ai-parrot/tests/transport/ -v`
- [ ] Hook tests pass: `pytest packages/ai-parrot/tests/test_hooks.py packages/ai-parrot/tests/test_matrix_hook.py -v`
- [ ] Core hook import tests pass: `pytest packages/ai-parrot/tests/core/hooks/test_imports.py -v`
- [ ] No remaining references to `parrot.transport` in test files: `grep -rn "from parrot\.transport" packages/ai-parrot/tests/` returns nothing
- [ ] No remaining references to `parrot.autonomous.hooks` in test files: `grep -rn "from parrot\.autonomous\.hooks" packages/ai-parrot/tests/` returns nothing
- [ ] `test_backward_compat_shim` test method no longer exists in `test_imports.py`

---

## Test Specification

After updating all imports, run the full test suite for affected areas:

```bash
# Transport tests (all should pass):
pytest packages/ai-parrot/tests/transport/ -v

# Hook system tests (all should pass):
pytest packages/ai-parrot/tests/test_hooks.py -v
pytest packages/ai-parrot/tests/test_matrix_hook.py -v

# Core hook import tests (should pass after removing shim test):
pytest packages/ai-parrot/tests/core/hooks/test_imports.py -v

# Verify no stale imports remain:
grep -rn "from parrot\.transport\." packages/ai-parrot/tests/
grep -rn "from parrot\.autonomous\.hooks" packages/ai-parrot/tests/
# Both should return empty
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fix-parrot-transport.spec.md` for full context
2. **Check dependencies** — TASK-1333, TASK-1334, and TASK-1335 must all be completed
3. **Verify the Codebase Contract** — confirm the new import paths work:
   - `python -c "from parrot.autonomous.transport.filesystem import FilesystemTransport"`
   - `python -c "from parrot.core.hooks.base import BaseHook"`
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** all import replacements systematically
6. **Run tests** to verify everything passes
7. **Move this file** to `sdd/tasks/completed/TASK-1336-update-test-imports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-28
**Notes**: Updated all 14 files listed in the task spec. Additionally fixed 2 files not listed in the
spec (`test_cli.py` and `test_transport.py`) that also had stale `parrot.transport.*` imports — these
were needed to satisfy the acceptance criterion "No remaining references to `parrot.transport` in test files".
Removed `test_backward_compat_shim` method from `tests/core/hooks/test_imports.py`.
All tests pass: 116 transport tests + 53 hook/matrix/core tests = 169 total.

**Deviations from spec**: Updated `test_cli.py` and `test_transport.py` in addition to the listed 14 files
— both had stale transport imports and are necessary for the acceptance criteria to pass.
