---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, dev-loop]
tags: [sdd-coder, test-scope, task-tier-gate, ledger-fix]
---

# Feature Specification: sdd-coder engine fixes 3 (task-tier gate: "no tests collected" is not a failure)

**Feature ID**: FEAT-782
**Date**: 2026-10-30
**Author**: Jesus Lara (with Claude, via `/sdd-fix`)
**Status**: approved
**Target version**: next patch
**Source**: ledger fix group `fixgroup:9987fbacaf3d` (`wikitoolkit ledger plan-fix`)

---

## 1. Motivation & Business Requirements

### Problem Statement

The sdd-coder engine's task-tier gate (`SddCoderEngine._task_tier_gate`,
FEAT-709) runs the task's tests through the test-scope kernel. Two defects
combine into a false `validation_failed`:

1. **Declared targets are run under the agent marker filter.**
   `test_scope.planner.build_plan` sends every non-contract pytest target —
   including `reason="declared"`, i.e. the files the task itself names in its
   `## Validation Commands` — through the default invocation with
   `-m "not e2e and not real_llm and not integration"`. A task whose own tests
   live under `tests/integration/` (auto-marked `integration`) has all of them
   deselected. Contract targets already get the permissive
   `OVERRIDE_MARKER_EXPRESSION` (`"not real_llm"`); declared targets do not.
2. **pytest exit 5 is counted as a failure.** When every collected test is
   deselected pytest exits 5 ("no tests collected"). `parse_junit_report`
   maps any non-zero exit to `status="failed"` and `build_verdict` flags
   `exit_code != 0` with no failed nodes as an unclassified failure, so the
   verdict is `failed` with `failures=()`. The engine then reports
   "task-tier validation failed: 0 failure(s)" — a message with no signal.

Observed on FEAT-761 / TASK-4838: 3 attempts burned (retry ladder + same-seat
repair) although the task's Validation Commands pass (30 passed); `coder_merge`
refused (`validation_failed`) and the merge was done by hand.

Ledger issues covered:

| Issue | Severity | Kind | Summary |
|---|---|---|---|
| `issue:8c423c5612c2` | major | bug | task-tier gate treats "no tests collected" (pytest exit 5) as a validation failure for tests/integration |

### Goals
- Declared pytest targets run with `OVERRIDE_MARKER_EXPRESSION`, in the same
  per-distribution invocation as contract targets (one permissive invocation
  per distribution, so `suite_name()` keys stay unique).
- A pytest run that exits 5 and reports 0 tests yields `RunReport.status ==
  "no_tests"`, which is never a failure.
- `build_verdict`: `no_tests` reports add a note; when every report is
  `no_tests` the verdict is `unavailable` (fail closed, distinct reason),
  otherwise it does not change the status.
- The engine's `validation_failed` diagnostics show the verdict notes whenever
  the verdict carries no failures, instead of "0 failure(s)".

### Non-Goals (explicitly out of scope)
- Changing `AGENT_MARKER_EXPRESSION` or the marker filter for mirror / import /
  core / escalated targets.
- Letting the gate pass when it has no signal at all (all-empty stays blocking).
- Changing `parse_junit` / `SuiteResult` (test-report recording), the green
  cache, or `select_tests.py`'s exit codes.
- Non-pytest runners (exit 5 is pytest-specific).

---

## 2. Architectural Design

### Overview

**M1 — planner (`test_scope/planner.py`).** In `build_plan`'s pytest branch,
the permissive group becomes `reason in {"declared", "contract"}` (was
`"contract"` only); the default group is everything else. The permissive
invocation always uses `OVERRIDE_MARKER_EXPRESSION`. The contract marker sweep
(`(<markers>) and not real_llm`) is unchanged and still emitted only when the
contract declares markers. `marker_expression_for` keeps its signature and
behaviour (public, used by tests).

**M2 — pytest no-tests status (`test_scope/runners/pytest.py`).**
`PytestAdapter.parse_report` returns a report with `status="no_tests"` when
`not timed_out`, `exit_code == 5` and the parsed report has `tests == 0`
(including a missing report file). Constant `PYTEST_NO_TESTS_EXIT = 5`.

**M3 — verdict (`test_scope/verdict.py`).** In `build_verdict`, a `no_tests`
report skips the unclassified-failure checks and appends the note
`"<suite>: pytest collected no tests (exit 5)"`. Status precedence becomes
`timed_out > failed > unavailable (every report no_tests) > passed`; the
all-empty case also appends `"no runner collected any test; the gate has no
signal"`. An empty `reports` sequence keeps today's `passed`.

**M4 — engine diagnostics (`sdd_coder/engine.py`).** The `validation_failed`
`TaskResult.diagnostics` uses `"; ".join(verdict.notes)` whenever
`not verdict.failures and verdict.notes` (was: only for `unavailable`).

### Integration Points

| Existing Component | Change | Notes |
|---|---|---|
| `test_scope.planner.build_plan` | modify | declared joins the permissive invocation |
| `PytestAdapter.parse_report` | modify | `no_tests` status |
| `test_scope.verdict.build_verdict` | modify | `no_tests` handling + `unavailable` |
| `SddCoderEngine._run_task` gate branch | modify | diagnostics text only |
| `background.py` verdict→outcome | none | `unavailable` already maps to `failed` outcome |

---

## 3. Module Breakdown

One task (TASK-4936) covers M1–M4: the four edits are small and must land
together for the reported scenario to pass.

---

## 4. Test Specification

`packages/ai-parrot/tests/flows/dev_loop/test_scope/`:

| Test | File | Asserts |
|---|---|---|
| declared target uses override marker | `test_planner.py` | `-m` == `OVERRIDE_MARKER_EXPRESSION` for a declared-only plan |
| declared + contract share one invocation | `test_planner.py` | one invocation per distribution, both targets, override marker |
| mirror target keeps agent marker | `test_planner.py` | `-m` == `AGENT_MARKER_EXPRESSION` |
| exit 5 / 0 tests → `no_tests` | `test_runner_pytest.py` | with and without a junit file |
| exit 5 with tests > 0 stays `failed` | `test_runner_pytest.py` | no masking of real runs |
| all `no_tests` → `unavailable` + notes | `test_verdict.py` | status and both notes |
| `no_tests` + passing report → `passed` | `test_verdict.py` | note present, status passed |

Existing pins updated: `test_runner_pytest.py::…byte-identical` (declared-only
argv now carries the override marker) and `test_green_cache.py::test_marker_change_invalidates`
(uses a `mirror` target so the policy marker still drives its argv).

## 5. Acceptance Criteria

- AC1: a declared-only pytest plan's `-m` is `OVERRIDE_MARKER_EXPRESSION`.
- AC2: declared and contract targets of one distribution produce exactly one permissive invocation.
- AC3: `PytestAdapter.parse_report(exit_code=5, …)` with 0 tests returns `status == "no_tests"`.
- AC4: `build_verdict` over only `no_tests` reports returns `unavailable` with notes; mixed with a passing report returns `passed`.
- AC5: engine diagnostics for a failure-less verdict list its notes.
- AC6: the `test_scope` and `sdd_coder` test packages pass; `ruff check` clean on changed files.

## 6. Codebase Contract

See TASK-4936 (Verified Imports, Existing Signatures, Does NOT Exist).

## 7. Implementation Notes & Constraints
- Fail closed is preserved: an all-empty gate still blocks the merge, now with a readable reason.
- `suite_name()` maps `OVERRIDE_MARKER_EXPRESSION` invocations to `<dist>[contract]`; merging declared into that invocation keeps the key unique per distribution.

## 8. Open Questions
None.

## Revision History
- v0.1 (2026-10-30): initial, from `/sdd-fix issue:8c423c5612c2`.
