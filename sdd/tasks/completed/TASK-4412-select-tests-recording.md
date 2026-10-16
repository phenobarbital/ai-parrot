# TASK-4412: `select_tests.py` — `--feature/--report-task/--no-ledger` recording

**Feature**: FEAT-695 — sdd-done test-results table
**Spec**: `sdd/specs/sdd-done-tests.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4411
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 2. It wires the kernel (TASK-4411) into the CLI used by the
sdd-worker fallback lane and by `/sdd-done`'s closeout re-run. `--no-ledger` makes a run
report-only, so the closeout never mutates the escalation ledger (spec §9 S6, AC12).

---

## Scope

- Add flags `--feature`, `--report-task`, `--no-ledger` to `_build_parser()`.
- In the `--run` loop, when both `--feature` and `--report-task` are set:
  - compute a unique junit path per invocation;
  - run `report.with_junit(...)` (keeping the existing `--timeout` append);
  - time the run;
  - `report.append_suite(..., source="select_tests", tier=args.tier)` with `head_sha` (`git rev-parse HEAD` in the worktree) and `base_ref=args.base`.
- When `--report-task` is set and the plan has no invocations, write a record with a `selection_error` note.
- With `--no-ledger`, skip `record_red_run` / `record_green_escalation`.
- Without the new flags, the argv and behaviour stay byte-identical (regression test).
- Add tests to `tests/sdd_scripts/test_select_tests.py`.

**NOT in scope**: kernel logic (TASK-4411), `background.py`, the CLI `test_report.py`, any `.md`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/select_tests.py` | MODIFY | flags + recording in the run loop |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/sdd/select_tests.py never imports parrot. Kernel modules are reached through _load_kernel():
kernel = _load_kernel()                    # line 20 — returns top-level `test_scope`
import test_scope.report as report_mod     # same path-dependent pattern as `import test_scope.guard as guard_mod` (line ~79), with `# noqa: PLC0415`
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py
def _build_parser() -> argparse.ArgumentParser          # line 29; --json at line 36, --timeout after it
def main(argv: list[str] | None = None) -> int          # line 52
#   plan = kernel.plan_tests(worktree=..., changed_files=kernel.changed_files(worktree, args.base), tier=..., declared=...)
#   run loop (lines 100-125):
#     argv = list(invocation.argv); if args.timeout is not None: argv.append(f"--timeout={args.timeout}")
#     result = subprocess.run(argv, cwd=worktree)        # line 108
#     kernel.context.record_red_run(worktree, [invocation.distribution])            # line 115
#     kernel.context.record_green_escalation(worktree, [dist], core_files, ...)      # line 123
# test_scope/report.py (TASK-4411): junit_path_for, with_junit, parse_junit, append_suite, RERUN_RECORD
```

### Does NOT Exist
- ~~`--junitxml` / `--report-json` flags~~ — the flags are exactly `--feature`, `--report-task`, `--no-ledger`.
- ~~`kernel.report`~~ — `test_scope/__init__.py` does not export it; import `test_scope.report` explicitly.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/select_tests.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_select_tests.py", "action": "MODIFY"}
  ],
  "contract_symbols": ["sym:scripts/sdd/select_tests.py#main", "sym:scripts/sdd/select_tests.py#_build_parser"]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add the three flags after `--json`. *Why*: spec §3 M2 fixes these names; TASK-4415 writes them into the command text.
2. Gate recording on `args.feature and args.report_task`. *Why*: no flags → byte-identical argv (AC1).
3. Wrap the ledger calls in `if not args.no_ledger:`. *Why*: AC12.

### `scripts/sdd/select_tests.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    parser.add_argument("--json", action="store_true")' scripts/sdd/select_tests.py)
# AFTER — insert below `    parser.add_argument("--json", action="store_true")` (verified: scripts/sdd/select_tests.py:36)
    parser.add_argument("--feature", default=None, help="FEAT-<NNN>: record structured results (FEAT-695)")
    parser.add_argument("--report-task", default=None, help="TASK-<NNN> or _rerun: record owner (FEAT-695)")
    parser.add_argument("--no-ledger", action="store_true", help="report-only: never touch the escalation ledger")
```
```python
# occurrences: 1 (verified: grep -c '        result = subprocess.run(argv, cwd=worktree)' scripts/sdd/select_tests.py)
# REPLACE `        result = subprocess.run(argv, cwd=worktree)` (verified: scripts/sdd/select_tests.py:108)
        recording = bool(args.feature and args.report_task)
        if recording:
            junit = report_mod.junit_path_for(args.feature, args.report_task, invocation.distribution, ordinal)
            argv = list(report_mod.with_junit(SimpleInvocation(argv), junit))  # FILL IN: build from local argv, not invocation.argv
        started = time.monotonic()
        result = subprocess.run(argv, cwd=worktree)
        if recording:
            # FILL IN: parse_junit(...) + append_suite(..., head_sha=head_sha, base_ref=args.base, tier=args.tier, source="select_tests")
            pass
```
**Why**: the local `argv` already carries `--timeout`. The junit argument must be appended to that local list, never to `invocation.argv`, which stays unmodified (comment at line 102). `SimpleInvocation` is illustrative only. FILL IN: append `f"--junitxml={junit}"` directly, or call `with_junit` on an invocation copy. `ordinal` comes from `enumerate(plan.invocations)`. Resolve `head_sha` once, before the loop.

### FILL IN checklist
- [ ] junit append on the local argv only — keep `--timeout` behaviour (test at line 246 must still pass)
- [ ] empty plan + `--report-task` → `append_suite`-equivalent record carrying a `selection_error` note
- [ ] `if not args.no_ledger:` around both ledger calls
- [ ] tests: `test_select_tests_flags_absent_is_identical`, `test_select_tests_records`, `test_no_ledger_skips_escalation_ledger`, `test_empty_plan_selection_error` (reuse `fixture_monorepo` + `_captured_argvs`; set `SDD_TEST_REPORT_DIR` to tmp)

---

## Acceptance Criteria
- [ ] Spec AC1, AC7, AC12 hold for the CLI.
- [ ] All existing tests in `tests/sdd_scripts/test_select_tests.py` still pass.

## Validation Commands
- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Agent Instructions
Follow `sdd/templates/task.md` § Agent Instructions. Close with `scripts/sdd/close_task.sh TASK-4412 sdd-done-tests verified`.

---

## Completion Note

- Task: TASK-4412
- Feature: sdd-done-tests
- Implementation SHA: fba50fb24014c5127f8d3fb40b7f42dbb2da152c
- Closed at (UTC): 2026-10-16T01:22:46+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 121.7s · Tokens: n/a |
