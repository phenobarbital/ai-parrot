# TASK-4542: Retire the dead escalation-ledger writes in `select_tests` and the supervisor

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:9b27d46a6bb2`

---

## Context

FEAT-699 moved core/cap escalation out of planning: `plan_tests()` builds its
plan through `build_plan(...)` **without** passing `escalated=` or
`skipped_escalations=` (`test_scope/select.py:246-258`), and a core hit became a
plan *note* ("covered by nightly", `select.py:241`) instead of a `core` target.
No production path can therefore emit a `TestTarget` whose `reason` is `"core"`
or `"escalated"`, and `plan.escalated` / `plan.skipped_escalations` are always
empty tuples.

Two consumers of that retired contract are still live and are now unreachable
code: the escalation-ledger writes in `scripts/sdd/select_tests.py` and
`ValidationSupervisor._record_invocation_outcome` in `background.py`, plus the
always-empty fields printed by the CLI and by `_selection_header`.

The sibling issue `issue:1e684c2b1d72` (closed by PR #1731) already rewrote the
*planner* tests for the new semantics; the tests that still exercise these dead
branches do so by hand-building synthetic legacy plans, so they only prove that
dead code still runs.

---

## Scope

- Remove the two escalation-ledger write blocks from `scripts/sdd/select_tests.py`
  (`is_core_escalation` / `is_cap_escalation` and the `record_red_run` /
  `record_green_escalation` calls they guard).
- Remove the two always-empty CLI print loops (`# escalated:` and `# skipped:`).
- Re-point `--no-ledger`: the flag **stays** (it still guards the green-cache
  write at `select_tests.py:520` and `/sdd-done` passes it) — only its help text
  changes to describe the green cache.
- Remove `ValidationSupervisor._record_invocation_outcome`, its single call site,
  and the now-unused `record_green_escalation` / `record_red_run` import in
  `background.py`.
- Drop the always-empty `escalated=` / `skipped_escalations=` fields from
  `_selection_header`'s `# selection …` line.
- Delete the tests that only exercised the removed branches and update the one
  header assertion.

**NOT in scope**:
- `record_green_escalation` / `record_red_run` themselves in
  `test_scope/context.py` — `parrot/flows/dev_loop/nodes/qa.py:62,634` still
  calls `record_green_escalation`, so the module API stays.
- The `escalated` / `skipped_escalations` **fields** on `ScopePlan` /
  `ScopePlanModel`. They are constructed positionally or by keyword in ~8 test
  modules and carried through `green_cache.py:207-209`; removing the fields is a
  separate, wider change.
- The `core_hits` field and the "covered by nightly" note — still live.
- Anything in `_run_verdict_mode` (that is TASK-4543).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/select_tests.py` | MODIFY | Drop dead escalation-ledger writes + dead print loops; re-point `--no-ledger` help |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | Drop `_record_invocation_outcome`, its call site, its import, and the dead header fields |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | Delete the three synthetic-legacy-plan ledger tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py` | MODIFY | Delete the five `_record_invocation_outcome` tests; update the selection-header assertion |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/sdd/select_tests.py — imported lazily inside the removed blocks only
import test_scope.context as ledger  # verified: select_tests.py:469, 475 (both go away)

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:54 — becomes unused
from parrot.flows.dev_loop.test_scope.context import record_green_escalation, record_red_run
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py:59 — EXACT current line; only the help string changes
    parser.add_argument("--no-ledger", action="store_true", help="report-only: never touch the escalation ledger")

# scripts/sdd/select_tests.py:520 — LIVE use of the same flag; must keep working
    if namespace is not None and not args.no_ledger:

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:1417
    async def _record_invocation_outcome(
        self, *, worktree: Path, invocation: "Invocation", plan: "ScopePlan", exit_code: int
    ) -> None:

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:1510
    @staticmethod
    def _selection_header(plan: "ScopePlan") -> str:

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py:246 — proves the
# planner never passes escalated / skipped_escalations
    return build_plan(
        targets, tier=tier, worktree=worktree, policy=policy,
        core_hits=hits, notes=notes, contract=contract, mode=mode, registry=registry,
    )
```

### Does NOT Exist
- ~~a production path emitting `TestTarget(reason="core")` or `reason="escalated"`~~ —
  `plan_tests` cannot produce one (verified: `select.py:139-258`)
- ~~`plan.skipped_escalations` non-empty from `plan_tests`~~ — defaults to `()` in
  `build_plan` (verified: `planner.py:76`) and is never passed
- ~~`ScopePlan.skipped_escalations` is removable here~~ — still a constructor
  keyword in 8 test modules; out of scope

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/select_tests.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_select_tests.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#_build_parser",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._record_invocation_outcome",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py#ValidationSupervisor._selection_header",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/select.py#plan_tests"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `--no-ledger` is a **public CLI contract**: `.claude/commands/sdd-done.md:266`,
  `.agent/workflows/sdd-done.md:179` and `.agents/skills/sdd-done/SKILL.md:133`
  all pass it, and `test_done_optimization_contract.py:124` asserts the literal
  string `--no-ledger` appears in those docs. Keep the flag and keep its
  green-cache behaviour at `select_tests.py:520`.
- Deleting `_record_invocation_outcome` must not change the surrounding
  invocation loop's control flow in `_supervise` — it is a fire-and-forget call
  between `_read_log_since` and `_parse_invocation_report`.
- `test_scope/context.py` is untouched; do not remove its functions.

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py:618-640` — the remaining
  live caller of `record_green_escalation`, which is why the module stays.

---

## Implementation Blueprint

### Steps (in order)
1. Edit `select_tests.py` — delete the dead print loops and both ledger blocks; reword the `--no-ledger` help — *why*: these branches are unreachable from `plan_tests`.
2. Edit `background.py` — delete the import, the call site, the method and the dead header fields — *why*: same retired contract, supervisor side.
3. Delete the tests that only build synthetic legacy plans; update the header assertion — *why*: they assert on code that no longer exists.
4. Run the validation commands — *why*: AC gate.

### `scripts/sdd/select_tests.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'help="report-only: never touch the escalation ledger"' scripts/sdd/select_tests.py)
# REPLACE line 59 with:
    parser.add_argument(
        "--no-ledger", action="store_true", help="report-only: never write the green test cache"
    )

# DELETE lines 361-364 verbatim (the two dead loops; keep the `# note:` loop above them):
#        for dist in plan.escalated:
#            print(f"# escalated: {dist}")  # noqa: T201 - CLI output
#        for dist in plan.skipped_escalations:
#            print(f"# skipped: {dist}")  # noqa: T201 - CLI output

# DELETE the FEAT-699 comment block and both ledger branches (lines 452-483):
#   - the `# FEAT-699: ...` comment through `is_cap_escalation = ...`
#   - inside `if result.returncode != 0:` the trailing
#       `if not args.no_ledger and (is_core_escalation or is_cap_escalation): ... record_red_run(...)`
#     leaving the `continue` in place
#   - the whole `if not args.no_ledger and (is_core_escalation or is_cap_escalation):`
#     block that calls `record_green_escalation`
```
**Why this shape**: the loop keeps collecting `failed_nodeids` / `unclassified_failure`
exactly as before; only the ledger side effects go. `--no-ledger` survives because its
*other* reader (the green cache, line 520) is live.

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot.flows.dev_loop.test_scope.context import record_green_escalation, record_red_run' <file>)
# DELETE line 54 entirely.

# DELETE the call site at lines 1036-1038:
#            await self._record_invocation_outcome(
#                worktree=worktree, invocation=invocation, plan=plan, exit_code=exit_code
#            )

# DELETE the whole `async def _record_invocation_outcome(...)` method (lines 1417-1447).

# REPLACE the _selection_header body's first element (lines 1513-1517) with:
        lines = [f"# selection tier={plan.tier}\n"]
```
**Why**: `escalated` and `skipped_escalations` are always empty, so the header's
two bracket pairs are noise. `plan` may become an unused parameter of
`_supervise` after the call site goes — check and leave it if other code reads it.

### FILL IN checklist
- [ ] `background.py::_supervise` — confirm `plan` is still used after the call-site removal; if not, drop the now-unused local/parameter only if nothing else reads it.

---

## Acceptance Criteria

- [ ] `grep -n "is_core_escalation\|is_cap_escalation\|record_red_run\|record_green_escalation" scripts/sdd/select_tests.py` returns nothing
- [ ] `grep -n "_record_invocation_outcome\|record_green_escalation\|record_red_run" packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` returns nothing
- [ ] `scripts/sdd/select_tests.py --no-ledger` still parses and still suppresses the green-cache write (line ~520 unchanged)
- [ ] `_selection_header` emits `# selection tier=<tier>` with no `escalated=` / `skipped_escalations=` fields
- [ ] `test_scope/context.py` is unmodified and `nodes/qa.py` still imports `record_green_escalation`
- [ ] All validation commands pass
- [ ] `ruff check scripts/sdd/select_tests.py packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` is clean

---

## Validation Commands

- `pytest tests/sdd_scripts/test_select_tests.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_done_optimization_contract.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_context.py -q`

---

## Test Specification

Tests to **delete** (they build synthetic legacy plans with `reason="escalated"`,
which `plan_tests` can no longer produce):

- `tests/sdd_scripts/test_select_tests.py::test_run_records_green_cap_escalation`
- `tests/sdd_scripts/test_select_tests.py::test_run_rearms_red_cap_escalation`
- `tests/sdd_scripts/test_select_tests.py::test_no_ledger_skips_escalation_ledger`
- `test_supervisor_ledger.py::test_supervisor_records_green_escalation`
- `test_supervisor_ledger.py::test_supervisor_rearms_on_red_escalation`
- `test_supervisor_ledger.py::test_supervisor_rearms_on_timeout`
- `test_supervisor_ledger.py::test_supervisor_records_nothing_without_escalation`
- `test_supervisor_ledger.py::test_supervisor_ledger_failure_never_fails_validation`

Tests to **keep** (they are now regression guards that the ledger is never touched):

- `tests/sdd_scripts/test_select_tests.py::test_run_red_fallback_run_leaves_ledger_untouched`
- `tests/sdd_scripts/test_select_tests.py::test_run_core_change_without_contract_is_a_note_never_an_escalation`

Test to **update**:

```python
# packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_supervisor_ledger.py:250
    assert empty_log.startswith("# selection tier=merge\n")
```

---

## Agent Instructions

Follow the standard SDD task loop (see `sdd/templates/task.md` §Agent Instructions).
Work in `.claude/worktrees/feat-FEAT-709-language-agnostic-validation-runners`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: Claude Opus 5 (/sdd-fix, agent:sdd-fix)
**Date**: 2026-10-21
**Notes**: Removed both escalation-ledger write blocks and the two always-empty
print loops from `select_tests.py`; removed `_record_invocation_outcome`, its
call site, its import and the dead `escalated=`/`skipped_escalations=` header
fields from `background.py`. `--no-ledger` was kept — its green-cache reader at
`select_tests.py:493` is live and `/sdd-done` passes the flag — with the help
text re-pointed at the cache. Deleted the 8 tests that only exercised the
removed branches through synthetic legacy plans; kept
`test_run_red_fallback_run_leaves_ledger_untouched` and
`test_run_core_change_without_contract_is_a_note_never_an_escalation` as
regression guards and refreshed the former's docstring.
Verified: `plan` is still used by `_supervise` (`cached`, `notes`,
`plan=invocation_plan`), so the parameter stays — FILL IN item resolved.
Evidence: `tests/sdd_scripts/test_select_tests.py` 21 passed;
`test_scope` + `sdd_coder` suites 840 passed; `ruff check` clean on all four files.

**Deviations from spec**: Three header assertions in
`test_start_logs_selection_summary` needed updating, not the one the task file
predicted — the test also pins the all-skipped and non-empty headers. Their
intent (an all-skipped plan stays distinguishable from an empty diff) is
preserved: the distinction now rides the `# note:` line the plan already emits.
The task file's premise that `is_core_escalation = bool(plan.core_hits)` was
stale — that gate had already been narrowed to `invocation.targets` on this
branch; the remaining debt was the unreachable ledger writes themselves.
