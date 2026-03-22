# TASK-386: Lazy Import Utility

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-056. All subsequent lazy-import refactoring tasks depend on this utility module. It provides a standardized, canonical pattern for lazy-importing optional dependencies across the entire codebase, replacing the 4-5 ad-hoc patterns currently in use.

Implements: Spec Module 1 — Lazy Import Utility.

---

## Scope

- Create `parrot/_imports.py` with two public functions:
  - `lazy_import(module_path, package_name=None, extra=None)` — imports a module on demand, raises a clear `ImportError` with install instructions if missing.
  - `require_extra(extra, *modules)` — checks that all listed modules are importable, raises clear error if not.
- Error messages must include: the missing package name and `pip install ai-parrot[<extra>]`.
- Use only stdlib (`importlib`, `types`) — no external dependencies.
- Write unit tests in `tests/test_lazy_imports.py`.

**NOT in scope**: Refactoring any existing files to use this utility (that's TASK-388+).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/_imports.py` | CREATE | Lazy import utility module |
| `tests/test_lazy_imports.py` | CREATE | Unit tests for lazy_import and require_extra |

---

## Implementation Notes

### Pattern to Follow

```python
import importlib
from types import ModuleType


def lazy_import(
    module_path: str,
    package_name: str | None = None,
    extra: str | None = None,
) -> ModuleType:
    """Import a module lazily, raising a clear error if not installed."""
    try:
        return importlib.import_module(module_path)
    except ImportError as e:
        pkg = package_name or module_path.split(".")[0]
        if extra:
            msg = (
                f"'{pkg}' is required but not installed. "
                f"Install it with: pip install ai-parrot[{extra}]"
            )
        else:
            msg = f"'{pkg}' is required but not installed. Install it with: pip install {pkg}"
        raise ImportError(msg) from e


def require_extra(extra: str, *modules: str) -> None:
    """Check that all required modules for an extra are importable."""
    for mod in modules:
        lazy_import(mod, extra=extra)
```

### Key Constraints
- Must be zero-dependency (stdlib only)
- Must return the actual module object (not a proxy) so callers can use it normally
- Error messages must be user-friendly and actionable
- Thread-safe (importlib.import_module is already thread-safe)

### References in Codebase
- `parrot/memory/skills/store.py` — existing try/except + flag pattern (to be replaced)
- `parrot/tools/jiratoolkit.py` — existing try/except with message pattern
- `parrot/tools/flowtask/tool.py` — existing importlib.import_module pattern

---

## Acceptance Criteria

- [ ] `parrot/_imports.py` exists with `lazy_import()` and `require_extra()`
- [ ] `lazy_import("json")` returns the json module (installed package)
- [ ] `lazy_import("nonexistent_pkg_xyz", extra="db")` raises `ImportError` containing `pip install ai-parrot[db]`
- [ ] `require_extra("db", "json", "os")` passes silently (all installed)
- [ ] `require_extra("db", "nonexistent_pkg_xyz")` raises `ImportError`
- [ ] All tests pass: `pytest tests/test_lazy_imports.py -v`

---

## Test Specification

```python
# tests/test_lazy_imports.py
import pytest
from parrot._imports import lazy_import, require_extra


class TestLazyImport:
    def test_import_installed_module(self):
        """Successfully imports an installed module."""
        mod = lazy_import("json")
        assert hasattr(mod, "dumps")

    def test_import_missing_module_with_extra(self):
        """Raises ImportError with install instructions for missing module."""
        with pytest.raises(ImportError, match=r"pip install ai-parrot\[testextra\]"):
            lazy_import("nonexistent_pkg_xyz_12345", extra="testextra")

    def test_import_missing_module_without_extra(self):
        """Raises ImportError with pip install for missing module."""
        with pytest.raises(ImportError, match=r"pip install nonexistent"):
            lazy_import("nonexistent_pkg_xyz_12345", package_name="nonexistent")

    def test_import_submodule(self):
        """Can import submodules."""
        mod = lazy_import("os.path")
        assert hasattr(mod, "join")

    def test_custom_package_name(self):
        """Error message uses custom package name."""
        with pytest.raises(ImportError, match="my-custom-pkg"):
            lazy_import("nonexistent", package_name="my-custom-pkg")


class TestRequireExtra:
    def test_all_available(self):
        """Passes when all modules are importable."""
        require_extra("core", "json", "os")

    def test_missing_module(self):
        """Raises ImportError when a module is missing."""
        with pytest.raises(ImportError, match=r"pip install ai-parrot\[db\]"):
            require_extra("db", "json", "nonexistent_pkg_xyz_12345")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — this task has no dependencies
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-386-lazy-import-utility.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-03-22
**Notes**: Implemented `parrot/_imports.py` with `lazy_import()` and `require_extra()` using only stdlib. All 21 tests pass.

**Deviations from spec**: none
