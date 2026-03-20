# TASK-261: Comprehensive Unit Tests — ShellTool Security

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-259
**Assigned-to**: null

---

## Context

> Write the comprehensive test suite for the entire ShellTool security system. 50+ tests covering all 6 validation layers, all 3 security levels, all command rules, sandbox enforcement, integration with ShellTool, and backward compatibility.

---

## Scope

### Test Files
- `tests/tools/shell_tool/test_security_models.py` — ValidationResult, CommandRule, enums
- `tests/tools/shell_tool/test_security_policy.py` — SecurityPolicy presets and defaults
- `tests/tools/shell_tool/test_command_sanitizer.py` — 6-layer validation pipeline
- `tests/tools/shell_tool/test_command_rules.py` — Per-command argument restrictions
- `tests/tools/shell_tool/test_sandbox.py` — Path sandbox enforcement
- `tests/tools/shell_tool/test_security_levels.py` — RESTRICTIVE/MODERATE/PERMISSIVE behavior
- `tests/tools/shell_tool/test_shell_tool_security.py` — Integration with ShellTool
- `tests/tools/shell_tool/conftest.py` — Shared fixtures (policies, sanitizers)

### Test Coverage (from spec Section 4)

**SecurityPolicy & Presets** (6 tests):
- Restrictive preset defaults, moderate preset defaults, permissive preset defaults
- Safe defaults contains expected commands, custom commands merged, denied commands comprehensive

**CommandSanitizer Validation** (21 tests):
- Deny: rm -rf, rm -r, dd, mkfs, fork bomb, shutdown, sudo, eval
- Deny: command substitution, backtick expansion, process substitution
- Deny: sensitive paths, kernel fs access, pipe to shell
- Allow: safe git, safe python, safe echo, safe ls
- Limits: command length, malformed command, empty command

**CommandRule Argument Restrictions** (8 tests):
- curl -o denied, curl file:// denied, find -exec denied, find -delete denied
- sed -i denied, awk system() denied, python -c dangerous denied, pip --target denied

**Path Sandbox** (5 tests):
- Inside allowed, outside denied, traversal denied, URLs ignored, flags skipped

**SecurityLevel Behavior** (7 tests):
- Restrictive denies/allows, moderate denies/allows, permissive denies/allows

**ValidationResult** (4 tests):
- Frozen, str format, risk score range, batch validation

**ShellTool Integration** (8 tests):
- Default moderate, rejects rm -rf, allows echo, plan validates steps
- Custom policy, no-policy backward compat, error has result, output truncation

**Backward Compatibility** (2 tests):
- Old FORBIDDEN_PATHS still blocked, old FORBIDDEN_CMD_PATTERN covered

**Total: 61+ tests**

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `tests/tools/shell_tool/conftest.py` | CREATE | Shared fixtures: policies, sanitizers, sample commands |
| `tests/tools/shell_tool/test_security_models.py` | CREATE | ValidationResult, CommandRule, enums |
| `tests/tools/shell_tool/test_security_policy.py` | CREATE | SecurityPolicy presets and defaults |
| `tests/tools/shell_tool/test_command_sanitizer.py` | CREATE | 6-layer validation pipeline |
| `tests/tools/shell_tool/test_command_rules.py` | CREATE | Per-command argument restrictions |
| `tests/tools/shell_tool/test_sandbox.py` | CREATE | Path sandbox enforcement |
| `tests/tools/shell_tool/test_security_levels.py` | CREATE | RESTRICTIVE/MODERATE/PERMISSIVE |
| `tests/tools/shell_tool/test_shell_tool_security.py` | CREATE | Integration with ShellTool |

---

## Implementation Notes

- All sanitizer tests can be pure unit tests — no subprocess execution needed
- ShellTool integration tests should mock subprocess to avoid actual command execution
- Use `pytest.mark.parametrize` for test vectors where appropriate
- Use `tmp_path` fixture for sandbox tests
- Import from `parrot.tools.shell_tool.security`

---

## Acceptance Criteria

- [ ] 50+ unit tests across all test files
- [ ] All 6 validation layers covered
- [ ] All 3 security levels covered
- [ ] All default command rules tested
- [ ] Sandbox enforcement tested with real path resolution
- [ ] ShellTool integration tested (mocked subprocess)
- [ ] Backward compatibility verified
- [ ] All tests pass: `pytest tests/tools/shell_tool/ -v`
- [ ] No ruff lint errors

---

## Agent Instructions

1. **Read** spec Section 4 (Testing) for full test matrix
2. **Read** `parrot/tools/shell_tool/security.py` for implementation details
3. **Create** test files with shared conftest
4. **Run** `pytest tests/tools/shell_tool/ -v`
5. **Run** `ruff check tests/tools/shell_tool/`
6. **Move** to completed, update index

---

## Completion Note

Completed 2026-03-09. 94 new tests added across 5 new files (320 total in shell_tool suite):

- `conftest.py` — shared fixtures: policies, sanitizers, sample commands, sandbox_dir
- `test_command_rules.py` — 32 tests: curl (−o, −O, file://, gopher://), wget (file://, --post-data), find (−exec, −execdir, −delete), sed (−i), awk (system(), getline), python3 (-c dangerous), pip (--target, --prefix, --root), git
- `test_sandbox.py` — 15 tests: inside/outside sandbox, path traversal, URL ignored, flags skipped, validate_path() for file actions including sensitive/kernel path detection
- `test_security_levels.py` — 20 tests: RESTRICTIVE (empty allowlist, unlisted denied, explicit allowed), MODERATE (safe defaults, denied list, unknown denied), PERMISSIVE (arbitrary allowed, sudo still denied, custom denied), level comparison
- `test_shell_tool_security.py` — 27 tests: default moderate policy, policy injection (custom/restrictive/permissive/None), assert_command_safe raises on denied, plan raises for dangerous steps, no-policy backward compat, output truncation config wiring

All 320 tests pass; ruff reports no lint errors.

Note: Actual subprocess execution was NOT tested due to system-level issue: `/bin/sh -l` (login shell) sources a broken `/etc/profile` on this machine. All security validation logic is tested at the Python level without subprocess invocation.
