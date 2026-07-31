---
type: Wiki Overview
title: 'TASK-006: Repo provisioning step (clone/pull configured repos before Development)'
id: doc:sdd-tasks-completed-task-006-repo-provisioning-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements Module 4 (G3). Before Development runs, the flow must clone/pull
  the
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.research
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-006: Repo provisioning step (clone/pull configured repos before Development)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-002, TASK-003
**Assigned-to**: unassigned

---

## Context

Implements Module 4 (G3). Before Development runs, the flow must clone/pull the
configured `RepoSpec` list and expose the primary clone path as
`ResearchOutput.repo_path`, so DevelopmentNode runs with `cwd=<clone>`. Clones
live under `WORKTREE_BASE_PATH` so the dispatcher's cwd-safety guard passes.

---

## Scope

- Add a provisioning step that, given a `git_toolkit: GitToolkit` and a list of
  `RepoSpec`, clones/pulls each into
  `<DEV_LOOP_REPO_BASE_PATH>/<run_id>/<alias>` and returns the primary clone
  path. Implement it as a method on `ResearchNode` (preferred) or a small
  `nodes/repo_provision.py` helper invoked by `ResearchNode.execute`.
- Wire `ResearchNode.__init__` to accept a `git_toolkit` and a `repos:
  list[RepoSpec]` (default `[]`); when `repos` is empty, behaviour is unchanged
  (no clone — preserves today's subagent-creates-worktree path).
- Set `ResearchOutput.repo_path` to the primary clone; keep `worktree_path`
  working.
- Unit tests with `GitToolkit.clone_repo` mocked.

**NOT in scope**: GitToolkit clone/pull internals (TASK-002); declarative
wiring of the node (TASK-010).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | MODIFY | Accept `git_toolkit`/`repos`; clone before dispatch; set `repo_path` |
| `packages/ai-parrot/tests/flows/dev_loop/test_research_repo_provision.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.nodes.research import ResearchNode      # research.py:102
from parrot.flows.dev_loop.models import RepoSpec, ResearchOutput  # models.py (RepoSpec from TASK-003)
from parrot_tools.gittoolkit import GitToolkit                     # gittoolkit.py:968
from parrot.conf import WORKTREE_BASE_PATH                          # conf.py:846
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
class ResearchNode(DevLoopNode):
    def __init__(self, dispatcher, jira_toolkit, log_toolkits=None,
                 summarizer_llm=None, plan_llm=None, name="research")   # :102  ← add git_toolkit, repos
    async def execute(self, ctx, deps, **kwargs) -> ResearchOutput      # :125
    # writes shared["research_output"], shared["log_excerpts"], shared["jira_issue_key"]
    async def _ensure_worktree_safe(self, ...)                          # :673 (worktree-safety pattern to reuse)

# from TASK-002
async def GitToolkit.clone_repo(self, repository, dest_dir, branch=None, *, private=False, depth=None) -> Dict
async def GitToolkit.pull_repo(self, repo_path, branch=None) -> Dict
```

### Does NOT Exist
- ~~`ResearchNode` git_toolkit/repos params today~~ — added here.
- ~~`ResearchOutput.repo_path` before TASK-003~~ — depends on TASK-003.
- cloning OUTSIDE `WORKTREE_BASE_PATH` — would break `ClaudeCodeDispatcher._enforce_cwd_under_worktree_base`.

---

## Implementation Notes

### Key Constraints
- Empty `repos` ⇒ no clone, no behavioural change (back-compat).
- Clone dest must be under `WORKTREE_BASE_PATH` (use `DEV_LOOP_REPO_BASE_PATH`).
- Primary repo = first `RepoSpec` (v1 single-primary; see spec §8 open question).
- Async; `self.logger` around clone start/finish (never log tokens).

### References in Codebase
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py:673` — `_ensure_worktree_safe` worktree handling.
- `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py:81` — Development uses `cwd=research.worktree_path` (will use `repo_path` when set).

---

## Acceptance Criteria

- [ ] Each configured `RepoSpec` triggers a `git_toolkit.clone_repo(...)`.
- [ ] Clones land under `WORKTREE_BASE_PATH`; `ResearchOutput.repo_path` set to the primary clone.
- [ ] Empty `repos` ⇒ no clone call; `ResearchOutput` unchanged from today.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_research_repo_provision.py -v` passes.
- [ ] `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` clean.

---

## Test Specification
```python
async def test_research_clones_configured_repos(mock_dispatcher, mock_jira):
    git = AsyncMock(); git.clone_repo.return_value = {"path": "/abs/.claude/worktrees/repos/run-x/nav"}
    node = ResearchNode(dispatcher=mock_dispatcher, jira_toolkit=mock_jira,
                        git_toolkit=git, repos=[RepoSpec(alias="nav", url="org/nav")])
    # ... execute with a ctx whose shared has a WorkBrief + run_id
    git.clone_repo.assert_called_once()
```

---

## Agent Instructions
Standard SDD lifecycle. Confirm `research.py` line numbers before editing.

## Completion Note

**Status**: done — 2026-06-20

**What changed** (`nodes/research.py`)
- `ResearchNode.__init__` gained keyword-only `git_toolkit=None` and
  `repos: Optional[List[RepoSpec]]=None` (stored via `object.__setattr__`).
- Added `_provision_repos(run_id)`: clones each `RepoSpec` into
  `<DEV_LOOP_REPO_BASE_PATH>/<run_id>/<alias>` (under `WORKTREE_BASE_PATH`,
  R4) via `git_toolkit.clone_repo(url, dest, branch=…, private=…)`; returns the
  **first** repo's path (v1 single-primary). No-op (returns `""`) when no repos
  configured.
- `execute` calls it after the worktree-safety check and, when a primary path
  is returned, `research_out = research_out.model_copy(update={"repo_path": …})`.
  Empty repos ⇒ `repo_path` stays `""` and behaviour is unchanged.

**Scope note**: development.py's `cwd` (currently `research.worktree_path`) is
**not** modified here — it's not in this task's file list. Wiring Development to
prefer `repo_path` belongs to the integration task **TASK-010**.

**Verification**
- `pytest test_research_repo_provision.py` → 5 passed (clones each, empty no-op,
  private/branch forwarded, execute sets `repo_path`, empty leaves it "").
- **Pre-existing failures unrelated to this task**: `test_research.py` shows 10
  failures BOTH with and without my change (verified via `git stash` of
  research.py — identical 10 failed/1 passed). Root cause: the test env has
  `JIRA_PROJECT` configured, so `_find_existing_issue` reaches
  `jira_search_issues`, whose fixtures return `{"issues": []}` instead of the
  `{"status": ...}` shape the code expects. My change does not touch that path.
- `ruff check` clean on both files.
