---
name: sdd-brief-hotfix-flow
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd, workflow, hotfix, ledger, commands]
status: brainstorm
created: 2026-10-17
---

# /sdd-brief — one-command brief flow for hotfixes and single-issue fixes

## Intent

The full SDD pipeline (`/sdd-brainstorm → /sdd-spec → /sdd-task`) is sized
for features. A hotfix — e.g. repairing GitHub code-scanning alert #224 —
does not need three documents and two id reservations; it needs **direct
research, a short Q&A for the genuinely open decisions, one actionable
document, and a worktree based on the right branch**.

Today that need is partially served by `/sdd-spec --type hotfix`
(FEAT-466): no FEAT/TASK id reservation, identity = Jira key or slug,
worktree `hotfix-<KEY>-<slug>` from `origin/main`, `/sdd-task` normally
skipped. But it is still spec-shaped (interview-first, feature-document
template) rather than research-first, and `/sdd-done` refuses to open the
PR against `main`, leaving a manual step.

`/sdd-brief` **replaces `/sdd-spec --type hotfix`** with a purpose-built
command: research-first intake from several source kinds (including the
work ledger), bounded Q&A, a single fused spec+task document (the
*brief*), and a worktree whose base branch drives everything downstream.

## Decisions already made (with the user — binding)

1. **`/sdd-brief` replaces `/sdd-spec --type hotfix`.** The hotfix path is
   removed from `/sdd-spec`, which becomes feature-only. Hard cut, no
   deprecation shim (established repo policy: no external consumers).
2. **Sources** include a work-ledger issue id. For a ledger source the
   command internally reuses the `/sdd-fix` retrieval machinery
   (`wikitoolkit ledger show` / `plan-fix` for the finding and its
   evidence, `ledger claim` to take ownership) and then performs full
   research on that issue.
3. **Base-branch resolution**:
   - Ledger-sourced briefs are **always based on `dev`** — never `main`.
     An explicit `--base-branch main` combined with a ledger source is
     refused.
   - All other sources (code-scanning alert, GitHub issue, Jira, free
     text, file) default to **`main`** — it is a hotfix command — with
     `--base-branch` available for the exceptions (`dev`, `staging`).
4. **`/sdd-done` opens the PR itself in every flow**, targeting the flow's
   `base_branch`: `main` for a hotfix brief, `dev` for the regular
   `sdd-spec → sdd-task` feature flow. This **relaxes the FEAT-187 rule**
   "never opens a PR against main": opening the PR is now allowed; what
   remains forbidden is the **direct merge** — `--merge` is still refused
   when `base_branch == main`, and merging the main PR stays the only
   human act. CLAUDE.md, `sdd-done.md`, and `docs/sdd/WORKFLOW.md` must be
   updated to the new wording.
5. **Downstream is unchanged**: `sdd-worker` / `sdd-coder` work in the
   brief's worktree exactly as they do today; the brief (or its task
   sections) plays the role of the task file.
6. **Hard cut, one feature**: the dev-loop **autonomous hotfix lane
   migrates to briefs in this same feature**. `/sdd-spec --type hotfix`
   is removed outright — no internal-only transition period. The
   `sdd-research` agent and the dev_loop hotfix code paths are re-pointed
   at `/sdd-brief` semantics as part of this work.

## Goals

- One command from "here is a bug/alert/issue" to "worktree ready with an
  actionable brief inside it".
- Research-first: fetch the source artifact (e.g.
  `gh api repos/{owner}/{repo}/code-scanning/alerts/{n}`), locate the code
  via the wiki (`wiki_symbol_lookup`, `wiki_blast_radius`), pull
  `wikitoolkit ledger context` for the touched files, and establish the
  root cause **before** asking the user anything.
- Bounded Q&A: only the decisions research could not settle (e.g.
  suppress-vs-refactor for a scanning alert, scope of the fix). Hard cap
  (~5 questions); `--no-interview` skips it and records the assumptions in
  the brief.
- A single brief document that an implementer (human, `sdd-worker`, or
  `sdd-coder`) can execute without reading anything else.
- Optional task split (`--split`, or automatic when research reveals >1
  independent chunk) using local ids `HOTFIX-<KEY>-1..N` — **no**
  `reserve_ids.py` calls, consistent with FEAT-466.

## Non-goals

- Not a replacement for `/sdd-fix` as the ledger **drain** command.
  `/sdd-fix` keeps draining the ledger wholesale; `/sdd-brief issue:<id>`
  is the deep-research alternative for a single issue that deserves it.
- No change to the feature flow (`/sdd-brainstorm`, `/sdd-spec` for
  features, `/sdd-task`, `/sdd-start`).
- No change to sync-down automation (FEAT-187's
  `.github/workflows/sync-down.yml` and `/sdd-done --sync-down` stay
  exactly as they are — a merged hotfix still propagates main → staging/dev
  that way).
- No new id kinds in `sdd/tasks/.id_ledger.json`.

## Anti-goals (failure even if it "works")

- Any path by which the brief flow pushes to or merges into `main`
  directly. The PR is opened by `/sdd-done`; the merge is human.
- Reintroducing FEAT/TASK id reservation on the hotfix path (FEAT-466
  removed it deliberately — reserving on `main` while another session
  holds `dev` deadlocks).
- Writing or committing the brief in the **shared main checkout**. The
  brief is committed **inside the worktree** and rides in the fix PR
  (established practice; the shared tree is used by parallel sessions).
- A "quick" flow that silently skips research and produces a
  guess-shaped brief.

## Constraints

- Worktree rules are unchanged (`.claude/rules/worktree-management.md`):
  always under `.claude/worktrees/`, created from `origin/<base_branch>`
  via `scripts.sdd.ensure_worktree`, never `HEAD`, never
  `claude --worktree`. `git worktree add -b X <path> origin/main`
  auto-sets upstream to `origin/main`, so the command must run
  `git -C <wt> branch --unset-upstream` immediately (a bare `git push`
  must never target `main`).
- The repo has a hook that auto-commits `sdd/` edits in the main checkout
  instantly. The brief must therefore be **written inside the worktree
  from the start**, never drafted under the main checkout's `sdd/` and
  moved. The builder must verify how/whether that hook behaves inside a
  worktree and make the write path deterministic.
- `rtk` / Bubblewrap sandbox rules for in-worktree execution apply as for
  any SDD command.
- Identity when there is no Jira ticket: the slug (or the ledger id for
  ledger sources) is the `<KEY>` — never ask to create a ticket just to
  have a key (established practice).

## Design

### CLI

```
/sdd-brief <source> [--base-branch main|dev|staging] [--no-interview]
           [--split] [--research full|light]
```

`<source>` is auto-detected:

| Source shape | Fetch via | Default base |
|---|---|---|
| Code-scanning URL / `cs:224` | `gh api .../code-scanning/alerts/224` | `main` |
| GitHub issue / PR URL | `gh api` / `gh issue view` | `main` |
| Jira key (`NAV-123`) | jiratoolkit | `main` |
| Ledger id (`issue:<hex>` or bare hex) | `wikitoolkit ledger show` + `plan-fix`, then `ledger claim` | `dev` (mandatory) |
| Free text / file path | as given | `main` |

### Phases

1. **Research** — fetch the source artifact; locate code (wiki symbol
   lookup, blast radius); `ledger context` on the touched files; root
   cause statement with evidence (file:line). `--research light` bounds
   this for trivially-located fixes.
2. **Q&A** — only unresolved decisions, ≤5 questions, skippable
   (`--no-interview` records assumptions in the brief under
   "Assumptions").
3. **Brief document** — written **inside the worktree** (created first,
   step 4 ordering is: worktree, then brief, then commit). See format
   below.
4. **Worktree** — `ensure_worktree` from `origin/<base>`:
   - base `main` → `hotfix-<KEY>-<slug>` (unchanged naming — `/sdd-done`
     and tooling already recognize it).
   - base `dev` (ledger source) → `fix-<id>-<slug>`, matching the
     `/sdd-fix` fast-lane branch convention (`fix/<id>-<slug>` branch).
   - Commit the brief (and the minimal index, below) in the worktree.
5. **Handoff** — print the worktree path and the exact next step
   (`/sdd-start`-equivalent instruction, or
   `claude --agent sdd-worker` inside the worktree).

### The brief document

`sdd/briefs/<slug>.brief.md`, committed inside the worktree. Frontmatter:

```yaml
kind: brief
slug: <slug>
base_branch: main          # or dev (ledger)
source: {type: code-scanning, ref: "224", url: "..."}
jira_issue_key: null       # or the key
ledger_issue: null         # or issue:<hex> (claimed)
created: <ISO-8601>
```

Body sections: **Problem** · **Root cause** (evidence, file:line) ·
**Research findings** · **Decisions** (from Q&A) / **Assumptions** (if
`--no-interview`) · **Fix plan** · **Validation commands**.

### Task materialization (design call)

The brief does **not** carry inline task sections that downstream tooling
would have to learn to parse. Instead, `/sdd-brief` **materializes
standard task files** — the `sdd/templates/task.md` shape (Codebase
Contract, Acceptance Criteria, Validation Commands sections) — under
`sdd/briefs/<slug>/tasks/HOTFIX-<KEY>-N-<task-slug>.md`, inside the
worktree. One file for the single-task case; several when `--split`.
This is what makes Decision 5 ("downstream unchanged") actually true:
`sdd-worker`'s planner, the `parrot-sdd-coder` MCP chunker and fidelity
gate, and `/sdd-start`-style manual implementation all consume the same
task-file shape they consume today, with zero Python changes in the
coder pipeline.

A per-brief index at `sdd/briefs/<slug>.index.json` reuses the per-spec
index schema (`feature_id: null`, keyed by slug, `tasks[].file` pointing
at the materialized task files). It deliberately does **not** live in
`sdd/tasks/index/` — so `check_id_collisions.py`, `check_task_state.py`,
`/sdd-status`, and `/sdd-next` never ingest `HOTFIX-*` ids and need no
schema relaxation, and a merged hotfix brief syncing `main → dev` cannot
pollute the feature board. In-flight briefs remain visible through the
worktree listing (`/sdd-status`'s FEAT-582 worktree panel). Task closure
for briefs flips the index status and fills the Completion Note **in
place** — no `active/ → completed/` move, `close_task.sh` is not used.

### Type-system boundary (design call)

Briefs **bypass `FlowMeta` / `resolve_flow()` entirely**. They are a new
document kind with their own light frontmatter (`kind: brief`), parsed by
the command layer — not a third value in `FlowMeta.type`. Rationale:
`FlowMeta` ships in the wikitoolkit wheel
(`parrot.knowledge.wiki.ledger.sdd_meta`), so touching its
`Literal["feature","hotfix"]` or the `hotfix ⇒ main` validator would
force a wikitoolkit release + MCP restart, and a dev-based ledger brief
would violate that validator anyway. `FlowMeta`, its validators, and the
dev-loop Pydantic contracts stay untouched.

### Changes to existing commands

- **`/sdd-spec`**: remove `--type hotfix` and the FEAT-466 §"TYPE ==
  hotfix" branch; `resolve_flow()` keeps rejecting `type: hotfix`
  frontmatter with a pointer to `/sdd-brief`.
- **`/sdd-done`**: resolve a brief by slug/KEY (in addition to FEAT-ID).
  Because the brief, its index, and its task files exist **only in the
  worktree** until the PR merges, brief resolution is worktree-based:
  match `hotfix-*` / `fix-*` worktrees by slug (the command already runs
  from inside a worktree via its `IN_WORKTREE=1` path; from the main repo
  it scans `$WORKTREES_DIR`). Verification reads
  `sdd/briefs/<slug>.index.json` and runs the brief's Validation
  Commands; the `close_task.sh` / `sdd/ledger` snapshot steps are skipped
  as they already are for `TYPE == hotfix` today. Then: read
  `base_branch` from brief frontmatter; **open the PR itself against
  `base_branch` in all flows, `main` included**; keep refusing `--merge`
  into `main`; `--sync-down` unchanged.
- **Ledger lifecycle for `issue:<id>` briefs**: `ledger claim` at research
  start; if the user aborts before the worktree exists, release the claim
  (or print the release command). `ledger close --resolved-by` runs only
  when the fix is confirmed merged (`--merge` on a dev-based brief, or
  `--sync-down`-time for a main-based one); when `/sdd-done` only opens
  the PR, it prints the `ledger close` command next to the PR link
  instead of closing an issue whose fix is not yet on the base branch.
- **Policy docs**: update the FEAT-187 wording in `CLAUDE.md`,
  `.claude/commands/sdd-done.md`, and `docs/sdd/WORKFLOW.md` from "never
  opens a PR against main" to "never merges into main; opens the PR".
- **`/sdd-fix`**: unchanged behavior; its plan-fix output may suggest
  `/sdd-brief issue:<id>` for issues graded hotfix-deep (builder's
  choice on wording).
- **Dev-loop autonomous lane — in scope (Decision 6)**:
  - `sdd-research` prompt twins (`.claude/agents/sdd-research.md` AND
    `packages/ai-parrot/src/parrot/flows/dev_loop/_subagent_data/
    sdd-research.md` — both must be edited, the latter may need
    `git add -f`): replace the literal
    `/sdd-spec <slug> --type hotfix --base-branch main --no-interview`
    invocation with the `/sdd-brief <source> --no-interview` equivalent.
  - `dev_loop/nodes/development.py` hotfix code paths (built on
    "hotfix ⇒ no per-spec index, `feat_id == ''`") are re-pointed at the
    per-brief index (`sdd/briefs/<slug>.index.json` + materialized task
    files) instead of the index-less assumption.
  - dev_loop Pydantic contracts (`DevRequestBrief` and friends) keep
    their shape where possible; where the `hotfix ⇒ main` coupling is
    hardcoded, they learn the brief's `base_branch` instead. These models
    live in the `ai-parrot` package (not the wikitoolkit wheel), so no
    wikitoolkit release is implied — `FlowMeta` itself stays untouched
    (Type-system boundary above).
  - Final sweep: grep `type: hotfix` / `--type hotfix` across `.claude/`,
    `.agent/`, `.agents/`, `packages/*/src/parrot/flows/`, `docs/` — no
    reference to the removed path may survive, and the dev-loop
    hotfix-mode tests move to the brief shape in the same change.

## Left to the builder

- Exact brief template file (`sdd/templates/brief.md` — remember the
  `.gitignore` `templates/` trap: `git add -f`).
- `plan_worktree` extension for the `fix-<id>-<slug>` naming kind — as a
  **command-layer helper**, not a `FlowMeta` change (see Type-system
  boundary above), to avoid forcing a wikitoolkit release.
- The `gh api` field mapping for code-scanning alerts (rule, locations,
  state) and which alert states are refused (e.g. already `dismissed`).
- Interview question selection heuristics within the ≤5 cap.
- Pointing `sdd-worker` at a brief: the per-brief index is
  schema-compatible with a per-spec index, so the orchestrator's entry
  point just receives `sdd/briefs/<slug>.index.json`; builder verifies no
  hardcoded `sdd/tasks/index/` path remains in its prompt.
- Whether `/sdd-brief` prints a `--sync-down` reminder in its handoff text.
