# TASK-256: SecurityPolicy Dataclass & Defaults

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-255
**Assigned-to**: claude-session

---

## Context

> Define the `SecurityPolicy` dataclass with three preset factory methods (`restrictive`, `moderate`, `permissive`), the default denied commands set (50+ binaries), and the default command rules (10+ per-command `CommandRule` instances).

---

## Scope

### SecurityPolicy (dataclass)
- Fields per spec: `level`, `allowed_commands`, `denied_commands`, `command_rules`, `sandbox_dir`, `max_command_length`, `max_output_bytes`, `max_stderr_bytes`, `allow_shell_operators`, `allow_chaining`, `allow_env_expansion`, `allow_command_substitution`, `allow_glob`, `denied_patterns`, `audit_log`
- `@classmethod restrictive(cls, allowed_commands, sandbox_dir, command_rules)` → RESTRICTIVE preset
- `@classmethod moderate(cls, allowed_commands, sandbox_dir)` → MODERATE preset with safe defaults merged
- `@classmethod permissive(cls, denied_commands, sandbox_dir)` → PERMISSIVE preset

### Default Denied Commands
- Module-level `_DEFAULT_DENIED_COMMANDS: Set[str]` with 50+ dangerous binaries across categories: destructive, privilege escalation, network, interpreters/shells, system management, package managers, credentials, data exfiltration, container escape

### Default Command Rules
- Module-level `_default_command_rules() → Dict[str, CommandRule]` returning rules for: `curl`, `wget`, `git`, `find`, `cp`, `mv`, `python3`, `python`, `pip`, `sed`, `awk`
- Each rule has appropriate `denied_args`, `denied_patterns`, `risk_base` per spec table

### Safe Defaults for MODERATE
- Module-level set: `ls, cat, head, tail, wc, grep, find, echo, date, whoami, pwd, env, printenv, uname, sort, uniq, cut, awk, sed, tr, tee, diff, md5sum, sha256sum, file, stat, python3, python, pip, node, npm, git, curl, wget, mkdir, cp, mv, touch`

**NOT in scope**: CommandSanitizer validation logic, SecureShellMixin, ShellTool integration.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/security.py` | MODIFY | Add SecurityPolicy, _DEFAULT_DENIED_COMMANDS, _default_command_rules(), safe defaults |

---

## Acceptance Criteria

- [ ] `SecurityPolicy` dataclass with all 15 fields
- [ ] `SecurityPolicy.restrictive()` factory with correct defaults
- [ ] `SecurityPolicy.moderate()` factory merging user commands with safe defaults
- [ ] `SecurityPolicy.permissive()` factory with correct defaults
- [ ] `_DEFAULT_DENIED_COMMANDS` contains 50+ dangerous binaries
- [ ] `_default_command_rules()` returns rules for 10+ commands
- [ ] Each factory method sets correct `allow_*` toggles per spec table
- [ ] No ruff lint errors
- [ ] Unit tests for all 3 presets and default sets

---

## Agent Instructions

1. **Read** spec Section 2 (Data Models → SecurityPolicy) and the user's reference code
2. **Modify** `parrot/tools/shell_tool/security.py` — add SecurityPolicy after the data models from TASK-255
3. **Run** `ruff check parrot/tools/shell_tool/security.py`
4. **Write tests** in `tests/tools/shell_tool/test_security_policy.py`
5. **Run** `pytest tests/tools/shell_tool/test_security_policy.py -v`
6. **Move** to completed, update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Added to `parrot/tools/shell_tool/security.py`:
- `_DEFAULT_DENIED_COMMANDS` — 55+ dangerous binaries across 10 categories
- `_MODERATE_SAFE_DEFAULTS` — safe commands set for moderate policy
- `_default_command_rules()` — rules for 11 commands (curl, wget, git, find, cp, mv, python3, python, pip, sed, awk)
- `SecurityPolicy` dataclass with 15 fields and 3 factory classmethods (`restrictive`, `moderate`, `permissive`)

78 tests pass in `tests/tools/shell_tool/test_security_policy.py`. No lint errors.
