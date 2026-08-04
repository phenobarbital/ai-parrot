# TASK-2117: WebAgent run_tests Enhancements

**Feature**: FEAT-410 — WebAgent CI/CD QA Runner Enhancements
**Spec**: `sdd/specs/webagent-cicd-qa-runner.spec.md`
**Status**: done
**Completed**: 2026-08-04
**Verification**: verified (evidence: commits + files present in feat-410-webagent-cicd-qa-runner worktree)
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2115
**Assigned-to**: unassigned

---

## Context

This is the core task for FEAT-410. It implements Spec Modules 2 and 3 —
modifying `WebAgent` to support tag-based test filtering, per-test retry
with `max_retries`, per-test timeout via `asyncio.wait_for()`, screenshot
directory management, and updating the system prompt so the LLM knows
about the new assertion semantics (wait timeouts, response_status,
accessibility_check).

The retry/timeout/filtering logic lives in Python code (not in the LLM
prompt). The LLM is only informed about assertion semantics so it can
execute them correctly via MCP tools.

---

## Scope

- Add `default_timeout_ms: int = 60_000` parameter to `WebAgent.__init__()`
- Add `screenshot_dir: str | None = None` parameter to `WebAgent.__init__()`
- Add `tags: list[str] | None = None` parameter to `WebAgent.run_tests()`
- Implement tag-based filtering in `run_tests()`: when `tags` is provided,
  only execute test cases whose `tags` intersect; unmatched cases get
  `QAFinding(status="skip", detail="Filtered by tags")`
- Implement retry loop: for each test case, call the LLM up to
  `1 + case.max_retries` times, stopping on first pass. Track retries in
  `QAFinding.retries`.
- Implement per-test timeout: wrap the LLM `ask()` call with
  `asyncio.wait_for()` using `case.timeout_ms or self.default_timeout_ms`;
  on timeout, produce `QAFinding(status="error", detail="...")`
- Refactor `run_tests()` to process one test case at a time instead of
  sending all cases in a single prompt (required for per-test retry/timeout)
- Include `screenshot_dir` and assertion `wait_timeout_ms` information in
  the per-test prompt so the LLM knows where to save and how long to wait
- Update `WEB_AGENT_SYSTEM_PROMPT` to document new assertion types
  (`response_status`, `accessibility_check`) and `wait_timeout_ms` semantics
- Write comprehensive unit tests (mocking `ask()`)

**NOT in scope**:
- Model field changes — TASK-2115 (already done)
- JUnit XML output — TASK-2116
- CLI runner — TASK-2118
- Example files — TASK-2119

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/chrome.py` | MODIFY | Enhance WebAgent.__init__(), run_tests(), WEB_AGENT_SYSTEM_PROMPT |
| `packages/ai-parrot/tests/bots/test_chrome.py` | MODIFY | Tests for retry, timeout, tag filtering, screenshot_dir |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field            # verified: chrome.py:6
from typing import Literal                        # verified: chrome.py:4
import logging                                    # verified: chrome.py:3
import asyncio                                    # stdlib — add this import
from ..models import AIMessage                    # verified: chrome.py:8
from .agent import BasicAgent                     # verified: chrome.py:9
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/chrome.py

class WebAgent(BasicAgent):                       # line 161
    system_prompt_template: str = WEB_AGENT_SYSTEM_PROMPT  # line 164

    def __init__(                                 # line 166
        self,
        name: str = "WebAgent",
        chrome_config: ChromeConfig | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self._prompt_builder = None               # line 177
        self.chrome_config = chrome_config or ChromeConfig()  # line 178
        self.logger = logging.getLogger(f"{self.name}.WebAgent")  # line 179

    async def configure(self, app=None) -> None:  # line 181
        # Unchanged — do NOT modify

    async def run_tests(                          # line 203
        self,
        test_cases: list[QATestCase],
        url: str | None = None,
    ) -> AIMessage:
        cases_text = "\n\n".join(                 # line 217
            case.model_dump_json(indent=2) for case in test_cases
        )
        base_url = url or test_cases[0].url       # line 220
        prompt = (...)                            # line 221-227
        return await self.ask(prompt, structured_output=QAReport)  # line 228

# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(NotificationMixin, Chatbot):     # line 29
    # ask() inherited from Chatbot/BaseBot:
    async def ask(
        self,
        prompt: str,
        structured_output: type[BaseModel] | None = None,
        **kwargs,
    ) -> AIMessage: ...

# QATestCase fields (after TASK-2115)
class QATestCase(BaseModel):
    name: str
    url: str
    steps: list[str]
    expected: str
    assertions: list[QAAssertion] = []
    screenshot_on_fail: bool = True
    viewport: str | None = None
    tags: list[str] = []
    max_retries: int = Field(default=0, ge=0)       # ADDED BY TASK-2115
    timeout_ms: int | None = Field(default=None, ge=1000)  # ADDED BY TASK-2115

# QAFinding (after TASK-2115)
class QAFinding(BaseModel):
    test_name: str
    status: Literal["pass", "fail", "error", "skip"]
    detail: str
    screenshot_path: str | None = None
    console_errors: list[str] = []
    duration_ms: int | None = None
    retries: int = 0                               # ADDED BY TASK-2115
```

### Does NOT Exist
- ~~`WebAgent.default_timeout_ms`~~ — does not exist yet (this task adds it)
- ~~`WebAgent.screenshot_dir`~~ — does not exist yet (this task adds it)
- ~~`WebAgent._execute_single_test()`~~ — does not exist yet (internal helper this task may create)
- ~~`WebAgent.run_single_test()`~~ — no per-test public method exists
- ~~`BasicAgent.ask_with_timeout()`~~ — no such method; use `asyncio.wait_for()`

---

## Implementation Notes

### Architecture of the refactored `run_tests()`

The current `run_tests()` sends ALL test cases in a single `ask()` call.
This must be refactored to process one test case at a time so that retry
and timeout can be applied per-test.

```python
async def run_tests(
    self,
    test_cases: list[QATestCase],
    url: str | None = None,
    tags: list[str] | None = None,
) -> AIMessage:
    base_url = url or test_cases[0].url
    findings: list[QAFinding] = []

    for case in test_cases:
        # 1. Tag filtering
        if tags and not set(tags).intersection(case.tags):
            findings.append(QAFinding(
                test_name=case.name,
                status="skip",
                detail="Filtered by tags",
            ))
            continue

        # 2. Retry loop with timeout
        finding = None
        for attempt in range(1 + case.max_retries):
            timeout_s = (case.timeout_ms or self.default_timeout_ms) / 1000
            try:
                single_report = await asyncio.wait_for(
                    self._execute_single_test(case, base_url),
                    timeout=timeout_s,
                )
                finding = single_report  # QAFinding from single test
                if finding.status == "pass":
                    break
            except asyncio.TimeoutError:
                finding = QAFinding(
                    test_name=case.name,
                    status="error",
                    detail=f"Timed out after {case.timeout_ms or self.default_timeout_ms}ms",
                )
            finding.retries = attempt
        findings.append(finding)

    # 3. Build aggregate report
    report = QAReport(
        summary=f"{sum(1 for f in findings if f.status == 'pass')}/{len(findings)} passed",
        url=base_url,
        findings=findings,
        total=len(findings),
        passed=sum(1 for f in findings if f.status == "pass"),
        failed=sum(1 for f in findings if f.status == "fail"),
        errors=sum(1 for f in findings if f.status == "error"),
        skipped=sum(1 for f in findings if f.status == "skip"),
    )
    return AIMessage(response=report.summary, output=report)
```

### Per-test prompt construction (`_execute_single_test`)

Create a private helper that builds a prompt for one test case and calls
`self.ask()`:

```python
async def _execute_single_test(
    self, case: QATestCase, base_url: str,
) -> QAFinding:
    prompt = (
        f"Execute the following QA test case against {base_url}.\n"
        f"Navigate to the URL, execute the steps, evaluate the expected "
        f"result and any assertions.\n"
    )
    if self.screenshot_dir:
        prompt += f"Save failure screenshots to: {self.screenshot_dir}\n"
    # Include wait_timeout_ms info for assertions
    for a in case.assertions:
        if a.wait_timeout_ms and a.check in ("element_visible", "element_not_visible", "text_contains"):
            prompt += f"For '{a.check}' on '{a.target}': wait up to {a.wait_timeout_ms}ms.\n"
    prompt += f"\nTest case:\n{case.model_dump_json(indent=2)}"

    result = await self.ask(prompt, structured_output=QAFinding)
    return result.output
```

### System Prompt Update

Add documentation for new assertion types and wait semantics:

```python
WEB_AGENT_SYSTEM_PROMPT = """\
You are a web interaction agent with access to a Chrome browser via Chrome \
DevTools tools. ...

Assertion types you support:
- element_visible: Check if a CSS selector is visible on the page. \
  Respect the wait_timeout_ms — wait up to that many milliseconds before \
  declaring the element not found.
- element_not_visible: Inverse of element_visible.
- text_contains: Check if the page contains the specified text.
- url_matches: Check the current URL matches the target pattern.
- no_console_errors: Verify no JavaScript errors in the console.
- no_network_failures: Verify no failed network requests (4xx/5xx).
- response_status: Verify the HTTP response status code matches the target value.
- accessibility_check: Perform basic accessibility validation — check for \
  ARIA roles, alt text on images, proper heading hierarchy.
- screenshot_diff: (placeholder — not yet implemented)
- performance: Check performance metrics against thresholds.

When an assertion has a wait_timeout_ms value, wait up to that many \
milliseconds for the condition to become true before reporting failure.\
"""
```

### Key Constraints
- `configure()` is NOT modified — Chrome connection logic stays the same
- `_execute_single_test()` returns a `QAFinding`, not a `QAReport` — this
  means the `structured_output` for per-test calls is `QAFinding`
- The aggregate `QAReport` is built in Python from the individual findings,
  NOT returned by the LLM
- `AIMessage` construction: `AIMessage(response=report.summary, output=report)`
- Screenshot directory must NOT be created by `run_tests()` — the caller
  is responsible for ensuring it exists

---

## Acceptance Criteria

- [ ] `WebAgent(default_timeout_ms=30000).default_timeout_ms == 30000`
- [ ] `WebAgent(screenshot_dir="/tmp/ss").screenshot_dir == "/tmp/ss"`
- [ ] `run_tests(cases, tags=["smoke"])` only executes smoke-tagged cases
- [ ] Unmatched cases appear as `QAFinding(status="skip")`
- [ ] `run_tests()` with `max_retries=2` calls `ask()` up to 3 times for
      a failing test
- [ ] `run_tests()` with `timeout_ms=1000` produces `status="error"` on
      timeout
- [ ] `screenshot_dir` appears in per-test prompt when set
- [ ] `wait_timeout_ms` info appears in prompt for element-based assertions
- [ ] `WEB_AGENT_SYSTEM_PROMPT` documents all assertion types including
      `response_status` and `accessibility_check`
- [ ] `run_tests()` with no tags runs all tests (backward compatible)
- [ ] All existing tests still pass
- [ ] New tests pass: `pytest packages/ai-parrot/tests/bots/test_chrome.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_chrome.py — APPEND these tests

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from parrot.bots.agent import BasicAgent
from parrot.bots.chrome import (
    ChromeConfig, QAAssertion, QAFinding, QAReport, QATestCase, WebAgent,
)


def test_web_agent_default_timeout_ms():
    agent = WebAgent(name="test")
    assert agent.default_timeout_ms == 60_000


def test_web_agent_custom_timeout_ms():
    agent = WebAgent(name="test", default_timeout_ms=30_000)
    assert agent.default_timeout_ms == 30_000


def test_web_agent_screenshot_dir_default():
    agent = WebAgent(name="test")
    assert agent.screenshot_dir is None


def test_web_agent_screenshot_dir_custom():
    agent = WebAgent(name="test", screenshot_dir="/tmp/screenshots")
    assert agent.screenshot_dir == "/tmp/screenshots"


@pytest.mark.asyncio
async def test_run_tests_tag_filtering():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", tags=["smoke"]),
            QATestCase(name="t2", url="/", steps=["s"], expected="e", tags=["regression"]),
        ]
        result = await agent.run_tests(cases, tags=["smoke"])
        report = result.output

        assert report.total == 2
        assert report.skipped == 1
        # Only one ask() call (the smoke test), not two
        assert agent.ask.call_count == 1


@pytest.mark.asyncio
async def test_run_tests_empty_after_tag_filtering():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()
        agent.ask = AsyncMock()

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", tags=["regression"]),
        ]
        result = await agent.run_tests(cases, tags=["smoke"])
        report = result.output

        assert report.total == 1
        assert report.skipped == 1
        assert report.passed == 0
        agent.ask.assert_not_called()


@pytest.mark.asyncio
async def test_run_tests_no_tags_runs_all():
    """Backward compatibility: no tags filter runs everything."""
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = None
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [
            QATestCase(name="t1", url="/", steps=["s"], expected="e", tags=["smoke"]),
            QATestCase(name="t2", url="/", steps=["s"], expected="e", tags=["regression"]),
        ]
        result = await agent.run_tests(cases)

        assert agent.ask.call_count == 2


@pytest.mark.asyncio
async def test_run_tests_screenshot_dir_in_prompt():
    with patch.object(BasicAgent, "__init__", return_value=None):
        agent = WebAgent.__new__(WebAgent)
        agent.name = "test"
        agent.chrome_config = ChromeConfig()
        agent.default_timeout_ms = 60_000
        agent.screenshot_dir = "/tmp/qa-screenshots"
        agent.logger = MagicMock()

        pass_finding = QAFinding(test_name="t1", status="pass", detail="ok")
        mock_msg = MagicMock()
        mock_msg.output = pass_finding
        agent.ask = AsyncMock(return_value=mock_msg)

        cases = [QATestCase(name="t1", url="/", steps=["s"], expected="e")]
        await agent.run_tests(cases)

        prompt = agent.ask.call_args[0][0]
        assert "/tmp/qa-screenshots" in prompt
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webagent-cicd-qa-runner.spec.md`
2. **Check dependencies** — verify TASK-2115 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm WebAgent signatures
4. **Key design decision**: `run_tests()` now processes tests one-at-a-time
   (not all in one prompt) to support per-test retry and timeout. The
   structured output for individual tests is `QAFinding` (not `QAReport`).
   The aggregate `QAReport` is built in Python.
5. **Update status** → `"in-progress"`
6. **Implement**, **test**, **verify**, **complete**

---

## Completion Note

*(Agent fills this in when done)*
