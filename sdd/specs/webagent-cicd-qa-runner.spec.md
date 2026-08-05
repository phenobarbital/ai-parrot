---
type: feature
base_branch: dev
---

# Feature Specification: WebAgent CI/CD QA Runner Enhancements

**Feature ID**: FEAT-410
**Date**: 2026-08-04
**Author**: Jesus Lara
**Status**: draft
**Target version**: 0.next

---

## 1. Motivation & Business Requirements

### Problem Statement

The `WebAgent` already supports headless Chrome via CDP/MCP and has
`QATestCase`/`QAReport` Pydantic models for structured QA testing. However,
it is not production-grade for CI/CD pipelines (CircleCI, GitHub Actions,
GitLab CI). The missing pieces are:

- **No retry mechanism** — a single network glitch or slow render fails the
  entire test case with no recovery, causing false negatives in CI.
- **No per-test timeout** — a hanging page blocks the entire pipeline
  indefinitely.
- **No tag-based filtering** — users cannot selectively run `smoke` tests on
  PRs and the `full` suite on merge to main.
- **No JUnit XML output** — CI systems cannot natively parse `QAReport` to
  display pass/fail badges and test result dashboards.
- **No screenshot artifact management** — failure screenshots exist
  conceptually but are not saved to a directory CI can collect.
- **No CLI entry point** — running QA tests requires writing a Python script;
  there is no `python -m` runner.
- **Assertions lack wait semantics** — element-based assertions fire
  immediately without waiting for the DOM to stabilize, causing false
  failures on SPAs.

### Goals

- Make `WebAgent.run_tests()` reliable enough for CI/CD gate decisions
  (deploy-or-block).
- Provide first-class JUnit XML output for CI dashboard integration.
- Support tag-based test selection via both API and environment variables.
- Add a zero-code CLI runner that reads test definitions from JSON/YAML files.
- Keep full backward compatibility — all new fields have defaults.

### Non-Goals (explicitly out of scope)

- **Visual regression testing** (screenshot-diff) — the `screenshot_diff`
  assertion type exists as a placeholder; pixel-comparison is a separate
  feature.
- **Parallel test execution** — tests run sequentially within a single
  `run_tests()` call. Multi-browser parallelism is out of scope.
- **Test recording/codegen** — recording user sessions into `QATestCase` YAML
  is a separate initiative.
- **Playwright/Selenium integration** — this spec is strictly for the
  CDP/MCP-based `WebAgent`, not the separate Playwright-based
  `agent-browser` skill or the Selenium-based `WebScrapingTool`.

---

## 2. Architectural Design

### Overview

This feature extends the existing `WebAgent` and its Pydantic models in
`packages/ai-parrot/src/parrot/bots/chrome.py` with CI/CD-oriented
capabilities. A new `chrome_runner.py` module provides a CLI entry point.

The architecture remains the same: `WebAgent` → `MCPEnabledMixin` →
`chrome-devtools-mcp` (npx, stdio) → Chrome (CDP, headless). The changes
are in the orchestration layer around `run_tests()`, not in the Chrome
connection layer.

```
┌──────────────────────────────────────────────────────┐
│  CI Pipeline (CircleCI / GH Actions / GitLab CI)     │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │  python -m parrot.bots.chrome_runner          │    │
│  │    --test-file tests/qa/smoke.json            │    │
│  │    --headless --tags smoke                    │    │
│  │    --junit-output results.xml                 │    │
│  │    --screenshot-dir qa-screenshots/           │    │
│  │    --url http://localhost:3000                 │    │
│  └────────────────────┬─────────────────────────┘    │
│                       │                              │
│  ┌────────────────────▼─────────────────────────┐    │
│  │  WebAgent.run_tests(cases, tags, url)         │    │
│  │    ├─ filter by tags                          │    │
│  │    ├─ for each case:                          │    │
│  │    │    ├─ apply timeout (asyncio.wait_for)   │    │
│  │    │    ├─ execute via LLM + MCP tools        │    │
│  │    │    ├─ on fail: retry up to max_retries   │    │
│  │    │    └─ save screenshot to screenshot_dir   │    │
│  │    └─ build QAReport                          │    │
│  └────────────────────┬─────────────────────────┘    │
│                       │                              │
│  ┌────────────────────▼─────────────────────────┐    │
│  │  QAReport                                     │    │
│  │    ├─ .to_junit_xml() → results.xml           │    │
│  │    └─ .exit_code → 0 | 1                      │    │
│  └──────────────────────────────────────────────┘    │
│                                                      │
│  exit($exit_code)  → CI pass/fail decision           │
└──────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `WebAgent` (chrome.py) | extends in-place | New fields on models, new logic in `run_tests()` |
| `BasicAgent.ask()` | calls | Unchanged — `structured_output=QAReport` |
| `ChromeConfig` | unchanged | No modifications needed |
| `MCPEnabledMixin` | inherited | Chrome connection layer stays the same |
| `AIMessage` | consumed | `run_tests()` returns `AIMessage` with `.output: QAReport` |
| `ChromeManager` | unchanged | Already passes `--no-sandbox`, `--disable-dev-shm-usage` for Docker/CI |

### Data Models

#### New / Modified Pydantic Models

```python
# --- QAAssertion (MODIFIED) ---
class QAAssertion(BaseModel):
    check: Literal[
        "element_visible", "element_not_visible",
        "text_contains", "url_matches",
        "no_console_errors", "no_network_failures",
        "screenshot_diff", "performance",
        "response_status",       # NEW — verify HTTP status code
        "accessibility_check",   # NEW — basic a11y (ARIA, alt text)
    ]
    target: str | None = None
    value: str | None = None
    wait_timeout_ms: int = Field(  # NEW
        default=5000, ge=0,
        description="Max wait for element-based checks before asserting"
    )

# --- QATestCase (MODIFIED) ---
class QATestCase(BaseModel):
    name: str
    url: str
    steps: list[str]
    expected: str
    assertions: list[QAAssertion] = []
    screenshot_on_fail: bool = True
    viewport: str | None = None
    tags: list[str] = []
    max_retries: int = Field(       # NEW
        default=0, ge=0,
        description="Retry failed test up to N times before final failure"
    )
    timeout_ms: int | None = Field( # NEW
        default=None, ge=1000,
        description="Per-test timeout in ms; None → use agent default"
    )

# --- QAFinding (MODIFIED) ---
class QAFinding(BaseModel):
    test_name: str
    status: Literal["pass", "fail", "error", "skip"]
    detail: str
    screenshot_path: str | None = None
    console_errors: list[str] = []
    duration_ms: int | None = None
    retries: int = 0       # NEW — how many retries were attempted

# --- QAReport (MODIFIED) ---
class QAReport(BaseModel):
    summary: str
    url: str
    findings: list[QAFinding] = []
    total: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: int | None = None

    @property
    def exit_code(self) -> int:            # NEW
        """Return 0 if all pass, 1 if any failure/error."""
        return 1 if (self.failed + self.errors) > 0 else 0

    def to_junit_xml(self) -> str:          # NEW
        """Serialize to JUnit XML format."""
        ...
```

### New Public Interfaces

```python
# --- WebAgent (MODIFIED) ---
class WebAgent(BasicAgent):
    def __init__(
        self,
        name: str = "WebAgent",
        chrome_config: ChromeConfig | None = None,
        default_timeout_ms: int = 60_000,    # NEW
        screenshot_dir: str | None = None,   # NEW
        **kwargs,
    ): ...

    async def run_tests(
        self,
        test_cases: list[QATestCase],
        url: str | None = None,
        tags: list[str] | None = None,       # NEW
    ) -> AIMessage: ...

# --- CLI runner (NEW module) ---
# parrot/bots/chrome_runner.py
async def run_qa(
    test_file: str,
    url: str | None = None,
    headless: bool = True,
    tags: list[str] | None = None,
    junit_output: str | None = None,
    screenshot_dir: str | None = None,
    default_timeout_ms: int = 60_000,
) -> int:
    """Execute QA tests from a file, return exit code."""
    ...

def main() -> None:
    """CLI entry point: python -m parrot.bots.chrome_runner"""
    ...
```

---

## 3. Module Breakdown

### Module 1: Model Enhancements
- **Path**: `packages/ai-parrot/src/parrot/bots/chrome.py`
- **Responsibility**: Add new fields to `QAAssertion`, `QATestCase`,
  `QAFinding`. Add `exit_code` property and `to_junit_xml()` method to
  `QAReport`.
- **Depends on**: None (pure Pydantic model changes)

### Module 2: WebAgent run_tests Enhancements
- **Path**: `packages/ai-parrot/src/parrot/bots/chrome.py`
- **Responsibility**: Modify `WebAgent.__init__()` to accept
  `default_timeout_ms` and `screenshot_dir`. Modify `run_tests()` to
  support tag filtering, per-test timeout via `asyncio.wait_for()`,
  retry logic, and screenshot saving.
- **Depends on**: Module 1

### Module 3: System Prompt Enhancement
- **Path**: `packages/ai-parrot/src/parrot/bots/chrome.py`
- **Responsibility**: Update `WEB_AGENT_SYSTEM_PROMPT` to instruct the LLM
  about wait timeouts on assertions, retry semantics, and the new assertion
  types (`response_status`, `accessibility_check`).
- **Depends on**: Module 1

### Module 4: JUnit XML Serialization
- **Path**: `packages/ai-parrot/src/parrot/bots/chrome.py`
- **Responsibility**: Implement `QAReport.to_junit_xml()` using
  `xml.etree.ElementTree` (stdlib only, no new dependencies). Map
  `QAFinding` statuses to JUnit conventions.
- **Depends on**: Module 1

### Module 5: CLI Runner
- **Path**: `packages/ai-parrot/src/parrot/bots/chrome_runner.py`
- **Responsibility**: Provide `python -m parrot.bots.chrome_runner` entry
  point with `argparse`. Read test definitions from JSON (and optionally
  YAML if `pyyaml` is installed). Parse env vars `CHROME_HEADLESS`,
  `TARGET_URL`, `QA_TAGS`. Write JUnit XML output. Return exit code.
- **Depends on**: Module 1, Module 2, Module 4

### Module 6: Tests
- **Path**: `packages/ai-parrot/tests/bots/test_chrome.py`
- **Responsibility**: Extend existing test suite with tests for all new
  fields, `to_junit_xml()`, tag filtering, retry logic, timeout handling,
  and CLI argument parsing.
- **Depends on**: Module 1, Module 2, Module 4, Module 5

### Module 7: Examples & Documentation
- **Path**: `examples/chrome_qa_test.py`, `examples/chrome_ci_test.py` (NEW)
- **Responsibility**: Update existing example with new features. Create
  new CI-oriented example showing headless + tags + JUnit output +
  screenshot artifacts + exit code.
- **Depends on**: Module 2, Module 5

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_qa_assertion_wait_timeout_default` | 1 | `wait_timeout_ms` defaults to 5000 |
| `test_qa_assertion_new_check_types` | 1 | `response_status` and `accessibility_check` are valid |
| `test_qa_test_case_max_retries_default` | 1 | `max_retries` defaults to 0 |
| `test_qa_test_case_timeout_ms_default` | 1 | `timeout_ms` defaults to None |
| `test_qa_test_case_timeout_ms_minimum` | 1 | `timeout_ms < 1000` raises ValidationError |
| `test_qa_finding_retries_default` | 1 | `retries` defaults to 0 |
| `test_qa_report_exit_code_pass` | 1 | `exit_code` is 0 when all pass |
| `test_qa_report_exit_code_fail` | 1 | `exit_code` is 1 when any fail |
| `test_qa_report_exit_code_error` | 1 | `exit_code` is 1 when any error |
| `test_qa_report_to_junit_xml_valid` | 4 | Output is well-formed XML parseable by `ET.fromstring()` |
| `test_qa_report_to_junit_xml_failure_detail` | 4 | Failure messages include console errors |
| `test_qa_report_to_junit_xml_statuses` | 4 | Maps pass/fail/error/skip correctly |
| `test_run_tests_tag_filtering` | 2 | Only tagged cases are serialized in prompt |
| `test_run_tests_empty_after_filtering` | 2 | Returns report with 0 total when no tags match |
| `test_run_tests_retry_on_failure` | 2 | `ask()` called up to `1 + max_retries` times for failing case |
| `test_run_tests_timeout_marks_error` | 2 | Timeout produces `status="error"` finding |
| `test_run_tests_screenshot_dir` | 2 | Screenshot directory instruction is in prompt |
| `test_web_agent_default_timeout` | 2 | `default_timeout_ms` defaults to 60000 |
| `test_cli_parse_args_minimal` | 5 | `--test-file` is required |
| `test_cli_parse_args_full` | 5 | All flags parse correctly |
| `test_cli_env_vars` | 5 | `CHROME_HEADLESS`, `TARGET_URL`, `QA_TAGS` override defaults |
| `test_serialization_roundtrip_new_fields` | 1 | New fields survive JSON round-trip |

### Integration Tests

| Test | Description |
|---|---|
| `test_junit_xml_circleci_compat` | Generated XML matches CircleCI's expected JUnit schema |
| `test_cli_runner_exit_code` | `chrome_runner.main()` returns 1 on failure, 0 on success |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_test_cases() -> list[QATestCase]:
    return [
        QATestCase(
            name="smoke-homepage",
            url="http://localhost:3000",
            steps=["Wait for page to fully load"],
            expected="No errors",
            assertions=[QAAssertion(check="no_console_errors")],
            tags=["smoke"],
            max_retries=1,
            timeout_ms=30_000,
        ),
        QATestCase(
            name="regression-login",
            url="http://localhost:3000/login",
            steps=["Submit empty form"],
            expected="Validation errors shown",
            assertions=[
                QAAssertion(
                    check="element_visible",
                    target=".error",
                    wait_timeout_ms=3000,
                ),
            ],
            tags=["regression"],
        ),
    ]

@pytest.fixture
def sample_qa_report() -> QAReport:
    return QAReport(
        summary="1/2 passed",
        url="http://localhost:3000",
        findings=[
            QAFinding(test_name="t1", status="pass", detail="ok"),
            QAFinding(test_name="t2", status="fail", detail="not ok",
                      console_errors=["TypeError: x is undefined"],
                      retries=2),
        ],
        total=2, passed=1, failed=1,
    )
```

---

## 5. Acceptance Criteria

- [ ] `QATestCase(max_retries=2)` — `run_tests()` retries a failing test
      case up to 2 additional times before marking as final failure
- [ ] `QATestCase(timeout_ms=30000)` — test case is aborted after 30 seconds
      with `status="error"` and appropriate detail
- [ ] `QAAssertion(check="element_visible", wait_timeout_ms=3000)` — the
      wait timeout is communicated to the LLM in the prompt
- [ ] `run_tests(test_cases, tags=["smoke"])` — only test cases tagged
      `smoke` are executed; unmatched cases are reported as `status="skip"`
- [ ] `QA_TAGS=smoke,critical` env var is respected by the CLI runner
- [ ] `report.to_junit_xml()` — produces valid JUnit XML parseable by
      `xml.etree.ElementTree.fromstring()` and by CircleCI's test parser
- [ ] `report.exit_code` — returns 0 when all pass, 1 when any fail/error
- [ ] `WebAgent(screenshot_dir="qa-screenshots/")` — failure screenshots
      are saved with predictable names (`{test_name}_{timestamp}.png`)
- [ ] `python -m parrot.bots.chrome_runner --test-file tests.json --headless
      --tags smoke --junit-output results.xml --screenshot-dir ./screenshots
      --url http://localhost:3000` — works end-to-end
- [ ] All new fields have sensible defaults — zero breaking changes to
      existing code using `QATestCase`, `QAFinding`, `QAReport`, or `WebAgent`
- [ ] Existing `examples/chrome_qa_test.py` continues to work unchanged
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/bots/test_chrome.py -v`
- [ ] New `examples/chrome_ci_test.py` demonstrates full CI usage pattern

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports

```python
# Core models — packages/ai-parrot/src/parrot/bots/chrome.py
from pydantic import BaseModel, Field            # verified: chrome.py:6
from typing import Literal                        # verified: chrome.py:4
from ..models import AIMessage                    # verified: chrome.py:8
from .agent import BasicAgent                     # verified: chrome.py:9

# For JUnit XML — stdlib
import xml.etree.ElementTree as ET               # stdlib, no install needed

# For CLI runner — stdlib
import argparse                                   # stdlib
import asyncio                                    # stdlib
import json                                       # stdlib
import os                                         # stdlib
import sys                                        # stdlib
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/chrome.py

class ChromeConfig(BaseModel):                    # line 12
    browser_url: str | None = None                # line 44
    headless: bool = False                        # line 45
    user_data_dir: str | None = None              # line 46
    channel: Literal["stable", "beta", "dev", "canary"] | None = None  # line 47
    viewport: str | None = None                   # line 48
    executable_path: str | None = None            # line 49
    isolated: bool = False                        # line 50
    no_usage_statistics: bool = True              # line 51
    auto_connect: bool = False                    # line 52
    port: int = Field(default=9222, ge=1, le=65535)  # line 53

    def to_mcp_args(self) -> list[str]:           # line 55

class QAAssertion(BaseModel):                     # line 85
    check: Literal[                               # line 88
        "element_visible", "element_not_visible",
        "text_contains", "url_matches",
        "no_console_errors", "no_network_failures",
        "screenshot_diff", "performance",
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

class WebAgent(BasicAgent):                       # line 161
    system_prompt_template: str = WEB_AGENT_SYSTEM_PROMPT  # line 164

    def __init__(                                 # line 166
        self,
        name: str = "WebAgent",
        chrome_config: ChromeConfig | None = None,
        **kwargs,
    ): ...
        # Sets: self._prompt_builder = None       # line 177
        # Sets: self.chrome_config                # line 178
        # Sets: self.logger                       # line 179

    async def configure(self, app=None) -> None:  # line 181
        # Calls: self.add_chrome_devtools_mcp_server(...)  # line 190

    async def run_tests(                          # line 203
        self,
        test_cases: list[QATestCase],
        url: str | None = None,
    ) -> AIMessage:
        # Serializes all cases to JSON
        # Calls: self.ask(prompt, structured_output=QAReport)  # line 228

# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(NotificationMixin, Chatbot):     # line 29
    async def ask(                                # (inherited from Chatbot/BaseBot)
        self,
        prompt: str,
        structured_output: type[BaseModel] | None = None,
        **kwargs,
    ) -> AIMessage: ...

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage:
    response: str       # text summary
    output: Any         # structured output (QAReport when structured_output used)
    metadata: dict      # provider metadata
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `QAReport.to_junit_xml()` | `xml.etree.ElementTree` | stdlib | Python stdlib |
| `WebAgent.run_tests()` (retry) | `BasicAgent.ask()` | method call | `chrome.py:228` |
| `WebAgent.run_tests()` (timeout) | `asyncio.wait_for()` | stdlib | Python stdlib |
| `chrome_runner.main()` | `WebAgent` | constructor + `run_tests()` | `chrome.py:166` |
| `chrome_runner` (YAML) | `pyyaml` | optional import | `pip install pyyaml` |

### Does NOT Exist (Anti-Hallucination)

- ~~`WebAgent.default_timeout_ms`~~ — does not exist yet (this spec adds it)
- ~~`WebAgent.screenshot_dir`~~ — does not exist yet (this spec adds it)
- ~~`QAReport.to_junit_xml()`~~ — does not exist yet (this spec adds it)
- ~~`QAReport.exit_code`~~ — does not exist yet (this spec adds it)
- ~~`QATestCase.max_retries`~~ — does not exist yet (this spec adds it)
- ~~`QATestCase.timeout_ms`~~ — does not exist yet (this spec adds it)
- ~~`QAFinding.retries`~~ — does not exist yet (this spec adds it)
- ~~`QAAssertion.wait_timeout_ms`~~ — does not exist yet (this spec adds it)
- ~~`parrot.bots.chrome_runner`~~ — module does not exist yet
- ~~`parrot.bots.chrome.run_qa()`~~ — function does not exist yet
- ~~`WebAgent.run_single_test()`~~ — no per-test method exists; everything
  goes through `run_tests()`

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Pydantic backward compatibility** — all new fields MUST have defaults so
  existing code using `QATestCase(name=..., url=..., steps=..., expected=...)`
  continues to work without changes.
- **System prompt as LLM contract** — the retry/timeout/wait logic is
  orchestrated by `run_tests()` in Python, but the assertion semantics
  (wait for element, check a11y, check response status) are communicated
  to the LLM via the system prompt. The LLM must know about
  `wait_timeout_ms` on assertions so it waits before declaring failure.
- **stdlib only for JUnit XML** — use `xml.etree.ElementTree` to build the
  XML document. No lxml or external XML library.
- **YAML is optional** — the CLI runner must work with JSON input. YAML
  support uses a conditional `import yaml` with a clear error message if
  PyYAML is not installed.

### Retry Strategy

The retry loop lives in `run_tests()`, not in the LLM prompt:

```python
for case in filtered_cases:
    finding = None
    for attempt in range(1 + case.max_retries):
        finding = await self._execute_single_test(case, url)
        if finding.status == "pass":
            break
        finding.retries = attempt
    findings.append(finding)
```

This means each retry is a fresh `ask()` call for that single test case.
The LLM does not need to know about retries — it just executes the test
and reports the result.

### Timeout Strategy

Timeouts wrap the `ask()` call with `asyncio.wait_for()`:

```python
timeout_s = (case.timeout_ms or self.default_timeout_ms) / 1000
try:
    result = await asyncio.wait_for(
        self.ask(prompt, structured_output=QAReport),
        timeout=timeout_s,
    )
except asyncio.TimeoutError:
    finding = QAFinding(
        test_name=case.name,
        status="error",
        detail=f"Test timed out after {case.timeout_ms or self.default_timeout_ms}ms",
    )
```

### JUnit XML Schema

The JUnit XML format expected by CircleCI/GitHub Actions:

```xml
<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="WebAgent QA" tests="3" failures="1" errors="0"
             skipped="0" time="12.345">
    <testcase name="homepage-smoke" time="2.100">
    </testcase>
    <testcase name="login-validation" time="5.200">
      <failure message="Validation errors not shown">
        Console errors:
        - TypeError: x is undefined
      </failure>
    </testcase>
    <testcase name="nav-check" time="0.0">
      <skipped message="Filtered by tags"/>
    </testcase>
  </testsuite>
</testsuites>
```

### Known Risks / Gotchas

1. **LLM non-determinism** — the same `QATestCase` may produce different
   results across runs. `max_retries` mitigates this but does not eliminate
   it. Document that WebAgent QA tests are best suited for smoke/gate tests
   (5–20 cases), not 500-case regression suites.

2. **Cost per run** — each `ask()` call costs LLM tokens. With retries,
   worst case is `sum(1 + max_retries for case in cases)` LLM calls per
   `run_tests()` invocation. The CLI runner should log estimated cost.

3. **Timeout interaction with retries** — if a test times out, the timeout
   counts as one attempt. A test with `max_retries=2, timeout_ms=30000`
   could block for up to 90 seconds before being marked as error.

4. **Screenshot saving** — the LLM reports `screenshot_path` in `QAFinding`
   but the actual screenshot is taken by `chrome-devtools-mcp` tools. The
   `screenshot_dir` parameter must be communicated in the prompt so the LLM
   knows where to save. The directory must exist before `run_tests()` is
   called.

5. **YAML dependency** — PyYAML is not a core dependency. The CLI runner
   must handle `ImportError` gracefully and suggest `pip install pyyaml`.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `xml.etree.ElementTree` | stdlib | JUnit XML generation |
| `argparse` | stdlib | CLI argument parsing |
| `pyyaml` | `>=6.0` (optional) | YAML test file support |

---

## 8. Open Questions

- [ ] Should skipped tests (filtered by tags) appear in the JUnit XML as
      `<skipped/>` elements, or be omitted entirely? — *Owner: Jesus*
- [ ] Should the CLI runner support a `--max-retries` global override that
      applies to all test cases regardless of per-case `max_retries`? —
      *Owner: Jesus*
- [ ] Should `to_junit_xml()` include timing information per test suite
      (requires tracking start/end times in `run_tests()`)? — *Owner: Jesus*

---

## Worktree Strategy

- **Isolation unit**: per-spec (all tasks sequential in one worktree)
- **Rationale**: All modules modify the same file (`chrome.py`) except
  Module 5 (new file) and Module 7 (examples). Sequential execution
  avoids merge conflicts.
- **Cross-feature dependencies**: None — this feature builds on existing
  `WebAgent` already merged to `dev`.
- **Recommended workflow**:
  ```bash
  git checkout dev
  git worktree add -b feat-410-webagent-cicd-qa-runner \
    .claude/worktrees/feat-410-webagent-cicd-qa-runner HEAD
  cd .claude/worktrees/feat-410-webagent-cicd-qa-runner
  claude --agent sdd-worker --model sonnet --verbose
  ```

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-04 | Jesus Lara | Initial draft |
