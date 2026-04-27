# TASK-888: Unit-test sweep + shared fixtures for dev-loop

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-874, TASK-875, TASK-876, TASK-877, TASK-878, TASK-879, TASK-880, TASK-881, TASK-882, TASK-883, TASK-884, TASK-885, TASK-886, TASK-887
**Assigned-to**: unassigned

---

## Context

Each module-level task carries its own unit tests scaffolded in its
file. This task is a **consolidation pass**: it adds shared fixtures
in `conftest.py`, fills any gaps in the spec §4 unit-test list that
weren't covered by individual tasks, and verifies the whole
`packages/ai-parrot/tests/flows/dev_loop/` suite passes together with
no cross-test pollution.

Spec §4 names 21 unit tests. By the time you start this task, ~18 of
them already exist (in `test_models.py`, `test_dispatcher.py`, etc.).
This task fills the remaining gaps and adds the canonical fixtures.

---

## Scope

- Implement `packages/ai-parrot/tests/flows/dev_loop/conftest.py` with:
  - `sample_bug_brief` fixture (from spec §4 fixture block).
  - `fake_dispatch_messages` fixture (mock SDK message stream).
  - `fake_redis` fixture (uses `fakeredis` if available, else mock).
  - `mock_dispatcher` fixture (a `MagicMock` with an `AsyncMock`
    `dispatch` attribute pre-wired with sensible defaults).
  - `mock_jira` fixture (toolkit with the four most-used methods
    pre-mocked).
- Audit each test file produced by TASKs 874, 878, 879, 880-887 for
  spec §4 coverage. Add any missing tests:
  - `test_settings_defaults` (probably absent from individual tasks
    if TASK-876 didn't cover all six constants).
  - Any `@pytest.mark.parametrize` rounding off the discriminated union
    coverage.
- Add a single top-level integration assertion: importing
  `parrot.flows.dev_loop` does NOT trigger a `claude_agent_sdk`
  import. Use `sys.modules` introspection.

**NOT in scope**:
- Live integration tests (TASK-889).
- Tests that require a real Redis (use `fakeredis`).
- Tests that require a real Claude Code subprocess.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/conftest.py` | CREATE | Shared fixtures. |
| `packages/ai-parrot/tests/flows/dev_loop/test_lazy_import.py` | CREATE | Asserts no SDK import side-effect. |
| Existing `test_*.py` files | MODIFY (as needed) | Refactor to consume shared fixtures. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
# fakeredis is optional — fall back to mocks if unavailable
try:
    import fakeredis.aioredis as fakeredis_async   # noqa
    FAKEREDIS_AVAILABLE = True
except ImportError:
    FAKEREDIS_AVAILABLE = False

from parrot.flows.dev_loop import (
    BugBrief, FlowtaskCriterion, ShellCriterion, LogSource,
)
```

### Existing Signatures to Use

The fixtures rely entirely on the public API exposed by
`parrot.flows.dev_loop.__init__`. No new internal calls.

### Does NOT Exist

- ~~`pytest_asyncio.plugin`-specific imports~~ — `pytest-asyncio` is
  expected to be installed; mark async tests with `@pytest.mark.asyncio`.
- ~~A central `tests/conftest.py` import~~ — the dev-loop fixtures live
  in their own subdirectory `conftest.py`.

---

## Implementation Notes

### `conftest.py`

```python
# packages/ai-parrot/tests/flows/dev_loop/conftest.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from parrot.flows.dev_loop import (
    BugBrief, FlowtaskCriterion, ShellCriterion, LogSource,
)


@pytest.fixture
def sample_bug_brief() -> BugBrief:
    return BugBrief(
        summary=("Customer sync flowtask drops the last row when the "
                 "input has >1000 records"),
        affected_component="etl/customers/sync.yaml",
        log_sources=[LogSource(kind="cloudwatch",
                               locator="/etl/prod/customers",
                               time_window_minutes=120)],
        acceptance_criteria=[
            FlowtaskCriterion(name="customers-sync-passes",
                              task_path="etl/customers/sync.yaml",
                              expected_exit_code=0),
            ShellCriterion(name="lint-clean", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def fake_dispatch_messages():
    """Mimics the message stream that ClaudeAgentClient.ask_stream() yields.

    The objects are duck-typed — no real claude_agent_sdk import — so
    tests can run in environments without the SDK extra installed.
    """
    class _AssistantMessage:
        def __init__(self, content): self.content = content
    class _TextBlock:
        def __init__(self, text): self.text = text
    class _ResultMessage:
        def __init__(self, **kw):
            self.subtype = kw.get("subtype", "success")
            self.num_turns = kw.get("num_turns", 1)
            self.total_cost_usd = kw.get("total_cost_usd", 0.0)

    return [
        _AssistantMessage(content=[
            _TextBlock(text='{"jira_issue_key":"OPS-1",'
                            '"spec_path":"sdd/specs/x.spec.md",'),
        ]),
        _AssistantMessage(content=[
            _TextBlock(text='"feat_id":"FEAT-130",'
                            '"branch_name":"feat-130-fix",'
                            '"worktree_path":'
                            '"/abs/.claude/worktrees/feat-130-fix",'
                            '"log_excerpts":[]}'),
        ]),
        _ResultMessage(),
    ]


@pytest.fixture
def mock_jira():
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_transition_issue = AsyncMock()
    j.jira_add_comment = AsyncMock()
    j.jira_assign_issue = AsyncMock()
    return j


@pytest.fixture
def mock_dispatcher():
    d = MagicMock()
    d.dispatch = AsyncMock()
    return d
```

### Lazy-import test

```python
# packages/ai-parrot/tests/flows/dev_loop/test_lazy_import.py
import sys
import importlib


def test_import_does_not_pull_in_sdk():
    # Force a clean reimport
    for mod in list(sys.modules):
        if mod.startswith("parrot.flows.dev_loop") or \
           mod.startswith("claude_agent_sdk"):
            del sys.modules[mod]
    importlib.import_module("parrot.flows.dev_loop")
    assert "claude_agent_sdk" not in sys.modules, (
        "Importing parrot.flows.dev_loop must not pull in claude_agent_sdk"
    )
```

### Key Constraints

- Tests run under `pytest -p asyncio_mode=auto` OR with explicit
  `@pytest.mark.asyncio` — match the existing project convention by
  reading `pyproject.toml [tool.pytest.ini_options]`.
- No flaky timing assertions. The semaphore-blocking test in TASK-878
  is the only place that uses `asyncio.sleep`; if it's flaky on CI,
  switch to `asyncio.wait_for` with a short timeout instead of
  pinning timings.

### References in Codebase

- Existing `tests/` subdirectories — copy the conftest pattern from
  the most recent test suite (e.g. `tests/loaders/`).

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/ -v` passes
  with all 21 spec-§4 unit tests + the lazy-import test.
- [ ] No test depends on a live Redis or live Claude Code SDK.
- [ ] All async tests use `@pytest.mark.asyncio` (or rely on
  `asyncio_mode=auto` if the project uses it).
- [ ] `ruff check packages/ai-parrot/tests/flows/dev_loop/`.

---

## Test Specification

This task primarily refactors and consolidates — the test files
themselves come from earlier tasks. Verify by running:

```bash
pytest packages/ai-parrot/tests/flows/dev_loop/ -v --tb=short
```

and inspect the names match spec §4 line-for-line.

---

## Agent Instructions

1. Confirm TASKs 874-887 are all completed.
2. Read each `tests/flows/dev_loop/test_*.py` to inventory current
   coverage; cross-reference with spec §4.
3. Update index → `"in-progress"`.
4. Add `conftest.py` and the lazy-import test. Refactor existing test
   files to consume the shared fixtures (only where it reduces
   duplication; do NOT rewrite for style).
5. Run the full suite. Fix any test interactions.
6. Move to completed.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
