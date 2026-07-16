---
type: Wiki Overview
title: 'Feature Specification: Fix Parrot Transport'
id: doc:sdd-specs-fix-parrot-transport-spec-md
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
- concept: mod:parrot.autonomous.transport.base
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem
  rel: mentions
- concept: mod:parrot.autonomous.transport.filesystem.cli
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

---
type: feature
base_branch: dev
---

# Feature Specification: Fix Parrot Transport

**Feature ID**: FEAT-196
**Date**: 2026-05-28
**Author**: Jesus Lara
**Status**: approved
**Target version**: next

---

## 1. Motivation & Business Requirements

### Problem Statement

The `parrot/transport` package is broken because the hooks system was migrated from
`parrot.autonomous.hooks.*` to `parrot.core.hooks.*`, but backward-compatibility
shims were only partially implemented:

1. **Missing module-level shims**: `parrot/autonomous/hooks/__init__.py` re-exports via
   `from parrot.core.hooks import *`, but submodule imports like
   `from parrot.autonomous.hooks.base import BaseHook` fail because `base.py`, `models.py`,
   etc. were never created as shim files.

2. **Broken production code**: `parrot/transport/filesystem/hook.py` lines 8-9 import from
   `parrot.autonomous.hooks.base` and `parrot.autonomous.hooks.models` — both fail at runtime.

3. **Package misplacement**: `parrot/transport/` is only consumed by `parrot/autonomous` and
   its test suite, yet lives as a top-level package. It belongs under `parrot/autonomous/`.

4. **Console script affected**: The `parrot-fs` entry point in `pyproject.toml:103`
   references `parrot.transport.filesystem.cli:main` — must be updated after the move.

5. **8 test files broken**: All test files importing from `parrot.autonomous.hooks.*`
   submodules fail.

### Goals

- Fix all broken imports so `FilesystemTransport`, `FilesystemHook`, and the `parrot-fs`
  CLI work again
- Move `parrot/transport/` into `parrot/autonomous/transport/` to reflect correct ownership
- Remove the incomplete `parrot/autonomous/hooks/` backward-compat shim directory
- Update all test files to use canonical import paths
- Clean up stale root-level `parrot/transport/` bytecode directory

### Non-Goals (explicitly out of scope)

- MCP transports (`parrot/mcp/transports/`) — independent and working, not touched
- Adding `FilesystemHookConfig` to `core/hooks/__init__.py.__all__` — import directly
  from `parrot.core.hooks.models` instead (resolved in brainstorm)
- Creating any backward-compat shims or deprecation warnings at the old `parrot.transport`
  path (clean break — resolved in brainstorm)
- Modifying `parrot.core.hooks` internals

---

## 2. Architectural Design

### Overview

This is a pure refactoring with zero behavior changes. The approach (brainstorm Option A):

1. **Move** `packages/ai-parrot/src/parrot/transport/` →
   `packages/ai-parrot/src/parrot/autonomous/transport/`. Internal structure preserved.
2. **Fix** `filesystem/hook.py` imports to point to `parrot.core.hooks.*` directly.
3. **Delete** `parrot/autonomous/hooks/` shim directory (and `brokers/` subdirectory).
4. **Update** `pyproject.toml` console script `parrot-fs` entry point.
5. **Update** all test imports to new paths.
6. **Delete** root-level `parrot/transport/` (bytecode-only, no source).

After the refactoring, the import paths are:
```python
from parrot.autonomous.transport import AbstractTransport
from parrot.autonomous.transport import FilesystemTransport
from parrot.autonomous.transport import FilesystemHook
from parrot.core.hooks.base import BaseHook
from parrot.core.hooks.models import FilesystemHookConfig, HookType
```

### Component Diagram

```
BEFORE:                                  AFTER:

parrot/                                  parrot/
├── transport/         ← TOP LEVEL       ├── autonomous/
│   ├── base.py                          │   ├── transport/         ← MOVED HERE
│   └── filesystem/                      │   │   ├── base.py
│       ├── hook.py  ← BROKEN            │   │   └── filesystem/
│       └── ...                          │   │       ├── hook.py   ← FIXED
├── autonomous/                          │   │       └── ...
│   └── hooks/       ← STALE SHIMS      │   └── (hooks/ DELETED)
└── core/                                └── core/
    └── hooks/       ← CANONICAL             └── hooks/            ← CANONICAL
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.core.hooks.base.BaseHook` | depends on | `FilesystemHook` inherits from `BaseHook` |
| `parrot.core.hooks.models.FilesystemHookConfig` | depends on | Config model for `FilesystemHook` |
| `parrot.core.hooks.models.HookType` | depends on | Enum used by `FilesystemHook.hook_type` |
| `pyproject.toml` console_scripts | modifies | `parrot-fs` entry point path changes |
| `parrot.autonomous.__init__` | unchanged | Currently empty — no circular import risk |

### Data Models

No new data models. `FilesystemHookConfig` already exists in `parrot.core.hooks.models`
(line 301) and is unchanged.

### New Public Interfaces

No new interfaces. The existing `AbstractTransport`, `FilesystemTransport`,
`FilesystemHook`, `FilesystemTransportConfig` are all preserved — only their
import paths change.

New canonical imports after move:
```python
from parrot.autonomous.transport import AbstractTransport
from parrot.autonomous.transport.filesystem import FilesystemTransport
from parrot.autonomous.transport.filesystem import FilesystemHook
from parrot.autonomous.transport.filesystem import FilesystemTransportConfig
from parrot.autonomous.transport.filesystem.cli import main  # parrot-fs CLI
```

---

## 3. Module Breakdown

### Module 1: Package Move

- **Path**: `packages/ai-parrot/src/parrot/autonomous/transport/` (new location)
- **Responsibility**: Move the entire `parrot/transport/` tree into `parrot/autonomous/transport/`,
  preserving all files and internal structure. Update `parrot/autonomous/transport/__init__.py`
  to export `AbstractTransport`.
- **Depends on**: none

### Module 2: Fix Hook Imports

- **Path**: `packages/ai-parrot/src/parrot/autonomous/transport/filesystem/hook.py` (after move)
- **Responsibility**: Change lines 8-9 from broken `parrot.autonomous.hooks.*` imports to
  canonical `parrot.core.hooks.*` imports:
  - `from parrot.core.hooks.base import BaseHook`
  - `from parrot.core.hooks.models import FilesystemHookConfig, HookType`
- **Depends on**: Module 1

### Module 3: Remove Shims & Update Entry Points

- **Path**: `packages/ai-parrot/src/parrot/autonomous/hooks/` (delete),
  `packages/ai-parrot/pyproject.toml` (modify line 103)
- **Responsibility**:
  - Delete `parrot/autonomous/hooks/__init__.py` and `parrot/autonomous/hooks/brokers/__init__.py`
    (the entire `hooks/` shim directory)
  - Update `pyproject.toml` line 103: `parrot-fs = "parrot.autonomous.transport.filesystem.cli:main"`
  - Delete root-level `parrot/transport/` directory (bytecode only)
  - Remove old `packages/ai-parrot/src/parrot/transport/` directory after move
- **Depends on**: Module 1

### Module 4: Update All Test Imports

- **Path**: `packages/ai-parrot/tests/transport/` and related test files
- **Responsibility**: Update every import in test files:
  - `parrot.transport.*` → `parrot.autonomous.transport.*` (all transport test files)
  - `parrot.autonomous.hooks.base` → `parrot.core.hooks.base` (test_hooks.py, test_matrix_hook.py, etc.)
  - `parrot.autonomous.hooks.models` → `parrot.core.hooks.models`
  - `parrot.autonomous.hooks.manager` → `parrot.core.hooks.manager`
  - `parrot.autonomous.hooks.scheduler` → `parrot.core.hooks.scheduler`
  - `parrot.autonomous.hooks.file_watchdog` → `parrot.core.hooks.file_watchdog`
  - `parrot.autonomous.hooks.matrix` → `parrot.core.hooks.matrix`
  - Remove or update `test_backward_compat_shim` in `tests/core/hooks/test_imports.py:102-106`
- **Depends on**: Module 1, Module 2, Module 3

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_transport_import` | Module 1 | `from parrot.autonomous.transport.filesystem import FilesystemTransport` works |
| `test_config_import` | Module 1 | `from parrot.autonomous.transport.filesystem import FilesystemTransportConfig` works |
| `test_hook_import` | Module 2 | `from parrot.autonomous.transport.filesystem import FilesystemHook` works |
| `test_abstract_transport_import` | Module 1 | `from parrot.autonomous.transport.base import AbstractTransport` works |
| `test_hook_config_from_models` | Module 2 | `from parrot.core.hooks.models import FilesystemHookConfig` works |
| `test_hook_type` | Module 2 | `FilesystemHook.hook_type == HookType.FILESYSTEM` |
| `test_old_import_fails` | Module 3 | `from parrot.transport import AbstractTransport` raises `ImportError` |

### Integration Tests

| Test | Description |
|---|---|
| `test_hook_start_stop` | `FilesystemHook` starts/stops transport correctly (existing test, updated imports) |
| `test_dispatch_emits_event` | Messages dispatched through `FilesystemHook` produce `HookEvent` instances |
| `test_bidirectional_exchange` | Two agents exchange messages via `FilesystemTransport` |
| `test_parrot_fs_cli` | `parrot-fs` console script resolves to new module path |

### Test Data / Fixtures

Existing test fixtures remain unchanged — they use `tmp_path` for filesystem transport
root directories. No new fixtures needed.

---

## 5. Acceptance Criteria

- [ ] `from parrot.autonomous.transport import AbstractTransport` works
- [ ] `from parrot.autonomous.transport.filesystem import FilesystemTransport` works
- [ ] `from parrot.autonomous.transport.filesystem import FilesystemHook` works
- [ ] `from parrot.autonomous.transport.filesystem import FilesystemTransportConfig` works
- [ ] `from parrot.core.hooks.base import BaseHook` works (already works — regression check)
- [ ] `from parrot.core.hooks.models import FilesystemHookConfig` works (already works — regression check)
- [ ] `from parrot.transport import AbstractTransport` raises `ImportError` (clean break)
- [ ] `parrot-fs` console script entry point references `parrot.autonomous.transport.filesystem.cli:main`
- [ ] `python -m parrot.autonomous.transport.filesystem` works as entry point
- [ ] `parrot/autonomous/hooks/` directory does not exist (shims removed)
- [ ] Root-level `parrot/transport/` directory does not exist (bytecode cleaned)
- [ ] All transport tests pass: `pytest packages/ai-parrot/tests/transport/ -v`
- [ ] All hook tests pass: `pytest packages/ai-parrot/tests/test_hooks.py packages/ai-parrot/tests/test_matrix_hook.py -v`
- [ ] Core hook import tests pass: `pytest packages/ai-parrot/tests/core/hooks/test_imports.py -v`
- [ ] No breaking changes to `parrot.core.hooks` public API
- [ ] MCP transports unaffected — no files under `parrot/mcp/transports/` modified

---

## 6. Codebase Contract

### Verified Imports

```python
# Canonical hook imports (confirmed working — use these in all fixed code):
from parrot.core.hooks.base import BaseHook              # packages/ai-parrot/src/parrot/core/hooks/base.py:12
from parrot.core.hooks.models import HookType            # packages/ai-parrot/src/parrot/core/hooks/models.py (in __all__)
from parrot.core.hooks.models import FilesystemHookConfig  # packages/ai-parrot/src/parrot/core/hooks/models.py:301 (NOT in __all__, import from models directly)
from parrot.core.hooks.models import HookEvent           # packages/ai-parrot/src/parrot/core/hooks/models.py (in __all__)
from parrot.core.hooks.manager import HookManager        # packages/ai-parrot/src/parrot/core/hooks/manager.py
from parrot.core.hooks.models import SchedulerHookConfig  # in __all__
from parrot.core.hooks.models import FileWatchdogHookConfig  # in __all__
from parrot.core.hooks.models import MatrixHookConfig    # in __all__
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/transport/base.py
class AbstractTransport(ABC):                                           # line 9
    async def start(self) -> None: ...                                  # line 23
    async def stop(self) -> None: ...                                   # line 28
    async def send(self, to: str, content: str,
                   msg_type: str = "message",
                   payload: Optional[Dict[str, Any]] = None,
                   reply_to: Optional[str] = None) -> str: ...          # line 33
    async def broadcast(self, content: str,
                        channel: str = "general",
                        payload: Optional[Dict[str, Any]] = None) -> None: ...  # line 56
    async def messages(self) -> AsyncGenerator[Dict[str, Any], None]: ...  # line 72
    async def list_agents(self) -> List[Dict[str, Any]]: ...            # line 81
    async def reserve(self, paths: List[str], reason: str = "") -> bool: ...  # line 89
    async def release(self, paths: Optional[List[str]] = None) -> None: ...  # line 107
    async def set_status(self, status: str, message: str = "") -> None: ...  # line 118

# packages/ai-parrot/src/parrot/transport/filesystem/hook.py
class FilesystemHook(BaseHook):                                         # line 15
    hook_type = HookType.FILESYSTEM                                     # line 29
    def __init__(self, config: FilesystemHookConfig, **kwargs: Any): ...  # line 31
    async def start(self) -> None: ...                                  # line 49
    async def stop(self) -> None: ...                                   # line 65

# packages/ai-parrot/src/parrot/core/hooks/base.py
class BaseHook(ABC):                                                    # line 12
    hook_type: HookType = HookType.SCHEDULER                            # line 23
    def __init__(self, *, name: str = "", hook_id: Optional[str] = None,
                 enabled: bool = True, target_type: Optional[str] = None,
                 target_id: Optional[str] = None,
                 metadata: Optional[dict] = None): ...                  # line 25

# packages/ai-parrot/src/parrot/core/hooks/models.py
class FilesystemHookConfig(BaseModel):                                  # line 301
    name: str = "filesystem_hook"                                       # line 305
    enabled: bool = True                                                # line 306
    target_type: Optional[str] = "agent"                                # line 307
    target_id: Optional[str] = None                                     # line 308
    metadata: Dict[str, Any] = Field(default_factory=dict)              # line 309
    transport: Dict[str, Any] = Field(default_factory=dict)             # line 312
    command_prefix: str = ""                                            # line 315
    allowed_agents: Optional[List[str]] = None                          # line 316
```

### Files to Move (complete manifest)

Source: `packages/ai-parrot/src/parrot/transport/`
Target: `packages/ai-parrot/src/parrot/autonomous/transport/`

```
transport/__init__.py           → autonomous/transport/__init__.py
transport/base.py               → autonomous/transport/base.py
transport/filesystem/__init__.py → autonomous/transport/filesystem/__init__.py
transport/filesystem/base.py    → autonomous/transport/filesystem/base.py
transport/filesystem/channel.py → autonomous/transport/filesystem/channel.py
transport/filesystem/cli.py     → autonomous/transport/filesystem/cli.py
transport/filesystem/config.py  → autonomous/transport/filesystem/config.py
transport/filesystem/feed.py    → autonomous/transport/filesystem/feed.py
transport/filesystem/hook.py    → autonomous/transport/filesystem/hook.py
transport/filesystem/inbox.py   → autonomous/transport/filesystem/inbox.py
transport/filesystem/__main__.py → autonomous/transport/filesystem/__main__.py
transport/filesystem/registry.py → autonomous/transport/filesystem/registry.py
transport/filesystem/reservation.py → autonomous/transport/filesystem/reservation.py
transport/filesystem/transport.py → autonomous/transport/filesystem/transport.py
```

### Files to Delete

```
packages/ai-parrot/src/parrot/autonomous/hooks/__init__.py
packages/ai-parrot/src/parrot/autonomous/hooks/brokers/__init__.py
packages/ai-parrot/src/parrot/autonomous/hooks/brokers/   (directory)
packages/ai-parrot/src/parrot/autonomous/hooks/           (directory)
packages/ai-parrot/src/parrot/transport/                  (entire directory after move)
parrot/transport/                                         (root-level bytecode directory)
```

### Files to Modify (import updates)

Source files:
- `autonomous/transport/filesystem/hook.py` — lines 8-9

Config files:
- `packages/ai-parrot/pyproject.toml` — line 103

Test files (transport imports `parrot.transport.*` → `parrot.autonomous.transport.*`):
- `tests/transport/test_abstract_transport.py` — lines 5, 120
- `tests/transport/filesystem/test_imports.py` — lines 7, 13, 19, 25, 31, 37, 43, 51, 52
- `tests/transport/filesystem/conftest.py` — lines 5, 6
- `tests/transport/filesystem/test_channel.py` — lines 7, 8
- `tests/transport/filesystem/test_registry.py` — lines 7, 8
- `tests/transport/filesystem/test_config.py` — lines 6, 66
- `tests/transport/filesystem/test_feed.py` — lines 7, 8
- `tests/transport/filesystem/test_inbox.py` — lines 7, 8
- `tests/transport/filesystem/test_reservation.py` — line 7
- `tests/transport/filesystem/test_integration.py` — lines 8, 9, 10, 11, 199, 235
- `tests/transport/filesystem/test_hook.py` — lines 8, 9, 10

Test files (hook imports `parrot.autonomous.hooks.*` → `parrot.core.hooks.*`):
- `tests/test_hooks.py` — lines 9, 10, 11-16, 17, 18
- `tests/test_matrix_hook.py` — lines 8, 9-13, 137, 307, 311
- `tests/transport/filesystem/test_imports.py` — line 37
- `tests/transport/filesystem/test_hook.py` — lines 8, 186
- `tests/transport/filesystem/test_integration.py` — line 8
- `tests/core/hooks/test_imports.py` — lines 102-106 (remove backward-compat test)

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.autonomous.hooks.base`~~ — module file does not exist (only package-level `__init__.py` shim)
- ~~`parrot.autonomous.hooks.models`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.manager`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.scheduler`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.file_watchdog`~~ — module file does not exist
- ~~`parrot.autonomous.hooks.matrix`~~ — module file does not exist
- ~~`FilesystemHookConfig` in `core/hooks/__init__.py.__all__`~~ — NOT in `__all__`; must import from `parrot.core.hooks.models` directly
- ~~`parrot/autonomous/__init__.py` has imports~~ — file is empty (no circular import risk)
- ~~`parrot.autonomous.transport`~~ — does NOT exist yet (will be created by this spec)

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Use `git mv`** for the package move to preserve history
- All internal imports within the filesystem transport use relative paths (`.config`, `.feed`,
  `.transport`, etc.) — these do NOT need updating after the move
- `FilesystemHookConfig` must be imported from `parrot.core.hooks.models` (not the package
  `__init__`) because it's not in `__all__`
- The `__main__.py` uses only relative imports (`from .cli import main`) — no change needed
  to file contents, only the module path for `python -m` invocation changes

### Known Risks / Gotchas

- **Root-level `parrot/transport/` stale bytecode**: Contains `.pyc` files from old builds.
  If not cleaned, Python could resolve the old path from bytecode cache. Delete the directory.
- **`test_backward_compat_shim` test**: In `tests/core/hooks/test_imports.py:102-106`, this
  test verifies `parrot.autonomous.hooks` re-exports work. It must be removed since we're
  deleting the shims — otherwise it becomes a guaranteed test failure.
- **`parrot.autonomous.__init__.py` is empty**: No risk of circular imports from moving
  transport into autonomous. Verified.
- **`python -m parrot.transport.filesystem`**: After the move, the correct invocation becomes
  `python -m parrot.autonomous.transport.filesystem`. The `__main__.py` contents don't change.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| No new dependencies | — | Pure refactor — only import paths change |

---

## Worktree Strategy

- **Isolation**: `per-spec` — all tasks run sequentially in one worktree
- **Rationale**: The package move (Module 1) must complete before import fixes (Modules 2-4)
  can be applied. All tasks touch overlapping files. Sequential execution is the only safe model.
- **Cross-feature dependencies**: None — no in-flight specs touch `parrot/transport/` or
  `parrot/autonomous/hooks/`

---

## 8. Open Questions

- [x] Is `parrot/transport/` used outside `parrot/autonomous`? — *Resolved in brainstorm*: No. Only filesystem transport tests and `parrot/autonomous`-related test files import from it. MCP transports are a separate package at `parrot/mcp/transports/`.
- [x] Should we keep backward-compat shims? — *Resolved in brainstorm*: No. Clean break — remove all shims.
- [x] Should `FilesystemHookConfig` be added to `core/hooks/__init__.py.__all__`? — *Resolved in brainstorm*: No. Import directly from `parrot.core.hooks.models`.
- [x] Should the root-level `parrot/transport/` directory be cleaned up? — *Resolved in spec*: Yes. It contains only `__pycache__` bytecode — delete it.
- [x] Are there runtime/CLI entry points referencing `parrot.transport` paths? — *Resolved in spec*: Yes. `pyproject.toml:103` has `parrot-fs = "parrot.transport.filesystem.cli:main"` — must be updated. Also `__main__.py` for `python -m` invocation.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-28 | Jesus Lara | Initial draft from brainstorm |
