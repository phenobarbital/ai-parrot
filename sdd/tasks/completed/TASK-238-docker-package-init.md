# TASK-238: Docker Package Init & Registry

**Feature**: Docker Toolkit (FEAT-033)
**Spec**: `sdd/specs/docker-toolkit.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-237
**Assigned-to**: claude-opus-4-6

---

## Context

> Package initialization, exports, and toolkit registry registration.
> Implements spec Section 3 — Module 6.

---

## Scope

- Update `parrot/tools/docker/__init__.py` with public exports.
- Export: `DockerToolkit`, `DockerConfig`, `DockerExecutor`, `ComposeGenerator`.
- Register `DockerToolkit` with the toolkit registry.

**NOT in scope**: Implementation of any classes (done in prior tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/docker/__init__.py` | MODIFY | Public exports and registry registration |

---

## Implementation Notes

### Pattern to Follow
```python
"""Docker Toolkit — manage containers and compose stacks."""
from .config import DockerConfig
from .executor import DockerExecutor
from .compose import ComposeGenerator
from .toolkit import DockerToolkit

__all__ = [
    "DockerConfig",
    "DockerExecutor",
    "ComposeGenerator",
    "DockerToolkit",
]
```

### Key Constraints
- Follow the same export pattern as `parrot/tools/pulumi/__init__.py`.
- Register with toolkit registry if the project uses one.

### References in Codebase
- `parrot/tools/pulumi/__init__.py` — export pattern
- `parrot/tools/registry.py` — toolkit registry

---

## Acceptance Criteria

- [ ] `from parrot.tools.docker import DockerToolkit` works
- [ ] `from parrot.tools.docker import DockerConfig` works
- [ ] `__all__` lists all public exports
- [ ] No circular import issues
- [ ] No linting errors

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-237 must be done
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** following the scope above
4. **Verify** imports work correctly
5. **Move this file** to `sdd/tasks/completed/TASK-238-docker-package-init.md`
6. **Update index** → `"done"`

---

## Completion Note

**Completed by**: claude-opus-4-6
**Date**: 2026-03-09
**Notes**: Updated `parrot/tools/docker/__init__.py` with 15 public exports covering all main classes, input models, and output models. Registered `DockerToolkit` as `"docker"` in `parrot/tools/registry.py` via `_get_supported_toolkits()`. All imports verified, no circular dependencies. 14 tools exposed via `get_tools()`.

**Deviations from spec**: Also exported all model classes (ContainerInfo, ImageInfo, PortMapping, etc.) for convenience — follows Pulumi pattern.
