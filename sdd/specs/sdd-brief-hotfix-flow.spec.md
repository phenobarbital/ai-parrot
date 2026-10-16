---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, dev-loop]
tags: [sdd, workflow, hotfix, ledger, commands]
---

# Feature Specification: /sdd-brief — One-Command Brief Flow for Hotfixes and Single-Issue Fixes

**Feature ID**: FEAT-698
**Date**: 2026-10-17
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

The full SDD pipeline (`/sdd-brainstorm → /sdd-spec → /sdd-task`) is sized for
features. A hotfix — e.g. repairing a GitHub code-scanning alert — does not
need three documents and two id reservations; it needs **direct research, a
short Q&A for the genuinely open decisions, one actionable document, and a
worktree based on the right branch**.

Today that need is partially served by `/sdd-spec --type hotfix` (FEAT-466):
no FEAT/TASK id reservation, identity = Jira key or slug, worktree
`hotfix-<KEY>-<slug>` from `origin/main`, `/sdd-task` normally skipped. But it
is still spec-shaped (interview-first, feature-document template) rather than
research-first, and `/sdd-done` refuses to open the PR against `main`, leaving
a manual step.

`/sdd-brief` **replaces `/sdd-spec --type hotfix`** (hard cut — the dev-loop
autonomous hotfix lane migrates in this same feature) with a purpose-built
command: research-first intake from several source kinds (including the work
ledger), bounded Q&A, a single fused spec+task document (the *brief*), and a
worktree whose base branch drives everything downstream.

### Goals

- One command from "here is a bug/alert/issue" to "worktree ready with an
  actionable brief inside it".
- Research-first: fetch the source artifact, locate the code (wiki symbol
  lookup / blast radius), pull `ledger context`, and establish root cause
  **before** asking the user anything.
- Bounded Q&A: ≤5 questions, only for decisions research could not settle;
  `--no-interview` skips it and records assumptions.
- A brief an implementer (human, `sdd-worker`, or `sdd-coder`) can execute
  without reading anything else — via **materialized standard task files**.
- `/sdd-done` opens the PR itself in every flow, targeting the flow's
  `base_branch` (`main` included); direct merge into `main` stays forbidden.
- The dev-loop autonomous hotfix lane (sdd-research + DevelopmentNode paths)
  runs on briefs; `/sdd-spec --type hotfix` is removed outright.

### Non-Goals (explicitly out of scope)

- Replacing `/sdd-fix` as the ledger **drain** command (`/sdd-brief
  issue:<id>` is the deep-research alternative for a single issue).
- Any change to the feature flow (`/sdd-brainstorm`, feature `/sdd-spec`,
  `/sdd-task`, `/sdd-start`).
- Any change to sync-down automation (`.github/workflows/sync-down.yml`,
  `/sdd-done --sync-down`).
- New id kinds in `sdd/tasks/.id_ledger.json`; any change to `FlowMeta` or
  anything else in the wikitoolkit wheel
  (`parrot/knowledge/wiki/ledger/sdd_meta.py`).
- Teaching `/sdd-status` / `/sdd-next` to ingest briefs (in-flight briefs are
  visible via the FEAT-582 worktree panel).

**Anti-goals** (failure even if it "works"): any path that pushes to or
merges into `main` directly; committing the brief in the shared main
checkout; reintroducing FEAT/TASK id reservation on the hotfix path; a
"quick" flow that silently skips research (see S9 research floor, §3 M1).

---

## 2. Architectural Design

### Overview

`/sdd-brief <source>` auto-detects the source kind, researches it, interviews
the user only on genuinely open decisions, then provisions the worktree and
writes everything **inside it**: the brief document
(`sdd/briefs/<slug>.brief.md`), materialized standard task files
(`sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-N-<task-slug>.md`), and a per-brief
index (`sdd/briefs/<slug>.index.json`).

Briefs **bypass `FlowMeta` / `resolve_flow()` entirely** — they are a new
document kind (`kind: brief`) parsed by a repo-local helper
(`scripts/sdd/brief_meta.py`), never a third value in `FlowMeta.type`
(which ships in the wikitoolkit wheel; a change there would force a
wikitoolkit release and break the `hotfix ⇒ main` validator for dev-based
ledger briefs).

Base-branch resolution (binding, from the brainstorm):

| Source | Default base | Overridable? |
|---|---|---|
| Ledger issue id (`issue:<hex>` / bare hex) | `dev` | **No** — `--base-branch main` with a ledger source is refused |
| Code-scanning alert, GitHub issue/PR, Jira key, text, file | `main` | Yes (`--base-branch dev\|staging`) |

Identity: Jira key when one exists; the ledger short id for ledger sources;
otherwise the slug. That `<KEY>` names the worktree
(`hotfix-<KEY>-<slug>` on `main`, `fix-<KEY>-<slug>` on `dev`/`staging`),
the task ids (`HOTFIX-<KEY>-N`), and the index identity
(`feature_id: "BRIEF-<KEY>"` — non-empty for every index consumer, never
matching `^FEAT-\d+$`, so no id-ledger collision and no feature-board
ingestion; S2).

Task materialization is what keeps Decision 5 ("downstream unchanged") true:
`sdd-worker`'s planner, the `parrot-sdd-coder` MCP chunker and fidelity gate,
and manual `/sdd-start`-style implementation all consume the exact
`sdd/templates/task.md` shape they consume today.

`/sdd-done` gains a **separate brief lane** (S4): resolve by slug/KEY via
worktree scan → verify via the per-brief index + the brief's Validation
Commands → push → `gh pr create --base "$BASE_BRANCH"` (fail-closed, S5) →
in-place task closure (no `active/ → completed/` move, no `close_task.sh`).
The FEAT-187 policy wording changes from "never opens a PR against main" to
"never **merges** into main; opens the PR" — the merge of a main PR remains
the only human act.

Rejected in brainstorm: keeping the autonomous dev-loop lane on an
internal-only `/sdd-spec --type hotfix` (phased cut) — the user chose the
hard cut in one feature.

### Component Diagram

```
/sdd-brief <source>
   │  detect: cs:NNN | gh-issue | JIRA-KEY | issue:<hex> | text/file
   ├─ Research (gh api / jira / wikitoolkit ledger show+plan-fix+claim,
   │            wiki symbol lookup, blast radius, ledger context)
   ├─ Q&A (≤5, --no-interview ⇒ Assumptions)
   ├─ scripts/sdd/brief_meta.py ──→ WorktreePlan (hotfix-/fix-)
   │            │                        │
   │            │                scripts/sdd/ensure_worktree.py
   │            │                 (+ unset-upstream, S6)
   │            ▼                        ▼
   └─ writes INSIDE worktree: sdd/briefs/<slug>.brief.md
                              sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-N-*.md
                              sdd/briefs/<slug>.index.json (BRIEF-<KEY>)
                                         │
             sdd-worker / parrot-sdd-coder / dev-loop DevelopmentNode
             (TaskScheduler ← ResearchOutput.index_path, S3)
                                         │
             /sdd-done <slug>  ── verify ─ push ─ gh pr create --base <base>
                                   (--merge refused for main; ledger close
                                    only after merge confirmation, S7)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `scripts/sdd/ensure_worktree.py` `ensure()` | uses + extends | new `--brief` input; unset-upstream + verify after create (S6) |
| `scripts.sdd.sdd_meta.WorktreePlan` | constructs | `brief_meta.plan_brief_worktree()` builds the plan directly; `plan_worktree()` and `FlowMeta` untouched |
| `wikitoolkit ledger` (`show`/`plan-fix`/`claim`/`close`) | uses | ledger source intake + transactional claim lifecycle (S7) |
| `TaskScheduler` (`dev_loop/task_scheduler.py`) | extends | `from_index_path()` so briefs schedule from `sdd/briefs/<slug>.index.json` (S3) |
| `DevelopmentNode` (`dev_loop/nodes/development.py`) | modifies | explicit index resolution before the `feat_id` scan (S3) |
| `ResearchOutput` (`dev_loop/models/base.py`) | extends | optional `index_path` field (S3) |
| `parrot-sdd-coder` checkpoint/engine | unchanged | satisfied by non-empty `feature_id: "BRIEF-<KEY>"` (S2) |
| `/sdd-done`, `/sdd-spec`, CLAUDE.md, WORKFLOW.md | modifies | brief lane, hotfix-path removal, FEAT-187 rewording |

### Data Models

```python
# scripts/sdd/brief_meta.py (CREATE — repo-local, NOT in the wikitoolkit wheel)
class BriefSource(BaseModel):
    type: Literal["code-scanning", "github-issue", "jira", "ledger", "text", "file"]
    ref: str                      # "224", "NAV-123", "issue:<hex>", path, …
    url: str | None = None

class BriefMeta(BaseModel):
    kind: Literal["brief"]
    slug: str
    key: str                      # Jira key | ledger short id | slug
    base_branch: str              # main (default) | dev | staging
    source: BriefSource
    jira_issue_key: str | None = None
    ledger_issue: str | None = None   # "issue:<hex>" once claimed (S7)
    created: str                  # ISO-8601
    # validator: source.type == "ledger" ⇒ base_branch == "dev"
```

Per-brief index — same schema as the per-spec index (FEAT-145), header
differences only: `feature_id: "BRIEF-<KEY>"`, `feature: <slug>`,
`spec: sdd/briefs/<slug>.brief.md`, `type: "brief"`, `base_branch` from the
brief; `tasks[].id` are `HOTFIX-<KEY>-N`, `tasks[].file` point at the
materialized task files.

### New Public Interfaces

```python
# scripts/sdd/brief_meta.py
def parse_brief(doc_path: Path) -> BriefMeta: ...
def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan: ...
def write_brief_index(meta: BriefMeta, tasks: list[BriefTask], worktree_root: Path) -> Path: ...
```

New user-facing command: `/sdd-brief <source> [--base-branch main|dev|staging]
[--no-interview] [--split] [--research full|light]`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: /sdd-brief command | no | — | interview wording and procedure authoring need judgment |
| M2: brief_meta + worktree plumbing | yes | signatures above; naming `hotfix-<KEY>-<slug>` / `fix-<KEY>-<slug>`; `BRIEF-<KEY>` identity; unset-upstream after create | |
| M3: /sdd-done brief lane + policy | no | — | policy wording touches a non-negotiable rule; needs care |
| M4: /sdd-spec hotfix removal | yes | delete the FEAT-466 hotfix branches; error pointer to /sdd-brief | |
| M5: dev-loop migration | yes | `index_path` field; `from_index_path`; twin prompt edit is a fixed substitution | |
| M6: tests + docs sweep | yes | test list in §4; grep inventory in M6 scope | |

### Module 1: `/sdd-brief` command + brief template
- **Path**: `.claude/commands/sdd-brief.md` (CREATE), `sdd/templates/brief.md`
  (CREATE — `.gitignore` has a global `templates/` rule: `git add -f`),
  codex twin `.agents/skills/sdd-brief/` (CREATE, mirror of the
  `.agents/skills/sdd-spec` layout).
- **Responsibility**: source detection and fetch (code-scanning via
  `gh api repos/{owner}/{repo}/code-scanning/alerts/{n}`; GitHub issue/PR via
  `gh`; Jira via jiratoolkit; ledger via `wikitoolkit ledger show` +
  `plan-fix` + `claim`), research, bounded Q&A, then (inside the worktree M2
  provisions) writing the brief, the materialized task files, and the index,
  and committing them. Ledger claim lifecycle is transactional (S7): claim at
  research start, persist in `ledger_issue`, release (or print the release
  command) on abort in any pre-worktree phase. **Research floor (S9)**: every
  mode including `--research light` must record a fetched/identified source,
  a root-cause statement, and ≥1 verified `path:line` anchor — otherwise the
  command refuses to create the worktree.
- **Depends on**: Module 2.
- **Interface Skeleton** (command contract — this is a procedure doc, not Python):
  ```
  /sdd-brief <source> [--base-branch main|dev|staging] [--no-interview]
             [--split] [--research full|light]
  # ledger source + --base-branch main  -> hard refusal
  # output: worktree path, brief path, task file list, next-step handoff
  # (claude --agent sdd-worker inside the worktree, or manual /sdd-start-style)
  ```

### Module 2: Brief metadata & worktree plumbing
- **Path**: `scripts/sdd/brief_meta.py` (CREATE),
  `scripts/sdd/ensure_worktree.py` (MODIFY).
- **Responsibility**: `BriefMeta`/`BriefSource` parsing and emission;
  `plan_brief_worktree()` building a `WorktreePlan` directly —
  `hotfix-<KEY>-<slug>` / base `origin/main`, or `fix-<KEY>-<slug>` / base
  `origin/dev|staging` (S1; the fast lane's `fix/<id>-<slug>` branch
  namespace is untouched and worktree-less); `write_brief_index()` with
  `feature_id: "BRIEF-<KEY>"` (S2). `ensure_worktree`: accept `--brief
  <brief.md|planned-meta>` and, for EVERY created worktree, run
  `git branch --unset-upstream` and assert `@{upstream}` is absent before
  returning (S6).
- **Depends on**: `scripts.sdd.sdd_meta` (read-only reuse of
  `WorktreePlan`, `WORKTREE_ROOT`).
- **Interface Skeleton**:
  ```python
  # scripts/sdd/brief_meta.py (new)
  class BriefSource(BaseModel): ...          # see §2 Data Models
  class BriefMeta(BaseModel): ...            # validator: ledger ⇒ base_branch == "dev"

  def parse_brief(doc_path: Path) -> BriefMeta:
      """Parse a brief's frontmatter; raises ValidationError on bad shape."""

  def plan_brief_worktree(meta: BriefMeta) -> WorktreePlan:  # WorktreePlan verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:328
      """hotfix-<KEY>-<slug> for main, fix-<KEY>-<slug> otherwise; base_ref=origin/<base_branch>."""

  def write_brief_index(meta: BriefMeta, tasks: list[dict], worktree_root: Path) -> Path:
      """Write sdd/briefs/<slug>.index.json (feature_id='BRIEF-<KEY>'); returns the path."""

  # scripts/sdd/ensure_worktree.py (modifies ensure(), main())
  def ensure(plan, *, repo_root, sync=True, require_paths=(), dry_run=False) -> tuple[Path, bool]:
      """Unchanged signature. After _create_worktree (verified: scripts/sdd/ensure_worktree.py:110):
      unset the auto-upstream and assert `git rev-parse @{upstream}` fails for the new branch."""
  ```

### Module 3: `/sdd-done` brief lane + PR policy change
- **Path**: `.claude/commands/sdd-done.md` (MODIFY), `CLAUDE.md` (MODIFY),
  `docs/sdd/WORKFLOW.md` (MODIFY), `sdd/WORKFLOW.md` (MODIFY),
  `.claude/rules/worktree-management.md` (MODIFY, §5 Finish),
  `.agents/skills/sdd-done/` twin (MODIFY).
- **Responsibility**: a **dedicated brief resolution/verification lane** (S4):
  resolve `<slug|KEY>` by scanning `$WORKTREES_DIR` for `hotfix-*`/`fix-*`
  entries (the feature lane's `sdd/tasks/index/*.json` glob never sees
  briefs); verify via `sdd/briefs/<slug>.index.json` task states + the
  brief's Validation Commands; in-place closure (Completion Note in the task
  file, status flip in the index — no `close_task.sh`); skip the
  ledger-snapshot step exactly as `TYPE == hotfix` does today. **PR policy
  (S5)**: in every lane `/sdd-done` pushes the branch and runs `gh pr create
  --base "$BASE_BRANCH" --head "$BRANCH"` itself (never the hardcoded
  `feat-<FEAT-ID>-<slug>` name), prints the PR URL, and retains the
  worktree/branch when PR creation fails; `--merge` is rejected **before any
  push** when the resolved base is `main`. Ledger close (S7): only after
  merge confirmation (`--merge` on a dev-based brief, or `--sync-down` time
  for a main-based one); when only the PR was opened, print the exact
  `wikitoolkit ledger close <id> --resolved-by …` command next to the URL.
  Policy wording: CLAUDE.md:159 and WORKFLOW.md "never pushes to or opens a
  PR against `main`" become "never **merges** into `main`; opens the PR —
  merging the main PR is the human act".
- **Depends on**: Module 2 (index shape, worktree naming).

### Module 4: `/sdd-spec` hotfix-path removal
- **Path**: `.claude/commands/sdd-spec.md` (MODIFY),
  `.agent/workflows/sdd-spec.md` (MODIFY), `.agents/skills/sdd-spec/`
  (MODIFY), `docs/sdd/CODEX.md` (MODIFY).
- **Responsibility**: remove `--type hotfix` from the usage line and the
  FEAT-466 branches (§2d hotfix validation text, §5 "SKIP ENTIRELY when
  TYPE == hotfix" block, §7 hotfix output block); an explicit
  `--type hotfix` now aborts with a pointer to `/sdd-brief`. `resolve_flow()`
  / `FlowMeta` stay untouched — `type: hotfix` frontmatter on LEGACY specs
  still parses (historical artifacts in `sdd/specs/` are not rewritten);
  only the command surface refuses to scaffold new ones.
- **Depends on**: Module 1 (the replacement must exist first).

### Module 5: Dev-loop autonomous lane migration
- **Path**: `.claude/agents/sdd-research.md`,
  `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md`,
  `.agents/agents/sdd-research/agent.md`, `.agent/agents/sdd-research/agent.md`
  (all four twins MODIFY — the `_subagent_data` copy may need `git add -f`);
  `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` (MODIFY);
  `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` (MODIFY);
  `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` (MODIFY).
- **Responsibility**: twins replace the literal
  `/sdd-spec <slug> --type hotfix --base-branch main --no-interview`
  invocation (kind == "bug") with `/sdd-brief <source> --no-interview`
  (+ `--base-branch` from the brief's override fields, which keep their
  current precedence; a `kind=="bug"` brief overridden to `flow_type:
  "feature"` keeps going down the feature path unchanged). `ResearchOutput`
  gains `index_path: Optional[str]` (S3); `TaskScheduler.from_index_path()`
  loads a scheduler from an explicit index file; `DevelopmentNode.
  _build_scheduler` tries `research.index_path` first and only then the
  legacy `feat_id` scan — so a `--split` brief pools and a single-task brief
  degrades to the single-agent path exactly as today. `DevRequestBrief` /
  `WorkBrief` keep their shape (their `flow_type`/`base_branch` override
  fields already express everything a brief run needs); the
  `hotfix ⇒ main` validator in `dev_flow/models.py` stays — it governs the
  flow_type override, not briefs.
- **Depends on**: Modules 1 and 2.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py  (modifies ResearchOutput, verified :347)
  class ResearchOutput(BaseModel):
      index_path: Optional[str] = Field(
          default=None,
          description="Explicit per-brief index path inside the worktree (sdd/briefs/<slug>.index.json); None ⇒ legacy per-spec index scan.",
      )

  # packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py  (modifies, verified :201)
  @classmethod
  def from_index_path(cls, worktree_path: str, index_path: str) -> Optional["TaskScheduler"]:
      """Build a scheduler from an explicit index file (repo-relative to the worktree)."""

  # packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py  (modifies _build_scheduler, verified :1344)
  async def _build_scheduler(self, research: ResearchOutput) -> Optional[TaskScheduler]:
      """research.index_path first (S3); fall back to _find_feature_slug scan; None ⇒ single-agent."""
  ```

### Module 6: Tests, docs and reference sweep
- **Path**: tests in §4; `docs/sdd/WORKFLOW.md`, `sdd/WORKFLOW.md`,
  `docs/sdd/CODEX.md`, `CLAUDE.md` cross-references.
- **Responsibility**: migrate the hotfix-mode tests to the brief shape (S8);
  final sweep — `grep -rn -- "--type hotfix"` across `.claude/`, `.agents/`,
  `.agent/`, `scripts/`, `packages/*/src/parrot/flows/`, `docs/`,
  `sdd/templates/` must return nothing outside historical `sdd/`
  artifacts and `ensure_worktree.py`'s generic `--type` CLI choice (which
  stays: `plan_worktree` still names legacy hotfix worktrees).
- **Depends on**: Modules 3, 4, 5.

---

## 4. Test Specification

### Unit Tests

- `packages/ai-parrot/tests/sdd_scripts/test_brief_meta.py` (NEW — follow the
  existing scripts-test layout): `parse_brief` happy/invalid; ledger ⇒ dev
  validator; `plan_brief_worktree` naming for main/dev; `write_brief_index`
  header (`feature_id == "BRIEF-<KEY>"`, task file pointers).
- `ensure_worktree`: new-worktree branch has **no upstream** after `ensure()`
  (S6), including the reuse path (reused worktrees are not re-mutated).
- `test_empty_feat_id.py` (MODIFY, S8): keeps the guard that `feat_id == ""`
  + no `index_path` ⇒ no scheduler; ADDS `index_path`-set ⇒ scheduler built
  from `sdd/briefs/<slug>.index.json`.
- `test_development_node.py` (MODIFY): single-task brief degrades to
  `_execute_single`; `--split` brief with 2+ tasks pools.
- `test_flow_type_override.py` / `test_research_base_branch.py` (MODIFY):
  re-point the `kind=="bug"` expectations from the `/sdd-spec --type hotfix`
  contract to the `/sdd-brief` contract (base `main`, no FEAT id,
  `index_path` carried).
- `task_scheduler`: `from_index_path` loads HOTFIX-* ids; missing/corrupt
  index returns None.

### Integration Tests

- sdd_coder checkpoint round-trip over a brief index: header with
  `feature_id: "BRIEF-<KEY>"` passes `checkpoint.py` validation (S2) and
  binds executions correctly.
- End-to-end dry run of the brief scaffold: brief + tasks + index written in
  a temp worktree, `parse_brief` → `plan_brief_worktree` → `ensure(dry_run)`.

### Test Data / Fixtures

```
fixture: minimal brief dir (brief.md + 2 task files + index.json, BRIEF-key)
fixture: fake gh code-scanning alert JSON (rule, most_recent_instance.location)
```

(No E2E-gate surface — the `e2e` frontmatter key is intentionally absent.)

---

## 5. Acceptance Criteria

- [ ] `/sdd-brief` from a code-scanning alert produces a
  `hotfix-<KEY>-<slug>` worktree from `origin/main` containing a committed
  brief, ≥1 materialized task file in `sdd/templates/task.md` shape, and
  `sdd/briefs/<slug>.index.json` — with `sdd/tasks/.id_ledger.json` untouched.
- [ ] `/sdd-brief issue:<id>` claims the ledger issue, bases on `dev`
  (`fix-<id>-<slug>`), and refuses an explicit `--base-branch main`.
- [ ] The per-brief index header carries non-empty
  `feature_id: "BRIEF-<KEY>"` and passes sdd_coder checkpoint validation (S2).
- [ ] Research floor (S9): in every research mode the brief records source,
  root cause, and ≥1 verified `path:line` anchor, or no worktree is created.
- [ ] New worktrees come out of `ensure()` with no upstream configured (S6).
- [ ] `/sdd-done <slug|KEY>` on a brief verifies via the per-brief index +
  Validation Commands, pushes, and opens the PR itself against the brief's
  `base_branch` — `main` included; `--merge` on a main-based brief is
  rejected before any push; worktree/branch are retained if `gh pr create`
  fails (S5).
- [ ] Ledger close runs only after merge confirmation; a PR-only finish
  prints the exact `ledger close` command (S7).
- [ ] `/sdd-spec --type hotfix` aborts with a pointer to `/sdd-brief`; the
  FEAT-466 hotfix blocks are gone from the command docs; legacy
  `type: hotfix` specs still parse (FlowMeta untouched).
- [ ] All four sdd-research twins invoke `/sdd-brief` for `kind == "bug"`;
  the M6 sweep grep comes back clean.
- [ ] A `--split` brief dispatches the dev-loop pool via
  `ResearchOutput.index_path`; a single-task brief runs the single-agent
  path (S3).
- [ ] `git diff` of the feature touches nothing under
  `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/` (wheel boundary).
- [ ] All tests in §4 pass; `ruff check` clean on touched Python.

---

## 6. Codebase Contract

### Verified Imports

```python
from scripts.sdd.sdd_meta import FlowMeta, WorktreePlan, plan_worktree, resolve_flow  # verified: scripts/sdd/sdd_meta.py:10-26 (shim re-export)
from scripts.sdd.ensure_worktree import EnsureWorktreeError, ensure  # verified: scripts/sdd/ensure_worktree.py:25,48
from parrot.flows.dev_loop.task_scheduler import TaskScheduler  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py:201 (from_worktree)
from parrot.flows.dev_loop.models.base import ResearchOutput, WorkBrief  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py:347,229-240
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py — WHEEL-SHIPPED, DO NOT MODIFY
class FlowMeta(BaseModel):                       # line 99
    type: Literal["feature", "hotfix"]           # line 102
    base_branch: str                             # line 103
    # _hotfix_implies_main validator             # lines 105-109
class WorktreePlan(BaseModel):                   # line 328
    name: str; path: str; base_ref: str          # lines 331-333
def plan_worktree(meta, *, slug, feature_id=None, jira_key=None) -> WorktreePlan  # line 336
WORKTREE_ROOT: str = ".claude/worktrees"         # line 322

# scripts/sdd/ensure_worktree.py
def ensure(plan, *, repo_root, sync=True, require_paths=(), dry_run=False) -> tuple[Path, bool]  # line 48
def _create_worktree(plan, target_path, *, repo_root) -> None  # line 189 — add unset-upstream AFTER its call site (line 110)
# CLI main(): --slug --feature-id --jira-key --spec --index --base-branch --type --no-sync --dry-run --json  # lines 233-247

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py
@staticmethod
def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]  # line 1309; feat_id=="" early-None at 1323-1329
async def _build_scheduler(self, research: ResearchOutput) -> Optional[TaskScheduler]  # line 1344; scans via _find_feature_slug at 1362

# packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py
@classmethod
def from_worktree(cls, worktree_path: str, feature_slug: str) -> Optional["TaskScheduler"]  # line 201

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/checkpoint.py
# index header validation requires non-empty feature_id/base_branch/spec  # lines 462-466

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py
# ExecutionPoolView.feature_id / snapshot feature_id: Field(..., min_length=1)  # lines 473,505
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `plan_brief_worktree()` | `WorktreePlan` | direct construction | `sdd_meta.py:328-333` |
| `/sdd-brief` worktree step | `ensure()` | CLI `python -m scripts.sdd.ensure_worktree --brief …` | `ensure_worktree.py:48,225` |
| per-brief index | sdd_coder checkpoint | non-empty `feature_id` header | `checkpoint.py:462-466` |
| `DevelopmentNode._build_scheduler` | `TaskScheduler.from_index_path` | `research.index_path` | `development.py:1344-1365` |
| sdd-research twins | `/sdd-brief` | prompt invocation (kind == "bug") | `.claude/agents/sdd-research.md:75` |

### Does NOT Exist (Anti-Hallucination)

- ~~`scripts/sdd/brief_meta.py`~~ — created by M2.
- ~~`sdd/briefs/`~~ — directory does not exist yet (born inside worktrees).
- ~~`/sdd-brief` command, `.claude/commands/sdd-brief.md`, `sdd/templates/brief.md`~~ — created by M1.
- ~~`FlowMeta.type == "brief"`~~ — must NEVER exist; `plan_worktree()` raises `ValueError` for any type beyond feature/hotfix (sdd_meta.py:384-385).
- ~~`ResearchOutput.index_path`~~ / ~~`TaskScheduler.from_index_path`~~ — created by M5.
- ~~any `--unset-upstream` call in `ensure_worktree.py`~~ — S6 adds it; today a bare `git push` from a fresh worktree targets the base branch.
- ~~`close_task.sh` support for briefs~~ — briefs never use it (in-place closure).
- ~~a WorkBrief/DevRequestBrief `kind == "brief"`~~ — brief runs still enter as `kind == "bug"`; only the scaffolding command changes.

### Edit Sites (Blueprint Anchors)

Verified against: `8c47f58e4`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `.claude/commands/sdd-brief.md` | CREATE | — | — | — |
| `sdd/templates/brief.md` | CREATE (`git add -f`) | — | — | — |
| `scripts/sdd/brief_meta.py` | CREATE | — | — | — |
| `.agents/skills/sdd-brief/` | CREATE | — | — | — |
| `scripts/sdd/ensure_worktree.py` | MODIFY | `    _create_worktree(plan, target_path, repo_root=repo_root)` | `ensure_worktree.py:110` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `> **CRITICAL — \`/sdd-done\` NEVER pushes to \`main\` and NEVER opens a PR against \`main\` (FEAT-145).**` | `sdd-done.md:46` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `**Hard refusal — \`BASE_BRANCH == "main"\`:**` | `sdd-done.md:548` | 1 |
| `.claude/commands/sdd-spec.md` | MODIFY | `**\`TYPE == "hotfix"\` (FEAT-466 — no id reserved):**` | `sdd-spec.md:718` | 1 |
| `CLAUDE.md` | MODIFY | `**\`/sdd-done\` NEVER pushes to or opens a PR against \`main\`** —` | `CLAUDE.md:159` | 1 |
| `docs/sdd/WORKFLOW.md` | MODIFY | `` (`--merge` merges directly). It never pushes to or opens a PR against `main`. `` | `WORKFLOW.md:89` | 1 |
| `.claude/agents/sdd-research.md` | MODIFY | `/sdd-spec <slug> --type hotfix --base-branch main --no-interview       # kind == "bug"` | `sdd-research.md:75` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/sdd-research.md` | MODIFY | same anchor as above | `sdd-research.md:75` | 1 |
| `.agents/agents/sdd-research/agent.md` | MODIFY | `(unverified — check before use)` — re-grep `--type hotfix` | — | — |
| `.agent/agents/sdd-research/agent.md` | MODIFY | `(unverified — check before use)` — re-grep `--type hotfix` | — | — |
| `.agent/workflows/sdd-spec.md` | MODIFY | `(unverified — check before use)` — re-grep `--type hotfix` | — | — |
| `docs/sdd/CODEX.md` | MODIFY | `(unverified — check before use)` — re-grep `--type hotfix` | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py` | MODIFY | `    flow_type: Optional[Literal["feature", "hotfix"]] = Field(` | `base.py:229` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/development.py` | MODIFY | `    def _find_feature_slug(worktree_path: str, feat_id: str) -> Optional[str]:` | `development.py:1309` | 1 |
| `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py` | MODIFY | `    def from_worktree(cls, worktree_path: str, feature_slug: str) -> Optional["TaskScheduler"]:` | `task_scheduler.py:201` | 1 |

Test files from §4 are intentionally not anchored here — they are reshaped
per the Test Specification, not patched at a single site.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Command docs mirror the structure/tone of `.claude/commands/sdd-spec.md`
  and `sdd-done.md` (numbered steps, CRITICAL callouts, exact bash blocks).
- `scripts/sdd/*` style: Pydantic models, Google docstrings, strict typing,
  argparse `main(argv) -> int` (see `ensure_worktree.py`).
- Twin discipline: every sdd-research/sdd-spec prompt change lands in ALL its
  twins in the same commit (`git add -f` for `_subagent_data/`).

### Known Risks / Gotchas

- **Wheel boundary**: nothing under `parrot/knowledge/wiki/ledger/` may
  change — it ships in the wikitoolkit wheel; a change forces a release +
  MCP restart. `brief_meta.py` is repo-local on purpose.
- **sdd/ auto-commit hook**: an instant-commit hook may fire on `sdd/` edits
  in the main checkout. The brief flow writes `sdd/briefs/**` only inside
  the worktree; the builder must verify the hook's behavior inside worktrees
  and keep the write path deterministic (brainstorm constraint).
- **Upstream hazard**: until S6 lands, a fresh worktree's bare `git push`
  targets the base branch (`origin/main` for hotfix briefs) — the unset must
  happen before any agent is handed the worktree.
- **Naming collision**: brief worktrees `fix-<KEY>-<slug>` vs fast-lane
  branches `fix/<id>-<slug>` — different namespaces (dash vs slash); never
  "normalize" one into the other.
- **Ledger truth**: never `ledger close` at PR-open time (S7) — a dev-based
  PR left unmerged with a closed issue misstates the ledger.
- **Historical artifacts**: `sdd/specs/*.spec.md` with `type: hotfix` and
  completed TASK files mentioning `--type hotfix` are history — the M6 sweep
  must not rewrite them.
- **`templates/` gitignore trap**: `sdd/templates/brief.md` needs
  `git add -f` (CLAUDE.md heads-up).

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| none new | — | `gh`, `wikitoolkit`, `pydantic`, `pyyaml` already in use |

---

## 8. Open Questions

- [x] Does `/sdd-brief` replace `/sdd-spec --type hotfix`? — *Resolved in
  brainstorm*: yes — hard cut, including the dev-loop autonomous lane in
  this same feature (Decision 6).
- [x] Base branch for ledger-sourced briefs? — *Resolved in brainstorm*:
  always `dev`; `--base-branch main` with a ledger source is refused.
- [x] May `/sdd-done` open PRs against `main`? — *Resolved in brainstorm*:
  yes — it opens the PR in every flow; what stays forbidden is the direct
  merge (`--merge` refused for main; merging the main PR is the human act).
- [x] Default base for non-ledger sources? — *Resolved in brainstorm*:
  `main` (it is a hotfix command), `--base-branch` for exceptions.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-698/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Brief-specific worktree plan (architecture) | CONFIRM | `plan_worktree` cannot represent a dev-based brief; command-layer helper, FlowMeta untouched; `fix-` (worktree) vs `fix/` (fast-lane branch) disambiguated | §2 Overview, §3 M2, §7 |
| S2 | No null feature_id through the coder pipeline (architecture) | CONFIRM | checkpoint.py:462-466 and ExecutionPoolView (min_length=1) verified; index carries `BRIEF-<KEY>` | §2 Data Models, §3 M2, §6 |
| S3 | Explicit brief index path in ResearchOutput (api) | CONFIRM | `_find_feature_slug` scan verified blind to `sdd/briefs/`; `index_path` + `from_index_path` added | §3 M5 |
| S4 | /sdd-done as separate brief state machine (architecture) | CONFIRM | dedicated brief lane, no conditionals through the feature path | §3 M3 |
| S5 | Main-target PR creation fail-closed (risk) | CONFIRM | `gh pr create --base $BASE_BRANCH --head $BRANCH`, URL printed, worktree retained on failure, `--merge` rejected pre-push | §3 M3, §5 |
| S6 | Unset + verify upstream after worktree creation (risk) | CONFIRM | `_create_worktree` verified to not unset; `ensure()` gains unset + assert | §3 M2, §5 |
| S7 | Ledger claims as a transaction (risk) | CONFIRM | claim persisted in brief frontmatter; release on abort; close only post-merge | §3 M1, M3, §7 |
| S8 | Brief-shape test coverage replaces empty-feat tests (testing) | CONFIRM | enumerated in §4 | §4 |
| S9 | Non-negotiable minimum for --research light (risk) | CONFIRM | source + root cause + ≥1 verified path:line anchor, else no worktree | §3 M1, §5 |

Summary: **9** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree (`feat-FEAT-698-sdd-brief-hotfix-flow`);
  the sdd-coder engine gives each task its own sub-worktree inside it.
- **Module dependency graph**: M2 → M1 (command invokes `brief_meta` /
  `ensure_worktree --brief`); M2 → M3 (index shape, worktree naming);
  M2 → M5 (index shape); M1 → M4 (replacement must exist before removal);
  M1 → M5 (twins invoke the new command); M3, M4, M5 → M6 (sweep verifies
  the end state). M3 ∥ M4 ∥ M5 are expected to run concurrently once M1/M2
  land.
- **Shared files**: `CLAUDE.md` (M3 rewording; M4 removes the FEAT-466
  hotfix notes in the SDD table) — serialize the tasks touching it.
  `docs/sdd/WORKFLOW.md` (M3 and M6) — serialize.
- **Exclusive resources**: none (no extension rebuilds, no lockfiles, no
  migrations).
- **Cross-feature dependencies**: none — FEAT-694/695 ledger work is merged.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-17 | Jesus Lara + Claude | Initial draft from accepted brainstorm + codex design research (9/9 confirmed) |
