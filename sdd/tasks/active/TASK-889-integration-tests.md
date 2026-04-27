# TASK-889: Live integration tests (`@pytest.mark.live`)

**Feature**: FEAT-129 — Dev-Loop Orchestration with Claude Code Subagent Mirror
**Spec**: `sdd/specs/dev-loop-orchestration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-888
**Assigned-to**: unassigned

---

## Context

Implements the four integration tests in spec §4:

1. `test_end_to_end_happy_path` — full flow against a fixture worktree
   with a deliberately-broken Flowtask YAML; PR is opened.
2. `test_end_to_end_qa_failure_path` — same, but Dev fails to fix the
   bug; ticket lands in "Needs Human Review", no PR.
3. `test_concurrent_flows_respect_dispatcher_cap` — 4 flow runs with
   `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES=2`; assert ≤2 in flight at
   any time.
4. `test_websocket_replay_after_disconnect` — connect/disconnect/
   reconnect cycle with `replay=true` against a real Redis (or
   `fakeredis`).

These tests are gated behind `@pytest.mark.live` and skipped when
`ANTHROPIC_API_KEY` / the `claude` CLI / Redis are unavailable.

Spec acceptance criterion: "At least one of the live integration
tests passes against a real worktree on a developer machine."

---

## Scope

- Add `live` marker to `pyproject.toml` (or wherever pytest markers
  are declared) if not already present.
- Implement four integration tests in
  `packages/ai-parrot/tests/flows/dev_loop/integration/`:
  - `test_end_to_end_happy_path.py`
  - `test_end_to_end_qa_failure_path.py`
  - `test_concurrency.py`
  - `test_websocket_replay.py`
- Provide a `tests/flows/dev_loop/integration/fixtures/` directory
  containing a small "broken Flowtask YAML" used by the e2e tests.
- Tests skip gracefully when:
  - `ANTHROPIC_API_KEY` is not set, OR
  - `which claude` returns nothing, OR
  - Redis is unreachable.

**NOT in scope**:
- CI integration. The team runs these manually on a dev machine; CI
  runs unit tests only. Document this in `tests/flows/dev_loop/integration/README.md`.
- Any chaos/fault-injection tests (out of scope for v1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/integration/__init__.py` | CREATE | Namespace marker. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/conftest.py` | CREATE | `live` skip helper, fixture worktree builder. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_end_to_end_happy_path.py` | CREATE | E2E happy path. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_end_to_end_qa_failure_path.py` | CREATE | E2E failure path. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_concurrency.py` | CREATE | Cap enforcement. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/test_websocket_replay.py` | CREATE | Replay-after-disconnect. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/fixtures/broken_flowtask.yaml` | CREATE | Sample broken Flowtask used by e2e. |
| `packages/ai-parrot/tests/flows/dev_loop/integration/README.md` | CREATE | How to run + prerequisites. |
| `packages/ai-parrot/pyproject.toml` | MODIFY (if needed) | Add `live` marker registration. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
import os
import shutil
import asyncio
import pytest

from parrot.flows.dev_loop import (
    BugBrief, FlowtaskCriterion, LogSource, ShellCriterion,
)
from parrot.flows.dev_loop.flow import build_dev_loop_flow
from parrot.flows.dev_loop.dispatcher import ClaudeCodeDispatcher

# May import the orchestrator if the test exercises flow-level
# concurrency:
# from parrot.autonomous.orchestrator import AutonomousOrchestrator
```

### Existing Signatures to Use

```python
# Skip helper pattern
@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY")
    or shutil.which("claude") is None,
    reason="requires Claude Code CLI and ANTHROPIC_API_KEY",
)
async def test_end_to_end_happy_path():
    ...
```

### Does NOT Exist

- ~~`pytest.mark.live` without registration~~ — pytest emits a warning
  for unregistered markers. Add `live` to the marker list in
  `pyproject.toml`'s `[tool.pytest.ini_options]` (or wherever the
  project declares them).
- ~~A bundled Flowtask runtime~~ — the test fixture is YAML only; the
  test asserts the dev-loop produces a fix, NOT that flowtask itself
  runs. The QA subagent invokes a stub `flowtask` shim provided in
  `fixtures/`.

---

## Implementation Notes

### Concurrency test outline

```python
@pytest.mark.live
@pytest.mark.asyncio
async def test_concurrent_flows_respect_dispatcher_cap(monkeypatch):
    # Cap dispatcher at 2; spawn 4 concurrent dispatches; instrument
    # the dispatcher to publish dispatch.queued + dispatch.started
    # events; assert that at no time were more than 2 dispatches
    # between started/completed.
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES", "2")
    ...
    # Verify by reading the Redis stream timestamps post-hoc.
```

### Worktree fixture

Each E2E test creates its own ephemeral worktree under
`/tmp/dev-loop-it-<run_id>/.claude/worktrees/feat-test-<n>` and tears
it down on teardown. Override `WORKTREE_BASE_PATH` for the test session
via `monkeypatch.setenv("WORKTREE_BASE_PATH", str(tmp_path))`.

### Key Constraints

- Each test under 5 minutes wall-clock when running live (Claude calls
  are fast for trivial tasks).
- No test leaks worktrees, branches, or tickets. Use a sandbox Jira
  project for live tests; the project ID is supplied via
  `JIRA_TEST_PROJECT_KEY` env var.
- Tests MUST clean up Redis streams they create
  (`flow:test-*:flow`, `flow:test-*:dispatch:*`).

### References in Codebase

- Existing `@pytest.mark.live` tests (search the repo: `grep -r
  "@pytest.mark.live" tests/`).

---

## Acceptance Criteria

- [ ] All four integration test files exist and follow the skip
  pattern.
- [ ] When the live prerequisites ARE present:
  `pytest -m live packages/ai-parrot/tests/flows/dev_loop/integration/ -v`
  passes for at least `test_end_to_end_happy_path` (per spec §5).
- [ ] When the live prerequisites are NOT present:
  `pytest packages/ai-parrot/tests/flows/dev_loop/integration/ -v`
  reports them as **skipped**, never as **errored**.
- [ ] `live` marker is registered in `pyproject.toml`.
- [ ] `tests/flows/dev_loop/integration/README.md` documents how to
  run them (env vars, prerequisites).

---

## Test Specification

The four tests above. See spec §4 for the full descriptions.

---

## Agent Instructions

1. Confirm TASK-888 is completed.
2. Read existing `@pytest.mark.live` tests for the project's skip
   convention.
3. Update index → `"in-progress"`.
4. Implement the four tests + supporting fixtures + README.
5. Run them locally if `claude` CLI + Redis are available.
6. Move to completed.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**:
