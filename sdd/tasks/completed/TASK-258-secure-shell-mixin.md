# TASK-258: SecureShellMixin — Integration Mixin

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-257
**Assigned-to**: claude-session

---

## Context

> Implement the `SecureShellMixin` class that provides `set_security_policy()`, `validate_command()`, and `assert_command_safe()` methods. This mixin is designed to be composed into `ShellTool` for backward-compatible security injection.

---

## Scope

### SecureShellMixin
- `_sanitizer: Optional[CommandSanitizer] = None`
- `set_security_policy(self, policy: SecurityPolicy) → None` — creates `CommandSanitizer` from policy
- `validate_command(self, command: str) → ValidationResult` — returns ALLOWED if no sanitizer set (backward compat), otherwise delegates to sanitizer
- `assert_command_safe(self, command: str) → None` — calls `validate_command()`, raises `CommandSecurityError` if DENIED or NEEDS_REVIEW

### Behavior
- With no sanitizer set (`_sanitizer = None`): all commands allowed (backward compatible)
- `NEEDS_REVIEW` treated as DENIED in `assert_command_safe()` (per Open Q1 resolution)

**NOT in scope**: Modifying ShellTool, BaseAction, or actions.py.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/security.py` | MODIFY | Add `SecureShellMixin` class |

---

## Acceptance Criteria

- [ ] `SecureShellMixin` with `_sanitizer` attribute defaulting to `None`
- [ ] `set_security_policy()` creates and stores `CommandSanitizer`
- [ ] `validate_command()` with no sanitizer returns ALLOWED
- [ ] `validate_command()` with sanitizer delegates to `CommandSanitizer.validate()`
- [ ] `assert_command_safe()` raises `CommandSecurityError` on DENIED
- [ ] `assert_command_safe()` raises `CommandSecurityError` on NEEDS_REVIEW
- [ ] `assert_command_safe()` returns None on ALLOWED
- [ ] `CommandSecurityError.result` contains the `ValidationResult`
- [ ] No ruff lint errors

---

## Agent Instructions

1. **Read** spec Section 2 (Integration Mixin)
2. **Read** `parrot/tools/shell_tool/security.py` (from TASK-255/256/257)
3. **Add** `SecureShellMixin` class
4. **Run** `ruff check`
5. **Write tests** in `tests/tools/shell_tool/test_secure_shell_mixin.py`
6. **Run** `pytest tests/tools/shell_tool/test_secure_shell_mixin.py -v`
7. **Move** to completed, update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Added `SecureShellMixin` to `parrot/tools/shell_tool/security.py`:
- `_sanitizer: Optional[CommandSanitizer] = None` class attribute
- `set_security_policy(policy)` — creates and stores `CommandSanitizer`
- `validate_command(command)` — ALLOWED passthrough when no sanitizer; otherwise delegates to `CommandSanitizer.validate()`
- `assert_command_safe(command)` — raises `CommandSecurityError` on DENIED or NEEDS_REVIEW (per Open Q1 resolution)

25 tests pass in `tests/tools/shell_tool/test_secure_shell_mixin.py`. No lint errors.
