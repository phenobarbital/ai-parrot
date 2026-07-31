---
type: Wiki Overview
title: 'TASK-1700: Integration Tests'
id: doc:sdd-tasks-completed-task-1700-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: from parrot.flows.dev_loop.code_review import (
relates_to:
- concept: mod:parrot.flows.dev_loop.code_review
  rel: mentions
- concept: mod:parrot.flows.dev_loop.factories
  rel: mentions
- concept: mod:parrot.flows.dev_loop.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.qa
  rel: mentions
---

# TASK-1700: Integration Tests

**Feature**: FEAT-270 — Multi-Dispatcher Code Review Gate
**Spec**: `sdd/specs/new-codereviewers.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1697, TASK-1698
**Assigned-to**: unassigned

---

## Context

> This task implements Module 9 from the spec — integration tests that verify
> the full QA flow (deterministic QA → code review + fix → re-run) works
> end-to-end with each reviewer type, and that the server wiring correctly
> selects the reviewer based on the config var.

---

## Scope

- Write integration tests in `test_code_review.py`:
  - `test_full_qa_flow_claude_review`: End-to-end with Claude reviewer mock
  - `test_full_qa_flow_codex_review`: End-to-end with Codex reviewer mock
  - `test_full_qa_flow_gemini_review`: End-to-end with Gemini reviewer mock
  - `test_server_wiring_default`: Default config creates Claude reviewer
  - `test_server_wiring_codex`: `DEV_LOOP_CODEREVIEW_AGENT=codex` creates Codex reviewer
  - `test_server_wiring_gemini`: `DEV_LOOP_CODEREVIEW_AGENT=gemini` creates Gemini reviewer
  - `test_server_wiring_invalid`: Invalid agent name raises `RuntimeError`
- Verify existing `test_qa_codereview.py` tests still pass (backward compat)
- Run full test suite for `dev_loop/` and verify no regressions

**NOT in scope**: Implementation code (all previous tasks).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_code_review.py` | MODIFY | Add integration tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.code_review import (
    AbstractCodeReviewDispatcher,
    CodeReviewDispatcherFactory,
    ClaudeCodeReviewDispatcher,
    CodexCodeReviewDispatcher,
    GeminiCodeReviewDispatcher,
)
from parrot.flows.dev_loop.models import (
    CodeReviewVerdict,
    CodeReviewFinding,
    QAReport,
    BugBrief,
    ResearchOutput,
    AcceptanceCriterion,
)
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.factories import build_dev_loop_node_factories
from parrot.flows.dev_loop.flow import build_dev_loop_flow
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py
# Read this file for existing test patterns and fixtures
```

### Does NOT Exist
N/A — all components should exist by the time this task runs.

---

## Implementation Notes

### Key Constraints
- Integration tests use mocked dispatchers (no real CLI invocations)
- Tests must verify the full flow: deterministic QA → review → fix → rerun
- Use `AsyncMock` for all dispatcher `dispatch()` / `review()` calls
- Verify that `CodeReviewVerdict` with `files_modified` triggers the re-run
- Verify backward compatibility: `QANode(dispatcher=mock)` without
  `codereview_dispatcher` works (auto-wraps in Claude reviewer)

### References in Codebase
- `packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py` — existing test patterns
- `packages/ai-parrot/tests/flows/dev_loop/` — other test files for fixtures

---

## Acceptance Criteria

- [ ] All integration tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_code_review.py -v`
- [ ] All existing tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_qa_codereview.py -v`
- [ ] No regressions: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] Tests cover all three reviewer types (Claude, Codex, Gemini)
- [ ] Tests cover the re-run path and the skip-rerun path
- [ ] Tests cover server wiring with different `DEV_LOOP_CODEREVIEW_AGENT` values

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from parrot.flows.dev_loop.models import CodeReviewVerdict, CodeReviewFinding, QAReport


class TestFullQAFlowIntegration:
    @pytest.mark.asyncio
    async def test_claude_review_fix_rerun(self):
        """Full QA → Claude review → fix → rerun cycle."""
        # Setup: QANode with ClaudeCodeReviewDispatcher
        # Mock: deterministic QA passes, reviewer finds+fixes an issue,
        #       re-run passes
        # Assert: overall QA passes, files_modified populated

    @pytest.mark.asyncio
    async def test_codex_review_fix_rerun(self):
        """Full QA → Codex review → fix → rerun cycle."""

    @pytest.mark.asyncio
    async def test_gemini_review_pass_no_fix(self):
        """Full QA → Gemini review passes → no rerun needed."""


class TestServerWiringIntegration:
    def test_default_creates_claude_reviewer(self):
        """No DEV_LOOP_CODEREVIEW_AGENT defaults to Claude reviewer."""

    def test_codex_agent_creates_codex_reviewer(self):
        """DEV_LOOP_CODEREVIEW_AGENT=codex creates Codex reviewer."""

    def test_invalid_agent_raises(self):
        """Invalid DEV_LOOP_CODEREVIEW_AGENT raises RuntimeError."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1697, TASK-1698 are in `sdd/tasks/completed/`
3. **Read existing tests** in `test_qa_codereview.py` for patterns and fixtures
4. **Update status** in `sdd/tasks/index/new-codereviewers.json` → `"in-progress"`
5. **Implement** following the scope above
6. **Run** the full dev_loop test suite to verify no regressions
7. **Move this file** to `sdd/tasks/completed/TASK-1700-integration-tests.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-03
**Notes**: Added to `test_code_review.py`: `TestFullQAFlowIntegration`
(`test_claude_review_fix_rerun`, `test_codex_review_fix_rerun`,
`test_gemini_review_pass_no_fix` — each drives `QANode.execute()` end-to-end
through a real concrete review dispatcher wrapping a mocked underlying
dispatcher, covering the rerun and skip-rerun paths) and
`TestServerWiringIntegration` (`test_server_wiring_default`,
`test_server_wiring_codex`, `test_server_wiring_gemini`,
`test_server_wiring_invalid` — load `examples/dev_loop/server.py` via
`importlib` like `test_server_repo_wiring.py` does, monkeypatch
`conf.config` with a small fake exposing `DEV_LOOP_CODEREVIEW_AGENT`, run
`_on_startup`, and assert the `codereview_dispatcher` kwarg captured from
the (monkeypatched) `build_dev_loop_flow` call is the right concrete
reviewer type, or that an invalid agent name raises `RuntimeError`).
`TestServerWiring` (factory-level `create()` smoke tests) was already added
in TASK-1698 — left as-is since it satisfies this task's Test Specification
too.

Full `dev_loop/` suite (excluding `-m live`): 341 passed, 4 failed. The 4
failures (`test_server_repo_wiring.py::test_server_builds_flow_with_repos`,
`test_webhook.py::TestSweepFinishedWorktrees::{test_removes_only_merged_and_closed,
test_remove_orphans_also_clears_no_pr, test_per_branch_error_is_isolated}`)
reproduce identically with `git stash` applied against the pre-FEAT-270
`qa.py`/`code_review.py` (verified during TASK-1697) and pass individually
in isolation — confirmed pre-existing test-order/pollution flakiness,
unrelated to this feature. `test_qa_codereview.py` (16 tests) and
`test_code_review.py` (38 tests) both fully green. `ruff check` clean across
every file this feature touched.

**Deviations from spec**: none — all integration tests added to
`test_code_review.py` per the task's file list.
