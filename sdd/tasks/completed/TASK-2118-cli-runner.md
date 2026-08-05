# TASK-2118: CLI QA Runner Entry Point

**Feature**: FEAT-410 — WebAgent CI/CD QA Runner Enhancements
**Spec**: `sdd/specs/webagent-cicd-qa-runner.spec.md`
**Status**: done
**Completed**: 2026-08-04
**Verification**: verified (evidence: commits + files present in feat-410-webagent-cicd-qa-runner worktree)
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2115, TASK-2116, TASK-2117
**Assigned-to**: unassigned

---

## Context

This task implements Spec Module 5 (CLI Runner) — a zero-code entry point
for running WebAgent QA tests from the command line. This is what CI
pipelines invoke directly:

```bash
python -m parrot.bots.chrome_runner \
  --test-file tests/qa/smoke.json \
  --headless \
  --tags smoke \
  --junit-output results.xml \
  --screenshot-dir qa-screenshots/ \
  --url http://localhost:3000
```

The runner reads test case definitions from a JSON (or optionally YAML)
file, constructs a `WebAgent` with the appropriate configuration, executes
`run_tests()`, writes JUnit XML output if requested, and exits with 0
(all pass) or 1 (any failure).

---

## Scope

- Create new module `packages/ai-parrot/src/parrot/bots/chrome_runner.py`
- Implement `argparse`-based CLI with flags:
  - `--test-file` (required) — path to JSON/YAML file with QATestCase defs
  - `--url` — base URL override
  - `--headless` — flag, enables headless Chrome
  - `--tags` — comma-separated tag filter
  - `--junit-output` — path to write JUnit XML results
  - `--screenshot-dir` — directory for failure screenshots
  - `--default-timeout` — default timeout in ms (default: 60000)
  - `--port` — Chrome debugging port (default: 9222)
  - `--viewport` — viewport size (e.g. "1920x1080")
- Support environment variable overrides:
  - `CHROME_HEADLESS=1` → `--headless`
  - `TARGET_URL=...` → `--url`
  - `QA_TAGS=smoke,critical` → `--tags`
- Read test file: parse JSON array of QATestCase objects; if file ends in
  `.yaml`/`.yml`, attempt YAML parsing with graceful error on missing PyYAML
- Create `screenshot_dir` if it doesn't exist
- Call `WebAgent.run_tests()` with the parsed cases and options
- Write JUnit XML to `--junit-output` if specified
- Print human-readable summary to stdout
- `sys.exit(report.exit_code)`
- Add `__main__.py` or equivalent so `python -m parrot.bots.chrome_runner` works
- Write unit tests for argument parsing and test file loading

**NOT in scope**:
- Model changes — TASK-2115
- JUnit XML serialization — TASK-2116
- run_tests() logic — TASK-2117
- Example files — TASK-2119

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/chrome_runner.py` | CREATE | CLI entry point module |
| `packages/ai-parrot/tests/bots/test_chrome_runner.py` | CREATE | Unit tests for CLI runner |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# From this package — all verified in chrome.py
from parrot.bots.chrome import (
    ChromeConfig,       # line 12
    QATestCase,         # line 102
    QAReport,           # line 126 (with exit_code, to_junit_xml from TASK-2116)
    WebAgent,           # line 161 (with new params from TASK-2117)
)

# Stdlib
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
```

### Existing Signatures to Use (after TASK-2115/2116/2117)
```python
class ChromeConfig(BaseModel):
    headless: bool = False
    viewport: str | None = None
    no_usage_statistics: bool = True
    port: int = Field(default=9222, ge=1, le=65535)
    # ... other fields unchanged

class WebAgent(BasicAgent):
    def __init__(
        self,
        name: str = "WebAgent",
        chrome_config: ChromeConfig | None = None,
        default_timeout_ms: int = 60_000,         # ADDED BY TASK-2117
        screenshot_dir: str | None = None,        # ADDED BY TASK-2117
        **kwargs,
    ): ...

    async def configure(self, app=None) -> None: ...

    async def run_tests(
        self,
        test_cases: list[QATestCase],
        url: str | None = None,
        tags: list[str] | None = None,            # ADDED BY TASK-2117
    ) -> AIMessage: ...

class QAReport(BaseModel):
    @property
    def exit_code(self) -> int: ...               # ADDED BY TASK-2116
    def to_junit_xml(self, suite_name: str = "WebAgent QA") -> str: ...  # ADDED BY TASK-2116
```

### Does NOT Exist
- ~~`parrot.bots.chrome_runner`~~ — does not exist yet (this task creates it)
- ~~`WebAgent.from_cli_args()`~~ — no such factory
- ~~`QATestCase.from_file()`~~ — no such method; parse JSON manually
- ~~`ChromeConfig.from_env()`~~ — no such method; construct from parsed args

---

## Implementation Notes

### Module Structure

```python
# packages/ai-parrot/src/parrot/bots/chrome_runner.py
"""CLI runner for WebAgent QA tests.

Usage:
    python -m parrot.bots.chrome_runner --test-file tests.json --headless
    CHROME_HEADLESS=1 TARGET_URL=http://app:3000 python -m parrot.bots.chrome_runner --test-file tests.json
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from .chrome import ChromeConfig, QATestCase, WebAgent


def load_test_cases(file_path: str) -> list[QATestCase]:
    """Load QATestCase definitions from a JSON or YAML file."""
    path = Path(file_path)
    text = path.read_text(encoding="utf-8")

    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            print(
                "ERROR: PyYAML is required for YAML test files. "
                "Install with: uv pip install pyyaml",
                file=sys.stderr,
            )
            sys.exit(2)
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)

    if not isinstance(raw, list):
        raw = [raw]
    return [QATestCase.model_validate(item) for item in raw]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parrot.bots.chrome_runner",
        description="Run WebAgent QA tests from a definition file.",
    )
    parser.add_argument("--test-file", required=True, help="Path to JSON/YAML test definitions")
    parser.add_argument("--url", default=None, help="Base URL override")
    parser.add_argument("--headless", action="store_true", default=False, help="Run Chrome headless")
    parser.add_argument("--tags", default=None, help="Comma-separated tag filter")
    parser.add_argument("--junit-output", default=None, help="Path to write JUnit XML")
    parser.add_argument("--screenshot-dir", default=None, help="Directory for failure screenshots")
    parser.add_argument("--default-timeout", type=int, default=60000, help="Default timeout in ms")
    parser.add_argument("--port", type=int, default=9222, help="Chrome debugging port")
    parser.add_argument("--viewport", default=None, help="Viewport size (e.g. 1920x1080)")
    return parser


async def run_qa(args: argparse.Namespace) -> int:
    """Execute QA tests and return exit code."""
    # Apply env var overrides
    ...
    # Load test cases
    ...
    # Create and configure WebAgent
    ...
    # Run tests
    ...
    # Write JUnit XML if requested
    ...
    # Print summary
    ...
    return report.exit_code


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(run_qa(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

### Environment Variable Override Priority

CLI flags take precedence over env vars. Apply env vars only when the
flag is at its default:

```python
headless = args.headless or os.getenv("CHROME_HEADLESS", "0") == "1"
url = args.url or os.getenv("TARGET_URL")
tags_str = args.tags or os.getenv("QA_TAGS")
tags = tags_str.split(",") if tags_str else None
```

### Test File Format

JSON example (`tests/qa/smoke.json`):
```json
[
  {
    "name": "homepage-smoke",
    "url": "http://localhost:3000",
    "steps": ["Wait for page to fully load"],
    "expected": "No errors",
    "assertions": [{"check": "no_console_errors"}],
    "tags": ["smoke"],
    "max_retries": 1,
    "timeout_ms": 30000
  }
]
```

### Key Constraints
- YAML support is optional — handle `ImportError` gracefully
- Create `screenshot_dir` with `Path.mkdir(parents=True, exist_ok=True)`
- Use `asyncio.run()` in `main()` — the runner is a standalone script
- Exit code 2 for usage errors (bad args, missing file), 1 for test
  failures, 0 for all pass
- Log level defaults to INFO; add `--verbose` for DEBUG if time permits

---

## Acceptance Criteria

- [ ] `python -m parrot.bots.chrome_runner --test-file tests.json --headless`
      works end-to-end (with mocked WebAgent for unit tests)
- [ ] `--tags smoke,critical` only runs matching tests
- [ ] `--junit-output results.xml` writes valid JUnit XML file
- [ ] `--screenshot-dir ./screenshots` creates directory and passes to WebAgent
- [ ] `CHROME_HEADLESS=1` env var is respected
- [ ] `TARGET_URL=http://app:3000` env var is respected
- [ ] `QA_TAGS=smoke` env var is respected
- [ ] CLI flags override env vars
- [ ] Missing `--test-file` prints usage and exits with code 2
- [ ] Non-existent test file path prints error and exits with code 2
- [ ] YAML file with missing PyYAML prints install instruction and exits 2
- [ ] `load_test_cases()` parses valid JSON array of QATestCase objects
- [ ] Exit code is 0 on all pass, 1 on any failure
- [ ] All tests pass: `pytest packages/ai-parrot/tests/bots/test_chrome_runner.py -v`

---

## Test Specification

```python
# packages/ai-parrot/tests/bots/test_chrome_runner.py

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from parrot.bots.chrome_runner import build_parser, load_test_cases
from parrot.bots.chrome import QATestCase


def test_build_parser_requires_test_file():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_minimal():
    parser = build_parser()
    args = parser.parse_args(["--test-file", "tests.json"])
    assert args.test_file == "tests.json"
    assert args.headless is False
    assert args.url is None
    assert args.tags is None
    assert args.junit_output is None


def test_build_parser_full():
    parser = build_parser()
    args = parser.parse_args([
        "--test-file", "tests.json",
        "--url", "http://localhost:3000",
        "--headless",
        "--tags", "smoke,critical",
        "--junit-output", "results.xml",
        "--screenshot-dir", "./screenshots",
        "--default-timeout", "30000",
        "--port", "9333",
        "--viewport", "1920x1080",
    ])
    assert args.headless is True
    assert args.tags == "smoke,critical"
    assert args.default_timeout == 30000
    assert args.port == 9333


def test_load_test_cases_json(tmp_path):
    f = tmp_path / "tests.json"
    f.write_text(json.dumps([{
        "name": "t1", "url": "/", "steps": ["s"], "expected": "e",
    }]))
    cases = load_test_cases(str(f))
    assert len(cases) == 1
    assert cases[0].name == "t1"
    assert isinstance(cases[0], QATestCase)


def test_load_test_cases_single_object(tmp_path):
    """A single object (not wrapped in array) should also work."""
    f = tmp_path / "tests.json"
    f.write_text(json.dumps({
        "name": "t1", "url": "/", "steps": ["s"], "expected": "e",
    }))
    cases = load_test_cases(str(f))
    assert len(cases) == 1


def test_load_test_cases_with_new_fields(tmp_path):
    f = tmp_path / "tests.json"
    f.write_text(json.dumps([{
        "name": "t1", "url": "/", "steps": ["s"], "expected": "e",
        "max_retries": 2, "timeout_ms": 15000, "tags": ["smoke"],
    }]))
    cases = load_test_cases(str(f))
    assert cases[0].max_retries == 2
    assert cases[0].timeout_ms == 15000
    assert cases[0].tags == ["smoke"]
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/webagent-cicd-qa-runner.spec.md`
2. **Check dependencies** — verify TASK-2115, TASK-2116, TASK-2117 are
   completed
3. **Create** `chrome_runner.py` and its test file
4. **Test** with `pytest packages/ai-parrot/tests/bots/test_chrome_runner.py -v`
5. **Complete** per standard SDD workflow

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 4.5)
**Date**: 2026-08-04
**Notes**: Created `parrot/bots/chrome_runner.py` with `load_test_cases()`
(JSON always supported, YAML optional via `import yaml` with a graceful
`sys.exit(2)` + install hint on `ImportError`; missing file / invalid JSON
also exit 2), `build_parser()` (all 9 flags from the spec plus `--verbose`),
`run_qa()` (creates `screenshot_dir` if missing, builds `WebAgent` with
`default_timeout_ms`/`screenshot_dir`, calls `agent.configure()` then
`async with agent: run_tests(...)` — same pattern as
`examples/chrome_qa_test.py` — prints a human-readable summary, writes
JUnit XML when requested, returns `report.exit_code`), and `main()`
(env var overrides `CHROME_HEADLESS`/`TARGET_URL`/`QA_TAGS` applied only
when the corresponding CLI flag is at its default, so flags win;
`asyncio.run()` + `sys.exit()`). Verified `python -m
parrot.bots.chrome_runner --help` works end-to-end. Created
`tests/bots/test_chrome_runner.py` with 19 tests covering parser,
file loading (JSON/YAML/missing/invalid), `run_qa()` exit codes/tags/
JUnit output/screenshot dir (WebAgent mocked, no real Chrome), and
`main()` env var precedence + exit code propagation. All 19 pass;
`ruff check` clean.

**Deviations from spec**: none.
