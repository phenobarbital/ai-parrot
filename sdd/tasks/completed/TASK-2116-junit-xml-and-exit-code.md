# TASK-2116: JUnit XML Serialization & Exit Code

**Feature**: FEAT-410 — WebAgent CI/CD QA Runner Enhancements
**Spec**: `sdd/specs/webagent-cicd-qa-runner.spec.md`
**Status**: done
**Completed**: 2026-08-04
**Verification**: verified (evidence: commits + files present in feat-410-webagent-cicd-qa-runner worktree)
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2115
**Assigned-to**: unassigned

---

## Context

This task implements Spec Module 4 (JUnit XML Serialization) and adds the
`exit_code` property to `QAReport`. JUnit XML is the universal format for
CI test result dashboards — CircleCI, GitHub Actions, GitLab CI, and
Jenkins all parse it natively. This is the key integration point that makes
WebAgent QA results visible in CI pipelines.

---

## Scope

- Add `exit_code` computed property to `QAReport` — returns 0 when all pass,
  1 when any failure or error
- Implement `QAReport.to_junit_xml() -> str` method using stdlib
  `xml.etree.ElementTree`
- Map `QAFinding` statuses to JUnit XML conventions:
  - `pass` → `<testcase>` (no child element)
  - `fail` → `<testcase><failure message="...">details</failure></testcase>`
  - `error` → `<testcase><error message="...">details</error></testcase>`
  - `skip` → `<testcase><skipped message="..."/></testcase>`
- Include `console_errors` in failure/error message bodies
- Include `duration_ms` as `time` attribute (converted to seconds)
- Include `retries` count in failure details when > 0
- Write comprehensive unit tests

**NOT in scope**:
- `WebAgent` run_tests logic changes — TASK-2117
- CLI runner that writes the XML to disk — TASK-2118
- Example files — TASK-2119

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/chrome.py` | MODIFY | Add `exit_code` property and `to_junit_xml()` to `QAReport` |
| `packages/ai-parrot/tests/bots/test_chrome.py` | MODIFY | Add tests for JUnit XML output and exit_code |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field            # verified: chrome.py:6
from typing import Literal                        # verified: chrome.py:4
import xml.etree.ElementTree as ET               # stdlib — add this import
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/chrome.py

class QAFinding(BaseModel):                       # line 115
    test_name: str                                # line 118
    status: Literal["pass", "fail", "error", "skip"]  # line 119
    detail: str                                   # line 120
    screenshot_path: str | None = None            # line 121
    console_errors: list[str] = []                # line 122
    duration_ms: int | None = None                # line 123
    retries: int = 0                              # ADDED BY TASK-2115

class QAReport(BaseModel):                        # line 126
    summary: str                                  # line 129
    url: str                                      # line 130
    findings: list[QAFinding] = []                # line 131
    total: int = 0                                # line 132
    passed: int = 0                               # line 133
    failed: int = 0                               # line 134
    errors: int = 0                               # line 135
    skipped: int = 0                              # line 136
    duration_ms: int | None = None                # line 137
```

### Does NOT Exist
- ~~`QAReport.exit_code`~~ — does not exist yet (this task adds it)
- ~~`QAReport.to_junit_xml()`~~ — does not exist yet (this task adds it)
- ~~`QAReport.to_xml()`~~ — no such method
- ~~`QAReport.to_dict()`~~ — use `.model_dump()` (Pydantic v2)
- ~~`parrot.bots.chrome.JUnitWriter`~~ — no such class

---

## Implementation Notes

### JUnit XML Schema Reference

The JUnit XML format expected by CircleCI and GitHub Actions:

```xml
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="WebAgent QA" tests="3" failures="1" errors="0"
             skipped="0" time="12.345">
    <testcase name="homepage-smoke" classname="WebAgent QA" time="2.100">
    </testcase>
    <testcase name="login-validation" classname="WebAgent QA" time="5.200">
      <failure message="Validation errors not shown">
Detail: Validation errors not shown
Console errors:
- TypeError: x is undefined
Retries: 2
      </failure>
    </testcase>
    <testcase name="nav-check" classname="WebAgent QA" time="0.0">
      <skipped message="Filtered by tags"/>
    </testcase>
  </testsuite>
</testsuites>
```

### Key Constraints
- Use ONLY `xml.etree.ElementTree` (stdlib) — no lxml
- `time` attributes are in seconds (float), not milliseconds
- `classname` attribute on `<testcase>` is required by some CI parsers —
  use `"WebAgent QA"` as the default
- `exit_code` is a `@property`, NOT a stored field — computed from
  `failed + errors`
- Return type of `to_junit_xml()` is `str` — the complete XML document
  as a string with XML declaration

### Pattern to Follow
```python
import xml.etree.ElementTree as ET

@property
def exit_code(self) -> int:
    return 1 if (self.failed + self.errors) > 0 else 0

def to_junit_xml(self, suite_name: str = "WebAgent QA") -> str:
    testsuites = ET.Element("testsuites")
    testsuite = ET.SubElement(testsuites, "testsuite", ...)
    for finding in self.findings:
        tc = ET.SubElement(testsuite, "testcase", ...)
        # add failure/error/skipped children as needed
    tree = ET.ElementTree(testsuites)
    # serialize to string with xml_declaration
    ...
```

---

## Acceptance Criteria

- [ ] `QAReport(summary="ok", url="/", passed=3, total=3).exit_code == 0`
- [ ] `QAReport(summary="nok", url="/", failed=1, total=3).exit_code == 1`
- [ ] `QAReport(summary="err", url="/", errors=1, total=3).exit_code == 1`
- [ ] `report.to_junit_xml()` returns a string starting with `<?xml`
- [ ] Output is well-formed XML parseable by `ET.fromstring()`
- [ ] Passing tests produce `<testcase>` with no child elements
- [ ] Failing tests produce `<testcase><failure ...>` with console errors in body
- [ ] Error tests produce `<testcase><error ...>`
- [ ] Skipped tests produce `<testcase><skipped ...>`
- [ ] `time` attributes are in seconds (float)
- [ ] `retries` count is included in failure detail when > 0
- [ ] All existing tests still pass unchanged
- [ ] New tests pass: `pytest packages/ai-parrot/tests/bots/test_chrome.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_chrome.py — APPEND these tests

import xml.etree.ElementTree as ET
from parrot.bots.chrome import QAFinding, QAReport


def test_qa_report_exit_code_all_pass():
    r = QAReport(summary="ok", url="/", total=3, passed=3)
    assert r.exit_code == 0


def test_qa_report_exit_code_with_failure():
    r = QAReport(summary="nok", url="/", total=3, passed=2, failed=1)
    assert r.exit_code == 1


def test_qa_report_exit_code_with_error():
    r = QAReport(summary="err", url="/", total=3, passed=2, errors=1)
    assert r.exit_code == 1


def test_qa_report_exit_code_empty():
    r = QAReport(summary="empty", url="/")
    assert r.exit_code == 0


def test_to_junit_xml_well_formed():
    r = QAReport(
        summary="1/1 passed", url="http://localhost",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok")],
        total=1, passed=1,
    )
    xml_str = r.to_junit_xml()
    assert xml_str.startswith("<?xml")
    root = ET.fromstring(xml_str)
    assert root.tag == "testsuites"


def test_to_junit_xml_pass_no_children():
    r = QAReport(
        summary="ok", url="/",
        findings=[QAFinding(test_name="t1", status="pass", detail="ok", duration_ms=2100)],
        total=1, passed=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    tc = root.find(".//testcase[@name='t1']")
    assert tc is not None
    assert len(tc) == 0  # no child elements
    assert float(tc.get("time", "0")) == pytest.approx(2.1, abs=0.01)


def test_to_junit_xml_failure_with_console_errors():
    r = QAReport(
        summary="nok", url="/",
        findings=[QAFinding(
            test_name="t1", status="fail", detail="broken",
            console_errors=["TypeError: x is undefined"],
            retries=2,
        )],
        total=1, failed=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    failure = root.find(".//testcase/failure")
    assert failure is not None
    assert "broken" in (failure.text or "")
    assert "TypeError" in (failure.text or "")
    assert "Retries: 2" in (failure.text or "")


def test_to_junit_xml_error_status():
    r = QAReport(
        summary="err", url="/",
        findings=[QAFinding(test_name="t1", status="error", detail="timed out")],
        total=1, errors=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    error = root.find(".//testcase/error")
    assert error is not None


def test_to_junit_xml_skipped_status():
    r = QAReport(
        summary="skip", url="/",
        findings=[QAFinding(test_name="t1", status="skip", detail="filtered")],
        total=1, skipped=1,
    )
    root = ET.fromstring(r.to_junit_xml())
    skipped = root.find(".//testcase/skipped")
    assert skipped is not None


def test_to_junit_xml_suite_attributes():
    r = QAReport(
        summary="2/3", url="/",
        findings=[
            QAFinding(test_name="t1", status="pass", detail="ok"),
            QAFinding(test_name="t2", status="fail", detail="nok"),
            QAFinding(test_name="t3", status="skip", detail="filtered"),
        ],
        total=3, passed=1, failed=1, skipped=1, duration_ms=5000,
    )
    root = ET.fromstring(r.to_junit_xml())
    suite = root.find("testsuite")
    assert suite.get("tests") == "3"
    assert suite.get("failures") == "1"
    assert suite.get("skipped") == "1"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webagent-cicd-qa-runner.spec.md` for full context
2. **Check dependencies** — verify TASK-2115 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `QAReport` and `QAFinding` signatures
4. **Update status** in `sdd/tasks/index/webagent-cicd-qa-runner.json` → `"in-progress"`
5. **Implement** `exit_code` property and `to_junit_xml()` method
6. **Add tests** to `test_chrome.py`
7. **Verify** all acceptance criteria
8. **Move this file** to `sdd/tasks/completed/`
9. **Update index** → `"done"`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-04
**Notes**: Added `exit_code` computed property (`1 if failed+errors>0 else 0`)
and `to_junit_xml(suite_name="WebAgent QA")` to `QAReport`, built with stdlib
`xml.etree.ElementTree` only. Maps pass/fail/error/skip to the JUnit
conventions in the spec, includes console errors + retry count in
failure/error bodies via a `_junit_detail_body` static helper, and reports
`time` attributes in seconds. Appended 10 new unit tests. All 45 tests in
`test_chrome.py` pass (35 pre-existing + 10 new).

**Deviations from spec**: none
