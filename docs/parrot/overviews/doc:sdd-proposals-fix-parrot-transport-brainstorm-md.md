---
type: Wiki Overview
title: 'Brainstorm: fix-parrot-transport'
id: doc:sdd-proposals-fix-parrot-transport-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The `parrot/transport` package is broken because the hooks system was migrated
  from
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.autonomous
  rel: mentions
- concept: mod:parrot.autonomous.transport
  rel: mentions
- concept: mod:parrot.core.hooks
  rel: mentions
- concept: mod:parrot.core.hooks.base
  rel: mentions
- concept: mod:parrot.core.hooks.manager
  rel: mentions
- concept: mod:parrot.core.hooks.models
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Brainstorm: fix-parrot-transport

**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

The `parrot/transport` package is broken because the hooks system was migrated from
`parrot.autonomous.hooks.*` to `parrot.core.hooks.*`, but the backward-compatibility
shims were only partially implemented. Specifically:

1. **Missing module-level shims**: The `parrot/autonomous/hooks/__init__.py` re-exports
   via `from parrot.core.hooks import *`, but submodule imports like
   `from parrot.autonomous.hooks.base import BaseHook` fail because `base.py`,
   `models.py`, etc. were never created as shim files.

2. **Broken production code**: `parrot/transport/filesystem/hook.py` lines 8-9 import
   from `parrot.autonomous.hooks.base` and `parrot.autonomous.hooks.models` — both fail.

3. **`FilesystemHookConfig` not exported**: Defined in `parrot.core.hooks.models` (line 301)
   but missing from `core/hooks/__init__.py`'s `__all__` list.

4. **Package placement**: `parrot/transport/` is only used by `parrot/autonomous` and its
   tests. It should be consolidated under `parrot/autonomous/transport/`.

5. **8 test files broken**: All test files importing from `parrot.autonomous.hooks.*`
   submodules fail.

## Constraints & Requirements

- Clean break: no backward-compat shims at old import paths
- All existing tests must pass after migration
- MCP transports (`parrot/mcp/transports/`) are out of scope — they are independent and working
- Must not break `parrot.core.hooks` or the hooks manager system
- All imports should point directly to `parrot.core.hooks.*` (no indirection)

---

## Options Explored

### Option A: Move transport/ into autonomous/ + fix all imports directly

Move the entire `parrot/transport/` package into `parrot/autonomous/transport/`,
update all imports in source and tests to use `parrot.core.hooks.*` directly,
remove the `parrot/autonomous/hooks/` backward-compat shims, and delete the
now-empty `parrot/transport/` package.

This is a one-shot cleanup that eliminates both the broken imports and the
architectural debt of having transport at the wrong level.

Pros:
- Eliminates all broken imports in one pass
- Correct package ownership (transport belongs to autonomous)
- No legacy shim code to maintain
- Clean import graph: everything points to canonical locations
- Removes the confusing `parrot/autonomous/hooks/` re-export layer

Cons:
- Larger diff (more files touched)
- All test imports change too (from `parrot.transport.*` to `parrot.autonomous.transport.*`)
- Any external consumer using `parrot.transport` gets ImportError (clean break)

Effort: Medium

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | Pure refactor | Only import path changes |

Existing Code to Reuse:
- `packages/ai-parrot/src/parrot/transport/` — move entirely to `packages/ai-parrot/src/parrot/autonomous/transport/`
- `packages/ai-parrot/src/parrot/core/hooks/base.py` — canonical `BaseHook` class
- `packages/ai-parrot/src/parrot/core/hooks/models.py` — canonical `FilesystemHookConfig`, `HookType`

---

### Option B: Fix imports in-place (no package move)

Keep `parrot/transport/` at its current top-level location. Only fix the broken
imports in `filesystem/hook.py` and all test files to point to `parrot.core.hooks.*`.
Remove the `parrot/autonomous/hooks/` shims. Leave the package structure as-is.

Pros:
- Smaller diff — fewer files changed
- No import path changes for transport consumers
- Lower risk of merge conflicts

Cons:
- `parrot/transport/` remains at top level despite only being used by `parrot/autonomous`
- Doesn't address the architectural concern
- Future confusion about where transport code belongs

Effort: Low

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | Import fixes only | |

Existing Code to Reuse:
- `packages/ai-parrot/src/parrot/transport/filesystem/hook.py` — fix imports in place
- `packages/ai-parrot/src/parrot/core/hooks/` — target for updated imports

---

### Option C: Move transport/ into autonomous/ + deprecation shims

Same as Option A (move + fix) but also leave a thin `parrot/transport/__init__.py`
shim that raises `DeprecationWarning` and re-exports from the new location. This
gives external consumers a migration window.

Pros:
- Graceful migration path
- Existing code gets warnings instead of hard failures
- Clean long-term destination

Cons:
- More complexity (shim code to write and eventually remove)
- Two import paths work simultaneously (confusing)
- Need a follow-up to remove the shim

Effort: Medium-High

Libraries / Tools:
| Package | Purpose | Notes |
|---|---|---|
| No new dependencies | Deprecation shim pattern | Standard `warnings.warn` |

Existing Code to Reuse:
- Same as Option A, plus a deprecation shim module

---

## Recommendation

**Option A** is recommended because:

- The transport package has **zero external consumers** outside `parrot/autonomous` and its
  test suite. There is no one to break with a clean break.
- Maintaining backward-compat shims adds complexity for no benefit — the existing
  shims are already broken, proving they're not being tested against.
- Moving transport into autonomous correctly represents the ownership model: transport
  is an implementation detail of the autonomous agent system.
- The medium effort is justified because the fix + move can be done atomically,
  and we avoid accumulating more debt.

---

## Feature Description

### User-Facing Behavior

No user-facing behavior change. This is an internal refactoring. After the fix:
- `from parrot.autonomous.transport import FilesystemTransport` works
- `from parrot.autonomous.transport import FilesystemHook` works
- `from parrot.autonomous.transport import AbstractTransport` works
- All existing tests pass

### Internal Behavior

1. **Package move**: `packages/ai-parrot/src/parrot/transport/` is moved to
   `packages/ai-parrot/src/parrot/autonomous/transport/`. The internal structure
   (base.py, filesystem/) is preserved.

2. **Import fix in hook.py**: Lines 8-9 change from:
   ```python
   from parrot.autonomous.hooks.base import BaseHook
   from parrot.autonomous.hooks.models import FilesystemHookConfig, HookType
   ```
   to:
   ```python
   from parrot.core.hooks.base import BaseHook
   from parrot.core.hooks.models import FilesystemHookConfig, HookType
   ```

3. **Shim removal**: Delete `packages/ai-parrot/src/parrot/autonomous/hooks/` entirely
   (the `__init__.py` and `brokers/` shim directory).

4. **Test updates**: All test files update their imports from `parrot.transport.*` to
   `parrot.autonomous.transport.*`, and from `parrot.autonomous.hooks.*` submodules
   to `parrot.core.hooks.*` directly.

5. **Old package cleanup**: Remove the now-empty `packages/ai-parrot/src/parrot/transport/`
   directory.

### Edge Cases & Error Handling

- **`parrot/transport/` at repo root**: The root-level `parrot/transport/` directory
  contains only `__pycache__` files — it is NOT the source. Only the `packages/ai-parrot/src/`
  copy matters. The root copy should be verified and cleaned if it's just bytecode artifacts.
- **`test_backward_compat_shim` test**: In `tests/core/hooks/test_imports.py:102-106`,
  there's a test that verifies `parrot.autonomous.hooks` re-exports work. This test
  must be removed since we're deleting the shims.
- **Circular imports**: Moving transport into autonomous could theoretically create
  circular imports if autonomous already imports transport. Verify: `autonomous/__init__.py`
  is empty, so no risk.

---

## Capabilities

### New Capabilities
- `autonomous-transport-consolidation`: Transport package moved under parrot/autonomous where it belongs

### Modified Capabilities
- `filesystem-transport`: Import paths change from `parrot.transport.*` to `parrot.autonomous.transport.*`
- `core-hooks-exports`: Fix missing `FilesystemHookConfig` accessibility (import directly from models)

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/transport/` | moves to | `parrot/autonomous/transport/` |
| `parrot/transport/filesystem/hook.py` | modifies | Fix imports to use `parrot.core.hooks.*` |
| `parrot/autonomous/hooks/` | deletes | Remove backward-compat shims entirely |
| `tests/transport/` | modifies | All imports updated to new paths |
| `tests/test_hooks.py` | modifies | Imports updated to `parrot.core.hooks.*` |
| `tests/test_matrix_hook.py` | modifies | Imports updated to `parrot.core.hooks.*` |
| `tests/core/hooks/test_imports.py` | modifies | Remove backward-compat shim test |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/transport/base.py:9
class AbstractTransport(ABC):
    async def start(self) -> None: ...                    # line 23
    async def stop(self) -> None: ...                     # line 28
    async def send(self, to: str, content: str, ...) -> str: ...  # line 33
    async def broadcast(self, content: str, ...) -> None: ...     # line 56
    async def messages(self) -> AsyncGenerator[Dict[str, Any], None]: ...  # line 72
    async def list_agents(self) -> List[Dict[str, Any]]: ...      # line 81
    async def reserve(self, paths: List[str], ...) -> bool: ...   # line 89
    async def release(self, paths: Optional[List[str]] = None) -> None: ...  # line 107
    async def set_status(self, status: str, ...) -> None: ...     # line 118

# From packages/ai-parrot/src/parrot/transport/filesystem/hook.py:15
class FilesystemHook(BaseHook):
    hook_type = HookType.FILESYSTEM                       # line 29
    def __init__(self, config: FilesystemHookConfig, **kwargs: Any) -> None:  # line 31
    async def start(self) -> None: ...                    # line 49
    async def stop(self) -> None: ...                     # line 65

# From packages/ai-parrot/src/parrot/core/hooks/base.py:12
class BaseHook(ABC):
    hook_type: HookType = HookType.SCHEDULER              # line 23
    def __init__(self, *, name: str = "", ...) -> None:   # line 25

# From packages/ai-parrot/src/parrot/core/hooks/models.py:301
class FilesystemHookConfig(BaseModel):
    name: str = "filesystem_hook"                         # line 305
    enabled: bool = True                                  # line 306
    target_type: Optional[str] = "agent"                  # line 307
    target_id: Optional[str] = None                       # line 308
    metadata: Dict[str, Any] = Field(default_factory=dict)  # line 309
    transport: Dict[str, Any] = Field(default_factory=dict) # line 312
    command_prefix: str = ""                              # line 315
    allowed_agents: Optional[List[str]] = None            # line 316
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.core.hooks.base import BaseHook          # parrot/core/hooks/base.py:12
from parrot.core.hooks.models import HookType        # parrot/core/hooks/models.py (exported in __all__)
from parrot.core.hooks.models import FilesystemHookConfig  # parrot/core/hooks/models.py:301 (NOT in __all__ but importable directly)
from parrot.core.hooks.manager import HookManager    # parrot/core/hooks/manager.py
from parrot.core.hooks.models import HookEvent       # parrot/core/hooks/models.py (exported in __all__)
```

#### Key Attributes & Constants
- `HookType.FILESYSTEM` → `str` ("filesystem") — `parrot/core/hooks/models.py`
- `FilesystemHookConfig.transport` → `Dict[str, Any]` — `parrot/core/hooks/models.py:312`
- `BaseHook.hook_type` → `HookType` — `parrot/core/hooks/base.py:23`

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.autonomous.hooks.base`~~ — module file does not exist (only `__init__.py` shim at package level)
- ~~`parrot.autonomous.hooks.models`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.manager`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.scheduler`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.file_watchdog`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.matrix`~~ — module file does not exist
- ~~`FilesystemHookConfig` in `core/hooks/__init__.py.__all__`~~ — it is NOT in the `__all__` list (must import from `models` directly)
- ~~`parrot/autonomous/__init__.py` has imports~~ — file is empty (1 line, no content)

---

## Parallelism Assessment

- **Internal parallelism**: Limited. The package move, import fixes, and shim removal are tightly coupled — changing import paths in source requires matching changes in tests. Sequential execution in one worktree is safest.
- **Cross-feature independence**: No known in-flight specs touch `parrot/transport/` or `parrot/autonomous/hooks/`. Low conflict risk.
- **Recommended isolation**: per-spec
- **Rationale**: All tasks share the same files (transport source and tests). Moving a package and updating imports is inherently sequential — you can't fix tests for new paths before the move completes. A single worktree with sequential task execution is the right model.

---

## Open Questions

- [x] Is `parrot/transport/` used outside `parrot/autonomous`? — *Owner: Claude*: No. Only the filesystem transport tests and `parrot/autonomous`-related test files import from it. MCP transports are a separate package at `parrot/mcp/transports/`.
- [x] Should we keep backward-compat shims? — *Owner: Jesus*: No. Clean break — remove all shims.
- [x] Should `FilesystemHookConfig` be added to `core/hooks/__init__.py.__all__`? — *Owner: Jesus*: No. Import directly from `parrot.core.hooks.models`.
- [ ] Should the root-level `parrot/transport/` directory (containing only `__pycache__`) be cleaned up? — *Owner: Jesus*
- [ ] Are there any runtime/CLI entry points referencing `parrot.transport` paths (e.g., console_scripts, plugin registries)? — *Owner: implementer*
