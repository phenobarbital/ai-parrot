# TASK-4413: `ValidationSupervisor` records per-task test results

**Feature**: FEAT-695 — sdd-done test-results table
**Spec**: `sdd/specs/sdd-done-tests.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4411
**Assigned-to**: unassigned

---

## Context

This task implements spec §3 Module 3. `coder_run_validation` (the sdd-coder MCP seat path) runs
pytest through `ValidationSupervisor`. It must produce the same per-task records as the CLI: one
record per `task_ids` entry, with `source="coder_run_validation"` (spec AC2).

---

## Scope

- Carry `feature` and `task_ids` from `start()` into `_supervise()`.
- At both spawn sites (first invocation, and chained invocations), build the argv with a unique junit path before `protected_argv(...)`.
- After each `_await_one`, parse the junit and call `append_suite` once per task id. A `timed_out` outcome → `timed_out=True`.
- Resolve `feature` to a `FEAT-<NNN>` id: if it does not match `^FEAT-\d+$`, look up the per-spec index header `feature_id` (`sdd/tasks/index/*.json` under the worktree, matching `feature`). If that fails, record under the raw value and log a warning.
- Recording never raises and never changes `outcome`/`exit_code`.
- Add tests to `test_background_validation.py`.

**NOT in scope**: `_record_invocation_outcome` ledger semantics (unchanged); MCP models/toolkit signatures (unchanged — `feature`/`task_ids` already exist).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | junit at spawn + recording |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py` | MODIFY | new tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.select import changed_files, plan_tests  # verified: background.py:46
from parrot.flows.dev_loop.test_scope import report as test_report             # NEW module from TASK-4411
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
class ValidationSupervisor:                                                       # line 430
    async def start(self, *, feature: str, worktree: Path, execution_id: str, task_ids: list[str],
                    tier: Literal["merge", "feature"], timeout_seconds: int, request_id: str,
                    base_ref: Optional[str] = None) -> BackgroundRegistration     # line 487
    #   first, *rest = plan.invocations ; sandboxed_argv = protected_argv(worktree, list(first.argv))   ~line 591
    #   process = await asyncio.create_subprocess_exec(*sandboxed_argv, cwd=worktree, ...)              line 595
    async def _supervise(self, *, execution_id, handle, process, log_path, deadline,
                         remaining_invocations, first_invocation, plan, worktree) -> None               # ~line 725
    #   chained: next_process = await asyncio.create_subprocess_exec(...)                                line 757
    async def _record_invocation_outcome(self, *, worktree, invocation, plan, exit_code: int) -> None   # line 785
    async def _await_one(self, *, process, log_path, deadline) -> Tuple[Literal["completed","failed","timed_out"], int]  # line 816
_DEFAULT_BASE_REF = "origin/dev"                                                  # line 74
# test file helpers: _make_supervisor (line 41), _single_invocation_plan (line 53), _settle (line 59)
```

### Does NOT Exist
- ~~`ValidationSupervisor._record_test_results`~~ — create it in this task (name fixed below).
- ~~a counts field on the registry record~~ — counts go ONLY to `test_report` records; do not change `BackgroundRegistration`/registry schemas.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._record_invocation_outcome"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `_record_test_results` next to `_record_invocation_outcome`. *Why*: it keeps the ledger hook untouched and isolates best-effort recording.
2. Junit-augment the argv at both spawn sites, BEFORE `protected_argv`. *Why*: the sandbox binds `/tmp/claude-<uid>` (`worktree_environment.py:148`), so the default report root is writable inside bwrap.
3. Thread `feature_id`, `task_ids`, `base_ref` and the per-invocation junit paths into `_supervise` as new keyword args.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    async def _record_invocation_outcome(' background.py)
# BEFORE — insert above `    async def _record_invocation_outcome(` (verified: background.py:785)
    async def _record_test_results(
        self, *, worktree: Path, feature_id: str, task_ids: list[str], invocation: "PytestInvocation",
        junit_path: Path, exit_code: int, duration_s: float, timed_out: bool, tier: str, base_ref: str,
    ) -> None:
        """FEAT-695: write one test_report record per task id. Never raises, never alters the outcome."""
        try:
            # FILL IN: head_sha via `git rev-parse HEAD` (asyncio.to_thread); parse_junit; append_suite per task id, source="coder_run_validation"
            pass
        except Exception:  # noqa: BLE001 — recording must never fail a validation
            self.logger.warning("could not record test results for %s", invocation.distribution, exc_info=True)
```
```python
# occurrences: 2 (verified: grep -c 'process = await asyncio.create_subprocess_exec(' background.py)
# FILL IN: disambiguate — site 1 is preceded by `sandboxed_argv = protected_argv(worktree, list(first.argv))` (~line 591);
#          site 2 is `next_process = await asyncio.create_subprocess_exec(` inside the `for invocation in remaining_invocations:` loop (~line 757).
#          At both: argv = list(test_report.with_junit(inv, junit)) before protected_argv; record timing around _await_one,
#          then `await self._record_test_results(...)` right after the existing `_record_invocation_outcome(...)` call.
```
**Why**: the junit argument must reach pytest inside the sandbox. The registry/outcome code paths stay byte-identical except for that argument.

### FILL IN checklist
- [ ] feature → `FEAT-<NNN>` resolution via the per-spec index header (fallback: raw value + warning)
- [ ] junit path per invocation via `test_report.junit_path_for(feature_id, task_id_for_path, dist, ordinal)` — use the first task id for the file name; the record goes to every task id
- [ ] `timed_out=True` when `_await_one` returns `"timed_out"`
- [ ] tests: `test_supervisor_records_per_task` (2 task_ids → 2 records), `test_supervisor_timeout_status`, and a test that an unwritable report root leaves `outcome`/`exit_code` unchanged

---

## Acceptance Criteria
- [ ] Spec AC2 and AC7 hold for `coder_run_validation`.
- [ ] Existing tests in `test_background_validation.py` still pass.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`

---

## Agent Instructions
Follow `sdd/templates/task.md` § Agent Instructions. Close with `scripts/sdd/close_task.sh TASK-4413 sdd-done-tests verified`.

---

## Completion Note
*(Agent fills this in when done)*
