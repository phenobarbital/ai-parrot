---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Feature Specification: Dev-Loop Run Fidelity

**Feature ID**: FEAT-466
**Date**: 2026-08-27
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.28.x

---

## 1. Motivation & Business Requirements

### Problem Statement

A dev-loop run must honour the two things the operator declared: the **base
branch** implied by the work kind, and the **dev agent (LLM client)** selected
in the console. Today both are silently discarded, and neither failure is
observable until after the damage is done.

**Problem A — the declared base branch is never applied (realized incident).**

A `kind="bug"` run is supposed to flow as a hotfix from `main`. Instead the
branch is cut from `dev` while the PR still targets `main`. This is not
hypothetical: PR #1250 (head `feat-465-fix-weak-sha1-arango-store`, base
`main`) carried **93 commits of `dev`** and was merged into `main`.
`origin/main` is now `f4d928803`, and `main`/`dev` are effectively the same
tree — the release branch absorbed unreleased integration work.

Three independent links produce this:

1. `.claude/commands/sdd-spec.md:131` (§2d) defaults to `feature`/`dev` when
   no exploration document exists, and the command's usage line accepts no
   type/base-branch argument. The dev-loop bug path *never* has a brainstorm
   or proposal — `ResearchNode` dispatches `sdd-research`, which invokes
   `/sdd-spec` straight from the `BugBrief` — so the default always wins.
   §2d then runs `git checkout "$BASE_BRANCH"` → `dev`.
2. `.claude/agents/sdd-research.md:61-69` correctly states that `kind="bug"`
   implies `type: hotfix` / `base_branch: main` and a worktree cut from
   `origin/main`, but it delegates frontmatter authorship to `/sdd-spec` §5.1,
   which overrides it with §2d's values. `CLAUDE.md`'s worktree rule ("create
   worktrees manually from the current branch … `HEAD`") compounds this.
3. `nodes/deployment_handoff.py:132` forces the PR base to `"main"` from
   `brief.kind == "bug"` alone. `ResearchOutput` carries no `base_branch`
   field, so the base actually resolved upstream never reaches the handoff
   node, and **nothing validates the branch against the base** before
   `gh pr create`.

   Note the subtlety, measured against the real SHAs: an ancestry check is
   *not* sufficient here. `git merge-base --is-ancestor 5370f9256 43ba79e93`
   (old `main` vs the `feat-465` tip) returns **true** — because `main` was an
   ancestor of `dev`, a branch cut from `dev` still descends from `origin/main`.
   The discriminating signal is whether the branch carries commits that already
   live on a *sibling* long-lived branch (§2).

Underneath all three: `WorkKind` is `bug | enhancement | new_feature` while
SDD flow types are `feature | hotfix`. That mapping exists only as prose in
agent markdown — it is never executed as code.

**Problem B — the declared dev agent is silently replaced by the server's
env default.**

`DevelopmentNode.execute()` has two degradation branches that both fall
through to `_execute_single()`:

* `self._dispatcher_builder is None` (`development.py:192`) — already fixed
  for the shipped examples by commit `4f2fc7d0b`, which wired
  `functools.partial(build_dispatcher, …)` at `examples/dev_loop/server.py:1499`.
  `examples/dev_loop/server_dev.py:474` has had it since TASK-2129.
* `scheduler is None` (`development.py:200`) — no readable per-spec task
  index under `research.worktree_path` for `research.feat_id`. **Still live.**

`_execute_single()` (`development.py:437`) uses `self._dispatcher` /
`self._dispatch_profile`, both fixed at server startup from
`DEV_LOOP_DEVELOPMENT_AGENT`, and never consults the resolved pool config. So
a console "Agents & models" selection is discarded whenever the second branch
fires, and the run quietly executes on the env backend instead. The operator
is told nothing.

The rest of that path is already correct and must not be disturbed: the UI
sends `dev_agents` (`static/index.html:1344`), `_parse_dev_agents` builds
`DevAgentSpec` rows, `_resolve_pool_config` prefers the brief over the env
config (`development.py:426-430`), and `build_dispatcher` honours both
backend and `spec.model` across all nine backends.

### Goals

- A run's PR base branch is the base the branch was **actually cut from**,
  read from a single authoritative source, never inferred from `brief.kind`
  at handoff time.
- The `WorkKind → (flow type, base branch)` mapping is executable code with
  tests, not prose in an agent markdown file.
- `kind="bug"` defaults to `hotfix`/`main`, and the operator can override the
  flow type / base branch explicitly per run from the console.
- A run whose branch carries commits from a sibling long-lived branch is
  **blocked** with a clear error before any PR is opened.
- A bugfix/hotfix reserves **no** `FEAT`/`TASK` id at all. Ledger ids exist
  for features and the brainstorm/spec/task SDD flow; a hotfix is identified
  by its Jira issue key.
- A dev-agent selection made in the console is either honoured or reported —
  never silently replaced.

### Non-Goals (explicitly out of scope)

- Reverting or rewriting the merge of PR #1250 on `main`. The current state of
  `main` is accepted as-is; this spec only prevents recurrence.
- Auto-recutting or replaying a mis-based branch. Self-healing was considered
  and rejected in favour of blocking (§8) — the flow reports, a human re-cuts.
- Changing `scripts/sdd/reserve_ids.py` at all. Making the allocator
  branch-agnostic was considered and is no longer needed: the hotfix path
  stops reserving ids entirely, so the allocator's
  "current branch must equal `--base-branch`" precondition is never reached
  by a hotfix run. Feature runs keep reserving on `dev` exactly as today.
- Consolidating the id ledger onto a single canonical branch (§7 Known Risks).
- Changing `staging`-freeze semantics (FEAT-187) or the `sync-down.yml`
  automation.
- Any change to `build_dispatcher`'s per-backend model defaults.

---

## 2. Architectural Design

### Overview

One idea carries the whole spec: **resolve once, record it, and read the
record** — replacing three places that each independently guess.

For Problem A, the resolved `(type, base_branch)` pair becomes a value that
travels: `scripts/sdd/sdd_meta.py` gains an explicit resolver that takes the
work kind plus optional overrides; `/sdd-spec` accepts it as flags and writes
it into the spec frontmatter; `ResearchNode` reads it **back out of the
committed spec** (deterministically, in Python — never trusting the
subagent's self-report) and records it on `ResearchOutput.base_branch`;
both handoff nodes use that value and the `kind == "bug"` override is
deleted. A pre-PR **sibling-overlap** guard is the backstop for any path that
still drifts — deliberately not an ancestry check, which is provably blind to
the shape that produced PR #1250 (section 7).

For Problem B, `_execute_single()` stops being the "env dispatcher" path and
becomes the "one worker" path: when a pool config resolved, it materializes
its dispatcher from `pool_cfg.agents[0]` via the same `dispatcher_builder` the
pool path uses. When no pool config resolved, it behaves byte-identically to
today. Either way it emits a `WorkerSummary` recording the backend/model
actually used, so a substitution is visible on the run bundle.

### Component Diagram

```
  WorkBrief.kind ─┐
                  │            ┌─────────────────────────┐
  console override├───────────►│ sdd_meta.resolve_flow() │  (NEW, pure)
                  ┘            └───────────┬─────────────┘
                                           │ FlowMeta(type, base_branch)
                                           ▼
                            /sdd-spec --type --base-branch
                                           │
                                           ▼
                          sdd/specs/<slug>.spec.md frontmatter
                                           │  (single source of truth)
                                           ▼
   ResearchNode ──► sdd_meta.parse(spec) ──► ResearchOutput.base_branch (NEW)
                                           │
                                           ▼
   Deployment/FeatureHandoffNode ──► _assert_base_is_clean() (NEW) ──► gh pr create
                                    │ carries sibling-branch commits
                                    └──────────────► status="blocked"


   DevelopmentNode.execute()
        │
        ├─ pool_cfg is None ─────────────► _execute_single(pool_cfg=None)
        │                                     └─ env dispatcher (unchanged)
        └─ pool_cfg resolved
             ├─ scheduler built ─────────► _execute_pool(...)
             └─ scheduler is None ───────► _execute_single(pool_cfg=pool_cfg)
                                              └─ dispatcher_builder(agents[0])
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts/sdd/sdd_meta.FlowMeta` | extends | New `resolve_flow()` helper alongside `parse()` / `emit()`; the existing hotfix→main validator is reused, not duplicated |
| `ResearchOutput` (`models/base.py:323`) | extends | New `base_branch` field with `validation_alias` |
| `ResearchNode.execute` (`nodes/research.py:207`) | modifies | Reads the committed spec's frontmatter after the dispatch returns and stamps `base_branch` |
| `DeploymentHandoffNode` (`nodes/deployment_handoff.py`) | modifies | Deletes the `kind` override at :132; adds the sibling-overlap guard before `_create_pr` |
| `FeatureHandoffNode` (`nodes/feature_handoff.py:101`) | modifies | Same source-of-truth read; same guard (shared helper) |
| `scripts/sdd/reserve_ids.py` | untouched | Hotfix runs never call it (Module 2); feature runs unchanged |
| `ResearchOutput.feat_id` | reuses | Stays `""` for hotfix runs — already a supported shape (`runner.py:1378`) |
| `DevelopmentNode._execute_single` (`development.py:437`) | modifies | Accepts the resolved pool config; builds from `agents[0]` when present |
| `agent_builder.build_dispatcher` (`agent_builder.py:102`) | uses | Unchanged; called from the single path as well as the pool path |
| `WorkerSummary` (`models/base.py:454`) | uses | Already carries `agent` + `model`; reused to report the single path's actual backend |
| `.claude/commands/sdd-spec.md` | modifies | New `--type` / `--base-branch` flags, honoured when no exploration doc exists |
| `.claude/agents/sdd-research.md` | modifies | Passes the flags derived from `brief.kind` instead of relying on prose |
| `CLAUDE.md` | modifies | Worktree carve-out so "branch from `HEAD`" stops contradicting "hotfix branches from `origin/main`" |

### Data Models

```python
# scripts/sdd/sdd_meta.py — NEW helper (FlowMeta itself is unchanged)
def resolve_flow(
    *,
    kind: str | None = None,
    doc_path: Path | None = None,
    type_override: str | None = None,
    base_branch_override: str | None = None,
) -> FlowMeta:
    """Resolve (type, base_branch) from explicit overrides > document
    frontmatter > work-kind mapping > the feature/dev default."""


# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class ResearchOutput(BaseModel):
    ...
    base_branch: str = Field(
        default="",
        description=(
            "Branch the feature/hotfix branch was cut from, read back from "
            "the committed spec frontmatter. '' means unresolved — handoff "
            "nodes must then block rather than guess."
        ),
        validation_alias=AliasChoices("base_branch", "base"),
    )


class WorkBrief(BaseModel):
    ...
    flow_type: Optional[Literal["feature", "hotfix"]] = None   # console override
    base_branch: Optional[str] = None                          # console override
```

### New Public Interfaces

```python
# parrot/flows/dev_loop/nodes/base.py  (shared by BOTH handoff nodes)
async def assert_base_is_clean(
    branch: str,
    base: str,
    cwd: str,
    *,
    siblings: Optional[Iterable[str]] = None,
) -> None:
    """Raise BaseBranchMismatch when `branch` carries commits that already
    live on a sibling long-lived branch — i.e. when the PR would add commits
    that are not this branch's own work.

        adds = git rev-list --count origin/<base>..<branch>
        own  = git rev-list --count origin/<base>..<branch> \
                   --not origin/<sibling> [origin/<sibling2> ...]
        adds != own  =>  the branch was cut from the wrong base.

    An ancestry check is deliberately NOT the test here: `--is-ancestor`
    returns true for the PR #1250 shape (see section 7). `siblings` defaults
    to `sdd_meta.KNOWN_BRANCHES` minus `base`, filtered to refs that exist on
    the remote; `origin/<base>` and every sibling ref are fetched first so the
    verdict is never computed against a stale remote-tracking ref.
    """


# parrot/flows/dev_loop/nodes/development.py
async def _execute_single(
    self,
    shared: Dict[str, Any],
    research: ResearchOutput,
    pool_cfg: Optional[DevAgentPoolConfig] = None,
) -> DevelopmentOutput:
    ...
```

---

## 3. Module Breakdown

### Module 1: Executable work-kind → flow-type mapping
- **Path**: `scripts/sdd/sdd_meta.py`
- **Responsibility**: `resolve_flow()` with the documented precedence
  (explicit override > document frontmatter > `WorkKind` mapping > default).
  `bug → hotfix/main`; `enhancement`/`new_feature` → `feature/dev`. Reuses
  `FlowMeta`'s existing hotfix→main validator. Also fixes the latent crash:
  `parse()` raises `FileNotFoundError` on a missing path, so §2d's documented
  "default when no exploration doc exists" has no code path today.
- **Depends on**: nothing new.

### Module 2: A hotfix reserves no id — Jira key is its identity
- **Path**: `.claude/commands/sdd-spec.md`, `.claude/commands/sdd-task.md`,
  `.claude/agents/sdd-research.md`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
- **Responsibility**: Ledger ids (`FEAT-<NNN>` / `TASK-<NNN>`) exist for
  **features** and the brainstorm → spec → task SDD flow. A bugfix/hotfix is
  not a feature and must not consume one. So on the `type: hotfix` path:
  * `/sdd-spec` **skips** the `reserve_ids.py --kind feature` call entirely
    and writes no `FEAT-<NNN>`; the document's identity line carries the Jira
    issue key instead.
  * `/sdd-task` **skips** `reserve_ids.py --kind task`.
  * `sdd-research` names the branch and worktree
    `hotfix-<JIRA-KEY>-<slug>` (replacing `feat-<id>-<slug>`, which
    presupposes a reserved id) and leaves `ResearchOutput.feat_id` as `""`.
  Because the hotfix path never calls `reserve_ids.py`, the allocator's
  "current branch must equal `--base-branch`" and clean-tree preconditions
  (`reserve_ids.py:126-145`) are simply never reached — no allocator change,
  no destructive-reset exposure, and no push to `main`.
- **Consumer fallbacks**: every place that labels a run by `feat_id` falls
  back to `jira_issue_key`, following the pattern already established at
  `nodes/qa.py:194,342` (`research.jira_issue_key or research.feat_id`).
  Audited consumers: `run_bundle.py:310`, `deployment_handoff.py:505`,
  `nodes/qa.py:417`, `development.py:484` (`_find_feature_slug`).
- **Interaction with Module 7 (intentional)**: with no reserved ids there is
  no per-spec task index, so `_build_scheduler` returns `None` and a hotfix
  runs the single-agent path. That is the correct shape for a one-or-two-commit
  bugfix — and Module 7 is what makes that path honour the operator's declared
  dev agent instead of silently substituting the env default.
- **Depends on**: Module 1.

### Module 3: `/sdd-spec` and `sdd-research` flag plumbing
- **Path**: `.claude/commands/sdd-spec.md`, `.claude/agents/sdd-research.md`,
  `CLAUDE.md`
- **Responsibility**: `--type` / `--base-branch` flags on `/sdd-spec`, honoured
  when no exploration doc exists and validated by Module 1 (keeping the
  existing hotfix/main and feature/not-main aborts). `sdd-research` derives and
  passes them from `brief.kind`. `CLAUDE.md` gains a worktree carve-out so
  "create worktrees from the current branch … `HEAD`" stops contradicting
  "hotfix branches from `origin/main`".
- **Depends on**: Modules 1, 2.

### Module 4: `base_branch` on `ResearchOutput`
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py`,
  `nodes/research.py`
- **Responsibility**: Add the field; `ResearchNode` reads the committed spec's
  frontmatter via `sdd_meta.parse` after the dispatch returns and stamps it.
  Never trust the subagent's self-reported value.
- **Depends on**: Module 1.

### Module 5: Handoff nodes consume the recorded base + sibling-overlap guard
- **Path**: `nodes/deployment_handoff.py`, `nodes/feature_handoff.py`,
  `nodes/base.py`
- **Responsibility**: Delete the `kind == "bug"` override at
  `deployment_handoff.py:132-133`; both nodes read
  `research_output.base_branch` (blocking when it is `""` rather than falling
  back to a hardcoded default). Add `assert_base_is_clean()` as a shared
  helper in `nodes/base.py` and call it before `_create_pr` in **both** nodes;
  on failure return `{"status": "blocked", "error": …}` after
  `_mark_blocked(...)`, without opening a PR.
- **Depends on**: Module 4.

### Module 6: Console flow-type / base-branch override
- **Path**: `examples/dev_loop/server.py`, `examples/dev_loop/server_dev.py`,
  `examples/dev_loop/static/index.html`, `examples/dev_loop/static/dev.html`
- **Responsibility**: Surface an explicit flow-type / base-branch control that
  overrides the kind-derived default, carried on the brief and threaded into
  Module 3's flags.
- **Depends on**: Modules 1, 4.

### Module 7: Single-agent path honours the declared dev agent
- **Path**: `nodes/development.py`
- **Responsibility**: `_execute_single(pool_cfg=…)` materializes from
  `pool_cfg.agents[0]` via `self._dispatcher_builder` when a pool resolved;
  otherwise unchanged. Emit a `WorkerSummary` recording the backend/model
  actually used, and log requested-vs-actual at WARNING when they differ.
- **Depends on**: nothing new (uses existing `build_dispatcher`).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_flow_bug_defaults_to_hotfix_main` | 1 | `kind="bug"` with no overrides → `hotfix` / `main` |
| `test_resolve_flow_enhancement_defaults_to_feature_dev` | 1 | `enhancement` / `new_feature` → `feature`/`dev` |
| `test_resolve_flow_explicit_override_wins` | 1 | Explicit `type`/`base_branch` beats the kind mapping |
| `test_resolve_flow_rejects_hotfix_off_main` | 1 | `type=hotfix, base_branch=dev` raises (reuses `FlowMeta`'s validator) |
| `test_resolve_flow_missing_doc_returns_default` | 1 | Missing `doc_path` returns the default instead of `FileNotFoundError` |
| `test_hotfix_path_reserves_no_ids` | 2 | A `type: hotfix` run never invokes `reserve_ids.py`; the ledger is byte-identical before and after |
| `test_hotfix_branch_name_uses_jira_key` | 2 | Branch/worktree are `hotfix-<JIRA-KEY>-<slug>`, not `feat-<id>-<slug>` |
| `test_hotfix_research_output_feat_id_empty` | 2 | `ResearchOutput.feat_id == ""` validates and downstream labels fall back to `jira_issue_key` |
| `test_feature_path_still_reserves_ids` | 2 | Regression guard: `type: feature` reserves exactly as today |
| `test_research_output_base_branch_alias` | 4 | `{"base": "main"}` populates `base_branch` |
| `test_research_node_stamps_base_from_spec_frontmatter` | 4 | Spec says `hotfix`/`main`; subagent claims `dev`; the spec wins |
| `test_handoff_uses_recorded_base_not_kind` | 5 | `kind="bug"` + recorded `base_branch="dev"` → PR base `dev` |
| `test_handoff_blocks_on_empty_base_branch` | 5 | `base_branch == ""` blocks instead of defaulting to `"dev"` |
| `test_assert_base_is_clean_blocks_sibling_overlap` | 5 | The #1250 shape (93 adds vs 2 own commits) → `BaseBranchMismatch` |
| `test_assert_base_is_clean_passes_correctly_cut_branch` | 5 | adds == own → no raise |
| `test_assert_base_is_clean_ignores_cherry_picks` | 5 | Cherry-picked (re-SHA'd) commits on a sibling do not trigger a false block |
| `test_feature_handoff_guard_applied` | 5 | `FeatureHandoffNode` calls the same shared helper |
| `test_execute_single_uses_pool_spec_backend` | 7 | Pool config + no task index → runs on the spec's backend/model |
| `test_execute_single_without_pool_uses_env_dispatcher` | 7 | Regression guard: byte-identical legacy path |
| `test_execute_single_emits_worker_summary` | 7 | Actual backend/model recorded on `DevelopmentOutput` |

### Integration Tests

| Test | Description |
|---|---|
| `test_bug_run_end_to_end_targets_main` | Mocked dispatcher; `kind="bug"` yields frontmatter `hotfix`/`main`, branch cut from `origin/main`, PR base `main` |
| `test_enhancement_run_end_to_end_targets_dev` | Same, for `feature`/`dev` |
| `test_console_base_override_wins_over_kind` | Console override to `dev` on a `kind="bug"` run reaches the PR |

### Test Data / Fixtures

```python
@pytest.fixture
def spec_with_frontmatter(tmp_path):
    """Write a spec file with a given (type, base_branch) frontmatter and
    return its path, for ResearchNode's read-back."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `kind="bug"` run (mocked dispatcher) yields `type: hotfix` /
      `base_branch: main`, a branch cut from `origin/main`, and a PR whose
      base is `main`.
- [ ] `kind="enhancement"` and `kind="new_feature"` yield `feature`/`dev` and
      a PR base of `dev`.
- [ ] An explicit console flow-type / base-branch override wins over the
      kind-derived default and reaches the PR.
- [ ] A `type: hotfix` run reserves **no** `FEAT`/`TASK` id:
      `sdd/tasks/.id_ledger.json` is unchanged across the run, and
      `reserve_ids.py` is never invoked.
- [ ] A hotfix's branch and worktree are named `hotfix-<JIRA-KEY>-<slug>`,
      and every run label falls back to `jira_issue_key` when `feat_id` is `""`.
- [ ] A `type: feature` run reserves ids exactly as before (regression guard).
- [ ] Both handoff nodes block — `status="blocked"`, `_create_pr` never called —
      when the branch carries commits that already live on a sibling
      long-lived branch, i.e. when
      `rev-list origin/<base>..<branch>` ≠
      `rev-list origin/<base>..<branch> --not origin/<sibling>...`.
      Verified against the real #1250 SHAs (93 vs 0).
- [ ] Both handoff nodes block when `research_output.base_branch` is `""`
      rather than falling back to a hardcoded `"dev"`.
- [ ] No `kind`-derived base-branch guessing remains in either handoff node
      (`grep -n 'kind.*==.*"bug"' nodes/*handoff*.py` returns nothing).
- [ ] `ResearchNode` derives `base_branch` from the committed spec
      frontmatter, and a subagent that self-reports a different value does not
      change the outcome.
- [ ] A pool config with one spec and no readable task index runs
      `_execute_single` on **that spec's** backend/model, not the injected env
      dispatcher.
- [ ] With no pool config resolved, the single-agent path is unchanged
      (regression guard passes).
- [ ] The backend/model actually used is recorded on `DevelopmentOutput` and
      a requested-vs-actual mismatch is logged at WARNING.
- [ ] `scripts/sdd/reserve_ids.py` is unmodified by this feature.
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on every changed file.

---

## 6. Codebase Contract

### Verified Imports

```python
from scripts.sdd.sdd_meta import FlowMeta, parse, emit, KNOWN_BRANCHES  # scripts/sdd/sdd_meta.py:26,29,45,78
from parrot.flows.dev_loop.agent_builder import build_dispatcher, parse_pool_env, resolve_pool_max  # agent_builder.py:102,223,254
from parrot.flows.dev_loop.models.base import (
    WorkBrief, BugBrief, ResearchOutput, DevelopmentOutput,
    DevAgentSpec, DevAgentPoolConfig, WorkerSummary,
)  # models/base.py:138,223,323,476,388,420,454
```

### Existing Class Signatures

```python
# scripts/sdd/sdd_meta.py
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})   # line 26
class FlowMeta(BaseModel):                                               # line 29
    type: Literal["feature", "hotfix"]                                   # line 32
    base_branch: str                                                     # line 33
    @model_validator(mode="after")
    def _hotfix_implies_main(self) -> "FlowMeta": ...                    # line 35
def parse(doc_path: Path) -> FlowMeta: ...                               # line 45
def emit(meta: FlowMeta) -> str: ...                                     # line 78

# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
WorkKind = Literal["bug", "enhancement", "new_feature"]                  # line 116
class WorkBrief(BaseModel):                                              # line 138
    kind: WorkKind = Field(default="bug", ...)                           # line 151
BugBrief = WorkBrief                                                     # line 223
class ResearchOutput(BaseModel):                                         # line 323
    model_config = ConfigDict(populate_by_name=True)                     # line 336
    jira_issue_key: str                                                  # line 338
    spec_path: str                                                       # line 343
    feat_id: str                                                         # line 348
    branch_name: str                                                     # line 353
    worktree_path: str                                                   # line 358
    repo_path: str = ""                                                  # line 363
    log_excerpts: List[str]                                              # line 373
DevAgentBackend = Literal[...]                                           # line 383
class DevAgentSpec(BaseModel):                                           # line 388
    agent: DevAgentBackend                                               # line 396
    model: str = ""                                                      # line 399
    count: int = 1                                                       # line 402
    escalation_model: str = ""                                           # line 405
class DevAgentPoolConfig(BaseModel):                                     # line 420
    agents: List[DevAgentSpec]                                           # line 429
    isolation_mode: Literal["shared", "isolated"] = "shared"             # line 432
class WorkerSummary(BaseModel):                                          # line 454
    worker_id: str                                                       # line 462
    agent: str                                                           # line 465
    model: str                                                           # line 466
class DevelopmentOutput(BaseModel):                                      # line 476
    worker_summaries: List[WorkerSummary]                                # line 490

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
def __init__(self, *, dispatcher, dispatch_profile=None, pool_config=None,
             dispatcher_builder=None, pool_max=4, ...)                   # line 86
async def execute(self, ctx, deps=None, **kwargs) -> DevelopmentOutput:  # line 141
    if self._dispatcher_builder is None: ...degrade                      # line 192
    if scheduler is None: ...degrade                                     # line 200
def _resolve_pool_config(self, shared) -> Optional[DevAgentPoolConfig]:  # line 416
async def _execute_single(self, shared, research) -> DevelopmentOutput:  # line 437
    profile = self._dispatch_profile or ClaudeCodeDispatchProfile(...)   # line 449
    dev_out = await self._dispatcher.dispatch(...)                       # line 463
async def _build_scheduler(self, research) -> Optional[TaskScheduler]:   # line 512
async def _execute_pool(self, shared, research, pool_cfg, scheduler)     # line 539
    pool = DevAgentPool.build(pool_cfg, self._dispatcher_builder, ...)   # line 564

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/deployment_handoff.py
def __init__(self, *, jira_toolkit, ..., base_branch: str = "dev", ...)  # line 80
    object.__setattr__(self, "_base_branch", base_branch)                # line 93
    if getattr(brief, "kind", "bug") == "bug":                           # line 132
        object.__setattr__(self, "_base_branch", "main")                 # line 133  ← DELETE
async def _push_branch(self, branch: str, cwd: str) -> None:             # line 296
async def _create_pr(self, branch, title, body) -> str:                  # line 332
    "--base", self._base_branch,                                         # line 357-358
    "base": self._base_branch,                                           # line 428

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/feature_handoff.py
    base_branch: str = "dev",                                            # line 101
    "--base", self._base_branch, "--head", branch,                       # line 305
    "base": self._base_branch, "draft": True,                            # line 326

# scripts/sdd/reserve_ids.py  (READ-ONLY for this feature — do not modify)
def _assert_safe_to_reserve(root: Path, base_branch: str) -> None:      # line 106
    #   refuses on a dirty tree (besides the ledger)                    # line 134
    #   refuses when current_branch != base_branch                      # line 140
def reserve_ids(kind, count, base_branch, label, *, max_retries=5,
                repo_root=None, sleep_fn=time.sleep) -> IdReservation:  # line 165
    #   retry path: reset --hard HEAD~1 / reset --hard origin/<base>    # line 272,280-282

# Identity-fallback precedent (Jira key before feat_id) — follow this shape
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/qa.py
    research.jira_issue_key or research.feat_id                          # line 194, 342
    return document or research.spec_path or research.feat_id or ""      # line 417
# packages/ai-parrot/src/parrot/flows/dev_loop/runner.py
    feat_id="",   # an empty feat_id is ALREADY a supported shape        # line 1378
# packages/ai-parrot/src/parrot/flows/dev_loop/run_bundle.py
    feature_id=getattr(primary_output, "feat_id", "") or ""              # line 310
# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]  # line 484

# packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py
ConfigGetter = Callable[..., Any]                                        # line 63
def build_dispatcher(spec: DevAgentSpec, *, redis_url: str,
                     max_concurrent: int, stream_ttl_seconds: int,
                     config_getter: ConfigGetter = ...,
                     ) -> Tuple[DevLoopCodeDispatcher, BaseModel]:       # line 102
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `sdd_meta.resolve_flow()` | `FlowMeta._hotfix_implies_main` | model validation | `scripts/sdd/sdd_meta.py:35` |
| `ResearchNode` base read-back | `sdd_meta.parse()` | function call | `scripts/sdd/sdd_meta.py:45` |
| `ResearchOutput.base_branch` | `DeploymentHandoffNode._create_pr` | attribute read | `nodes/deployment_handoff.py:332` |
| `assert_base_is_clean` | `git rev-list --count … --not …` | subprocess, same shape as `_push_branch` | `nodes/deployment_handoff.py:296` |
| hotfix identity fallback | `research.jira_issue_key or research.feat_id` | existing precedent | `nodes/qa.py:194,342` |
| `_execute_single(pool_cfg=…)` | `build_dispatcher(spec, …)` | callable via `self._dispatcher_builder` | `agent_builder.py:102` |
| single-path `WorkerSummary` | `DevelopmentOutput.worker_summaries` | list append | `models/base.py:490` |

### Does NOT Exist (Anti-Hallucination)

- ~~`ResearchOutput.base_branch`~~ — no `base_branch` field anywhere in
  `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` today
  (verified: `grep -rn "base_branch" models/base.py` → no matches).
- ~~`sdd_meta.resolve_flow()`~~ / ~~`sdd_meta.resolve()`~~ — `sdd_meta.py`
  exposes only `FlowMeta`, `parse`, `emit`, `KNOWN_BRANCHES`.
- ~~`DevelopmentOutput.requested_agent`~~ / ~~`.actual_agent`~~ — no
  requested/actual backend fields exist anywhere under `flows/dev_loop/`.
- ~~`/sdd-spec --type` / `--base-branch`~~ — the command's usage line is
  `/sdd-spec <feature-name> [-- free-form description and notes]` only
  (`.claude/commands/sdd-spec.md:6`).
- ~~`WorkBrief.flow_type`~~ / ~~`WorkBrief.base_branch`~~ — the brief carries
  `kind`, `dev_agents`, `dev_isolation`, but no flow-type or base-branch field.
- ~~`sdd_meta.parse(missing_path)` returning a default~~ — it raises
  `FileNotFoundError`; the "default to feature/dev when no exploration doc
  exists" behaviour described at `.claude/commands/sdd-spec.md:131` has no
  implementation.
- ~~a `hotfix` code path in `flows/`~~ — `grep -rni "hotfix" --include=*.py
  packages/` matches only a test string in
  `tests/bots/test_github_reviewer.py:103`.
- ~~`hotfix-<JIRA-KEY>-<slug>` branch naming~~ — every current path hardcodes
  `feat-<id>-<slug>` (`.claude/agents/sdd-research.md:8,68-69,81,94`), which
  presupposes a reserved id.
- ~~`assert_base_is_clean` / `BaseBranchMismatch`~~ — no base-branch
  validation of any kind exists in either handoff node today.
- ~~a `--ledger-branch` flag on `reserve_ids.py`~~ — the CLI accepts only
  `--kind`, `--count`, `--base-branch`, `--label`, `--max-retries`
  (`scripts/sdd/reserve_ids.py:305-310`).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- `DevLoopNode` subclasses are frozen — mutate internals with
  `object.__setattr__`, exactly as `deployment_handoff.py:93` does.
- Degradation must be **loud**: every fallback logs at WARNING naming what was
  requested and what was used, mirroring `development.py:193`'s existing shape.
- Blocking follows the established contract: return
  `{"status": "blocked", "error": …}` and call `_mark_blocked(issue_key, …)`
  first, as the push/PR failure paths already do.
- New git plumbing uses the same async subprocess helper shape as
  `_push_branch` (`deployment_handoff.py:296`) — no blocking I/O.
- Google-style docstrings and strict type hints on everything new.

### Known Risks / Gotchas

- **An ancestry check is not sufficient — do not "simplify" the guard to one.**
  Measured against the real SHAs:
  `git merge-base --is-ancestor 5370f9256 43ba79e93` (old `main` vs the
  `feat-465` tip) returns **true**. Because `main` was an ancestor of `dev`, a
  branch cut from `dev` still descends from `origin/main`, so `--is-ancestor`
  alone would have waved PR #1250 through. The sibling-overlap comparison is
  the check that actually discriminates (93 adds vs 0 own commits).
- **`feat_id == ""` must be honoured by every consumer.** Module 2 makes it the
  normal case for hotfixes. The audited consumers are listed in §6; a missed
  one produces labels like `": fix the thing"` or a task-index lookup on an
  empty slug. `runner.py:1378` already constructs this shape, so it is
  reachable today — but it has never been the *primary* path before.
- **Cross-branch id-ledger collisions remain possible** (out of scope, §1).
  The ledger's compare-and-swap protects one branch at a time, so two runs
  reserving against *different* base branches can still be handed the same
  `FEAT-<NNN>`. This feature reduces the exposure to zero for hotfixes (they
  reserve nothing) but does not fix it for two concurrent feature runs on
  different bases. Mitigation for now: reserve only against `dev`.
- **The guard needs fetched refs.** `origin/<base>` and every sibling ref must
  be fetched inside the guard, or the verdict is computed against a stale
  remote-tracking ref.
- **Sibling set must come from `KNOWN_BRANCHES`, filtered to existing refs.**
  `sdd_meta.KNOWN_BRANCHES` is `{"main", "staging", "dev"}`
  (`scripts/sdd/sdd_meta.py:26`); `staging` may not exist on the remote, and
  passing a missing ref to `rev-list --not` fails the whole command.
- **A merged-while-open branch can false-positive.** If a hotfix branch's own
  commits are *merged* (not cherry-picked) into a sibling while its PR is
  open, they become sibling commits by SHA and the guard blocks. Cherry-picks
  are safe (new SHAs). Judged acceptable — that shape warrants a human look.
- **Do not disturb the legacy single-agent path.** `_execute_single` with no
  pool config must stay byte-identical — it is the path every existing run
  takes.
- **`main` currently equals `dev`.** Until they diverge again, a hotfix cut
  from `main` and one cut from `dev` produce the same tree, so the integration
  tests must assert on the *resolved base value*, not on diff contents.
- **`DevLoopNode` subclasses are frozen.** Mutate internals with
  `object.__setattr__`, as `deployment_handoff.py:93` does.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | No new dependencies; `pyyaml` and `pydantic` are already in use |

---

## 8. Open Questions

> All questions are resolved; this spec is approved.

- [x] What should happen when the branch does not match its resolved base? —
      *Resolved 2026-08-27*: **Block the run.** Both handoff nodes return
      `status="blocked"` with a clear error before `gh pr create`. No git
      surgery; a human re-cuts the branch. Auto-recut was rejected as too
      failure-prone; warn-and-proceed was rejected because it leaves the
      #1250 door open.
- [x] Should `kind="bug"` always mean `hotfix`/`main`? — *Resolved
      2026-08-27*: **Operator can choose.** `kind="bug"` *defaults* to
      `hotfix`/`main`, and the console exposes an explicit flow-type /
      base-branch control that overrides it. PR #1250 (a SHA-1 → SHA-256
      hardening fix) arguably never needed to be a hotfix.
- [x] Should the merge of PR #1250 into `main` be reverted? — *Resolved
      2026-08-27*: **No.** Accept the current state of `main`; this spec only
      prevents recurrence. Recorded in §1 as the motivating incident.
- [x] What exactly should the guard assert, and what is the commit-count cap? —
      *Resolved 2026-08-27*: **Sibling-overlap, exact — and therefore no cap.**
      Block when `rev-list origin/<base>..<branch>` differs from
      `rev-list origin/<base>..<branch> --not origin/<sibling>...`. This is
      deterministic and needs no threshold, so the cap question dissolves.
      Empirical grounding: an ancestry check returns *true* for the #1250
      shape (see §7), while the sibling comparison yields 93 vs 0. For
      reference, the last 25 PRs merged into `dev` carried 1–36 commits;
      #1250 carried 93.
- [x] How does a hotfix run reserve its `FEAT`/`TASK` ids given
      `reserve_ids.py`'s "current branch must equal `--base-branch`"
      constraint? — *Resolved 2026-08-27*: **It doesn't — a bugfix is not a
      feature and reserves no id.** Ledger ids exist for features and the
      brainstorm/spec/task SDD flow. A hotfix is identified by its Jira issue
      key, is named `hotfix-<JIRA-KEY>-<slug>`, and carries `feat_id == ""`
      (already a supported shape, `runner.py:1378`). The allocator is
      therefore never called on the hotfix path and needs no change — which
      supersedes the earlier direction to relax `reserve_ids.py` itself.
- [x] Should `FeatureHandoffNode` get the guard in this feature? — *Resolved
      2026-08-27*: **Yes, include it now.** It carries the same defect
      (hardcoded `base_branch="dev"` at `feature_handoff.py:101`, never given
      an override by `factories.py:244`, no recorded source of truth). Both
      nodes call one shared helper in `nodes/base.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-27 | Jesus Lara | Initial draft — Problems A (base branch) and B (dev-agent selection) |
| 0.2 | 2026-08-27 | Jesus Lara | Resolved all open questions; guard changed from `--is-ancestor` to exact sibling-overlap (ancestry proven blind to the #1250 shape); hotfix path reserves no ids (Jira-keyed identity) instead of relaxing the allocator; guard extended to `FeatureHandoffNode`; status → approved |
