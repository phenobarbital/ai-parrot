---
type: feature
base_branch: dev
feature_id: FEAT-832
projects: [ai-parrot]
tags: [sdd, sandbox, hooks, tests, ledger-fix]
discovered_from: issue:ca2e26e666cd
docs:
  policy: none
---

# Feature Specification: native-mode hook entry-point test sets launcher markers

**Feature ID**: FEAT-832
**Date**: 2026-11-07
**Author**: Jesus Lara (spec drafted with Claude via /sdd-fix)
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

`packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py::test_packaged_hook_entry_point_denies_in_native_mode_without_import_error`
fails on `origin/dev` with `KeyError: 'permissionDecision'`.

The test runs `python -m parrot.sdd.scripts.worktree_environment --hook` with only
`PARROT_SDD_SANDBOX_BACKEND=claude-native` set, and a Write to `<linked worktree>/.claude/settings.local.json`.
Since a7cec86e23 (2026-11-04), `worktree_environment.main` trusts `claude-native` only when both
`LAUNCHER_MARKERS` (`PARROT_SDD_SANDBOX_ROOTS`, `PARROT_SDD_CACHE_DIR`) are also set; otherwise it selects
`auto`. In `auto`, file tools go through `validate_write_path`, which guards only shared environments, so the
Write gets no decision. The native module (`validate_native_write_path`, which denies control paths) is never
loaded, so the test no longer exercises what its docstring says (TASK-5093: the packaged `-m` entry point
loads the sibling native module without an import error).

### Goals

- The test exercises the trusted native path again by exporting both launcher markers, and passes.
- The test environment is hermetic: inherited `PARROT_SDD_*` variables from the developer's shell do not leak in.

### Non-Goals (explicitly out of scope)

- No change to `worktree_environment.main`, `hook_response` or `native_claude_sandbox`.
- No change to what `auto` mode guards for file tools.

### Decision

The fallback from an untrusted `claude-native` to `auto` is intentional (a7cec86e23, covered by
`test_main_hand_exported_claude_native_falls_back_to_auto`). An untrusted request is treated like an
unlaunched session, whose file-tool guard is `validate_write_path`. The defect is the stale test, not the guard.

---

## 2. Architectural Design

Test-only change. In the failing test, build `env` from `os.environ` minus every `PARROT_SDD_*` key, then set
`PARROT_SDD_SANDBOX_BACKEND=claude-native`, `PARROT_SDD_SANDBOX_ROOTS=<feature>:<main>/.git:<main>`
(the same frozen-roots value used elsewhere in the file) and `PARROT_SDD_CACHE_DIR=<tmp_path>/cache`.

---

## 3. Module Breakdown

### Module 1: entry-point test markers
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py`
- **Responsibility**: export the launcher markers in `test_packaged_hook_entry_point_denies_in_native_mode_without_import_error`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_packaged_hook_entry_point_denies_in_native_mode_without_import_error` | M1 | with both markers, the Write to `.claude/settings.local.json` is denied by the native policy, not by a guard failure or import error |
| `test_main_hand_exported_claude_native_falls_back_to_auto` | M1 (unchanged) | still passes: without both markers the hook falls back to `auto` |

### Validation Contract

tests:
- packages/ai-parrot/tests/flows/dev_loop/test_worktree_environment.py
markers: none

### Test Data / Fixtures

None — the test builds its own `tmp_path` worktrees via `_native_hook_worktrees`.

---

## 5. Acceptance Criteria

- [ ] AC-1 `test_packaged_hook_entry_point_denies_in_native_mode_without_import_error` passes on the feature branch.
- [ ] AC-2 `test_worktree_environment.py` passes in full.
- [ ] AC-3 No source file under `packages/ai-parrot/src/` changes.
- [ ] `ruff check` clean on the changed file.

---

## 6. Codebase Contract

- `LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")` — `worktree_environment.py:572`.
- `main()` falls back to `auto` without both markers — `worktree_environment.py:795`.
- `ROOTS_ENV = "PARROT_SDD_SANDBOX_ROOTS"` (root, common git dir, primary checkout) — `native_claude_sandbox.py:35`.
- `_native_hook_worktrees(tmp_path) -> (feature, task, main)` — `test_worktree_environment.py:710`.
- Frozen-roots value precedent — `test_worktree_environment.py:919`.

---

## 7. Implementation Notes & Constraints

Run tests from the worktree with `PYTHONPATH=packages/ai-parrot/src`.

---

## 8. Open Questions

None.

---

## Revision History

| Rev | Date | Change |
|---|---|---|
| 0.1 | 2026-11-07 | Initial spec from ledger issue `issue:ca2e26e666cd` |
