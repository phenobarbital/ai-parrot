---
type: Wiki Overview
title: 'TASK-005: Live integration tests — clone→worktree & local→worktree'
id: doc:sdd-tasks-completed-task-005-live-integration-tests-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the **Integration Tests** of the spec §4. The unit tests in
relates_to:
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-005: Live integration tests — clone→worktree & local→worktree

**Feature**: FEAT-253 — Complete FEAT-250 Repo Wiring
**Spec**: `sdd/specs/complete-feat-250-dev-loop-repo-wiring.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-003, TASK-004
**Assigned-to**: unassigned

---

## Context

Implements the **Integration Tests** of the spec §4. The unit tests in
TASK-001..004 use mocks; this task proves the real path-resolution + git behavior
end-to-end with an actual `git` clone/worktree, guarded by `@pytest.mark.live` so
CI without network/git is unaffected.

---

## Scope

- Add `@pytest.mark.live` integration tests:
  - **clone→worktree-from-clone**: with a declared public fixture repo, a run
    clones into `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>` and the
    resulting `worktree_path` is a git worktree branched from the **clone**.
  - **local→worktree-from-BASE_DIR**: with no repo declared, a run produces a
    worktree branched from `BASE_DIR` and `repo_path == str(BASE_DIR)`.
- Skip cleanly when `git` is unavailable / no network.
- Prefer a tiny public fixture repo (or a locally-created bare repo) to avoid
  depending on a private remote in CI.

**NOT in scope**: implementation changes (TASK-001..004); the full SDK-driven
dev-loop e2e (covered by FEAT-250's existing live suite).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_repo_wiring_live.py` | CREATE | `@pytest.mark.live` integration tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import BASE_DIR
from parrot import conf
from parrot.flows.dev_loop.models import RepoSpec
from parrot_tools.gittoolkit import GitToolkit          # gittoolkit.py:968
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py
async def clone_repo(self, repository, dest_dir, branch=None, *, private=False, depth=None) -> dict  # :1599
async def pull_repo(self, repo_path, branch=None) -> dict                                            # :1662
# ResearchNode._provision_repos(run_id) -> str   (TASK-003: returns clone path or str(BASE_DIR))
```

### Does NOT Exist
- ~~A shared `live` pytest fixture for repos~~ — check `packages/ai-parrot/tests/`
  for an existing `live` marker registration in `pyproject.toml`/`conftest.py`
  before adding one; reuse FEAT-250's marker if present.

---

## Implementation Notes

### Pattern to Follow
- Gate with `pytestmark = pytest.mark.live` and a `shutil.which("git")` skip.
- For the clone test you may create a local bare repo with `git init --bare` +
  an initial commit and clone *that* (no network) to keep CI hermetic; document
  the choice in the test.
- Assert worktree provenance with `git -C <worktree> rev-parse --git-common-dir`
  (points back to the clone's `.git`, not the outer BASE_DIR repo).

### Key Constraints
- Tests must clean up created worktrees/clones (`git worktree remove`, rmtree).
- Never hardcode an absolute machine path other than via `BASE_DIR`/tmp.

---

## Acceptance Criteria

- [ ] `test_e2e_clone_then_worktree_from_clone` passes locally with `git` present.
- [ ] `test_e2e_local_run_worktree_from_base_dir` passes; asserts `repo_path == str(BASE_DIR)`.
- [ ] Both skip cleanly when `git` is unavailable.
- [ ] Tests leave no stray worktrees/clones behind.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_repo_wiring_live.py -v -m live` passes.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_repo_wiring_live.py
import shutil
import pytest

pytestmark = pytest.mark.live

skip_no_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

# test_e2e_clone_then_worktree_from_clone:
#   - create a local bare repo + seed commit; clone via GitToolkit.clone_repo
#   - assert clone path under BASE_DIR/.claude/worktrees/repos/...
#   - create a worktree from the clone; assert git-common-dir resolves to the clone

# test_e2e_local_run_worktree_from_base_dir:
#   - no repos: assert _provision_repos(...) == str(BASE_DIR)
#   - worktree created under BASE_DIR/.claude/worktrees branches from BASE_DIR
```

---

## Agent Instructions

1. Read the spec §4 Integration Tests.
2. Confirm TASK-003 + TASK-004 are in `sdd/tasks/completed/`.
3. Check for an existing `live` marker before registering one.
4. Update index → `in-progress`.
5. Implement, run the live tests locally.
6. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
