# TASK-223: Rename exceptions.pxi → exceptions.pyi (PEP 561 Stub)

**Feature**: Exception Migration — Cython to Pure Python (FEAT-031)
**Spec**: `sdd/specs/exception-migration.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-222
**Assigned-to**: claude-sonnet-4-6

---

## Context

> The type stub for `parrot/exceptions` is currently saved as `parrot/exceptions.pxi` — a Cython
> include-file extension. Its content is already a valid PEP 561 stub (its first line reads
> `# parrot/exceptions.pyi`). Renaming it to `exceptions.pyi` makes it discoverable by IDEs and
> type-checkers such as mypy and Pyright.

---

## Scope

1. Read `parrot/exceptions.pxi` to confirm its current content.
2. Verify the content accurately reflects the public API of the new `parrot/exceptions.py`
   (TASK-222). The expected stub content is:

```python
# parrot/exceptions.pyi
from typing import Any, Optional

class ParrotError(Exception):
    message: Any
    stacktrace: Optional[Any]
    def __init__(self, message: Any, *args, **kwargs) -> None: ...
    def __repr__(self) -> str: ...
    def __str__(self) -> str: ...
    def get(self) -> Any: ...

class ConfigError(ParrotError): ...
class SpeechGenerationError(ParrotError): ...
class DriverError(ParrotError): ...
class ToolError(ParrotError): ...
```

3. Create `parrot/exceptions.pyi` with the verified content.
4. The `.pxi` file will be deleted in TASK-226 (artifact cleanup).

**NOT in scope**: Deleting `.pxi`, modifying `setup.py`, updating callers, or writing tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/exceptions.pyi` | CREATE | PEP 561 type stub (content from `.pxi`) |

---

## Implementation Notes

- Do NOT delete `parrot/exceptions.pxi` in this task — deletion is deferred to TASK-226.
- If the content of `.pxi` needs minor adjustments to match `exceptions.py` (e.g., `get()` return
  type `str` vs `Any`), apply them in the new `.pyi` file.

---

## Acceptance Criteria

- [ ] `parrot/exceptions.pyi` exists
- [ ] `parrot/exceptions.pyi` declares `ParrotError`, `ConfigError`, `SpeechGenerationError`, `DriverError`, `ToolError`
- [ ] `ParrotError` stub includes `message`, `stacktrace`, `__init__`, `__repr__`, `__str__`, `get`
- [ ] Running `mypy parrot/exceptions.py` reports no errors

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/exception-migration.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Implement** following the scope and notes above
4. **Verify** all acceptance criteria are met
5. **Move this file** to `sdd/tasks/completed/TASK-223-rename-pyi-stub.md`
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-07
**Notes**:
- Confirmed `parrot/exceptions.pxi` content is a valid PEP 561 stub.
- Created `parrot/exceptions.pyi` with tightened return type: `get() -> str` (was `Any`).
- `mypy parrot/exceptions.py --ignore-missing-imports` → Success: no issues found.
- `.pxi` file left in place for deletion in TASK-226.

**Deviations from spec**: Return type of `get()` tightened from `Any` to `str` to match the
actual implementation.
