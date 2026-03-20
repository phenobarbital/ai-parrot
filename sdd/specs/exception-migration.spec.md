# Feature Specification: Exception Migration — Cython to Pure Python

**Feature ID**: FEAT-031
**Date**: 2026-03-07
**Author**: Jesus Lara
**Status**: approved
**Target version**: 1.x.x

---

## 1. Motivation & Business Requirements

### Problem Statement

`parrot/exceptions.pyx` defines the core exception hierarchy (`ParrotError`, `ConfigError`,
`SpeechGenerationError`, `DriverError`, `ToolError`) as Cython `cdef class` types. This creates
several maintenance and portability problems:

1. **Build dependency**: Every environment must have Cython + a C compiler installed and must
   execute `python setup.py build_ext --inplace` before any exception class is importable.
   This complicates CI, Docker images, and developer onboarding.
2. **`cdef class` restrictions**: Cython `cdef class` types cannot be used as Python base classes
   outside of Cython code, making it impossible to subclass `ParrotError` in pure Python modules
   without triggering `TypeError`.
3. **Pylint noise**: Every importer carries a `# pylint: disable=E0611` comment because pylint
   cannot introspect compiled `.so` extensions — 10 files are affected.
4. **Dead artifacts**: The compiled C file (`exceptions.c`) and shared object
   (`exceptions.cpython-311-x86_64-linux-gnu.so`) live in the source tree, polluting `git status`
   and `git diff`.
5. **Stub mismatch**: The type stub is saved as `exceptions.pxi` (a Cython include-file extension)
   instead of `exceptions.pyi`, so IDEs and type-checkers cannot find it.

### Goals

- Replace all Cython exception artifacts with a single `parrot/exceptions.py` pure Python file.
- Remove the `parrot.exceptions` entry from `setup.py`.
- Update all 10 dependent Python files to drop the `# pylint: disable=E0611` annotation.
- Provide a proper `parrot/exceptions.pyi` stub for IDE/type-checker support.
- Delete all stale Cython build artifacts (`.pyx`, `.pxd`, `.pxi`, `.c`, `.so`).

### Non-Goals (explicitly out of scope)

- Adding new exception classes beyond what already exists.
- Changing exception semantics or the public API surface.
- Migrating the other Cython extensions (`parrot/utils/types.pyx`,
  `parrot/utils/parsers/toml.pyx`) — those are out of scope.
- Changes to test infrastructure or CI pipeline beyond what is needed to drop the Cython build
  step for exceptions.

---

## 2. Architectural Design

### Overview

The migration is a pure substitution: the compiled `.so` is replaced by a `.py` file that exposes
the identical public interface. No callers change their import paths; only the `# pylint: disable`
suppressions and the build configuration are updated.

```
Before                                    After
──────────────────────────────────        ──────────────────────────────────
parrot/exceptions.pyx   (Cython)   ──►   parrot/exceptions.py   (pure Python)
parrot/exceptions.pxd   (header)   del
parrot/exceptions.pxi   (stub)     ──►   parrot/exceptions.pyi  (PEP 561 stub)
parrot/exceptions.c     (gen C)    del
parrot/exceptions.*.so  (binary)   del
setup.py  (Extension entry)        ──►   setup.py  (entry removed)

Callers (10 files)
  from ..exceptions import ConfigError  # pylint: disable=E0611   ──►
  from ..exceptions import ConfigError
```

### Pure Python Exception Class Design

The new `parrot/exceptions.py` mirrors the Cython implementation exactly:

```python
from typing import Any, Optional


class ParrotError(Exception):
    """Base class for Parrot exceptions."""

    def __init__(self, message: Any, *args, **kwargs) -> None:
        super().__init__(message)
        self.message: str = str(getattr(message, 'message', message))
        self.stacktrace: Optional[Any] = kwargs.get('stacktrace')
        self.args = kwargs  # type: ignore[assignment]

    def __repr__(self) -> str:
        return self.message

    __str__ = __repr__

    def get(self) -> str:
        """Return the message of the exception."""
        return self.message


class ConfigError(ParrotError):
    """Raised for configuration-related errors."""


class SpeechGenerationError(ParrotError):
    """Raised for errors related to speech generation."""


class DriverError(ParrotError):
    """Raised for errors related to driver operations."""


class ToolError(ParrotError):
    """Raised for errors related to tool operations."""
```

### Behavioural Equivalence Notes

| Aspect | Cython `cdef class` | Pure Python `class` |
|---|---|---|
| `isinstance(e, Exception)` | `True` | `True` |
| `isinstance(e, ParrotError)` | `True` | `True` |
| `str(e)` | returns `message` | returns `message` |
| `repr(e)` | returns `message` | returns `message` |
| `e.get()` | returns `message` | returns `message` |
| Subclassable in pure Python | `TypeError` | `True` |
| `raise ConfigError("x")` | works | works |

The only visible difference is that `cdef class` types were not subclassable from pure Python;
the pure Python replacement removes that restriction (a benefit, not a regression).

### Dependent Files Inventory

| File | Imported symbol | Change required |
|---|---|---|
| `parrot/bots/abstract.py` | `ConfigError` | remove `# pylint: disable=E0611` |
| `parrot/interfaces/google.py` | `ConfigError` | remove `# pylint: disable=E0611` + `# noqa` |
| `parrot/stores/abstract.py` | `ConfigError` | remove `# pylint: disable=E0611` |
| `parrot/stores/bigquery.py` | `DriverError` | remove `# pylint: disable=E0611` (if present) |
| `parrot/clients/google/generation.py` | `SpeechGenerationError` | remove `# pylint: disable=E0611` |
| `parrot/tools/qsource.py` | `ToolError` | remove `# pylint: disable=E0611` |
| `parrot/tools/querytoolkit.py` | `ToolError` | remove `# pylint: disable=E0611` + `# noqa` |
| `parrot/tools/nextstop/employee.py` | `ToolError` | remove `# pylint: disable=E0611` |
| `parrot/tools/epson/__init__.py` | `ToolError` | remove `# pylint: disable=E0611` + `# noqa` |
| `parrot/tools/sassie/__init__.py` | `ToolError` | remove `# pylint: disable=E0611` |

Import paths (`from ..exceptions import X`, `from ...exceptions import X`) remain unchanged.

### `setup.py` Change

Remove the `parrot.exceptions` `Extension` block entirely:

```python
# Remove this block:
Extension(
    name='parrot.exceptions',
    sources=['parrot/exceptions.pyx'],
    extra_compile_args=COMPILE_ARGS,
    language="c"
),
```

If `extensions` becomes empty after also checking the other extensions, the `setup.py` still
retains the remaining two extensions (`parrot.utils.types`, `parrot/utils/parsers/toml`).

### PEP 561 Stub

The existing `parrot/exceptions.pxi` content is already a valid Python type stub
(its first line reads `# parrot/exceptions.pyi`). Rename it to `parrot/exceptions.pyi`.
No content changes are needed.

### Artifact Deletion

The following files must be deleted after `parrot/exceptions.py` is in place and all
tests pass:

| File | Reason |
|---|---|
| `parrot/exceptions.pyx` | Replaced by `exceptions.py` |
| `parrot/exceptions.pxd` | Cython C-level declarations, no longer needed |
| `parrot/exceptions.pxi` | Renamed to `exceptions.pyi` |
| `parrot/exceptions.c` | Generated C file from Cython transpilation |
| `parrot/exceptions.cpython-311-x86_64-linux-gnu.so` | Compiled binary, replaced by `.py` |

---

## 3. Module Breakdown

### Module 1: `parrot/exceptions.py` — pure Python implementation
- **Path**: `parrot/exceptions.py`
- **Responsibility**: Define `ParrotError`, `ConfigError`, `SpeechGenerationError`,
  `DriverError`, `ToolError` as pure Python classes with identical public API.
- **Depends on**: nothing (stdlib only)

### Module 2: `parrot/exceptions.pyi` — PEP 561 stub
- **Path**: `parrot/exceptions.pyi`
- **Responsibility**: Rename `parrot/exceptions.pxi` → `parrot/exceptions.pyi`; verify content
  matches the public API of Module 1.
- **Depends on**: Module 1

### Module 3: `setup.py` — remove Cython extension
- **Path**: `setup.py`
- **Responsibility**: Delete the `parrot.exceptions` `Extension(...)` block.
- **Depends on**: Module 1

### Module 4: Dependent file cleanup — remove pylint suppressions
- **Paths**: all 10 files listed in the Dependent Files Inventory table above
- **Responsibility**: Remove `# pylint: disable=E0611` inline comments from exception import
  lines. Remove `# noqa` where it exists solely for E0611.
- **Depends on**: Module 1

### Module 5: Delete stale Cython artifacts
- **Files to delete**: `exceptions.pyx`, `exceptions.pxd`, `exceptions.pxi`,
  `exceptions.c`, `exceptions.cpython-311-x86_64-linux-gnu.so`
- **Responsibility**: Remove build artifacts from the source tree.
- **Depends on**: Modules 1–4 passing all tests

### Module 6: Unit tests
- **Path**: `tests/test_exceptions.py`
- **Responsibility**: Verify behavioural equivalence of the pure Python implementation;
  confirm subclassability and catch-hierarchy.
- **Depends on**: Module 1

---

## 4. Test Specification

### Unit Tests

| Test | Description |
|---|---|
| `test_parrot_error_message_string` | `ParrotError("hello").message == "hello"` |
| `test_parrot_error_message_object` | Object with `.message` attr is unwrapped correctly |
| `test_parrot_error_str` | `str(ParrotError("x")) == "x"` |
| `test_parrot_error_repr` | `repr(ParrotError("x")) == "x"` |
| `test_parrot_error_get` | `.get()` returns the message string |
| `test_parrot_error_stacktrace` | `ParrotError("x", stacktrace="tb").stacktrace == "tb"` |
| `test_parrot_error_stacktrace_default_none` | `.stacktrace` is `None` when not passed |
| `test_parrot_error_is_exception` | `isinstance(ParrotError("x"), Exception)` |
| `test_config_error_is_parrot_error` | `isinstance(ConfigError("x"), ParrotError)` |
| `test_speech_generation_error_is_parrot_error` | `isinstance(SpeechGenerationError("x"), ParrotError)` |
| `test_driver_error_is_parrot_error` | `isinstance(DriverError("x"), ParrotError)` |
| `test_tool_error_is_parrot_error` | `isinstance(ToolError("x"), ParrotError)` |
| `test_raise_and_catch_as_parrot_error` | `raise ConfigError("x")` caught by `except ParrotError` |
| `test_raise_and_catch_as_exception` | `raise ToolError("x")` caught by `except Exception` |
| `test_pure_python_subclassable` | A pure Python class can subclass `ParrotError` without `TypeError` |

```python
import pytest
from parrot.exceptions import (
    ParrotError,
    ConfigError,
    SpeechGenerationError,
    DriverError,
    ToolError,
)


class FakeMsg:
    message = "from object"


@pytest.mark.parametrize("cls", [ConfigError, SpeechGenerationError, DriverError, ToolError])
def test_subclass_is_parrot_error(cls):
    assert isinstance(cls("x"), ParrotError)


def test_pure_python_subclassable():
    class MyError(ParrotError):
        pass

    e = MyError("custom")
    assert isinstance(e, ParrotError)
    assert e.message == "custom"
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `parrot/exceptions.py` exists and defines `ParrotError`, `ConfigError`,
      `SpeechGenerationError`, `DriverError`, `ToolError` as pure Python classes.
- [ ] `ParrotError.__init__` accepts `message`, `*args`, `**kwargs`; stores `.message` as `str`,
      `.stacktrace` from kwargs, and `.args = kwargs`.
- [ ] `ParrotError.__str__` and `__repr__` both return `.message`.
- [ ] `ParrotError.get()` returns `.message`.
- [ ] All four subclasses (`ConfigError`, `SpeechGenerationError`, `DriverError`, `ToolError`)
      inherit from `ParrotError` and are importable from `parrot.exceptions`.
- [ ] `parrot/exceptions.pyi` exists (renamed from `.pxi`) and accurately reflects the public API.
- [ ] `setup.py` no longer contains an `Extension` for `parrot.exceptions`.
- [ ] All 10 dependent files have `# pylint: disable=E0611` removed from their exception import
      lines.
- [ ] Stale artifacts removed: `exceptions.pyx`, `exceptions.pxd`, `exceptions.pxi`,
      `exceptions.c`, `exceptions.cpython-311-x86_64-linux-gnu.so`.
- [ ] `pytest tests/test_exceptions.py -v` — all tests pass.
- [ ] `pytest` (full suite) — no regressions introduced.
- [ ] `pylint parrot/` — no new E0611 warnings.

---

## 6. Implementation Notes & Constraints

### Patterns to Follow

- Module-level docstring + Google-style docstrings on each class.
- Strict type hints throughout (`from typing import Any, Optional`).
- No third-party imports — stdlib only.
- Follow existing naming conventions (snake_case for methods).

### `self.args` Override Warning

The base `Exception` class stores positional arguments in `self.args` (a tuple). The Cython
original overwrites `self.args` with the `kwargs` dict, which is intentionally preserved in the
pure Python version for backward compatibility. Add an `# type: ignore[assignment]` annotation
on that line so mypy does not flag it.

### Deletion Order

Delete artifacts **after** `parrot/exceptions.py` is importable and all tests pass.
CPython's import machinery prefers `.so` extension modules over `.py` source files
when both exist in the same directory. Therefore the `.so` **must** be deleted (in TASK-226)
before the pure Python module becomes the active implementation at runtime.

### No `.pyc` / `__pycache__` Concerns

The `.so` removal does not leave orphaned `.pyc` files; `__pycache__` is managed by CPython
automatically. No manual cache invalidation is needed.

### External Dependencies

None. The pure Python implementation uses only the Python standard library.

---

## 7. Open Questions

None — scope is fully defined by the existing Cython implementation.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-03-07 | claude-session | Initial draft |
