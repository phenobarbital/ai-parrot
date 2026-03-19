# TASK-227: Unit Tests for parrot/exceptions.py

**Feature**: Exception Migration — Cython to Pure Python (FEAT-031)
**Spec**: `sdd/specs/exception-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-222
**Assigned-to**: claude-sonnet-4-6

---

## Context

> Creates `tests/test_exceptions.py` to verify behavioural equivalence of the pure Python
> exception implementation — message handling, hierarchy, catch semantics, and subclassability.

---

## Scope

Create `tests/test_exceptions.py` covering all test cases defined in the spec:

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
    """Helper: object with a .message attribute."""
    message = "from object"


# --- ParrotError base behaviour ---

def test_parrot_error_message_string():
    assert ParrotError("hello").message == "hello"


def test_parrot_error_message_object():
    e = ParrotError(FakeMsg())
    assert e.message == "from object"


def test_parrot_error_str():
    assert str(ParrotError("x")) == "x"


def test_parrot_error_repr():
    assert repr(ParrotError("x")) == "x"


def test_parrot_error_get():
    assert ParrotError("x").get() == "x"


def test_parrot_error_stacktrace():
    e = ParrotError("x", stacktrace="traceback here")
    assert e.stacktrace == "traceback here"


def test_parrot_error_stacktrace_default_none():
    e = ParrotError("x")
    assert e.stacktrace is None


def test_parrot_error_is_exception():
    assert isinstance(ParrotError("x"), Exception)


# --- Subclass hierarchy ---

@pytest.mark.parametrize("cls", [
    ConfigError,
    SpeechGenerationError,
    DriverError,
    ToolError,
])
def test_subclass_is_parrot_error(cls):
    assert isinstance(cls("x"), ParrotError)


@pytest.mark.parametrize("cls", [
    ConfigError,
    SpeechGenerationError,
    DriverError,
    ToolError,
])
def test_subclass_is_exception(cls):
    assert isinstance(cls("x"), Exception)


# --- Catch semantics ---

def test_raise_and_catch_as_parrot_error():
    with pytest.raises(ParrotError):
        raise ConfigError("cfg error")


def test_raise_and_catch_as_exception():
    with pytest.raises(Exception):
        raise ToolError("tool error")


def test_catch_specific_subclass():
    with pytest.raises(DriverError):
        raise DriverError("driver error")


# --- Pure Python subclassability ---

def test_pure_python_subclassable():
    class MyError(ParrotError):
        pass

    e = MyError("custom")
    assert isinstance(e, ParrotError)
    assert e.message == "custom"
    assert str(e) == "custom"
```

**NOT in scope**: Integration tests, modifying any production code, or testing the Cython version.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/test_exceptions.py` | CREATE | Unit tests for pure Python exception hierarchy |

---

## Implementation Notes

- Check whether a `tests/` directory exists; if not, create it with a `__init__.py`.
- Check whether `conftest.py` is needed for the test suite; use existing one if present.
- Run tests with: `source .venv/bin/activate && pytest tests/test_exceptions.py -v`
- All 15 tests must pass before marking this task done.

---

## Acceptance Criteria

- [ ] `tests/test_exceptions.py` exists
- [ ] `pytest tests/test_exceptions.py -v` — all tests pass, 0 failures
- [ ] Tests cover: message from string, message from object, `str()`, `repr()`, `get()`, stacktrace, `None` stacktrace, `isinstance(Exception)`, all 4 subclasses as `ParrotError`, catch via `ParrotError`, catch via `Exception`, catch specific subclass, pure Python subclassability

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/exception-migration.spec.md` for full context
2. **Confirm TASK-222 is done** (pure Python `exceptions.py` must exist)
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Run** `source .venv/bin/activate && pytest tests/test_exceptions.py -v` and confirm all pass
6. **Move this file** to `sdd/tasks/completed/TASK-227-unit-tests-exceptions.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**:
- Created `tests/test_exceptions.py` with 20 test cases (spec listed 15; parametrize over 4
  subclasses expanded the count to 20).
- Used `importlib.util.spec_from_file_location` to load `parrot/exceptions.py` directly,
  bypassing the still-present Cython `.so` which would shadow the `.py` at runtime.
- `test_pure_python_subclassable` confirms subclassing works — this test would fail against
  the Cython `cdef class` implementation.
- All 20 tests passed: `pytest tests/test_exceptions.py -v` → 20 passed in 0.26s.

**Deviations from spec**: Test count is 20 instead of 15 due to `@pytest.mark.parametrize`
expansion over 4 subclasses for `test_subclass_is_parrot_error` and `test_subclass_is_exception`.
Behaviour coverage is identical to spec.
