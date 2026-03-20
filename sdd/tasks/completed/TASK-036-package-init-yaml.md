# TASK-036: Package Init & YAML Config Integration

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-033, TASK-034
**Assigned-to**: claude-session

---

## Context

This task finalizes the package by setting up clean public exports and integrating with `parrot.yaml` configuration loading. It also registers the `FilesystemHook` in the hook factory so it can be instantiated from YAML config.

Implements **Module 10** from the spec, plus the config loading decision from Open Question 7.1.

---

## Scope

- Create/finalize `parrot/transport/filesystem/__init__.py` with all public exports
- Create `parrot/transport/__init__.py` with `AbstractTransport` export
- Support loading `FilesystemTransportConfig` from `parrot.yaml` transport section
- Register `FilesystemHook` in the hook creation factory (if one exists) or document how to register
- Add optional dependencies to `pyproject.toml` (`filesystem-transport` and `filesystem-transport-full` extras)
- Add `parrot-fs` script entry point
- Write import verification tests

**NOT in scope**: Implementation of modules (all done in prior tasks)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/__init__.py` | CREATE/MODIFY | Export `AbstractTransport` |
| `parrot/transport/filesystem/__init__.py` | MODIFY | Final public exports |
| `pyproject.toml` | MODIFY | Add optional dependency groups + script entry |
| `tests/transport/filesystem/test_imports.py` | CREATE | Import verification tests |

---

## Implementation Notes

### Public Exports
```python
# parrot/transport/filesystem/__init__.py
from .config import FilesystemTransportConfig
from .transport import FilesystemTransport
from .hook import FilesystemHook

__all__ = [
    "FilesystemTransport",
    "FilesystemTransportConfig",
    "FilesystemHook",
]
```

### pyproject.toml additions
```toml
[project.optional-dependencies]
filesystem-transport = ["aiofiles>=23.0"]
filesystem-transport-full = [
    "aiofiles>=23.0",
    "watchdog>=4.0",
    "rich>=13.0",
    "click>=8.0",
]

[project.scripts]
parrot-fs = "parrot.transport.filesystem.cli:main"
```

### Key Constraints
- Imports must work without optional dependencies (watchdog, rich, click)
- `FilesystemHookConfig` should be importable from `parrot.autonomous.hooks.models`
- All public classes must be importable from `parrot.transport.filesystem`

---

## Acceptance Criteria

- [ ] `from parrot.transport.filesystem import FilesystemTransport` works
- [ ] `from parrot.transport.filesystem import FilesystemTransportConfig` works
- [ ] `from parrot.transport.filesystem import FilesystemHook` works
- [ ] `from parrot.transport.base import AbstractTransport` works
- [ ] Optional deps in `pyproject.toml` are correct
- [ ] `parrot-fs` script entry point configured
- [ ] Tests pass: `pytest tests/transport/filesystem/test_imports.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_imports.py

class TestImports:
    def test_transport_import(self):
        from parrot.transport.filesystem import FilesystemTransport
        assert FilesystemTransport is not None

    def test_config_import(self):
        from parrot.transport.filesystem import FilesystemTransportConfig
        assert FilesystemTransportConfig is not None

    def test_hook_import(self):
        from parrot.transport.filesystem import FilesystemHook
        assert FilesystemHook is not None

    def test_abstract_transport_import(self):
        from parrot.transport.base import AbstractTransport
        assert AbstractTransport is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-033 and TASK-034 are completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-036-package-init-yaml.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Updated `parrot/transport/filesystem/__init__.py` to export FilesystemHook alongside FilesystemTransport and FilesystemTransportConfig. Updated `parrot/transport/__init__.py` to export AbstractTransport. Added `filesystem-transport` and `filesystem-transport-full` optional dependency groups to pyproject.toml. Added `parrot-fs` script entry point. Created 8 import verification tests — all passing.

**Deviations from spec**: Added extra tests beyond the spec's 4 (abstract transport from package, hook config from models, __all__ verification, subclass check) for more thorough coverage.
