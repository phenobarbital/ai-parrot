# TASK-4446: Node-level junit evidence in `test_scope.report`

**Feature**: FEAT-699 — Tests Optimization in the SDD Flow (spec-declared Validation Contract)
**Spec**: `sdd/specs/tests-optimization-sdd-flow.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4444
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4/5 prerequisite (design research S5). `parse_junit` (report.py:111) keeps only aggregate
counters, so neither the green cache nor the baseline verdict can tell WHICH node passed or failed. This
task makes every recorded `SuiteResult` carry canonical per-node statuses, failing closed when a node id
cannot be reconstructed.

---

## Scope

- `with_junit(invocation, junit_path)` additionally appends `-o junit_family=xunit1` (xunit1 carries the
  `file` attribute on each `<testcase>`, which is what makes node ids reconstructable).
- Add `nodeid_from_testcase(file_attr, classname, name) -> str | None`.
- `SuiteResult` gains `nodes: tuple[tuple[str, str], ...] = ()` (`(nodeid, status)`, status in
  `passed|failed|error|skipped`) and `unmapped: int = 0` (testcases whose node id could not be built), and
  `baseline: tuple[tuple[str, str], ...] = ()` (filled by TASK-4448/4450/4451 callers; empty here).
- `parse_junit` fills `nodes`/`unmapped`; `_record_from_payload` reads the new keys with defaults so
  pre-FEAT-699 JSON records still load.
- Add `suite_name(invocation) -> str`: the distribution, plus a stable suffix for non-default invocations
  of the same distribution — `"<dist>[contract]"` when argv's `-m` value is `OVERRIDE_MARKER_EXPRESSION`
  and `"<dist>[markers]"` for a marker sweep — so `append_suite` (keyed by suite) never overwrites the
  default invocation's result.

**NOT in scope**: rendering (TASK-4449), callers adopting `suite_name` (TASK-4450/4451).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` | MODIFY | Node-level parse, suite_name, xunit1 |
| `packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py` | MODIFY | New tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from .datatypes import PytestInvocation   # report.py:19
import xml.etree.ElementTree as ET        # report.py:14
```

### Existing Signatures to Use
```python
# test_scope/report.py
class SuiteResult: suite, tests, passed, failed, errors, skipped, duration_s, exit_code, argv, status  # line 36
def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]:   # line 101
def _empty_result(suite, argv, exit_code, duration_s, status) -> SuiteResult:        # line 106 (positional ctor!)
def parse_junit(junit_path, *, suite, argv, exit_code, duration_s, timed_out=False) -> SuiteResult:  # line 111
def _record_from_payload(payload) -> TaskTestRecord:                                 # line 142
```
- The marker values to recognise: `"not real_llm"` (TASK-4444 `planner.OVERRIDE_MARKER_EXPRESSION`) and a
  `-m` value starting with `"("` and ending with `" and not real_llm"` (the TASK-4444 marker sweep). Import the
  constant from `.planner` — do not duplicate the string.

### Does NOT Exist
- ~~`SuiteResult.nodes` / `.unmapped` / `.baseline`~~ — created here
- ~~a `file` attribute in default (xunit2) junit~~ — hence the `-o junit_family=xunit1` flag

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#SuiteResult",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#parse_junit",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#with_junit",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py#_record_from_payload"
  ]
}
```

---

## Implementation Notes

- Node id reconstruction (xunit1): `file="packages/a/tests/x/test_foo.py"`, `classname="packages.a.tests.x.test_foo.TestBar"`,
  `name="test_baz[1]"` → `packages/a/tests/x/test_foo.py::TestBar::test_baz[1]`. Class segments = the classname
  parts AFTER the module path derived from `file` (dots for `/`, `.py` dropped). No `file` attribute, or a
  classname that does not start with the module path → `None` (count it in `unmapped`). Never guess.
- Paths in `file` may be relative to the pytest rootdir; keep them as given (callers run with cwd = worktree).
- `_empty_result` builds `SuiteResult` positionally — the new fields MUST have defaults and be appended last.

---

## Implementation Blueprint

### Steps (in order)
1. Append the three defaulted fields to `SuiteResult` — *why*: positional constructors stay valid.
2. Add `nodeid_from_testcase`, extend `parse_junit` and `_record_from_payload` — *why*: S5 node evidence.
3. Add `suite_name`; extend `with_junit` — *why*: no overwritten records; reconstructable ids.

### `packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/report.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    status: str$' report.py — the SuiteResult field at line 48; CHECK: TaskTestRecord has no `status` field)
# AFTER — insert below `    status: str` inside SuiteResult (verified: report.py:48)
    nodes: tuple[tuple[str, str], ...] = ()  # FEAT-699: (nodeid, passed|failed|error|skipped)
    unmapped: int = 0  # testcases whose node id could not be reconstructed (fail closed)
    baseline: tuple[tuple[str, str], ...] = ()  # FEAT-699: (nodeid, BaselineVerdict.status) for failures
```
```python
# REPLACE with_junit body (verified: report.py:101-103):
def with_junit(invocation: PytestInvocation, junit_path: Path) -> tuple[str, ...]:
    """Invocation argv + isolated junit path, forcing xunit1 so testcases carry ``file`` (FEAT-699)."""
    return (*invocation.argv, "-o", "junit_family=xunit1", f"--junitxml={junit_path}")


def nodeid_from_testcase(file_attr: str | None, classname: str, name: str) -> str | None:
    """Canonical pytest node id for one xunit1 testcase, or None when it cannot be built safely."""
    # FILL IN: per Implementation Notes — bounded by "never guess"
    raise NotImplementedError


def suite_name(invocation: PytestInvocation) -> str:
    """Record key for one invocation: ``<dist>``, ``<dist>[contract]`` or ``<dist>[markers]``."""
    # FILL IN: read the value after "-m" in invocation.argv; compare to planner.OVERRIDE_MARKER_EXPRESSION / sweep shape
    raise NotImplementedError
```
```python
# parse_junit (verified: report.py:111-139): FILL IN — inside the existing try, iterate root.iter("testcase"),
#   status = failed if <failure>, error if <error>, skipped if <skipped>, else passed; collect (nodeid, status)
#   sorted by nodeid; unmapped += 1 when nodeid is None; pass nodes=..., unmapped=... to SuiteResult(...)
# _record_from_payload (verified: report.py:142-170): FILL IN — nodes=tuple(tuple(x) for x in item.get("nodes", ())),
#   unmapped=item.get("unmapped", 0), baseline=tuple(tuple(x) for x in item.get("baseline", ()))
```

### FILL IN checklist
- [ ] `nodeid_from_testcase` incl. module-level functions (no class) and parametrized names
- [ ] `suite_name`
- [ ] `parse_junit` node collection; aggregates unchanged
- [ ] backward-compatible `_record_from_payload`
- [ ] tests: xunit1 fixture XML → nodes; no `file` attr → unmapped; old JSON payload loads; suite_name variants; with_junit argv tail

---

## Acceptance Criteria

- [ ] A checked-in xunit1 XML fixture string yields the exact expected node ids and statuses.
- [ ] A testcase without `file` increments `unmapped` and is absent from `nodes`.
- [ ] A pre-FEAT-699 record JSON (no `nodes` key) still loads via `load_records`.
- [ ] Existing `test_report.py` tests pass (aggregate counts unchanged).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_report.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_stdlib_only.py -q`

---

## Test Specification

```python
XUNIT1 = """<testsuites><testsuite tests="2" failures="1" errors="0" skipped="0">
<testcase file="packages/a/tests/test_x.py" classname="packages.a.tests.test_x.TestC" name="test_ok"/>
<testcase file="packages/a/tests/test_x.py" classname="packages.a.tests.test_x" name="test_bad[1]"><failure/></testcase>
</testsuite></testsuites>"""

def test_parse_junit_nodes(tmp_path):
    # FILL IN: write XUNIT1, parse, assert nodes == (("packages/a/tests/test_x.py::TestC::test_ok","passed"),
    #          ("packages/a/tests/test_x.py::test_bad[1]","failed")) after sorting
    ...
```

---

## Agent Instructions

Standard. Close with `scripts/sdd/close_task.sh TASK-4446 tests-optimization-sdd-flow verified`.

---

## Completion Note

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
