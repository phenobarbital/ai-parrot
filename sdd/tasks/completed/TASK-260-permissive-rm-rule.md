# TASK-260: Permissive Mode — rm CommandRule for Safe Single-File Deletion

**Feature**: ShellTool Security — Command Sanitizer (FEAT-038)
**Spec**: `sdd/specs/shelltool-security.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S (1-2h)
**Depends-on**: TASK-257
**Assigned-to**: claude-session

---

## Context

> Per Open Question 2: In PERMISSIVE mode, `rm` should be allowed for single-file deletion when it does NOT use recursive/force flags and does NOT target system directories. Add a `CommandRule` for `rm` that enforces these restrictions.

---

## Scope

### CommandRule for `rm` in Permissive Mode
- Move `rm` from `_DEFAULT_DENIED_COMMANDS` to a conditional: denied in RESTRICTIVE/MODERATE, allowed with restrictions in PERMISSIVE
- Create `CommandRule` for `rm`:
  - `denied_args`: `-r`, `-R`, `--recursive`, `-f`, `--force`, `-rf`, `-fr`, `-rfi`, etc. (any flag combo containing `r` or `f`)
  - `denied_patterns`: regex for recursive flags in any position
  - `sandbox_paths`: inherit from global `sandbox_dir`
  - `risk_base`: 0.6 (elevated but below denial threshold if args pass)
- Update `SecurityPolicy.permissive()` to:
  - Remove `rm` from `denied_commands`
  - Add `rm` `CommandRule` to `command_rules`

### Implementation Note
- The `CommandRule.denied_args` check must handle combined flags like `-rf`, `-rfi`, etc.
- Pattern: `re.compile(r"-[a-zA-Z]*[rRf]")` to catch any flag combination containing r, R, or f

**NOT in scope**: Allowing `rm` in MODERATE or RESTRICTIVE modes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/shell_tool/security.py` | MODIFY | Add `rm` CommandRule, update `permissive()` factory |

---

## Acceptance Criteria

- [ ] `rm` remains denied in RESTRICTIVE and MODERATE modes
- [ ] `rm file.txt` ALLOWED in PERMISSIVE mode (risk < 0.7)
- [ ] `rm -rf /tmp` DENIED in PERMISSIVE mode
- [ ] `rm -r dir/` DENIED in PERMISSIVE mode
- [ ] `rm -f file` DENIED in PERMISSIVE mode
- [ ] `rm /etc/passwd` DENIED in PERMISSIVE mode (sandbox enforcement)
- [ ] Unit tests for all `rm` scenarios
- [ ] No ruff lint errors

---

## Agent Instructions

1. **Read** `security.py` and the spec Open Question 2
2. **Modify** `_DEFAULT_DENIED_COMMANDS` and `SecurityPolicy.permissive()`
3. **Add** `CommandRule` for `rm` in `_default_command_rules()`
4. **Run** `ruff check` and `pytest`
5. **Move** to completed, update index

---

## Completion Note

Added `rm` CommandRule to `_default_command_rules()` with:
- `denied_args`: `-r`, `-R`, `--recursive`, `-f`, `--force`
- `denied_patterns`: `r"-[a-zA-Z]*[rRf]"` to catch combined flags (`-rf`, `-fr`, `-rfi`, etc.)
- `risk_base`: 0.6 (below denial threshold of 0.7 when no flags triggered)

Updated `SecurityPolicy.permissive()` to remove `rm` from the effective denied_commands set (while `_DEFAULT_DENIED_COMMANDS` still contains `rm` so MODERATE and RESTRICTIVE continue to block it). The `rm` CommandRule is included in permissive command_rules.

Also fixed pre-existing `NameError: name 're' is not defined` in `models.py` (missing import), and removed the now-unused imports after `ruff --fix`.

Updated 2 pre-existing tests that expected `rm` to be in PERMISSIVE's deny list. Added 15 new unit tests in `TestPermissiveRmRule` covering all acceptance criteria. 226 tests pass, 0 lint errors.
