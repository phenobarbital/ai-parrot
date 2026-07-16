---
type: Wiki Overview
title: 'TASK-013: Live integration tests (initial draft PR, revision, private clone)'
id: doc:sdd-tasks-completed-task-013-live-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the integration-test portion of Module 12 / §4. End-to-end coverage
relates_to:
- concept: mod:parrot.flows.dev_loop.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.runner
  rel: mentions
---

# TASK-013: Live integration tests (initial draft PR, revision, private clone)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-010, TASK-012
**Assigned-to**: unassigned

---

## Context

Implements the integration-test portion of Module 12 / §4. End-to-end coverage
gated behind `@pytest.mark.live`, skipped when the `claude` CLI / API key / `gh`
are unavailable.

---

## Scope

- `test_e2e_initial_run_draft_pr` (`@pytest.mark.live`): real SDK + a fixture
  repo with a broken file; run the declarative flow Intent→…→Development→
  QA(both gates)→**draft** PR. Assert the PR is a draft.
- `test_e2e_revision_updates_same_pr` (`@pytest.mark.live`): after an initial
  draft PR, simulate a reviewer change-request → `run_revision`; assert a new
  commit on the same branch + a comment on the same `pr_number`, and **no**
  second PR.
- `test_e2e_private_repo_clone` (`@pytest.mark.live`): clone a private fixture
  repo via token/`gh`.
- A fixture worktree/repo + a `conftest.py` skip guard.

**NOT in scope**: unit tests (they live with each implementation task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_e2e_feat250.py` | CREATE | Live integration tests |
| `packages/ai-parrot/tests/flows/dev_loop/conftest.py` | MODIFY | Fixtures + live skip guard |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.flow import build_dev_loop_flow        # flow.py:154 (wrapper, post TASK-010)
from parrot.flows.dev_loop.runner import DevLoopRunner            # runner.py:41
from parrot.flows.dev_loop.models import WorkBrief, RepoSpec, RevisionBrief  # models.py
```

### Existing Signatures to Use
```python
# Existing live-test marker pattern in the repo (mirror it):
#   @pytest.mark.live  + skip when ANTHROPIC_API_KEY / `claude` CLI absent
# See FEAT-129 integration tests referenced in dev-loop-orchestration.spec.md §4.
# DevLoopRunner.run(brief, run_id=None, ...) -> FlowResult       # runner.py:70
# DevLoopRunner.run_revision(brief, run_id=None) -> FlowResult   # runner.py (TASK-012)
```

### Does NOT Exist
- ~~a hosted CI environment with `claude`/`gh` guaranteed~~ — tests MUST skip
  gracefully when prerequisites are missing.

---

## Implementation Notes

### Key Constraints
- Skip (not fail) when `ANTHROPIC_API_KEY`/`claude`/`gh` are unavailable.
- Use a disposable fixture repo under a temp dir within `WORKTREE_BASE_PATH`.
- Assert draft-ness via the PR API/`gh pr view --json isDraft`.
- Keep these out of the default unit run (marker-gated).

### References in Codebase
- `sdd/specs/dev-loop-orchestration.spec.md` §4 — FEAT-129 live-test conventions.

---

## Acceptance Criteria

- [ ] `test_e2e_initial_run_draft_pr` passes on a machine with the live prereqs; skips cleanly otherwise.
- [ ] `test_e2e_revision_updates_same_pr` asserts same-branch commit + same-PR comment, no new PR.
- [ ] `test_e2e_private_repo_clone` clones a private fixture repo.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_e2e_feat250.py -m live -v` passes locally (or skips with reason).

---

## Test Specification
```python
import os, pytest, shutil

live = pytest.mark.skipif(
    not (os.getenv("ANTHROPIC_API_KEY") and shutil.which("claude")),
    reason="live prereqs unavailable")

@live
@pytest.mark.live
async def test_e2e_initial_run_draft_pr(fixture_repo):
    ...  # assert PR is draft
```

---

## Agent Instructions
Standard SDD lifecycle. Run last (depends on TASK-010 + TASK-012).

## Completion Note

**Status**: done — 2026-06-20

**What changed**
- `conftest.py`: added live skip guards (`skip_unless_claude_available`,
  `skip_unless_github_available`, `skip_unless_private_repo_configured`),
  `temp_worktree_base` (points `WORKTREE_BASE_PATH`/`DEV_LOOP_REPO_BASE_PATH` at
  a tmp dir), and `fixture_git_repo` (disposable local repo with a deliberately
  broken file).
- `test_e2e_feat250.py` (new): three `@pytest.mark.live` tests —
  `test_e2e_initial_run_draft_pr` (Intent→…→QA→draft PR),
  `test_e2e_revision_updates_same_pr` (revision updates the same PR, no new
  PR), `test_e2e_private_repo_clone` (real `GitToolkit.clone_repo` of a private
  repo; asserts the clone lands on disk + token never in the payload).

**Behavior**: all three SKIP cleanly (never error) when prereqs are missing,
each with a clear reason naming the env-vars to set. The private-clone test is
the most CI-friendly (only `GITHUB_TOKEN` + `DEV_LOOP_TEST_PRIVATE_REPO`); the
initial-run/revision tests carry the intended wiring and skip pending a Jira
sandbox / existing draft PR — mirroring the repo's existing FEAT-129 live-test
convention (`integration/conftest.py`, `pytestmark = pytest.mark.live`).

**Verification**
- `pytest test_e2e_feat250.py -m live -v` → 3 skipped (clean, with reasons).
- Full dev_loop suite unaffected: 208 passed, 10 deselected (live), only the 10
  pre-existing `test_research.py` env failures remain.
- `ruff check` clean on both files.
