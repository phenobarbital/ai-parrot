---
type: Wiki Overview
title: 'Feature Specification: Dev-Loop Refactor — Declarative Flow, Repo Provisioning,
  Code-Review QA & PR Revision Loop'
id: doc:sdd-specs-dev-loop-refactor-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'The dev-loop (FEAT-129/132) automates "small operational fixes": classify
  a'
relates_to:
- concept: mod:parrot.bots
  rel: mentions
- concept: mod:parrot.bots.flows
  rel: mentions
- concept: mod:parrot.bots.flows.core.context
  rel: mentions
- concept: mod:parrot.bots.flows.core.node
  rel: mentions
- concept: mod:parrot.bots.flows.core.types
  rel: mentions
- concept: mod:parrot.bots.flows.flow.definition
  rel: mentions
- concept: mod:parrot.bots.flows.flow.flow
  rel: mentions
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.core.hooks.github_webhook
  rel: mentions
- concept: mod:parrot.flows.dev_loop._subagent_defs
  rel: mentions
- concept: mod:parrot.flows.dev_loop.dispatcher
  rel: mentions
- concept: mod:parrot.flows.dev_loop.flow
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
- concept: mod:parrot.flows.dev_loop.nodes.base
  rel: mentions
- concept: mod:parrot.flows.dev_loop.runner
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot_tools.gittoolkit
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: Dev-Loop Refactor — Declarative Flow, Repo Provisioning, Code-Review QA & PR Revision Loop

**Feature ID**: FEAT-250
**Date**: 2026-06-20
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.7.x (`ai-parrot`)

> **Lineage**: This builds on FEAT-129 (`dev-loop-orchestration.spec.md`) and
> FEAT-132 (`feat-129-upgrades.spec.md`). The dev-loop already runs on the
> **new** `AgentsFlow` engine (`parrot.bots.flows`, explicit `add_edge` +
> predicate routing + OR-join). This spec therefore is **not** an
> engine migration — it is a topology re-expression (programmatic →
> declarative `FlowDefinition`) plus four net-new capabilities.

---

## 1. Motivation & Business Requirements

### Problem Statement

The dev-loop (FEAT-129/132) automates "small operational fixes": classify a
Jira ticket, research it, dispatch a Claude Code subagent to write the fix,
verify acceptance criteria, push a branch and open a PR. Four gaps block it
from operating end-to-end against real, private, multi-repo codebases and from
closing the human-in-the-loop review cycle:

1. **No repository provisioning by the flow.** Today the worktree is created
   *inside* the `sdd-research` Claude Code dispatch. There is no first-class,
   deterministic way to declare *which* git repositories a run operates on, to
   clone/pull them up front, or to authenticate to **private** repos. The flow
   cannot be pointed at an arbitrary external codebase.
2. **QA is purely mechanical.** `QANode` runs acceptance criteria
   (`flowtask`/`shell` exit codes) + lint. There is no qualitative
   **code-review** gate that judges whether the change actually *resolves the
   reported issue* and meets the project's standards — the kind of review a
   human reviewer performs using `.claude/agents/code-reviewer.md`.
3. **PRs are opened directly, not as drafts**, and once opened the flow is
   "done". There is no mechanism to **listen** to reviewer comments on the PR
   and act on requested changes.
4. **No revision loop.** When a human comments on the PR asking for changes,
   re-running `Development → QA` is a fully manual re-trigger that produces a
   *new* PR. There is no automated "apply the feedback on the existing branch,
   re-verify, and update the same PR" cycle.

The topology is also pinned in imperative Python (`build_dev_loop_flow()`),
which makes it hard to serialize, version, or visualize the flow graph.

### Goals

- **G1 — Declarative topology.** Express the dev-loop graph as a
  `FlowDefinition` and run it via `AgentsFlow.from_definition(...)`, replacing
  the imperative `build_dev_loop_flow()` factory while preserving identical
  routing behaviour (bug/non-bug branch, QA pass/fail branch, on-error fan-in).
- **G2 — Node dependency injection for declarative flows.** Add a minimal
  `node_factories` hook to `AgentsFlow.from_definition` / `run_flow` so custom
  node types (which need a live `dispatcher`, `JiraToolkit`, `GitToolkit`,
  etc.) can be materialized declaratively. This is the enabling infra change
  for G1.
- **G3 — Repo provisioning.** Extend `GitToolkit` with `clone_repo` /
  `pull_repo`, supporting **private** repos via the toolkit's existing PAT /
  GitHub-App auth and via the `gh` CLI when present. The flow is configured
  with a list of repositories to clone/pull before `Development` runs.
- **G4 — Code-review QA gate.** Add a `sdd-codereview` subagent (templated on
  `.claude/agents/code-reviewer.md`). `QANode` dispatches it as an *additional*
  gate: a run passes QA only when the deterministic criteria/lint **and** the
  code-review both pass.
- **G5 — Draft PR.** `DeploymentHandoffNode` opens the PR in **DRAFT** mode.
- **G6 — PR revision loop.** A GitHub PR-comment / PR-review webhook starts a
  **new dev-loop run in "revision" mode** that enters directly at
  `Development` (skipping Intent/BugIntake/Research and repo re-clone, reusing
  the existing clone + branch), re-runs QA, then pushes to the **existing**
  branch and posts a comment on the **same** draft PR — it does **not** open a
  new PR.
- **G7 — Explicit close node.** Add a terminal `DevLoopCloseNode` that records
  the run's final state (Jira transition + summary comment) and ends the flow,
  on both the initial and revision paths.

### Non-Goals (explicitly out of scope)

- Replacing the AgentsFlow engine — it is already the FEAT-163 engine.
- Cyclic flows / loop-back edges inside a single DAG run — rejected because the
  scheduler is acyclic by construction (Kahn). The revision loop is a *new
  run*, not a cycle (see G6 / §2).
- Auto-merging the PR or undrafting it automatically — the human still
  marks-ready and merges.
- Replacing deterministic QA with LLM judgement — code-review is **additive**
  (G4), not a replacement (rejected alternative).
- Multi-tenant credential brokering for clones beyond the existing
  `GitToolkit` auth model.

---

## 2. Architectural Design

### Overview

Two layers change:

**A) Engine (small, generic).** `AgentsFlow.from_definition()` gains an
optional `node_factories: dict[str, Callable[[NodeDefinition, set[str],
set[str]], Node]]` parameter, keyed by `NodeDefinition.type`. During
`_materialize_nodes()`, any node whose `type` is not `agent`/`start`/`end` is
constructed by calling its factory (which closes over the live `dispatcher`,
toolkits, etc.) instead of the current generic
`cls(node_id, dependencies, successors)`. This is the single enabling change
that lets stateful dev-loop nodes live in a declarative graph. Custom node
types are also registered in `NODE_REGISTRY` via `@register_node("dev_loop.*")`
for definition-time validation.

**B) Dev-loop package.** The dev-loop is re-authored around a `FlowDefinition`
(`dev_loop/definition.py`) and a factory registry (`dev_loop/factories.py`)
that binds each declarative node id to a constructed node instance. Net-new
behaviour:

- `GitToolkit.clone_repo` / `pull_repo` (in `ai-parrot-tools`) provision repos.
- A repo-provisioning step (front of `ResearchNode`, gated by a
  `RepoSpec` list on the flow config) clones/pulls the configured repos under
  `WORKTREE_BASE_PATH` and sets `ResearchOutput.worktree_path` /
  `repo_path` accordingly. `Development` runs with `cwd=<clone path>`.
- A `sdd-codereview` subagent + a code-review gate inside `QANode`.
- `DeploymentHandoffNode` opens a **draft** PR.
- A revision FlowDefinition + `DevLoopRunner.run_revision(...)` entrypoint,
  fed by an extended GitHub webhook that emits `github.pr_comment` /
  `github.pr_review` events.
- `DevLoopCloseNode` terminal node.

The existing `github_reviewer.py::GitHubReviewer` (which already compares a PR
diff against the linked Jira ticket's acceptance criteria and submits
`REQUEST_CHANGES`/`APPROVE`) is the reference implementation for the
code-review prompt logic and the head-sha dedup strategy.

### Component Diagram

```
                     ┌──────────────────────────── INITIAL RUN ───────────────────────────┐
  WorkBrief ─► IntentClassifier ─(bug)─► BugIntake ─┐
                     │             (non-bug)─────────┼─► Research ─► [RepoProvision]
                     │                               │        (GitToolkit.clone/pull repos)
                     └───────── on_error ────────────┘                 │
                                                                       ▼
                                  Development ──► QA ──┬─(pass)─► DeploymentHandoff(DRAFT PR)
                                  (cwd=clone)          │                 │
                                       ▲               └─(fail)─► FailureHandler        │
                                       │  QA = deterministic criteria AND code-review  ▼
                                       │  (sdd-qa)          (sdd-codereview)        DevLoopClose
                                       │
   ┌─────────────────── REVISION RUN (new flow run, not a cycle) ──────────────────────┐
   │ GitHub PR comment / review  ─►  webhook (github.pr_comment)  ─►  DevLoopRunner     │
   │      .run_revision(RevisionBrief{repo_path, branch, pr_number, feedback})          │
   │   enters at ► Development(cwd=existing clone) ─► QA ─► RevisionHandoff ─► Close     │
   │   RevisionHandoff: git push to EXISTING branch + comment on SAME draft PR          │
   └───────────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AgentsFlow.from_definition` / `_materialize_nodes` (`flow/flow.py:351,440`) | extends | Add `node_factories` param + use it in the non-agent materialization branch. |
| `NODE_REGISTRY` / `register_node` (`flow/flow.py:106`) | uses | Register `dev_loop.*` node types for definition validation. |
| `FlowDefinition` / `NodeDefinition` / `EdgeDefinition` (`flow/definition.py`) | uses | Author the dev-loop graph; `NodeDefinition.type` will be `dev_loop.intent_classifier`, etc.; routing via `EdgeDefinition.condition`/`predicate`. |
| `GitToolkit` (`packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py:968`) | extends | New `clone_repo`/`pull_repo`; reuse existing PAT/GitHub-App auth + `repositories` registry; `create_pull_request(..., draft=True)` already exists at `:1488`. |
| `ClaudeCodeDispatcher` (`dev_loop/dispatcher.py`) | uses | Drives `sdd-codereview` dispatch (read-only, `permission_mode="plan"`). |
| `ClaudeCodeDispatchProfile` (`dev_loop/models.py`) | extends | Add `"sdd-codereview"` to the `subagent` Literal. |
| `load_subagent_definition` / `_VALID_NAMES` (`dev_loop/_subagent_defs.py`) | extends | Add `sdd-codereview` + ship `_subagent_data/sdd-codereview.md`. |
| `DeploymentHandoffNode` (`dev_loop/nodes/deployment_handoff.py:212`) | modifies | Add `--draft` to `gh pr create` and `draft=True` to the REST path. |
| `GitHubWebhookHook` (`parrot/core/hooks/github_webhook.py:12`) | extends | Classify `issue_comment` + `pull_request_review` events → `github.pr_comment` / `github.pr_review`. |
| `GitHubReviewer` (`parrot/bots/github_reviewer.py`) | reference / reuse | Code-review-vs-AC prompt + head-sha dedup pattern. |
| `DevLoopRunner` (`dev_loop/runner.py`) | extends | Add `run_revision(...)` entrypoint binding a `RevisionBrief`. |
| `webhook.py::register_pull_request_webhook` (`dev_loop/webhook.py`) | extends | Add a `pull_request.comment/review` handler that triggers `run_revision`. |
| `parrot.conf` (`conf.py:833+`) | extends | New settings: `DEV_LOOP_REPOS`, `DEV_LOOP_REPO_BASE_PATH`, `DEV_LOOP_REVISION_TRIGGER`, `DEV_LOOP_CODEREVIEW_MODEL`. |

### Data Models

```python
# parrot/flows/dev_loop/models.py  (additions)

class RepoSpec(BaseModel):
    """A git repository the dev-loop run operates on."""
    alias: str                                    # short name, also clone dir
    url: str                                      # https or owner/name slug
    branch: str = "main"                          # base branch to clone/branch from
    private: bool = False                         # use gh/token auth when True

class RevisionBrief(BaseModel):
    """Input to a revision-mode run (no new PR; update an existing one)."""
    repo_path: str                                # existing clone on disk
    branch: str                                   # existing feature branch
    pr_number: int
    repository: str                               # owner/name
    jira_issue_key: str
    feedback: str                                 # the reviewer comment text
    head_sha: str                                 # for dedup (mirrors GitHubReviewer)

# QAReport gains code-review fields (backward-compatible defaults):
class QAReport(BaseModel):
    passed: bool
    criterion_results: List[CriterionResult]
    lint_passed: bool
    lint_output: str = ""
    notes: str = ""
    code_review_passed: bool = True               # NEW — defaults True so old paths unaffected
    code_review_findings: List[str] = Field(default_factory=list)  # NEW

# ResearchOutput gains a repo handle (alias of worktree_path semantics):
#   repo_path: str  (== the clone the Development node will cd into)
```

`ClaudeCodeDispatchProfile.subagent` Literal becomes
`Literal["sdd-research", "sdd-worker", "sdd-qa", "sdd-codereview"]`.

### New Public Interfaces

```python
# parrot/bots/flows/flow/flow.py  (engine change)
@classmethod
def from_definition(
    cls,
    definition: FlowDefinition,
    *,
    agent_registry: Optional[AgentRegistry] = None,
    node_factories: Optional[
        dict[str, Callable[["NodeDefinition", set[str], set[str]], Node]]
    ] = None,
) -> "AgentsFlow": ...
# node_factories[node_type](node_def, dependencies, successors) -> Node

# packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py  (toolkit change)
async def clone_repo(
    self,
    repository: str,                  # alias, owner/name, or url
    dest_dir: str,
    branch: Optional[str] = None,
    *,
    private: bool = False,
    depth: Optional[int] = None,
) -> Dict[str, Any]:
    """Clone a repository to ``dest_dir``. Uses the configured PAT/App token
    (or ``gh`` when present) for private repos. Idempotent: pulls if the
    destination is already a clone of the same repo."""

async def pull_repo(self, repo_path: str, branch: Optional[str] = None) -> Dict[str, Any]:
    """Fast-forward an existing clone at ``repo_path`` to the latest ``branch``."""

# parrot/flows/dev_loop/definition.py
def build_dev_loop_definition(*, revision: bool = False) -> FlowDefinition:
    """Return the declarative dev-loop graph. ``revision=True`` returns the
    short graph that enters at Development and ends at RevisionHandoff/Close."""

def build_dev_loop_node_factories(
    *, dispatcher, jira_toolkit, git_toolkit, log_toolkits, redis_url, repos
) -> dict[str, Callable]:
    """Map each dev_loop.* node type to a factory closing over live deps."""

# parrot/flows/dev_loop/runner.py
async def run_revision(self, brief: RevisionBrief, *, run_id: str | None = None) -> FlowResult: ...
```

---

## 3. Module Breakdown

### Module 1: Engine — `node_factories` injection
- **Path**: `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py`
- **Responsibility**: Add `node_factories` to `from_definition` (store on the
  flow) and consult it in `_materialize_nodes()`'s non-`agent`/`start`/`end`
  branch: `factory = self._node_factories.get(node_def.type)`; if present,
  `fresh[nid] = factory(node_def, deps, succs)`; else fall back to the current
  generic construction. Validate custom types against `NODE_REGISTRY` exactly
  as today.
- **Depends on**: nothing new.

### Module 2: `GitToolkit.clone_repo` / `pull_repo`
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/gittoolkit.py`
- **Responsibility**: Async `clone_repo` / `pull_repo` via
  `asyncio.create_subprocess_exec("git", ...)`. For private repos: prefer
  `gh` (`gh repo clone`) when on `$PATH`; otherwise inject the toolkit's token
  into the clone URL (`https://x-access-token:<token>@github.com/<slug>.git`).
  Reuse `self.github_token` / GitHub-App token provider and the `repositories`
  alias registry (`RepositoryCredential`, `:47`). Idempotent clone (pull if the
  dest already tracks the same remote). Never echo the token to logs.
- **Depends on**: existing `GitToolkit` auth internals.

### Module 3: Dev-loop models
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models.py`
- **Responsibility**: Add `RepoSpec`, `RevisionBrief`; extend `QAReport`
  (`code_review_passed`, `code_review_findings`) and `ResearchOutput`
  (`repo_path`); extend `ClaudeCodeDispatchProfile.subagent` Literal.
- **Depends on**: M-none.

### Module 4: Repo provisioning
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  (extend) — or a new `nodes/repo_provision.py` if the Research node grows too
  large.
- **Responsibility**: For each configured `RepoSpec`, call
  `git_toolkit.clone_repo(...)`/`pull_repo(...)` into
  `<DEV_LOOP_REPO_BASE_PATH>/<run_id>/<alias>` (kept under
  `WORKTREE_BASE_PATH` so the dispatcher's cwd-safety guard
  `_enforce_cwd_under_worktree_base` passes). Set `ResearchOutput.repo_path`
  to the primary clone. Bug/spec research continues as today.
- **Depends on**: M2, M3.

### Module 5: `sdd-codereview` subagent
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-codereview.md`
  (new) + `_subagent_defs.py` (`_VALID_NAMES` += `"sdd-codereview"`).
- **Responsibility**: System-prompt body adapted from
  `.claude/agents/code-reviewer.md`: review the diff against the Jira
  acceptance criteria + the project rules, output a single JSON object
  (`{passed: bool, findings: [str], ...}`). Read-only.
- **Depends on**: M-none (data file + allowlist).

### Module 6: QA code-review gate
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py`
- **Responsibility**: After the deterministic dispatch, dispatch
  `sdd-codereview` (`permission_mode="plan"`, `allowed_tools=["Read","Bash","Grep","Glob"]`)
  with a brief = AC + diff/worktree path. Merge into the `QAReport`:
  `code_review_passed`, `code_review_findings`; final
  `passed = deterministic_passed and code_review_passed`. Node still never
  raises on failure — the flow takes the fail edge.
- **Depends on**: M3, M5.

### Module 7: Draft PR
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py`
- **Responsibility**: `_create_pr_with_gh` adds `--draft`; `_create_pr_via_rest`
  sends `"draft": true`. Title/body unchanged. Return PR number + URL (number
  needed for the revision loop).
- **Depends on**: M-none.

### Module 8: Declarative definition + factories
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/definition.py` (new),
  `packages/ai-parrot/src/parrot/flows/dev_loop/factories.py` (new).
- **Responsibility**: `build_dev_loop_definition(revision=…)` returns the
  `FlowDefinition` (nodes + edges mirroring the current routing: intent→bug/
  research branch, qa pass/fail branch, on_error fan-in to failure, plus the
  new close node). `build_dev_loop_node_factories(...)` returns the
  `{node_type: factory}` map binding live deps. `@register_node("dev_loop.*")`
  registers the node classes. The old `build_dev_loop_flow()` becomes a thin
  wrapper: `AgentsFlow.from_definition(build_dev_loop_definition(), node_factories=...)`.
- **Depends on**: M1, M4, M6, M7, M10.

### Module 9: Revision mode
- **Path**: `dev_loop/runner.py` (extend), `dev_loop/webhook.py` (extend),
  `parrot/core/hooks/github_webhook.py` (extend), `dev_loop/nodes/revision_handoff.py` (new).
- **Responsibility**:
  - `GitHubWebhookHook` classifies `issue_comment` (action `created`) and
    `pull_request_review` (action `submitted`) on dev-loop PRs → emits
    `github.pr_comment` / `github.pr_review` with `pr_number`, `body`,
    `head_sha`, `author`, `branch`, `repository`.
  - `webhook.py` handler filters by `DEV_LOOP_REVISION_TRIGGER` (default:
    any non-bot human comment that requests changes; optional `/revise`
    prefix), dedups by `head_sha` (mirrors `GitHubReviewer`), builds a
    `RevisionBrief`, and calls `DevLoopRunner.run_revision(...)`.
  - `run_revision` runs the **revision** `FlowDefinition` (enters at
    `Development` with `cwd=repo_path`, the existing branch already checked
    out; → QA → `RevisionHandoffNode` → Close).
  - `RevisionHandoffNode`: `git push` to the **existing** branch and
    `git_toolkit.add_pr_comment(pr_number, body=…)` on the **same** PR. No new
    PR.
- **Depends on**: M2, M3, M8, M10.

### Module 10: `DevLoopCloseNode`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/close.py` (new).
- **Responsibility**: Terminal node. Records the run's final state: a Jira
  summary comment + transition (e.g. "Ready to Deploy" on initial,
  "In Review – revised" on revision), and returns a terminal status dict. Pure
  AI-Parrot (no dispatch).
- **Depends on**: M3, JiraToolkit.

### Module 11: Settings
- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: Add:
  - `DEV_LOOP_REPOS` (list/JSON of `RepoSpec`, default `[]`)
  - `DEV_LOOP_REPO_BASE_PATH` (default: under `WORKTREE_BASE_PATH`, e.g.
    `".claude/worktrees/repos"`)
  - `DEV_LOOP_REVISION_TRIGGER` (default `"changes_requested"`; also
    `"any_comment"`, `"command"`)
  - `DEV_LOOP_CODEREVIEW_MODEL` (default `"claude-sonnet-4-6"`)
- **Depends on**: none.

### Module 12: Tests
- **Path**: `packages/ai-parrot/tests/flows/dev_loop/` + `tests/bots/flows/`
- **Responsibility**: §4.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_from_definition_uses_node_factories` | M1 | A custom node type with a registered factory is materialized via the factory (live dep injected), not the generic ctor. |
| `test_from_definition_factory_fresh_per_run` | M1 | Two `run_flow()` calls materialize independent node instances (no shared FSM). |
| `test_clone_repo_public` | M2 | `clone_repo("owner/name", dest)` runs `git clone` into `dest`. |
| `test_clone_repo_private_uses_token` | M2 | Private clone injects token (or `gh repo clone`); token never appears in returned dict/logs. |
| `test_clone_repo_idempotent_pulls` | M2 | Dest already a clone → `pull_repo` path, no re-clone. |
| `test_repospec_and_revisionbrief_models` | M3 | Pydantic validation round-trips; `QAReport` defaults `code_review_passed=True`. |
| `test_research_clones_configured_repos` | M4 | Each `RepoSpec` triggers a `clone_repo`; `ResearchOutput.repo_path` set under `WORKTREE_BASE_PATH`. |
| `test_qa_codereview_gate_blocks_on_fail` | M6 | Deterministic pass + code-review fail ⇒ `QAReport.passed is False`; node does not raise. |
| `test_qa_codereview_passes_when_both_pass` | M6 | Both pass ⇒ `passed is True`, `code_review_findings == []`. |
| `test_qa_codereview_dispatch_is_read_only` | M6 | `sdd-codereview` profile has `permission_mode="plan"`, no `Edit`/`Write`. |
| `test_deployment_handoff_opens_draft_pr` | M7 | `gh pr create` includes `--draft` (and REST path sends `draft=true`). |
| `test_definition_routing_matches_legacy` | M8 | Declarative graph routes bug→BugIntake, non-bug→Research, qa-pass→Handoff, qa-fail→Failure, on_error→Failure — identical to FEAT-132. |
| `test_register_node_dev_loop_types` | M8 | All `dev_loop.*` node types are in `NODE_REGISTRY`. |
| `test_webhook_emits_pr_comment_event` | M9 | `issue_comment.created` payload on a dev-loop PR → `github.pr_comment` event with `pr_number`/`head_sha`. |
| `test_revision_trigger_filters_bot_comments` | M9 | A comment authored by the flow-bot does not trigger a revision run. |
| `test_revision_dedup_by_head_sha` | M9 | Two events with the same `head_sha` trigger only one revision run. |
| `test_run_revision_enters_at_development` | M9 | Revision graph starts at `Development` (no Intent/Research/clone), ends at `RevisionHandoff`→`Close`. |
| `test_revision_handoff_no_new_pr` | M9 | `RevisionHandoffNode` calls `git push` + `add_pr_comment` on the existing PR; `create_pull_request` is **not** called. |
| `test_close_node_transitions_jira` | M10 | `DevLoopCloseNode` posts a summary comment + transition and returns a terminal status. |
| `test_settings_defaults` | M11 | New settings resolve to documented defaults. |

### Integration Tests

| Test | Description |
|---|---|
| `test_e2e_initial_run_draft_pr` (`@pytest.mark.live`) | Real SDK + a fixture repo with a broken file: Intent→…→Development→QA(both gates)→draft PR. Skipped without `claude` CLI / `ANTHROPIC_API_KEY`. |
| `test_e2e_revision_updates_same_pr` (`@pytest.mark.live`) | After an initial draft PR, a simulated reviewer comment triggers `run_revision`; asserts a new commit on the same branch + a comment on the same PR number, no second PR. |
| `test_e2e_private_repo_clone` (`@pytest.mark.live`) | Clones a private fixture repo via token/`gh`. |

### Test Data / Fixtures

```python
@pytest.fixture
def sample_repo_spec() -> RepoSpec:

…(truncated)…
