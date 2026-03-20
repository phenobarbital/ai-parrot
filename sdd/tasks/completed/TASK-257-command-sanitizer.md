# TASK-257: CommandSanitizer — 6-Layer Validation Pipeline

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-255, TASK-256
**Assigned-to**: claude-session

---

## Context

> Implement the `CommandSanitizer` class with its 6-layer validation pipeline. This is the core security engine that validates every command string before execution. Also includes the dangerous patterns registry.

---

## Scope

### Dangerous Patterns Registry
- Module-level `_DANGEROUS_PATTERNS: List[Tuple[str, str, float]]` — 20+ regex patterns with descriptions and risk scores
- Categories: command substitution, process substitution, chaining, pipes, redirects, env expansion, path traversal, sensitive files, kernel/device access, eval/exec/source, xargs, device node creation

### CommandSanitizer class
- `__init__(self, policy: SecurityPolicy)` — pre-compile all regex patterns, resolve sandbox_dir
- `validate(self, command: str) → ValidationResult` — main entry point, runs all 6 layers
- `validate_batch(self, commands: List[str]) → List[ValidationResult]`
- Internal methods:
  - `_extract_base_command(token)` — handles `/usr/bin/ls` → `ls`
  - `_check_patterns(command)` — Layer 2: dangerous pattern detection
  - `_is_pattern_allowed(reason)` — checks policy toggles for each pattern type
  - `_check_command_access(base_cmd)` — Layer 3: allow/deny list by SecurityLevel
  - `_check_command_rule(rule, args, raw_command)` — Layer 4: per-command argument rules
  - `_check_path_sandbox(tokens)` — Layer 5: path sandbox enforcement
  - `_deny(command, reasons, risk)` — helper to construct DENIED result

### Validation Pipeline
1. **Layer 0**: Basic sanity — empty check, length check
2. **Layer 1**: Parse & extract — `shlex.split()`, extract base command
3. **Layer 2**: Dangerous pattern detection — match against `_DANGEROUS_PATTERNS`, filter by policy toggles
4. **Layer 3**: Command access control — RESTRICTIVE/MODERATE/PERMISSIVE logic
5. **Layer 4**: Per-command argument rules — `CommandRule` enforcement
6. **Layer 5**: Path sandbox enforcement — resolve paths, check sandbox_dir
7. **Layer 6**: Custom denied patterns — `SecurityPolicy.denied_patterns`
8. **Final verdict**: risk >= 0.7 → DENIED, >= 0.4 → NEEDS_REVIEW, < 0.4 → ALLOWED

### Pipe Chain Per-Segment Validation (from Open Q3)
- When `allow_shell_operators=True` (MODERATE), split command on `|` and validate each segment's base command against allow/deny lists
- When `allow_shell_operators=False`, pipes detected in Layer 2 and blocked

**NOT in scope**: SecureShellMixin, ShellTool integration, output truncation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/security.py` | MODIFY | Add `_DANGEROUS_PATTERNS`, `CommandSanitizer` class |

---

## Acceptance Criteria

- [ ] `_DANGEROUS_PATTERNS` list with 20+ patterns, each with description and risk score
- [ ] `CommandSanitizer.__init__` pre-compiles all regexes
- [ ] `validate()` returns `ValidationResult` with correct verdict for all test vectors
- [ ] Layer 0: empty → ALLOWED, too-long → DENIED
- [ ] Layer 1: malformed (shlex error) → DENIED
- [ ] Layer 2: `$(...)` and backticks → DENIED (unless policy allows)
- [ ] Layer 2: sensitive paths `/etc/passwd`, `/proc/` → DENIED
- [ ] Layer 3: RESTRICTIVE blocks unlisted, MODERATE blocks denied+unlisted, PERMISSIVE blocks denied
- [ ] Layer 4: `find -exec`, `curl -o`, `sed -i`, `awk system()` → DENIED
- [ ] Layer 5: paths outside sandbox_dir → DENIED, URLs skipped
- [ ] Layer 6: custom denied patterns applied
- [ ] Pipe chain validation: `cat file | bash` → DENIED when each segment checked
- [ ] `validate_batch()` works for multiple commands
- [ ] Risk thresholds: 0.7+ → DENIED, 0.4-0.7 → NEEDS_REVIEW, <0.4 → ALLOWED
- [ ] No ruff lint errors

---

## Agent Instructions

1. **Read** spec Section 2 (Validation Pipeline) and the user's reference implementation
2. **Read** existing `parrot/tools/shell_tool/security.py` (from TASK-255/256)
3. **Add** `_DANGEROUS_PATTERNS` and `CommandSanitizer` class
4. **Run** `ruff check parrot/tools/shell_tool/security.py`
5. **Write tests** in `tests/tools/shell_tool/test_command_sanitizer.py`
6. **Run** `pytest tests/tools/shell_tool/test_command_sanitizer.py -v`
7. **Move** to completed, update index

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-09

Added to `parrot/tools/shell_tool/security.py`:
- `_DANGEROUS_PATTERNS` — 21 patterns with descriptions and risk scores covering command substitution, process substitution, chaining, pipes, redirects, env expansion, path traversal, sensitive files, kernel/device fs, eval/exec/source, xargs, device node creation, hex escapes
- `CommandSanitizer` class with 6-layer validation pipeline:
  - L0: sanity (empty, length)
  - L1: shlex parse + base command extraction
  - L2: dangerous pattern detection with policy-toggle filtering
  - L3: command allow/deny list + pipe-chain per-segment validation
  - L4: per-command argument rules (CommandRule)
  - L5: path sandbox enforcement
  - L6: custom denied patterns
  - Final verdict: risk >= 0.7 → DENIED, >= 0.4 → NEEDS_REVIEW, < 0.4 → ALLOWED
- `validate_batch()` method
- Audit logging via `_logger.warning()`

72 tests pass in `tests/tools/shell_tool/test_command_sanitizer.py` (186 total across all shell_tool tests). No lint errors.

Bug fixed: source/dot pattern narrowed to `(?:^|;|&&|\|\|)\s*\.\s+\S` to prevent false positive on `find . -name`.
