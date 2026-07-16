---
type: Wiki Overview
title: 'TASK-003: ResearchNode — BASE_DIR fallback + clone-sourced worktree'
id: doc:sdd-tasks-completed-task-003-provision-local-fallback-and-clone-worktree-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 3** — the core wiring. Today `_provision_repos`
relates_to:
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-003: ResearchNode — BASE_DIR fallback + clone-sourced worktree

**Feature**: FEAT-253 — Complete FEAT-250 Repo Wiring
**Spec**: `sdd/specs/complete-feat-250-dev-loop-repo-wiring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-001, TASK-002
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** — the core wiring. Today `_provision_repos`
(`research.py:250`) returns `""` when no repos are declared, and provisioning runs
*after* the `sdd-research` dispatch — so a declared clone never sources the
worktree. This task makes the **base repository** explicit: `BASE_DIR` when none
is declared, the clone otherwise; and ensures the worktree is branched from that
base repository. `DevelopmentNode` is intentionally left untouched (it keeps
`cwd=worktree_path`).

---

## Scope

- `_provision_repos`: when `self._repos` is empty OR `self._git_toolkit is None`,
  return `str(BASE_DIR)` (NOT `""`). When repos are declared, clone/pull the
  primary `RepoSpec` into `<conf.DEV_LOOP_REPO_BASE_PATH>/<run_id>/<alias>`
  (already anchored at `BASE_DIR` by TASK-001) and return that clone path.
- `execute`: run `_provision_repos` **before** the `sdd-research` dispatch.
  - When the resolved base repo is a **clone** (i.e. repos declared), pass
    `cwd = repo_path` to the `sdd-research` dispatch so `/sdd-spec`, `/sdd-task`,
    and `git worktree add` operate on the clone.
  - When **local** (base repo == `BASE_DIR`), keep `cwd = conf.WORKTREE_BASE_PATH`
    (the existing behavior — branches the worktree from `BASE_DIR`).
  - Always set `ResearchOutput.repo_path` to the resolved base repository and
    leave `worktree_path` as the per-run worktree (do NOT set
    `worktree_path = repo_path`).
- Keep `_ensure_worktree_safe(...)` working with the new ordering.
- Add/extend unit tests.

**NOT in scope**: changing `DevelopmentNode` (must stay on `worktree_path`);
`server.py` wiring (TASK-004); the parser itself (TASK-002); live e2e (TASK-005).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | BASE_DIR fallback, provisioning-before-dispatch, clone-sourced cwd. |
| `packages/ai-parrot/tests/flows/dev_loop/test_research_repo_provisioning.py` | CREATE | Unit tests (fallback, ordering, cwd selection). |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from navconfig import BASE_DIR                                  # pathlib.PosixPath
from parrot import conf                                         # WORKTREE_BASE_PATH, DEV_LOOP_REPO_BASE_PATH
from parrot.flows.dev_loop.models import RepoSpec, ResearchOutput   # models.py:185,240
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(DevLoopNode):
    def __init__(self, *, dispatcher, jira_toolkit, log_toolkits=None,
                 summarizer_llm=None, plan_llm=None,
                 git_toolkit=None, repos=None, name="research"): ...   # :104
    #   self._repos = list(repos or [])   :122      self._git_toolkit = git_toolkit  :121

    async def execute(self, ctx, deps=None, **kwargs) -> ResearchOutput:   # :133
        # CURRENT order to change:
        #   excerpts/jira ...
        #   cwd = os.path.abspath(conf.WORKTREE_BASE_PATH)                  # :206
        #   research_out = await self._dispatcher.dispatch(..., cwd=cwd)    # :213-220
        #   await self._ensure_worktree_safe(research_out.branch_name)      # :232
        #   primary_repo_path = await self._provision_repos(run_id)         # :237
        #   if primary_repo_path: research_out = research_out.model_copy(update={"repo_path": ...})  # :238-241

    async def _provision_repos(self, run_id: str) -> str:                   # :250
        # CURRENT: `if not self._repos or self._git_toolkit is None: return ""`   :260-261
        # base = os.path.join(os.path.abspath(conf.DEV_LOOP_REPO_BASE_PATH), run_id or "run")  :263-266
        # dest = os.path.join(base, repo.alias)                              :270
        # result = await self._git_toolkit.clone_repo(repo.url, dest, branch=repo.branch, private=repo.private)  :275-280
        # returns primary_path (first RepoSpec)                             :282-284

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py
class ResearchOutput(BaseModel):                                  # :240
    worktree_path: str   # :279
    repo_path: str = ""  # :284

# GitToolkit (idempotent clone: pulls if dest already a clone)
async def clone_repo(self, repository, dest_dir, branch=None, *, private=False, depth=None) -> dict  # gittoolkit.py:1599
```

### Does NOT Exist
- ~~`_provision_repos` returning a path when no repos declared~~ — returns `""`
  today; this task makes it return `str(BASE_DIR)`.
- ~~A deterministic "create_worktree" call in research.py~~ — the worktree is
  created by the `sdd-research` subagent (driven by its `cwd`); do NOT invent a
  `git worktree add` python call here.
- ~~`DevelopmentNode` honoring `repo_path`~~ — out of scope; leave `development.py:88`
  on `worktree_path`.

---

## Implementation Notes

### Pattern to Follow
- Compute the base repo first:
  ```python
  repo_path = await self._provision_repos(shared.get("run_id", ""))  # "" -> str(BASE_DIR)
  is_clone = bool(self._repos and self._git_toolkit is not None)
  dispatch_cwd = repo_path if is_clone else os.path.abspath(conf.WORKTREE_BASE_PATH)
  ```
- Pass `cwd=dispatch_cwd` to the `sdd-research` dispatch; after it returns, set
  `research_out = research_out.model_copy(update={"repo_path": repo_path})`.
- Verify `_ensure_worktree_safe` still receives the branch name from the dispatch
  result and that the dispatched cwd remains under `conf.WORKTREE_BASE_PATH`
  (R3): the clone dir is already under it (TASK-001).

### Key Constraints
- Async throughout; `self.logger` for the chosen base repo + dispatch cwd.
- Never log tokens (GitToolkit scrubs; don't echo `repo.url` with creds).
- `repo_path` is `str(...)` (PosixPath → str).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:133-284`
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:301` (cwd guard)

---

## Acceptance Criteria

- [ ] No repos / no git toolkit → `_provision_repos` returns `str(BASE_DIR)`.
- [ ] Declared repo → clone path under `BASE_DIR/.claude/worktrees/repos/<run_id>/<alias>`, returned as `repo_path`.
- [ ] `ResearchOutput.repo_path` is set and not equal to `worktree_path`.
- [ ] `sdd-research` dispatch `cwd == repo_path` when a repo is declared; `== conf.WORKTREE_BASE_PATH` when local.
- [ ] Provisioning is invoked before the `sdd-research` dispatch.
- [ ] `DevelopmentNode` dispatch still uses `cwd == research.worktree_path` (regression test).
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_research_repo_provisioning.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_research_repo_provisioning.py
# Use AsyncMock for dispatcher + git_toolkit; assert call ordering and cwd kwargs.
# - test_provision_repos_local_fallback_returns_base_dir
# - test_provision_repos_clone_path_anchored
# - test_research_sets_repo_path_distinct_from_worktree
# - test_research_dispatch_cwd_is_clone_when_declared
# - test_research_dispatch_cwd_is_worktree_base_when_local
# - test_provision_runs_before_dispatch        (assert call order via a manager mock)
# - test_development_cwd_still_worktree_path    (DevelopmentNode regression)
```

---

## Agent Instructions

1. Read the spec (§2 Overview, §3 Module 3, §7 R2/R3).
2. Confirm TASK-001 + TASK-002 are in `sdd/tasks/completed/`.
3. Verify the Codebase Contract — re-read `research.py:133-284` (line numbers may shift).
4. Update index → `in-progress`.
5. Implement, run tests + ruff.
6. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
