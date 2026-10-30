# TASK-4936: Task-tier gate — run declared tests with the override marker; "no tests collected" is not a failure

**Feature**: FEAT-782 — sdd-coder engine fixes 3 (task-tier gate: "no tests collected" is not a failure)
**Spec**: `sdd/specs/sdd-coder-engine-fixes-3.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: agent:sdd-fix
**Discovered-from**: `issue:8c423c5612c2`

---

## Context

Spec §1 / §2 M1–M4. The task-tier gate runs a task's declared test files with
`-m "not e2e and not real_llm and not integration"`, so a task whose own tests
live under `tests/integration/` has all of them deselected; pytest exits 5 and
`build_verdict` reports `failed` with zero failures (FEAT-761 / TASK-4838:
3 attempts burned, manual merge).

## Scope

- `planner.build_plan`: declared + contract pytest targets share one permissive
  invocation per distribution, always with `OVERRIDE_MARKER_EXPRESSION`; a declared
  target whose path is also a contract target is dropped (contract reason wins).
- `PytestAdapter.parse_report`: exit 5 with 0 tests (or no report) → `status="no_tests"`.
- `verdict.build_verdict`: `no_tests` is never a failure; note per suite; all
  `no_tests` → `unavailable` + "no signal" note.
- `engine.py` gate branch: diagnostics list notes whenever the verdict has no failures.
- Tests per spec §4; update the two existing pins.

**NOT in scope**: `AGENT_MARKER_EXPRESSION`, `parse_junit`/`SuiteResult`, green cache logic, `select_tests.py`, non-pytest runners.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py` | MODIFY | declared joins the permissive invocation |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/pytest.py` | MODIFY | `no_tests` status |
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py` | MODIFY | `no_tests` handling, `unavailable` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | diagnostics text |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py` | MODIFY | 3 tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_pytest.py` | MODIFY | 2 tests + pin update |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_verdict.py` | MODIFY | 2 tests |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py` | MODIFY | pin update (mirror target) |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py` | MODIFY | diagnostics test (AC5) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.test_scope.planner import OVERRIDE_MARKER_EXPRESSION, build_plan  # verified: test_planner.py:9
from parrot.flows.dev_loop.test_scope.policy import AGENT_FLAGS, AGENT_MARKER_EXPRESSION, ScopePolicy  # verified: test_planner.py:10
from parrot.flows.dev_loop.test_scope.datatypes import RunReport, ValidationVerdict  # verified: verdict.py:7
from parrot.flows.dev_loop.test_scope.verdict import build_verdict  # verified: verdict.py:30
```

### Existing Signatures to Use
```python
# planner.py
OVERRIDE_MARKER_EXPRESSION: str = "not real_llm"                                  # :19
def _invocation(distribution, targets, *, worktree, policy, marker_expression=None) -> Invocation  # :41
def build_plan(targets, *, tier, worktree, policy, ..., contract=None, ...) -> ScopePlan  # :68
#   pytest branch anchors :114-116 (contract_paths / default_targets / contract_targets)
# runners/pytest.py
class PytestAdapter: def parse_report(self, *, report_path, exit_code, stdout, stderr, duration_s, timed_out, suite) -> RunReport  # :65
from dataclasses import replace   # already imported :6
# datatypes.py
@dataclass(frozen=True) class RunReport: runner, suite, tests, passed, failed, errors, skipped, duration_s, exit_code, status, nodes=(), failure_text={}, unmapped=0
# verdict.py
def build_verdict(*, tier, reports, baseline=(), cached=(), notes=(), evidence=()) -> ValidationVerdict  # :30
# engine.py — gate branch diagnostics, anchor :3048
#   if verdict.status == "unavailable" and verdict.notes
# report.py
def suite_name(invocation) -> str   # OVERRIDE marker -> "<dist>[contract]"
```

### Does NOT Exist
- ~~a `"no_tests"` RunReport status~~ — this task introduces it.
- ~~a per-reason marker map in `ScopePolicy`~~ — only `marker_expression`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/pytest.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/planner.py#build_plan",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/verdict.py#build_verdict"
  ]
}
```

---

## Implementation Blueprint

1. `planner.py`: replace the three anchors with a permissive group
   (`declared` + `contract`, minus declared copies of contract paths) and a
   default group (the rest); the permissive invocation uses
   `marker_expression=OVERRIDE_MARKER_EXPRESSION`; the contract marker sweep is unchanged.
2. `runners/pytest.py`: `PYTEST_NO_TESTS_EXIT = 5`; after building the report,
   if `not timed_out and exit_code == PYTEST_NO_TESTS_EXIT and report.tests == 0`
   return `replace(report, status="no_tests")`.
3. `verdict.py`: `no_tests` → note + `continue` past the failure checks;
   precedence `timed_out > failed > unavailable(all no_tests) > passed`.
4. `engine.py`: condition becomes `not verdict.failures and verdict.notes`.

## Acceptance Criteria
AC1–AC6 of the spec.

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_planner.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runner_pytest.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_verdict.py packages/ai-parrot/tests/flows/dev_loop/test_scope/test_green_cache.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_engine_validation_gate.py -q`

## Test Specification
Spec §4.

## Agent Instructions
1. Work in the FEAT-782 worktree; `PYTHONPATH=packages/ai-parrot/src` for every pytest run.
2. `ruff check --fix` the changed files.
3. Commit only listed files; `scripts/sdd/close_task.sh TASK-4936 sdd-coder-engine-fixes-3 verified`; fill the Completion Note.

---

## Completion Note

*(filled in on completion)*
