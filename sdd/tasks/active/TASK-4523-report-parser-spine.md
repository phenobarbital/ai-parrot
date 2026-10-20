# TASK-4523: Report parser spine: runner-aware junit, failure text, `with_report`, closeout `n/a` cells

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4520
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (report half) and codex S10: `nodeid_from_testcase` returns None unless `file` ends in
`.py` (report.py:113) and `parse_junit` keeps only `(nodeid, status)`, so vitest nodes vanish and no excerpt
can be built. Fixtures land FIRST so the change is observable. Also renders `n/a` cache/baseline cells for
non-pytest suites in the `/sdd-done` table.

---

## Scope

- Create junit fixtures under `tests/flows/dev_loop/test_scope/fixtures/`: `vitest-junit.xml`, `vitest-nested.xml`, `vitest-nofile.xml`, `pytest-failure.xml` (with a `<failure>` body > 30 lines).
- `nodeid_from_testcase(..., runner="pytest")`: non-pytest ⇒ `<file>::<name>` for any `file`.
- Add `parse_junit_report(...) -> RunReport` retaining `failure_text`; keep `parse_junit(...) -> SuiteResult` delegating to it so FEAT-699 callers are unchanged.
- Replace `with_junit` with `with_report(invocation, report_path)`; `suite_name` → `<runner>:<distribution>[…]` for non-pytest, unchanged for pytest.
- `render_markdown`: non-pytest suites show `n/a` in cached/baseline columns.

**NOT in scope**: libtest / e2e parsers (TASK-4527/4528); verdict building (TASK-4529); call-site switch from `with_junit` in background.py/select_tests.py (TASK-4530/4529).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | parser spine |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-junit.xml` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-nested.xml` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-nofile.xml` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/pytest-failure.xml` | CREATE | fixture |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | MODIFY | new parser tests |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | with_junit → with_report call site |
| `scripts/sdd/select_tests.py` | MODIFY | with_junit → with_report call site |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cb3b32639` (2026-10-20). Re-run `grep -c` on every anchor before editing.

### Verified Imports
```python
from .datatypes import Invocation, RunReport  # TASK-4520
import xml.etree.ElementTree as ET  # already used by report.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py
class SuiteResult:  # line 37 — … nodes=(), unmapped=0, baseline=()
def with_junit(invocation, junit_path: Path) -> tuple[str, ...]          # line 106 — (*argv, "-o", "junit_family=xunit1", f"--junitxml={junit_path}")
def nodeid_from_testcase(file_attr, classname, name) -> str | None       # line 111 — `.py` only (line 113)
def suite_name(invocation) -> str                                        # line 127
def parse_junit(junit_path, *, suite, argv, exit_code, duration_s, timed_out=False) -> SuiteResult   # line 146
def _baseline_counts(results) -> tuple[int|None, int|None, int|None]     # line 408
def render_markdown(records, task_ids, *, final_head, rerun, rerun_skip_reason) -> str   # line 420
# callers of with_junit (switched in later tasks, keep a thin `with_junit = …`? NO — hard cut: update them HERE):
#   packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:1029   scripts/sdd/select_tests.py:248
```

### Does NOT Exist
- ~~`parse_junit_report`, `with_report`~~ — added here
- ~~failure text retention~~ — added here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-junit.xml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-nested.xml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-nofile.xml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/pytest-failure.xml",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py",
      "action": "MODIFY"
    },
    {
      "path": "scripts/sdd/select_tests.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#parse_junit",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#nodeid_from_testcase",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#with_junit",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#suite_name",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#render_markdown"
  ]
}
```

---

## Implementation Notes

- Hard cut: `with_junit` is removed, so this task ALSO updates its two callers (background.py:1029, select_tests.py:248) to `with_report` — add those two files to the commit. (They are listed below.)
- vitest junit: `<testcase classname="src/x.test.ts" name="..." file="src/x.test.ts">`; nested `<testsuite>` elements must be walked recursively (`iter("testcase")`).
- A testcase without a usable id counts in `unmapped` and the report status stays failed when exit_code != 0.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker. Signatures, names and paths here come from the spec's Interface Skeletons (§3) and are not renegotiable.

### Steps (in order)
1. Add fixtures — *why*: S10, observable before the change.
2. Runner-aware nodeid + `parse_junit_report` — *why*: vitest nodes and excerpts.
3. `with_report` + caller updates — *why*: hard cut.
4. `render_markdown` n/a cells — *why*: spec §5 closeout rows.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def nodeid_from_testcase(' …/report.py)
# REPLACE nodeid_from_testcase signature (report.py:111) with:
def nodeid_from_testcase(file_attr: str | None, classname: str, name: str, *, runner: str = "pytest") -> str | None:
    """pytest: canonical xunit1 node id (unchanged rule). Other runners: ``<file>::<name>``."""
    if runner != "pytest":
        return f"{file_attr}::{name}" if file_attr else None
    # FILL IN: existing pytest body unchanged

# NEW, above parse_junit (report.py:146):
def parse_junit_report(
    junit_path: Path, *, runner: str, suite: str, exit_code: int, duration_s: float, timed_out: bool = False
) -> RunReport:
    """Parse any junit file into a RunReport; retains <failure>/<error> text per node."""
    # FILL IN: walk iter("testcase"); status from child tags; failure_text[nodeid] = (message + "\n" + text);
    #          missing file ⇒ status "timed_out" if timed_out else "no_report"; unparsable ⇒ "no_report"

# parse_junit keeps its signature and builds its SuiteResult from parse_junit_report(..., runner="pytest").

# REPLACE with_junit (report.py:106) with:
def with_report(invocation: Invocation, report_path: Path) -> tuple[str, ...]:
    """Report argv per runner: pytest ⇒ xunit1 junitxml (as before); other runners already carry it."""
    if invocation.runner == "pytest":
        return (*invocation.argv, "-o", "junit_family=xunit1", f"--junitxml={report_path}")
    return tuple(invocation.argv)
```
**Why**: `parse_junit` stays for FEAT-699 callers; the new function is what adapters call.

### `packages/ai-parrot/tests/flows/dev_loop/test_scope/fixtures/vitest-junit.xml` (CREATE)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<testsuites name="vitest tests" tests="3" failures="1" errors="0" time="0.42">
  <testsuite name="src/lib/form.test.ts" tests="3" failures="1" errors="0" skipped="0" time="0.40">
    <testcase classname="src/lib/form.test.ts" file="src/lib/form.test.ts" name="renders a field" time="0.01"/>
    <testcase classname="src/lib/form.test.ts" file="src/lib/form.test.ts" name="skips hidden" time="0.01"/>
    <testcase classname="src/lib/form.test.ts" file="src/lib/form.test.ts" name="validates required" time="0.02">
      <failure message="expected true to be false" type="AssertionError">AssertionError: expected true to be false
 ❯ src/lib/form.test.ts:42:18</failure>
    </testcase>
  </testsuite>
</testsuites>
```
**Why**: Shape of vitest's built-in junit reporter (testcase carries `file`).

### FILL IN checklist
- [ ] pytest branch of `nodeid_from_testcase` — unchanged body
- [ ] `parse_junit_report` body
- [ ] `render_markdown` — `n/a` when `suite` does not start with a pytest distribution (non-pytest suites are `<runner>:<dist>`)
- [ ] `vitest-nested.xml`, `vitest-nofile.xml`, `pytest-failure.xml` fixtures
- [ ] caller updates: background.py:1029, select_tests.py:248 → `with_report`

---

## Acceptance Criteria

- [ ] vitest fixture yields 3 nodes `src/lib/form.test.ts::<name>` with the failing one's text retained.
- [ ] Nested-suite fixture parses every testcase; missing-`file` testcase increments `unmapped` and the report stays red.
- [ ] pytest junit output of `parse_junit` is unchanged for every existing test.
- [ ] `with_junit` no longer exists anywhere (`grep`).
- [ ] `ruff check` clean on every touched `.py` file

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_background_validation.py -q`
- `pytest tests/sdd_scripts/test_select_tests.py -q`

---

## Test Specification

Tests live in the files declared above; write the cases named in Acceptance Criteria. sdd_coder tests reuse the hermetic-root fixture in `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/conftest.py`.

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug language-agnostic-validation-runners --feature-id FEAT-709`), never on `dev`.
2. Every `Depends-on` task must be `done` in `sdd/tasks/index/language-agnostic-validation-runners.json`.
3. Verify the Codebase Contract first; fix stale entries in this file before coding.
4. Implement from the blueprint; complete every `FILL IN`; never change a fixed signature or path.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Stage only the files listed above (`git add -f` for `.claude/`, `.parrot/`, `artifacts/`).
7. Close with `scripts/sdd/close_task.sh TASK-4523 language-agnostic-validation-runners verified`, then fill the Completion Note.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
