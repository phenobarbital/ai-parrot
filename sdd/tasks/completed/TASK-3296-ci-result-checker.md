# TASK-3296: Structured CI result-checker + coverage-inventory tool

**Feature**: FEAT-562 — CI Test-Failure Root-Cause Remediation
**Spec**: `sdd/specs/ci-test-failures-root-cause-remediation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements the M2 §2d "structured result gate" and the §2a coverage-inventory
half of Module 2. The spec proved (via a focused reproduction with the repo's
own pytest config) that the originally-proposed `grep "SKIPPED"` gate is
**useless**: quiet-mode pytest prints `1 passed, 1 skipped`, never the literal
`SKIPPED` — so the grep gate would pass unconditionally forever, defeating its
purpose. This task builds the deterministic replacement: a stdlib-only checker
that parses pytest JUnit-XML reports and fails on missing/malformed reports,
failures/errors, zero executed required tests, and unexpected skips (including
collection/module-level skips), plus a coverage inventory that maps required
test selections to the reports that must contain them.

This tool is what TASK-3297's new `test-optional-integrations` job (and the
wiki/map jobs) invoke as their gate, so it must exist and be tested first.

---

## Scope

- Add `scripts/ci/check_ci_results.py`: a stdlib-only CLI that reads one or
  more JUnit-XML files (produced by `pytest --junitxml=...`) plus a coverage
  inventory (JSON), and exits non-zero on any of: missing/malformed XML,
  `<failure>`/`<error>` elements, zero executed required tests, a required
  selection with no matching report, or an unexpected skip (module-level /
  collection skips included), scoped to the mandatory offline selections.
- Support an allowlist of narrowly-recorded expected skips **by exact node ID
  + reason** (audited live/credential-gated cases), never a blanket
  module/provider allowance.
- Add `tests/ci/test_check_ci_results.py`: deterministic fixtures for ordinary
  pass, module-level skip, test-level skip, expected exception (`xfail`/allowed
  skip), unexpected exception (failure), collection error, missing report,
  malformed XML, and empty/missing required coverage. Demonstrate the gate
  fails when a required optional dependency is absent (its selection produced
  only skips) and passes when the same selection executes.

**NOT in scope**: editing `.github/workflows/ci.yml` (TASK-3297); adding
`importorskip` guards to test files (TASK-3297); the test-to-job mapping YAML
(TASK-3297). This task delivers the *tool and its tests only*.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/ci/check_ci_results.py` | CREATE | Stdlib JUnit-XML result + coverage-inventory checker (CLI) |
| `tests/ci/test_check_ci_results.py` | CREATE | Deterministic fixtures covering all gate outcomes |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Stdlib only — the spec (§7 External Dependencies) mandates the standard
# library for this checker so it runs in any CI profile without extras.
import argparse
import json
import sys
import xml.etree.ElementTree as ET  # JUnit-XML parser
from pathlib import Path
```

### Existing Signatures to Use
```python
# scripts/sdd/check_task_graph.py — an existing stdlib-only CLI checker in this
# repo. FOLLOW ITS STYLE for a deterministic exit-code gate: argparse entry
# point, a pure classification function that returns (errors, warnings), a
# __main__ guard that prints a report and sys.exit(1) on errors.
# (verified present: scripts/sdd/check_task_graph.py)
```

pytest JUnit-XML shape this parser must handle (produced by
`pytest --junitxml=<f>` — verified against pytest's documented schema; confirm
by generating one locally, e.g. `pytest tests/ci/ --junitxml=/tmp/r.xml`):
```xml
<testsuites>
  <testsuite name="pytest" tests="N" failures="F" errors="E" skipped="S">
    <testcase classname="tests.mod" name="test_x" time="0.01"/>
    <testcase classname="tests.mod" name="test_y">
      <skipped type="pytest.skip" message="reason"/>
    </testcase>
    <testcase classname="tests.mod" name="test_z">
      <failure message="...">...</failure>
    </testcase>
    <!-- a collection error is emitted as a testcase with an <error> child -->
  </testsuite>
</testsuites>
```

### Does NOT Exist
- ~~`scripts/ci/`~~ — the directory does not exist yet; this task creates it
  (verified: `ls scripts/ci` → not found).
- ~~a text-`grep` "SKIPPED" gate that works in quiet mode~~ — empirically
  false; quiet pytest prints lowercase `skipped` in the summary line only.
  Do not reintroduce a text-scanning gate.
- ~~`pytest`/`lxml` as a hard dep of this checker~~ — must be stdlib-only so
  it runs in the `lint-and-registry` job too.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "scripts/ci/check_ci_results.py", "action": "CREATE" },
    { "path": "tests/ci/test_check_ci_results.py", "action": "CREATE" }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Pattern to Follow
Mirror `scripts/sdd/check_task_graph.py`: a pure function
`check(reports, inventory) -> tuple[list[str], list[str]]` (errors, warnings)
that never prints or exits, plus a thin `main()` that prints the report and
`sys.exit(1)` when `errors` is non-empty. This keeps the checker unit-testable
with in-memory fixtures (no subprocess, no real pytest run).

### Key Constraints
- Stdlib only (no pytest/lxml import in the checker module itself).
- A collection/module-level skip is represented in JUnit-XML as a `<testcase>`
  with a `<skipped>` child whose name is the module or a setup node — treat it
  as a skip, not as "0 tests". The checker must NOT count a required selection
  that produced only skips as satisfied.
- Zero-skip enforcement is scoped to **mandatory offline selections** named in
  the inventory; a selection may carry a narrow, node-ID-level expected-skip
  allowlist with reasons.
- Deterministic: same inputs → same exit code and same report text.

### Inventory JSON shape (this task defines it; TASK-3297 authors instances)
Design a minimal, explicit schema, e.g.:
```json
{
  "selections": [
    {
      "id": "clients-anthropic",
      "report": "artifacts/logs/clients-anthropic.xml",
      "min_executed": 1,
      "allow_skips": [
        {"node_id": "tests/clients/test_anthropic_sdk_097.py::test_anthropic_live_smoke",
         "reason": "credential-gated live smoke; deselected offline"}
      ]
    }
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. Create `scripts/ci/check_ci_results.py` with argparse (`--inventory PATH`,
   `--reports-dir PATH` or repeated `--report`), a pure `check()` and a
   `main()` — *why*: a pure classifier is unit-testable without a real pytest run.
2. Parse each JUnit-XML with `ET.parse`; on `ET.ParseError` record a
   `malformed-report` error; on a missing file record `missing-report` —
   *why*: a missing/broken report must fail closed, never pass silently.
3. For each inventory selection, resolve its report, count executed vs skipped
   testcases, apply the node-ID allowlist, and record errors for
   `zero-executed`, `unexpected-skip`, `failure`, `error` — *why*: this is the
   whole point of the gate (§2d).
4. Create `tests/ci/test_check_ci_results.py` with `tmp_path`-written XML
   fixtures for every outcome named in Scope — *why*: proves the gate itself
   is correct before any job relies on it.

### `scripts/ci/check_ci_results.py` (CREATE)
```python
"""Deterministic CI result + coverage gate (FEAT-562 Module 2, §2d).

Parses pytest JUnit-XML reports against a coverage inventory and fails closed
on missing/malformed reports, failures/errors, zero-executed required
selections, and unexpected skips (module-level/collection skips included).
Stdlib only — runs in every CI profile without extras.
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _load_report(path: Path) -> tuple[list[dict], str | None]:
    """Return (testcases, error). ``error`` is set for missing/malformed XML."""
    if not path.is_file():
        return [], f"missing-report: {path}"
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [], f"malformed-report: {path}: {exc}"
    cases: list[dict] = []
    for tc in root.iter("testcase"):
        node_id = f"{tc.get('classname', '')}::{tc.get('name', '')}"
        kind = "pass"
        if tc.find("skipped") is not None:
            kind = "skip"
        elif tc.find("failure") is not None:
            kind = "failure"
        elif tc.find("error") is not None:
            kind = "error"
        cases.append({"node_id": node_id, "kind": kind})
    return cases, None


def check(inventory: dict, reports_dir: Path) -> tuple[list[str], list[str]]:
    """Classify every inventory selection. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    # FILL IN: iterate inventory["selections"]; for each, _load_report, then
    #   - record any missing/malformed error verbatim
    #   - executed = [c for c in cases if c["kind"] == "pass"]
    #   - failures/errors -> errors
    #   - skips not in the selection's allow_skips node-id set -> unexpected-skip error
    #   - len(executed) < selection.get("min_executed", 1) -> zero-executed error
    # bounded by: §2d "fail on missing/malformed reports, failures/errors, zero
    # executed required tests, missing inventory coverage, and unexpected skips".
    raise NotImplementedError


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit 1 on any error, 0 otherwise."""
    parser = argparse.ArgumentParser(description="CI result + coverage gate")
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, default=Path("artifacts/logs"))
    args = parser.parse_args(argv)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    errors, warnings = check(inventory, args.reports_dir)
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"{len(inventory.get('selections', []))} selections, "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
```
**Why this shape**: implements §2d's structured gate. `check()` is pure so the
tests below drive it with in-memory inventories + `tmp_path` XML; `main()` is a
thin CLI TASK-3297 calls from `ci.yml`. Do NOT add a pytest/lxml import — the
stdlib-only constraint (§7) is what lets `lint-and-registry` reuse it.

### `tests/ci/test_check_ci_results.py` (CREATE)
```python
"""Deterministic tests for the CI result gate (FEAT-562 Module 2, §2d)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Import the tool by path — it lives under scripts/, not an installed package.
import importlib.util

_CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "check_ci_results.py"
_spec = importlib.util.spec_from_file_location("check_ci_results", _CHECKER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


def _write_xml(path: Path, *, tests: int, failures: int = 0, errors: int = 0,
               cases: str = "") -> Path:
    """Write a minimal JUnit-XML file and return its path."""
    path.write_text(
        f'<testsuites><testsuite name="pytest" tests="{tests}" '
        f'failures="{failures}" errors="{errors}">{cases}</testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


def test_ordinary_pass(tmp_path):
    """A required selection with an executed test and no skips passes."""
    _write_xml(tmp_path / "r.xml", tests=1,
               cases='<testcase classname="tests.m" name="test_ok"/>')
    inv = {"selections": [{"id": "s", "report": str(tmp_path / "r.xml"), "min_executed": 1}]}
    errors, _ = mod.check(inv, tmp_path)
    assert errors == []
    # FILL IN: add the remaining fixtures named in Scope — bounded by §2d:
    #   module-level skip, test-level skip, allowed (node-id) skip, unexpected
    #   skip -> error, failure -> error, collection <error> -> error,
    #   missing report -> error, malformed XML -> error, zero-executed -> error,
    #   and the absent-dependency (only-skips) vs installed (executes) pair.
```
**Why**: proves the gate is correct before TASK-3297 wires it into CI — the
spec explicitly requires these deterministic fixtures (§2d, §4 Test Spec).

### FILL IN checklist
- [ ] `check_ci_results.py::check` — the selection-classification loop; bounded by §2d's failure list.
- [ ] `test_check_ci_results.py` — the remaining fixtures (module/test/allowed/unexpected skip, failure, collection error, missing/malformed report, zero-executed, absent-vs-installed pair); bounded by Scope + §4 Test Spec.

---

## Acceptance Criteria

- [ ] `python scripts/ci/check_ci_results.py --inventory <sample>` exits 0 on a
      clean report set and 1 on each failure mode.
- [ ] `pytest tests/ci/test_check_ci_results.py -v` passes, covering every
      outcome named in Scope (pass, module skip, test skip, allowed skip,
      unexpected skip, failure, collection error, missing report, malformed
      XML, zero-executed, absent-vs-installed dependency pair).
- [ ] The checker imports nothing outside the standard library.
- [ ] `ruff check scripts/ci/check_ci_results.py tests/ci/test_check_ci_results.py` clean.

---

## Test Specification

Covered by `tests/ci/test_check_ci_results.py` per the blueprint. Every gate
outcome is exercised with an in-memory inventory and a `tmp_path`-written XML;
no real pytest subprocess and no satellite dependency is required, so this
task's own tests run in bare `test-core`.

---

## Agent Instructions

Standard SDD flow. This task has no dependencies — it can start immediately.
Verify the `check_task_graph.py` style reference still exists before mirroring
it. Do not touch `.github/workflows/ci.yml` — that is TASK-3297.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
