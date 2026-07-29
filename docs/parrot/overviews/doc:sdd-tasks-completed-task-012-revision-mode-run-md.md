---
type: Wiki Overview
title: 'TASK-012: Revision-mode run (`run_revision` + `RevisionHandoffNode` + trigger)'
id: doc:sdd-tasks-completed-task-012-revision-mode-run-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements the run half of Module 9 (G6). A reviewer comment/review on a
  draft
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: mentions
- concept: mod:parrot.flows.dev_loop.runner
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

# TASK-012: Revision-mode run (`run_revision` + `RevisionHandoffNode` + trigger)

**Feature**: FEAT-250 — Dev-Loop Refactor
**Spec**: `sdd/specs/dev-loop-refactor.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-002, TASK-003, TASK-009, TASK-010, TASK-011
**Assigned-to**: unassigned

---

## Context

Implements the run half of Module 9 (G6). A reviewer comment/review on a draft
PR triggers a **new** dev-loop run in **revision mode** that enters at
Development (reusing the existing clone + branch), re-runs QA, then pushes to the
**existing** branch and comments on the **same** PR — no new PR. AgentsFlow is
acyclic, so this is a separate run, not a cycle.

---

## Scope

- `RevisionHandoffNode(DevLoopNode)` (`nodes/revision_handoff.py`): `git push`
  to the existing branch (subprocess, like `_push_branch`) and
  `git_toolkit.add_pr_comment(pr_number, body=...)` on the existing PR. **Never**
  calls `create_pull_request`. Sets `shared["mode"]="revision"` for the close node.
- Revision `FlowDefinition` (extend `build_dev_loop_definition(revision=True)`
  from TASK-010): start → development → qa → (pass) revision_handoff → close;
  (fail) → failure. cwd = existing clone (`RevisionBrief.repo_path`).
- `DevLoopRunner.run_revision(self, brief: RevisionBrief, *, run_id=None) ->
  FlowResult`: builds the revision flow, seeds shared state
  (`mode="revision"`, `repo_path`, `branch`, `pr_number`, `repository`,
  `jira_issue_key`, `feedback`, `head_sha`), runs it.
- `dev_loop/webhook.py`: register a handler for `github.pr_comment` /
  `github.pr_review` that:
  - filters by `DEV_LOOP_REVISION_TRIGGER` (default `changes_requested`: human,
    non-bot, change-requesting; also `any_comment` / `command` `/revise`),
  - drops bot-authored comments (the flow-bot account),
  - dedups by `head_sha` (mirror `GitHubReviewer`),
  - builds a `RevisionBrief` and calls `DevLoopRunner.run_revision(...)`.
- Unit tests (subprocess + toolkit + runner mocked).

**NOT in scope**: webhook event classification (TASK-011); the initial graph /
factories (TASK-010).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/revision_handoff.py` | CREATE | `RevisionHandoffNode` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` | MODIFY | `revision=True` graph |
| `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` | MODIFY | factory for `dev_loop.revision_handoff` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `run_revision(...)` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/webhook.py` | MODIFY | revision trigger handler |
| `packages/ai-parrot/tests/flows/dev_loop/test_revision_mode.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.runner import DevLoopRunner            # runner.py:41
from parrot.flows.dev_loop.models import RevisionBrief            # models.py (TASK-003)
from parrot.flows.dev_loop.nodes.base import DevLoopNode          # nodes/base.py:29
from parrot_tools.gittoolkit import GitToolkit                    # gittoolkit.py:968
from parrot.conf import DEV_LOOP_REVISION_TRIGGER, FLOW_BOT_JIRA_ACCOUNT_ID  # conf.py (TASK-004, :842)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
class DevLoopRunner:
    def __init__(self, flow: AgentsFlow, max_concurrent_runs=None)   # :41
    async def run(self, brief, run_id=None, initial_task="", extra_shared=None) -> FlowResult  # :70
    # builds FlowContext(initial_task=..., shared_data={...}); binds flow._run_id_holder

# packages/ai-parrot/src/parrot/flows/dev_loop/webhook.py
def register_pull_request_webhook(orchestrator, *, secret, path="/github/dev-loop",
                                  target_id="dev-loop-cleanup") -> None   # :113
async def cleanup_worktree(branch: str) -> None                          # :68 (subprocess pattern to mirror)

# GitToolkit (existing)
async def add_pr_comment(self, pr_number, body, repository=None) -> Dict[str, Any]   # gittoolkit.py:1630

# DeploymentHandoff push pattern to mirror:
# deployment_handoff.py:182  async def _push_branch(self, branch, cwd) -> None  (git push -u origin <branch>)
```

### Does NOT Exist
- ~~loop-back edges / cyclic flow~~ — revision is a SEPARATE run (acyclic engine).
- ~~`DevLoopRunner.run_revision`~~ — created here.
- ~~`RevisionHandoffNode`~~ — created here; it must NOT call `create_pull_request`.
- ~~a revision graph in `build_dev_loop_definition`~~ — the `revision=True`
  branch is authored here (the param exists from TASK-010).

---

## Implementation Notes

### Key Constraints
- Revision run skips Intent/BugIntake/Research/clone — it reuses
  `RevisionBrief.repo_path` and `branch` (already on disk from the initial run).
- `RevisionHandoffNode` updates the SAME PR (`add_pr_comment(pr_number, ...)`),
  never opens a new one.
- Dedup by `head_sha` + bot-author filter to avoid revision storms (R3); respect
  `FLOW_MAX_CONCURRENT_RUNS`.
- Trigger filter driven by `DEV_LOOP_REVISION_TRIGGER` (default `changes_requested`).

### References in Codebase
- `runner.py:70-126` — `run(...)` shared-state + run_id binding to mirror.
- `webhook.py:45-135` — webhook registration/transform pattern.
- `bots/github_reviewer.py` — head-sha dedup the trigger reuses.

---

## Acceptance Criteria

- [ ] `run_revision(RevisionBrief)` runs the revision graph: enters at Development (cwd=`repo_path`), → QA → RevisionHandoff → Close.
- [ ] `RevisionHandoffNode` pushes to the existing branch + `add_pr_comment` on the same `pr_number`; `create_pull_request` is NOT called.
- [ ] Bot-authored comments do not trigger a run; duplicate `head_sha` triggers once.
- [ ] `DEV_LOOP_REVISION_TRIGGER="changes_requested"` only fires on change requests.
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop/test_revision_mode.py -v` passes.

---

## Test Specification
```python
async def test_run_revision_enters_at_development(monkeypatch, sample_revision_brief):
    """The revision flow has no intent/research; first executed node is development."""

async def test_revision_handoff_no_new_pr(mock_git):
    node = RevisionHandoffNode(git_toolkit=mock_git)
    await node.execute(ctx_revision, deps)
    mock_git.add_pr_comment.assert_called_once()
    mock_git.create_pull_request.assert_not_called()

def test_revision_trigger_filters_bot_comments():
    """A comment from FLOW_BOT account does not enqueue run_revision."""
```

---

## Agent Instructions
Standard SDD lifecycle. Verify TASK-010/011/009 are completed first.

## Completion Note

**Status**: done — 2026-06-20

**What changed**
- `nodes/revision_handoff.py` (new): `RevisionHandoffNode(git_toolkit,
  name="revision_handoff")` — `git push` to the **existing** branch
  (subprocess, mirroring `_push_branch`) + `git_toolkit.add_pr_comment(pr_number,
  …)` on the **same** PR. Never calls `create_pull_request`. Sets
  `shared["mode"]="revision"`. Registered via `@register_dev_loop_node`.
- `definition.py`: `build_dev_loop_definition(revision=True)` now returns the
  revision graph (`development → qa → (pass) revision_handoff → close` /
  `(fail) failure_handler`; on_error fan-in to failure).
- `factories.py`: added `dev_loop.revision_handoff` factory.
- `runner.py`: added `build_dev_loop_revision_flow(...)` (declarative-materialize
  + explicit-edge execution, like the initial flow), extended
  `DevLoopRunner.__init__` with optional `dispatcher`/`jira_toolkit`/
  `git_toolkit`/`redis_url`, and `run_revision(brief, *, run_id=None)` which
  seeds the shared state (synthetic `ResearchOutput` + `WorkBrief` reusing the
  existing clone/branch) and runs the revision flow.
- `webhook.py`: `RevisionWebhookHandler` — filters by
  `DEV_LOOP_REVISION_TRIGGER`, drops bot-authored comments, dedups by
  `head_sha`, builds a `RevisionBrief`, and calls `run_revision`.

**v1 simplifications (documented):**
- `RevisionBrief` carries no acceptance criteria, so the revision QA re-runs a
  default `ruff check .` lint gate; the reviewer feedback is surfaced in shared
  state + the context `initial_task` (wiring it into the Development dispatch
  prompt would need a DevelopmentNode change, out of this task's scope).
- The webhook derives `repo_path = <WORKTREE_BASE_PATH>/<branch>` (the initial
  run's worktree convention) and reads `jira_issue_key` from the payload when
  present (close handles an empty key gracefully). `issue_comment` payloads lack
  a branch/head_sha, so only `pr_review` events build a brief by default.

**Corollary test updates (necessary):** `test_declarative_flow.py` —
`_DEV_LOOP_TYPES` gained `dev_loop.revision_handoff`;
`test_definition_revision_not_yet_implemented` → `test_definition_revision_graph`
(the revision graph is now implemented).

**Test-isolation fix:** `test_lazy_import` purges `parrot.flows.dev_loop` from
`sys.modules` and re-imports it, creating duplicate class identities. The
end-to-end `run_revision` test was made immune by driving the real node executes
with mocked **dependencies** (dispatcher/git/jira) + a patched global
`asyncio.create_subprocess_exec`, and comparing `output_model` by `__name__`
(not identity).

**Verification**
- `pytest test_revision_mode.py` → 9 passed (no-new-PR, push-fail blocks,
  revision flow shape, enters-at-development e2e, requires-deps, bot filter,
  changes_requested filter, head_sha dedup, /revise command trigger).
- Robust under re-import: `test_lazy_import + test_revision_mode` → 11 passed.
- Full dev_loop suite: 208 passed, only the 10 pre-existing `test_research.py`
  env failures remain.
- `ruff check` clean on all 7 touched files.
