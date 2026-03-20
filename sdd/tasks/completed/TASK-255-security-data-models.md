# TASK-255: Security Data Models

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: none
**Assigned-to**: claude-session

---

## Context

> Define the foundational data types for the ShellTool security system: enums, frozen dataclass for validation results, per-command rule dataclass, and the security error exception. These are pure data types with no logic dependencies.

---

## Scope

### Enums
- `SecurityLevel(str, Enum)` — `RESTRICTIVE`, `MODERATE`, `PERMISSIVE`
- `CommandVerdict(str, Enum)` — `ALLOWED`, `DENIED`, `NEEDS_REVIEW`

### ValidationResult (frozen dataclass)
- Fields: `verdict`, `command`, `reasons` (Tuple[str,...]), `sanitized_command` (Optional[str]), `risk_score` (float, 0.0-1.0)
- Properties: `is_allowed`, `is_denied`
- `__str__` — human-readable format with emoji status

### CommandRule (dataclass)
- Fields: `name`, `allowed_args` (Optional[Set[str]]), `denied_args` (Set[str]), `denied_patterns` (List[str]), `max_args` (Optional[int]), `require_absolute_path` (bool), `sandbox_paths` (Optional[List[str]]), `allow_pipe` (bool), `allow_redirect` (bool), `risk_base` (float)

### CommandSecurityError (Exception)
- `__init__(self, message: str, result: ValidationResult)`
- Stores `self.result`

**NOT in scope**: SecurityPolicy, CommandSanitizer, SecureShellMixin, integration with ShellTool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/security.py` | CREATE | All data model classes listed above |

---

## Implementation Notes

- Use `from __future__ import annotations` for forward refs
- Use `dataclasses` (not Pydantic) — matches reference implementation
- `ValidationResult` must be `frozen=True` (immutable)
- `CommandRule` uses `field(default_factory=...)` for mutable defaults
- Import only stdlib: `dataclasses`, `enum`, `typing`

---

## Acceptance Criteria

- [ ] `SecurityLevel` enum with 3 members
- [ ] `CommandVerdict` enum with 3 members
- [ ] `ValidationResult` frozen dataclass with all fields and properties
- [ ] `ValidationResult.__str__` returns emoji + verdict + command + reasons
- [ ] `CommandRule` dataclass with all 10 fields
- [ ] `CommandSecurityError` exception with `.result` attribute
- [ ] No ruff lint errors

---

## Agent Instructions

1. **Read** the spec at `sdd/specs/shelltool-security.spec.md` for full model definitions
2. **Create** `parrot/tools/shell_tool/security.py` with data models only
3. **Run** `ruff check parrot/tools/shell_tool/security.py`
4. **Run** `pytest tests/tools/shell_tool/test_security_models.py -v` (create minimal tests)
5. **Move** to completed, update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Created `parrot/tools/shell_tool/security.py` with:
- `SecurityLevel(str, Enum)` — RESTRICTIVE/MODERATE/PERMISSIVE
- `CommandVerdict(str, Enum)` — ALLOWED/DENIED/NEEDS_REVIEW
- `ValidationResult` — frozen dataclass with `is_allowed`/`is_denied` properties and `__str__` with emoji
- `CommandRule` — mutable dataclass with 10 fields for per-command argument restrictions
- `CommandSecurityError` — Exception subclass carrying `.result: ValidationResult`

36 tests pass in `tests/tools/shell_tool/test_security_models.py`. No lint errors.
