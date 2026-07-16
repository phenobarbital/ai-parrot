---
type: Wiki Overview
title: 'TASK-1334: Fix broken hook imports in filesystem/hook.py'
id: doc:sdd-tasks-completed-task-1334-fix-hook-imports-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: After the package move (TASK-1333), `filesystem/hook.py` still has broken
  imports
relates_to:
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.hook
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

# TASK-1334: Fix broken hook imports in filesystem/hook.py

**Feature**: FEAT-196 — Fix Parrot Transport
**Spec**: `sdd/specs/fix-parrot-transport.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1333
**Assigned-to**: unassigned

---

## Context

After the package move (TASK-1333), `filesystem/hook.py` still has broken imports
pointing to `parrot.autonomous.hooks.base` and `parrot.autonomous.hooks.models` — module
files that never existed (only the package-level `__init__.py` shim was created).
This task fixes those imports to point to the canonical `parrot.core.hooks.*` locations.

Implements: Spec Module 2 (Fix Hook Imports).

---

## Scope

- Update `packages/ai-parrot/src/parrot/autonomous/transport/filesystem/hook.py` lines 8-9:
  - `from parrot.autonomous.hooks.base import BaseHook` → `from parrot.core.hooks.base import BaseHook`
  - `from parrot.autonomous.hooks.models import FilesystemHookConfig, HookType` → `from parrot.core.hooks.models import FilesystemHookConfig, HookType`

**NOT in scope**:
- Moving the transport package (TASK-1333, already done)
- Deleting shims or updating pyproject.toml (TASK-1335)
- Updating test imports (TASK-1336)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/autonomous/transport/filesystem/hook.py` | MODIFY | Fix lines 8-9 import paths |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# CORRECT — use these exact imports:
from parrot.core.hooks.base import BaseHook              # packages/ai-parrot/src/parrot/core/hooks/base.py:12
from parrot.core.hooks.models import FilesystemHookConfig  # packages/ai-parrot/src/parrot/core/hooks/models.py:301
from parrot.core.hooks.models import HookType            # packages/ai-parrot/src/parrot/core/hooks/models.py (in __all__)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/core/hooks/base.py:12
class BaseHook(ABC):
    hook_type: HookType = HookType.SCHEDULER              # line 23
    def __init__(self, *, name: str = "", hook_id: Optional[str] = None,
                 enabled: bool = True, target_type: Optional[str] = None,
                 target_id: Optional[str] = None,
                 metadata: Optional[dict] = None): ...    # line 25

# packages/ai-parrot/src/parrot/core/hooks/models.py:301
class FilesystemHookConfig(BaseModel):
    name: str = "filesystem_hook"                         # line 305
    enabled: bool = True                                  # line 306
    target_type: Optional[str] = "agent"                  # line 307
    target_id: Optional[str] = None                       # line 308
    transport: Dict[str, Any] = Field(default_factory=dict) # line 312
    command_prefix: str = ""                              # line 315
    allowed_agents: Optional[List[str]] = None            # line 316
```

### Does NOT Exist
- ~~`parrot.autonomous.hooks.base`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.models`~~ — module file does not exist
- ~~`FilesystemHookConfig` in `core/hooks/__init__.py.__all__`~~ — NOT in `__all__`; must import from `parrot.core.hooks.models` directly

---

## Implementation Notes

### Exact Change
```python
# BEFORE (hook.py lines 8-9):
from parrot.autonomous.hooks.base import BaseHook
from parrot.autonomous.hooks.models import FilesystemHookConfig, HookType

# AFTER:
from parrot.core.hooks.base import BaseHook
from parrot.core.hooks.models import FilesystemHookConfig, HookType
```

### Key Constraints
- Only 2 lines change in 1 file
- The rest of hook.py uses relative imports (`.config`, `.transport`) — no changes needed
- Do NOT import `FilesystemHookConfig` from `parrot.core.hooks` (the package `__init__`) —
  it's not in `__all__`. Import from `parrot.core.hooks.models` explicitly.

---

## Acceptance Criteria

- [ ] `hook.py` imports `BaseHook` from `parrot.core.hooks.base`
- [ ] `hook.py` imports `FilesystemHookConfig, HookType` from `parrot.core.hooks.models`
- [ ] `from parrot.autonomous.transport.filesystem.hook import FilesystemHook` does not raise ImportError
- [ ] `FilesystemHook.hook_type == HookType.FILESYSTEM` still holds

---

## Test Specification

```python
# Verify the import chain works end-to-end:
def test_hook_import_chain():
    from parrot.autonomous.transport.filesystem.hook import FilesystemHook
    from parrot.core.hooks.base import BaseHook
    from parrot.core.hooks.models import HookType
    assert issubclass(FilesystemHook, BaseHook)
    assert FilesystemHook.hook_type == HookType.FILESYSTEM
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/fix-parrot-transport.spec.md` for full context
2. **Check dependencies** — TASK-1333 must be completed (transport moved)
3. **Verify the Codebase Contract** — confirm `parrot.core.hooks.base.BaseHook` and `parrot.core.hooks.models.FilesystemHookConfig` still exist at the stated line numbers
4. **Update status** in per-spec index → `"in-progress"`
5. **Implement** the 2-line import change
6. **Verify** by running `python -c "from parrot.autonomous.transport.filesystem.hook import FilesystemHook"`
7. **Move this file** to `sdd/tasks/completed/TASK-1334-fix-hook-imports.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-28
**Notes**: Changed exactly 2 lines in hook.py (lines 8-9):
- `from parrot.autonomous.hooks.base import BaseHook` -> `from parrot.core.hooks.base import BaseHook`
- `from parrot.autonomous.hooks.models import FilesystemHookConfig, HookType` -> `from parrot.core.hooks.models import FilesystemHookConfig, HookType`
All other file content unchanged.

**Deviations from spec**: none
