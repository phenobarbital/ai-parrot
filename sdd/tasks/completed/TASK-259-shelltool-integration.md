# TASK-259: ShellTool Integration — Wire Security into Existing Code

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-258
**Assigned-to**: claude-session

---

## Context

> Wire the `CommandSanitizer` and `SecureShellMixin` into the existing `ShellTool`, `BaseAction`, and action classes. Remove the old inline security (`FORBIDDEN_PATHS`, `_validate_command`, `_validate_path`) and replace with the new sanitizer. Add output truncation.

---

## Scope

### Modify `tool.py` — ShellTool
- `ShellTool` class extends `SecureShellMixin` (via mixin composition or explicit integration)
- Constructor accepts optional `security_policy: Optional[SecurityPolicy]` parameter
- If `security_policy` provided, call `self.set_security_policy(policy)`
- If no policy provided, default to `SecurityPolicy.moderate()`
- In `_execute()`, call `self.assert_command_safe(cmd)` for each command before dispatching
- In plan mode `_run_plan()`, validate each step's command before execution

### Modify `models.py` — BaseAction
- Remove `FORBIDDEN_PATHS` set
- Remove `FORBIDDEN_CMD_PATTERN` regex
- Remove `_validate_path()` method
- Remove `_validate_command()` method
- Add optional `sanitizer: Optional[CommandSanitizer] = None` to constructor

### Modify `actions.py` — Action Classes
- `RunCommand._run_impl()`: validation now happens at ShellTool level (remove `_validate_command` call from `_run_subprocess`)
- `ListFiles._run_impl()`: validate path arguments via sanitizer sandbox layer
- `CheckExists`, `ReadFile`, `WriteFile`, `DeleteFile`, `CopyFile`, `MoveFile`: validation via sanitizer (replace `_validate_path` calls)
- Add output truncation in `BaseAction._run_subprocess()` using `max_output_bytes`/`max_stderr_bytes` from policy

### Modify `__init__.py` — Exports
- Export: `SecurityPolicy`, `SecurityLevel`, `CommandSanitizer`, `ValidationResult`, `CommandVerdict`, `CommandRule`, `CommandSecurityError`, `SecureShellMixin`

**NOT in scope**: Changing the public API of ShellTool (command/plan interface stays the same).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/tool.py` | MODIFY | Extend SecureShellMixin, accept security_policy, call assert_command_safe |
| `parrot/tools/shell_tool/models.py` | MODIFY | Remove old security code, add sanitizer param |
| `parrot/tools/shell_tool/actions.py` | MODIFY | Replace _validate_path/_validate_command, add output truncation |
| `parrot/tools/shell_tool/__init__.py` | MODIFY | Export new security classes |

---

## Implementation Notes

- The key migration: `_validate_command()` was called in `_run_subprocess()`. Now validation happens in `ShellTool._execute()` via `assert_command_safe()` BEFORE action construction.
- File actions (`WriteFile`, `DeleteFile`, etc.) still need path validation. They should call `sanitizer._check_path_sandbox()` or the sanitizer should expose a `validate_path()` convenience method.
- Output truncation: in `_run_subprocess()`, after `stdout_buf`/`stderr_buf` collection, check byte length against policy limits.
- Backward compatibility: if `ShellTool()` is created with no args, it defaults to `SecurityPolicy.moderate()`. If created with `security_policy=None` explicitly, the mixin's `_sanitizer` stays `None` and all commands pass (backward compat).

---

## Acceptance Criteria

- [ ] `ShellTool` accepts `security_policy` parameter
- [ ] Default policy is `SecurityPolicy.moderate()`
- [ ] `assert_command_safe()` called before command execution
- [ ] `BaseAction.FORBIDDEN_PATHS` removed
- [ ] `BaseAction._validate_command()` removed
- [ ] `BaseAction._validate_path()` removed
- [ ] File actions use sanitizer for path validation
- [ ] Output truncation works at configured byte limits
- [ ] `__init__.py` exports all new security classes
- [ ] Existing tests still pass (backward compatibility)
- [ ] `rm -rf /` raises `CommandSecurityError` via ShellTool
- [ ] `echo hello` executes normally
- [ ] Plan mode validates each step
- [ ] No ruff lint errors

---

## Agent Instructions

1. **Read** all existing shell_tool files: `tool.py`, `models.py`, `actions.py`, `__init__.py`
2. **Read** `security.py` (from TASK-255/256/257/258)
3. **Modify** files per scope above
4. **Run** `ruff check parrot/tools/shell_tool/`
5. **Run** existing tests to verify backward compat
6. **Move** to completed, update index

---

## Completion Note

Completed 2026-03-09. All scope items implemented:

- `ShellTool` now extends `SecureShellMixin, AbstractTool` with `__init__` accepting `security_policy`
- Default policy is `SecurityPolicy.moderate()`; explicit `None` disables security (backward compat)
- `_NO_POLICY` sentinel distinguishes "not provided" from explicit `None`
- `assert_command_safe()` called in `_run_commands()` and plan-mode `_run_plan()` before action construction
- All file actions (WriteFile, DeleteFile, CopyFile, MoveFile) accept and forward `sanitizer` param
- `BaseAction._check_path()` replaces old `_validate_path()`, delegates to `CommandSanitizer.validate_path()`
- Output truncation added in non-PTY `_run_subprocess()` path using `max_output_bytes`/`max_stderr_bytes`
- `__init__.py` exports all 8 new security classes
- Old security code (`FORBIDDEN_PATHS`, `FORBIDDEN_CMD_PATTERN`, `_validate_command`, `_validate_path`) removed
- All 226 tests pass; ruff reports no lint errors
