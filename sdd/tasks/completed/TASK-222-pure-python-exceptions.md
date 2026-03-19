# TASK-222: Pure Python Exception Implementation

**Feature**: Exception Migration — Cython to Pure Python (FEAT-031)
**Spec**: `sdd/specs/exception-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: —
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Foundation task. Creates `parrot/exceptions.py` — the pure Python replacement for the current
> Cython `parrot/exceptions.pyx`. The new file exposes the identical public interface so all
> existing callers continue to work without import-path changes.

---

## Scope

Create `parrot/exceptions.py` with the following implementation:

```python
# -*- coding: utf-8 -*-
"""Parrot exception hierarchy."""
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

**Key invariants to preserve:**
- `self.args = kwargs` (overwrites `Exception.args` tuple — intentional for backward compat)
- `__str__ = __repr__` (both return `.message`)
- `get()` returns `.message` as a `str`

**NOT in scope**: Deleting Cython artifacts, updating `setup.py`, updating callers, or writing tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/exceptions.py` | CREATE | Pure Python exception hierarchy |

---

## Implementation Notes

- CPython prefers `.so` extension modules over `.py` source files in the same directory, so the
  `.so` must be deleted (TASK-226) before the pure Python module becomes the active implementation
  at runtime. This task only creates the file; deletion is a separate concern.
- Add `# type: ignore[assignment]` on the `self.args = kwargs` line so mypy stays quiet.
- Module-level docstring required; Google-style docstrings on each class.
- Stdlib only — no third-party imports.

---

## Acceptance Criteria

- [ ] `parrot/exceptions.py` exists
- [ ] `from parrot.exceptions import ParrotError, ConfigError, SpeechGenerationError, DriverError, ToolError` works
- [ ] `ParrotError("hello").message == "hello"`
- [ ] `str(ParrotError("hello")) == "hello"`
- [ ] `repr(ParrotError("hello")) == "hello"`
- [ ] `ParrotError("hello").get() == "hello"`
- [ ] Object with `.message` attr is unwrapped: `ParrotError(obj).message == obj.message`
- [ ] `ParrotError("x", stacktrace="tb").stacktrace == "tb"`
- [ ] `isinstance(ConfigError("x"), ParrotError)` is `True`
- [ ] A pure Python class can subclass `ParrotError` without `TypeError`

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/exception-migration.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Implement** following the scope and notes above
4. **Verify** all acceptance criteria are met
5. **Move this file** to `sdd/tasks/completed/TASK-222-pure-python-exceptions.md`
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**:
- Created `parrot/exceptions.py` with `ParrotError`, `ConfigError`, `SpeechGenerationError`,
  `DriverError`, `ToolError` as pure Python classes.
- All acceptance criteria verified by direct `.py` file load (bypassing the still-present `.so`).
- Discovered and corrected spec error: CPython prefers `.so` over `.py` in the same directory
  (not the other way around). Updated spec and TASK-226 accordingly.
- The `.so` shadows the new `.py` at runtime until TASK-226 deletes the Cython artifacts.

**Deviations from spec**: None in implementation. Spec note about `.so` vs `.py` precedence was
corrected in place (spec erroneously stated Python prefers `.py`; it is the opposite).
