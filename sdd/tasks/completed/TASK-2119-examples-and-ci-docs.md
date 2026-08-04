# TASK-2119: CI/CD Examples & Documentation

**Feature**: FEAT-410 — WebAgent CI/CD QA Runner Enhancements
**Spec**: `sdd/specs/webagent-cicd-qa-runner.spec.md`
**Status**: done
**Completed**: 2026-08-04
**Verification**: verified (evidence: commits + files present in feat-410-webagent-cicd-qa-runner worktree)
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2117, TASK-2118
**Assigned-to**: unassigned

---

## Context

This task implements Spec Module 7 (Examples & Documentation). It updates
the existing `chrome_qa_test.py` example to showcase new features (tags,
retries, timeout) and creates a new `chrome_ci_test.py` example that
demonstrates the full CI/CD usage pattern — headless mode, tag filtering,
JUnit XML output, screenshot artifacts, and exit code for pipeline gate
decisions.

---

## Scope

- Update `examples/chrome_qa_test.py` to demonstrate new model fields
  (`max_retries`, `timeout_ms`, `wait_timeout_ms`, new assertion types)
  while keeping backward compatibility with the existing usage pattern
- Create `examples/chrome_ci_test.py` — a CI-oriented example showing:
  - Headless mode via `CHROME_HEADLESS` env var
  - `TARGET_URL` env var for dynamic app URLs
  - `QA_TAGS` env var for tag-based filtering
  - `max_retries` for flakiness absorption
  - `timeout_ms` for pipeline protection
  - `screenshot_dir` for CI artifact collection
  - `to_junit_xml()` for CI test dashboard integration
  - `exit_code` for deploy-or-block gate decisions
  - Example `.circleci/config.yml` snippet in docstring
- Create `examples/qa-tests-sample.json` — a sample test definition file
  usable with `python -m parrot.bots.chrome_runner --test-file ...`

**NOT in scope**:
- Model changes — TASK-2115
- JUnit XML implementation — TASK-2116
- run_tests() logic — TASK-2117
- CLI runner — TASK-2118

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/chrome_qa_test.py` | MODIFY | Add new features to existing example |
| `examples/chrome_ci_test.py` | CREATE | CI/CD-oriented example |
| `examples/qa-tests-sample.json` | CREATE | Sample test definition file for CLI runner |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# All from packages/ai-parrot/src/parrot/bots/chrome.py
from parrot.bots.chrome import (
    ChromeConfig,    # line 12
    QAAssertion,     # line 85 (with wait_timeout_ms from TASK-2115)
    QATestCase,      # line 102 (with max_retries, timeout_ms from TASK-2115)
    WebAgent,        # line 161 (with default_timeout_ms, screenshot_dir from TASK-2117)
)
```

### Existing Example Signature
```python
# examples/chrome_qa_test.py — current structure (DO NOT break)
async def main():
    target = os.getenv("TARGET_URL", "https://concierge.trocdigital.io/")
    headless = os.getenv("CHROME_HEADLESS", "0") == "1"

    agent = WebAgent(
        name="QA-Agent",
        chrome_config=ChromeConfig(headless=headless, viewport="1920x1080", no_usage_statistics=True),
    )

    test_cases = [...]  # QATestCase list

    await agent.configure()
    async with agent:
        result = await agent.run_tests(test_cases, url=target)

    report = result.output
    # Print summary
```

### Does NOT Exist
- ~~`examples/chrome_ci_test.py`~~ — does not exist yet (this task creates it)
- ~~`examples/qa-tests-sample.json`~~ — does not exist yet
- ~~`WebAgent.from_config_file()`~~ — no such factory method
- ~~`QAReport.print_summary()`~~ — no such method; print manually

---

## Implementation Notes

### Updated `chrome_qa_test.py`

Keep the existing structure but enhance the test cases with new fields:

```python
test_cases = [
    QATestCase(
        name="homepage-loads",
        url=target,
        steps=["Wait for the page to fully load"],
        expected="Page loads without errors",
        assertions=[
            QAAssertion(check="no_console_errors"),
            QAAssertion(check="no_network_failures"),
            QAAssertion(check="response_status", target="200"),  # NEW
        ],
        tags=["smoke"],
        max_retries=1,      # NEW — retry once on failure
        timeout_ms=30_000,  # NEW — 30 second timeout
    ),
    QATestCase(
        name="login-validation",
        url=f"{target}/login",
        steps=[...],
        expected="Validation errors appear for required fields",
        assertions=[
            QAAssertion(check="url_matches", target="/login"),
            QAAssertion(
                check="element_visible",
                target=".error-message",
                wait_timeout_ms=3000,  # NEW — wait 3s for element
            ),
        ],
        tags=["regression"],
    ),
]
```

### New `chrome_ci_test.py`

```python
"""WebAgent CI/CD QA testing example.

Designed for CI pipelines — runs headless, outputs JUnit XML, exits
with 0 (pass) or 1 (fail) for deploy gate decisions.

Usage:
    # In CircleCI / GitHub Actions / GitLab CI:
    CHROME_HEADLESS=1 TARGET_URL=http://localhost:3000 \\
        python examples/chrome_ci_test.py

    # With tag filtering:
    QA_TAGS=smoke CHROME_HEADLESS=1 python examples/chrome_ci_test.py

    # Or use the CLI runner directly:
    python -m parrot.bots.chrome_runner \\
        --test-file examples/qa-tests-sample.json \\
        --headless --tags smoke --junit-output results.xml

Example .circleci/config.yml snippet:
    jobs:
      ui-qa:
        docker:
          - image: cimg/python:3.12-browsers
        steps:
          - checkout
          - run: uv pip install -e ".[all]"
          - run:
              command: python -m myapp serve --port 3000
              background: true
          - run: |
              CHROME_HEADLESS=1 TARGET_URL=http://localhost:3000 \\
              python examples/chrome_ci_test.py
          - store_test_results:
              path: qa-results/
          - store_artifacts:
              path: qa-screenshots/
"""
```

### Key Constraints
- `chrome_qa_test.py` changes must be backward compatible — the existing
  test cases must still work if run without the new features
- `chrome_ci_test.py` must work with `CHROME_HEADLESS=1` in Docker/CI
- `qa-tests-sample.json` must be parseable by `load_test_cases()` from
  TASK-2118

---

## Acceptance Criteria

- [ ] `examples/chrome_qa_test.py` runs without errors (both with and
      without `CHROME_HEADLESS=1`)
- [ ] `examples/chrome_qa_test.py` demonstrates `max_retries`, `timeout_ms`,
      `wait_timeout_ms`, and `response_status` assertion
- [ ] `examples/chrome_ci_test.py` exists and demonstrates full CI pattern:
      headless, tags, JUnit output, screenshots, exit code
- [ ] `examples/qa-tests-sample.json` is valid JSON parseable as
      `list[QATestCase]`
- [ ] `python -m parrot.bots.chrome_runner --test-file examples/qa-tests-sample.json`
      loads successfully (modulo actual Chrome being available)
- [ ] No import errors from any example file

---

## Test Specification

No automated tests for example files — they are documentation artifacts.
Manual verification:

```bash
# Verify examples import cleanly
python -c "import examples.chrome_qa_test"
python -c "import examples.chrome_ci_test"

# Verify JSON sample is valid
python -c "
import json
from parrot.bots.chrome import QATestCase
with open('examples/qa-tests-sample.json') as f:
    data = json.load(f)
for item in data:
    QATestCase.model_validate(item)
print('OK')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webagent-cicd-qa-runner.spec.md`
2. **Check dependencies** — verify TASK-2117 and TASK-2118 are completed
3. **Read the existing** `examples/chrome_qa_test.py` before modifying
4. **Create** the new example and sample JSON file
5. **Verify** imports work and JSON is valid
6. **Complete** per standard SDD workflow

---

## Completion Note

*(Agent fills this in when done)*
