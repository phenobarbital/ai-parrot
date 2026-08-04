# TASK-2115: QA Model Enhancements

**Feature**: FEAT-410 — WebAgent CI/CD QA Runner Enhancements
**Spec**: `sdd/specs/webagent-cicd-qa-runner.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundation task for FEAT-410. All other tasks depend on the
model changes introduced here. It implements Spec Module 1 (Model
Enhancements) — adding new fields to `QAAssertion`, `QATestCase`, and
`QAFinding` that enable retry, timeout, wait, and new assertion
capabilities needed for CI/CD pipelines.

All changes are backward-compatible: every new field has a default value,
so existing code constructing these models continues to work unchanged.

---

## Scope

- Add `wait_timeout_ms: int = Field(default=5000, ge=0)` to `QAAssertion`
- Add two new assertion check types: `"response_status"` and
  `"accessibility_check"` to the `QAAssertion.check` Literal
- Add `max_retries: int = Field(default=0, ge=0)` to `QATestCase`
- Add `timeout_ms: int | None = Field(default=None, ge=1000)` to `QATestCase`
- Add `retries: int = 0` to `QAFinding`
- Write unit tests for all new fields: defaults, validation, serialization
  round-trip

**NOT in scope**:
- `QAReport` changes (exit_code, to_junit_xml) — TASK-2116
- `WebAgent` changes (run_tests logic) — TASK-2117
- System prompt changes — TASK-2117
- CLI runner — TASK-2118

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/chrome.py` | MODIFY | Add new fields to QAAssertion, QATestCase, QAFinding |
| `packages/ai-parrot/tests/bots/test_chrome.py` | MODIFY | Add unit tests for new model fields |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field            # verified: chrome.py:6
from typing import Literal                        # verified: chrome.py:4
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/chrome.py

class QAAssertion(BaseModel):                     # line 85
    check: Literal[                               # line 88
        "element_visible",
        "element_not_visible",
        "text_contains",
        "url_matches",
        "no_console_errors",
        "no_network_failures",
        "screenshot_diff",
        "performance",
    ]
    target: str | None = None                     # line 98
    value: str | None = None                      # line 99

class QATestCase(BaseModel):                      # line 102
    name: str                                     # line 105
    url: str                                      # line 106
    steps: list[str]                              # line 107
    expected: str                                 # line 108
    assertions: list[QAAssertion] = []            # line 109
    screenshot_on_fail: bool = True               # line 110
    viewport: str | None = None                   # line 111
    tags: list[str] = []                          # line 112

class QAFinding(BaseModel):                       # line 115
    test_name: str                                # line 118
    status: Literal["pass", "fail", "error", "skip"]  # line 119
    detail: str                                   # line 120
    screenshot_path: str | None = None            # line 121
    console_errors: list[str] = []                # line 122
    duration_ms: int | None = None                # line 123
```

### Does NOT Exist
- ~~`QAAssertion.wait_timeout_ms`~~ — does not exist yet (this task adds it)
- ~~`QATestCase.max_retries`~~ — does not exist yet (this task adds it)
- ~~`QATestCase.timeout_ms`~~ — does not exist yet (this task adds it)
- ~~`QAFinding.retries`~~ — does not exist yet (this task adds it)
- ~~`QAAssertion.check` values `"response_status"` or `"accessibility_check"`~~ — not yet valid

---

## Implementation Notes

### Key Constraints
- All new fields MUST have defaults (backward compatibility is critical)
- `timeout_ms` minimum is 1000ms (ge=1000) but allows None (no timeout)
- `wait_timeout_ms` minimum is 0 (ge=0), defaults to 5000
- `max_retries` minimum is 0 (ge=0), defaults to 0 (no retries)
- `retries` on QAFinding is a plain int defaulting to 0 (no Field needed)
- The Literal for `check` must include ALL existing values plus the two new ones

### Pattern to Follow
The existing fields use `Field()` for constrained values (see `ChromeConfig.port`):
```python
port: int = Field(default=9222, ge=1, le=65535)  # line 53
```

---

## Acceptance Criteria

- [ ] `QAAssertion(check="response_status", target="200")` constructs without error
- [ ] `QAAssertion(check="accessibility_check")` constructs without error
- [ ] `QAAssertion()` still raises — `check` is required (no default)
- [ ] `QAAssertion(check="element_visible").wait_timeout_ms == 5000`
- [ ] `QATestCase(name="t", url="/", steps=["s"], expected="e").max_retries == 0`
- [ ] `QATestCase(name="t", url="/", steps=["s"], expected="e").timeout_ms is None`
- [ ] `QATestCase(name="t", url="/", steps=["s"], expected="e", timeout_ms=500)` raises `ValidationError`
- [ ] `QAFinding(test_name="t", status="pass", detail="ok").retries == 0`
- [ ] JSON serialization round-trip preserves all new fields
- [ ] All existing tests in `test_chrome.py` still pass unchanged
- [ ] All new tests pass: `pytest packages/ai-parrot/tests/bots/test_chrome.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_chrome.py — APPEND these tests

import pytest
from pydantic import ValidationError
from parrot.bots.chrome import QAAssertion, QATestCase, QAFinding


def test_qa_assertion_wait_timeout_default():
    a = QAAssertion(check="element_visible")
    assert a.wait_timeout_ms == 5000


def test_qa_assertion_wait_timeout_custom():
    a = QAAssertion(check="element_visible", wait_timeout_ms=3000)
    assert a.wait_timeout_ms == 3000


def test_qa_assertion_wait_timeout_zero():
    a = QAAssertion(check="element_visible", wait_timeout_ms=0)
    assert a.wait_timeout_ms == 0


def test_qa_assertion_response_status():
    a = QAAssertion(check="response_status", target="200")
    assert a.check == "response_status"


def test_qa_assertion_accessibility_check():
    a = QAAssertion(check="accessibility_check")
    assert a.check == "accessibility_check"


def test_qa_test_case_max_retries_default():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e")
    assert tc.max_retries == 0


def test_qa_test_case_max_retries_custom():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e", max_retries=3)
    assert tc.max_retries == 3


def test_qa_test_case_timeout_ms_default():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e")
    assert tc.timeout_ms is None


def test_qa_test_case_timeout_ms_custom():
    tc = QATestCase(name="t", url="/", steps=["s"], expected="e", timeout_ms=30000)
    assert tc.timeout_ms == 30000


def test_qa_test_case_timeout_ms_minimum():
    with pytest.raises(ValidationError):
        QATestCase(name="t", url="/", steps=["s"], expected="e", timeout_ms=500)


def test_qa_finding_retries_default():
    f = QAFinding(test_name="t", status="pass", detail="ok")
    assert f.retries == 0


def test_qa_finding_retries_custom():
    f = QAFinding(test_name="t", status="fail", detail="nok", retries=2)
    assert f.retries == 2


def test_new_fields_serialization_roundtrip():
    tc = QATestCase(
        name="t", url="/", steps=["s"], expected="e",
        max_retries=2, timeout_ms=15000,
        assertions=[QAAssertion(check="response_status", target="200", wait_timeout_ms=3000)],
    )
    restored = QATestCase.model_validate_json(tc.model_dump_json())
    assert restored.max_retries == 2
    assert restored.timeout_ms == 15000
    assert restored.assertions[0].wait_timeout_ms == 3000
    assert restored.assertions[0].check == "response_status"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webagent-cicd-qa-runner.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm the existing class signatures in
   `chrome.py` still match what is listed above
4. **Update status** in `sdd/tasks/index/webagent-cicd-qa-runner.json` → `"in-progress"`
5. **Implement** the model changes in `chrome.py`
6. **Add tests** to `test_chrome.py`
7. **Verify** all acceptance criteria are met
8. **Move this file** to `sdd/tasks/completed/TASK-2115-qa-model-enhancements.md`
9. **Update index** → `"done"`
10. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
