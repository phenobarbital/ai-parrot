---
type: Wiki Overview
title: AI-Parrot Spec-Driven Development (SDD) Platform
id: doc:docs-sdd-platform-md
tags:
- overview
timestamp: '2026-07-14T22:20:21+00:00'
summary: A reference for the `/sdd-*` command suite under `.claude/commands/`, the
---

# AI-Parrot Spec-Driven Development (SDD) Platform

A reference for the `/sdd-*` command suite under `.claude/commands/`, the
supporting agents under `.claude/agents/`, and the scripts under
`scripts/sdd/`. It explains what each piece does, how state flows between
them, and walks two end-to-end flows: **from a Jira ticket** and **from a
brainstorm** — through to a deployed (merged) feature.

> Companion docs: `docs/sdd/WORKFLOW.md` (methodology + task format),
> `docs/sdd/GUIDE.md`, `CLAUDE.md` (Git Parrot Flow + worktree policy).

---

## 1. What the platform is

SDD makes the **specification the single source of truth (SSOT)**. Humans
(and Claude, interactively) produce design documents; Claude Code agents
consume those documents and emit code. The whole pipeline is a chain of
slash commands, each of which:

1. Reads the artifact(s) produced by the previous stage.
2. Does one well-bounded job (explore, specify, decompose, implement, verify).
3. **Commits its output to git** so that other sessions and *worktrees* can
   see it (uncommitted files are invisible to worktrees).

The core design principles baked into every command:

- **Anti-hallucination via a Codebase Contract.** Before any code is
  proposed, the relevant classes/imports/signatures are *read from the real
  source* and recorded with file paths and line numbers, plus an explicit
  "Does NOT Exist" list. This is carried forward verbatim from brainstorm →
  spec → task → implementation.
- **Carry-forward, never re-ask.** Each stage maps the prior artifact's
  sections into its own and refuses to re-open resolved questions.
- **Per-spec isolation.** Each feature owns its own task index file, so
  parallel features never collide on shared mutable state.
- **Flow-aware branching (Git Parrot Flow).** Every artifact carries
  `type` + `base_branch` frontmatter; features land on `dev`/`staging`,
  hotfixes on `main` (via PR only).

---

## 2. The artifacts and where they live

```
sdd/
├── proposals/        # brainstorm + proposal docs (entry points)
│   ├── <slug>.brainstorm.md
│   ├── <key>-<slug>.brainstorm.md       # from Jira
│   └── <slug>.proposal.md
├── specs/            # the SSOT — <feature>.spec.md (with frontmatter)
├── tasks/
│   ├── active/       # TASK-<NNN>-<slug>.md  (pending / in-progress)
│   ├── completed/    # TASK-<NNN>-<slug>.md  (done)
│   └── index/        # <feature-slug>.json   (per-spec task index)
│       └── _orphans.json   # migration leftovers, never auto-suggested
├── state/            # <FEAT-ID>/  research checkpoints for /sdd-proposal
├── reviews/          # optional code-review reports
└── templates/        # brainstorm.md, proposal.md, spec.md, task.md, *.schema.json
```

Every document that drives branching carries YAML frontmatter parsed by
`scripts/sdd/sdd_meta.py`:

```yaml
---
type: feature        # or: hotfix
base_branch: dev     # feature → dev (default) or staging; hotfix → main (mandatory)
---
```

`sdd_meta.parse()` returns `feature/dev` defaults for legacy docs with no
frontmatter, and *raises* if `type: hotfix` is paired with any branch other
than `main`. The validation rule appears in every command:

- `type: feature` + `base_branch: main` → **abort** (features never base on `main`).
- `type: hotfix` + `base_branch != main` → **abort**.

---

## 3. The command suite

The commands fall into four groups: **entry / exploration**, **specification**,
**execution**, and **Jira bridge + utilities**.

### 3.1 Entry & exploration (idea → grounded document)

| Command | Input | Output | When to use |
|---|---|---|---|
| `/sdd-brainstorm` | free-form idea | `<slug>.brainstorm.md` (3+ options) | greenfield features, no existing code to investigate |
| `/sdd-fromjira` | Jira key | `<key>-<slug>.brainstorm.md` | Jira-seeded brainstorm (legacy; superseded by `/sdd-proposal`) |
| `/sdd-proposal` | Jira key / inline text / file | `<slug>.proposal.md` | **default for tickets/bugs** — research-first, confidence-graded |

**`/sdd-brainstorm`** — Structured idea exploration. Always asks **Round 0**
(flow type: feature/hotfix + base branch), then ≥2 rounds of Q&A, then
researches the codebase to build the Code Context section, then generates
≥3 distinct approaches (one unconventional), recommends one, describes the
feature, maps to SDD structures, assesses parallelism, and commits the
brainstorm. It explicitly forbids writing implementation code.

**`/sdd-fromjira`** — Same quality bar as brainstorm, but seeded from a Jira
ticket. It READS Jira (never modifies it) via mcp-atlassian (preferred) or a
`curl` fallback using `JIRA_INSTANCE`/`JIRA_USERNAME`/`JIRA_API_TOKEN` loaded
through navconfig. It extracts summary, description (ADF→HTML→text), acceptance
criteria (tries `customfield_10021/10022/10035`), components, labels, subtasks;
**classifies complexity** (`fix`/`simple`/`standard`/`complex`) to calibrate
how many Q&A rounds to run; then asks *gap-filling* questions (not generic
ones). Output adds a Jira metadata block to the frontmatter and maps each
option against the Jira AC.

**`/sdd-proposal`** — The research-first inversion of brainstorm. Instead of
asking the human to fill gaps, it investigates the repo *first*. Seven phases,
each checkpointed in `sdd/state/<FEAT-ID>/state.json` for resumability:

```
Phase 0  source resolution     (Jira | inline | file → source.md)
Phase 1  research plan          (planner prompt → research_plan.json) [gate]
Phase 2  agentic research       (budgeted: tight|default|loose → findings/F*.md)
Phase 3  synthesis              (chain-of-thought, evidence-grounded → synthesis.json)
         + lint                 (every path/symbol must trace to a finding ID)
Phase 4  review gate            (human validates synthesis)
Phase 5  targeted Q&A           (only for genuine unknowns, ≤5)
Phase 6  render proposal        (proposal.md w/ confidence map)
Phase 7  commit + recommend     (→ /sdd-spec or /sdd-brainstorm)
```

Budgets are hard limits (files read / greps / git calls / depth / wall
seconds). `overall_confidence` is bounded by the budget consumed and by the
weakest claim — if research was truncated, confidence is capped at `medium`
and it will not recommend jumping straight to `/sdd-task`. `--resume <FEAT-ID>`
re-enters at the last checkpoint; `--no-gate` runs unattended (autopilot mode).

All three exploration commands declare the same **section→spec mapping** so
`/sdd-spec` can consume any of them as a drop-in input (Problem Statement →
spec §1, Code Context → spec §6 Codebase Contract, etc.).

### 3.2 Specification (document → SSOT)

**`/sdd-spec <feature-name> [-- notes]`** — Scaffolds `sdd/specs/<feature>.spec.md`
from the template. If a `.brainstorm.md` / `.proposal.md` exists it is treated
as **authoritative input**:

- **§2a** maps every brainstorm section into a specific spec section.
- **§2b** parses Open Questions: `[x]` resolved answers are routed into the
  spec body *where the decision applies* AND echoed in §8 — never re-asked.
  `[ ]` unresolved questions carry into §8 and may be asked only if they
  genuinely block the design. If a resolved answer conflicts with the agent's
  instinct, **the brainstorm wins**.
- **§2c** prints a carry-forward summary before asking anything.
- **§2d** reads frontmatter via `sdd_meta`, validates flow type, then
  `git checkout <base>` + `git pull --ff-only` (aborts on dirty tree or
  non-fast-forward).
- **§4** rebuilds/re-verifies the **Codebase Contract** (§6 of the spec):
  read every referenced file, confirm imports resolve, record a "Does NOT
  Exist" subsection. Quality bar: every entry has a path + line number.
- Adds a **Worktree Strategy** section (`per-spec` vs `mixed`).
- Commits ONLY the spec file to `base_branch`.

The spec then has a lifecycle status; `status: approved` gates the next stage.

**`/sdd-task sdd/specs/<feature>.spec.md`** — Decomposes an **approved** spec
into atomic, testable, assignable tasks. Must run on the spec's `base_branch`
(not in a worktree). Steps:

1. Sync base branch (same `sdd_meta` + ff-only logic; refuses to run inside a
   worktree).
2. Read spec; warn if not `approved`.
3. Plan decomposition: one task per module/deliverable, 1–4h each, ordered by
   dependency. Mark tasks sharing no files as `parallel: true`.
4. **Per-task Codebase Contract**: copy the relevant verified
   imports/signatures/"Does NOT Exist" from spec §6, re-verify freshness, add
   task-specific anchors. A task without this section is incomplete (the
   implementing agent — often Sonnet/Haiku — *will* hallucinate without it).
5. Write `sdd/tasks/active/TASK-<NNN>-<slug>.md` (header carries
   `**Feature**: FEAT-<NNN> — <Title>`) and create/update the per-spec index
   `sdd/tasks/index/<feature>.json`.
6. Commit task files + index to `base_branch`.
7. Create the feature worktree:
   `git worktree add -b feat-<FEAT-ID>-<slug> .claude/worktrees/feat-<FEAT-ID>-<slug> HEAD`.

**Per-spec index schema** (header cached from spec frontmatter; `tasks[]` local
to the feature):

```json
{
  "feature": "<slug>", "feature_id": "FEAT-<NNN>",
  "spec": "sdd/specs/<slug>.spec.md",
  "type": "feature", "base_branch": "dev",
  "created_at": "...", "completed_at": null,
  "tasks": [{
    "id": "TASK-<NNN>", "slug": "...", "title": "...",
    "feature_id": "FEAT-<NNN>", "feature": "<slug>",
    "status": "pending", "priority": "high", "effort": "M",
    "depends_on": [], "parallel": false, "parallelism_notes": "...",
    "assigned_to": null, "started_at": null, "completed_at": null,
    "file": "sdd/tasks/active/TASK-<NNN>-<slug>.md"
  }]
}
```

### 3.3 Execution (tasks → code → merge)

**`/sdd-start TASK-<NNN>` (or slug)** — Picks up one task, validates, implements.
Run inside the feature worktree. Steps:

1. Resolve the task by globbing `sdd/tasks/index/*.json` (skip `_orphans.json`).
2. Validate readiness: status must be `pending`; every `depends_on` must be
   `done` (else print the blockers and STOP).
3. Detect context (branch/dir). With per-spec indexes, committing in the
   worktree is safe — no shared mutable state.
4. Mark `in-progress` in the index (in place) and commit *only* the index.
5. Read the task file + spec; print a kickoff summary.
6. **Begin implementation (the core purpose — do NOT stop at the summary):**
   verify the Codebase Contract first (grep/read each import & signature; never
   guess; never reference anything in "Does NOT Exist"), write the code, lint,
   run the acceptance-criteria tests, commit only task-scoped files with
   `feat(<slug>): TASK-<NNN> — <title>`.
   STOP only if a dependency is broken, the spec is ambiguous, or tests fail
   unfixably.
7. Mark done via `scripts/sdd/close_task.sh TASK-<NNN> <slug> verified` (see
   §4), fill the Completion Note, commit the SDD state.
8. Hint the next task or suggest `/sdd-done`.

**`/sdd-done FEAT-<ID>`** — Verifies, merges, and cleans up. Runs on the spec's
`base_branch`, NOT in a worktree (model: haiku). Steps:

1. Read frontmatter → `BASE_BRANCH`; abort if current branch ≠ base or inside a
   worktree.
2. Resolve the feature (match `feature_id`/`feature`/numeric suffix/substring).
3. Locate the worktree (`git worktree list | grep feat-<ID>`; fall back to
   remote branch).
4. Gather **evidence** per task from inside the worktree: matching commits,
   file existence, and (unless `--force`) tests.
5. Build a verification report classifying each task ✅ VERIFIED / ⚠️ PARTIAL /
   ❌ NO EVIDENCE.
6. Confirm with the user (`--dry-run` stops here; `--force` closes regardless).
7. Close tasks via `close_task.sh` on the base branch; commit SDD state.
8. Push the feature branch.
9. **Merge into base** (this is what actually brings the code in):
   - If `BASE_BRANCH == main` (hotfix): **hard refusal** — print a
     `gh pr create --base main` snippet and exit 0. `/sdd-done` *never* pushes
     to or PRs `main`.
   - Otherwise: `git merge --no-edit feat-<ID>-<slug>`, run
     `scripts/sdd/heal_orphans.sh <slug>` to reap any stalled `active/` copies,
     then `git push origin <base>`.
9.5. `--sync-down` (hotfix only): after the manual PR merges to `main`,
   propagate to `staging` and `dev` (normally done automatically by
   `.github/workflows/sync-down.yml`).
10. `--resolve-jira`: fetch available transitions and move the linked ticket to
   Done/Resolved (and its subtasks).
11. Remove the worktree (`git worktree remove` / `prune`), optionally delete the
   merged local branch.
12. Print the summary.

### 3.4 Jira bridge & utilities

| Command | Purpose |
|---|---|
| `/sdd-tojira <spec\|FEAT-ID>` | Export a spec to a Jira Story (+ `--with-subtasks`), write the Jira key back into the spec for reverse-linking, idempotent (re-runs UPDATE). |
| `/sdd-status [feature]` | Read-only task board aggregated across all per-spec indexes; shows blockers + an orphans panel. |
| `/sdd-next` | Suggest unblocked `pending` tasks (deps all `done`), sorted by priority/effort, annotated with worktree commands. |
| `/sdd-codereview <task>` | Apply the `code-reviewer` rubric to a completed task; structured report (Critical/Major/Minor + AC check). |
| `/sdd-explain [--deep] <target>` | Code-grounded architecture walkthrough (default) or implementation trace (`--deep`); strict anti-hallucination (read before explain, grep anchors not line numbers). |

`/sdd-tojira` is the reverse of `/sdd-fromjira`: the `jira:` metadata it writes
enables `/sdd-done --resolve-jira`, `/pr-review` auto-detection, and idempotent
re-export.

---

## 4. The supporting scripts (why they exist)

Agents tend to *paraphrase* a `mv` as a copy, which leaves a stale `active/`
file behind; when the feature branch merges, both copies land on the base
branch as a "stalled orphan". Two scripts remove that drift by making the
operation deterministic — there is nothing to paraphrase:

- **`scripts/sdd/close_task.sh <TASK-ID> <slug> [verified|partial|forced]`** —
  `git mv`s the task file from `active/` to `completed/`, stamps the index
  (`status=done`, `completed_at`, `verification`, `file`), stamps the header's
  `completed_at` when *all* tasks are done, stages the change, and enforces a
  **hard post-condition**: exit 3 if any `active/` copy survives. Idempotent.
- **`scripts/sdd/heal_orphans.sh <slug>`** — sweeps `active/` for files whose
  task is `done` in the index *and* has a `completed/` twin, removing them.
  Run unconditionally after every merge in `/sdd-done`.
- **`scripts/sdd/sdd_meta.py`** — the single source of truth for flow-type
  frontmatter (`parse`/`emit`, `FlowMeta` with the hotfix→main validator).
- `scripts/sdd/migrate_index.py` — one-time split of the legacy
  `.index.json` monolith into per-spec files (the monolith is preserved but
  ignored; unattributable tasks went to `_orphans.json`).

---

## 5. Autonomous agents

Planning needs human judgment; execution can be pre-authorized once the spec is
approved. The agents under `.claude/agents/`:

- **`sdd-worker`** — implements *all* tasks for a feature sequentially in
  dependency order, committing after each, inside a manually-created worktree.
  Implements exactly what tasks specify (no redesigns). Launch:
  `claude --agent sdd-worker --model sonnet --verbose`.
- **`sdd-autopilot`** — shell-level AgentCrew that chains
  `worker → code-reviewer → qa-runner → sdd-done → pr-review` with file-based
  quality gates in `.autopilot/` (`state.json` enables resume). Bounded retry
  budget; **blast-radius rules**: never merges PRs, never touches `main`/`dev`
  directly, never force-pushes, never works outside feature scope. It *can*
  push the feature branch, open a PR against `dev`, comment/label, draft a PR,
  and optionally update Jira.
- **`qa-runner`** — the QA stage of `sdd-autopilot`: runs the feature's
  pytest suite + `ruff`/`mypy` on changed files and maps acceptance criteria
  to tests, then writes a markdown `.autopilot/qa-report.md` with a
  greppable `verdict: PASS | FAIL`. Read + shell only (no edits); reports,
  never fixes.
- **`sdd-research`** / **`sdd-qa`** — phase subagents for the dev-loop flow
  (FEAT-129): research triages a failure → files Jira → `/sdd-spec` →
  `/sdd-task` → worktree, emitting a `ResearchOutput` JSON contract; QA runs
  acceptance criteria + lint deterministically under a no-edit permission mode
  and emits a `QAReport` JSON. (Distinct from `qa-runner`: `sdd-qa` emits a
  strict JSON `QAReport` for a programmatic dispatcher, while `qa-runner`
  emits a human/grep-friendly markdown report for the autopilot loop.)
- **`code-reviewer`** — the rubric backing `/sdd-codereview`.

---

## 6. End-to-end flow A — from Jira to deployment

```
┌─ PLAN (interactive, on dev) ─────────────────────────────────────────────┐
│ /sdd-proposal NAV-8036            research-first; → proposal.md + state/  │
│        │  (or /sdd-fromjira NAV-8036 for option-style brainstorm)         │
│        ▼                                                                  │
│ /sdd-spec <feature>               carry-forward brainstorm/proposal,       │
│        │                          rebuild §6 Codebase Contract, commit     │
│        ▼                          → sdd/specs/<feature>.spec.md (approve)  │
│ /sdd-tojira FEAT-071 --with-subtasks   (optional) sync spec → Jira         │
│        ▼                                                                  │
│ /sdd-task sdd/specs/<feature>.spec.md  decompose, commit, create worktree  │
└──────────────────────────────────────┬───────────────────────────────────┘
                                        │ spec approved + tasks committed
┌─ EXECUTE (in worktree) ───────────────▼───────────────────────────────────┐
│ cd .claude/worktrees/feat-071-<slug>                                      │
│ /sdd-start TASK-001  → implement → commit  (repeat per task, deps honored) │
│        … or: claude --agent sdd-worker   (all tasks unattended)            │
│        … or: claude --agent sdd-autopilot (worker→review→QA→done→pr-review)│
└──────────────────────────────────────┬───────────────────────────────────┘
                                        │ all tasks done
┌─ INTEGRATE (on dev) ──────────────────▼───────────────────────────────────┐
│ /sdd-done FEAT-071 --resolve-jira                                         │
│   verify evidence → close tasks → push branch → merge into dev →           │
│   heal orphans → push dev → transition NAV-8036 to Done → remove worktree  │
└──────────────────────────────────────┬───────────────────────────────────┘
                                        ▼
                         dev now contains the feature.
        Release: cut staging from dev at freeze; tag a release on main.
        sync-down.yml fast-forwards staging/dev after pushes to main.
```

Concrete sequence:

1. **`/sdd-proposal NAV-8036`** — reads the ticket, plans + runs budgeted
   codebase research, synthesizes a confidence-graded proposal, asks only about
   genuine unknowns, commits `sdd/proposals/nav-8036-<slug>.proposal.md` plus
   `sdd/state/FEAT-071/`. (Use `/sdd-fromjira NAV-8036` instead if you want a
   3-option brainstorm.)
2. **`/sdd-spec nav-8036-<slug>`** — consumes the proposal as authoritative,
   re-verifies the Codebase Contract, syncs `dev`, writes and commits the spec.
   Mark it `status: approved`.
3. **`/sdd-tojira FEAT-071 --with-subtasks`** *(optional)* — pushes the spec to
   Jira and writes the `jira:` key back so `/sdd-done` can resolve it later.
4. **`/sdd-task …spec.md`** — decomposes into tasks on `dev`, commits the
   index + task files, creates `.claude/worktrees/feat-071-<slug>`.
5. **Implement** — inside the worktree, `/sdd-start TASK-001 … TASK-00N` (or
   `sdd-worker` / `sdd-autopilot`). Each task verifies its contract, writes
   code, tests, commits.
6. **`/sdd-done FEAT-071 --resolve-jira`** — from `dev`: verify, close tasks,
   push the branch, **merge into `dev`**, heal orphans, push `dev`, transition
   the Jira ticket to Done, remove the worktree.

The feature is now "deployed" to the integration branch (`dev`). Promotion to
production follows the **Git Parrot Flow**: `dev → staging` is a manual cut at
release freeze; tagged releases live on `main`; `sync-down.yml` propagates
`main → staging → dev` automatically.

---

## 7. End-to-end flow B — from brainstorm to deployment

Identical except the entry point is a free-form idea rather than a ticket:

1. **`/sdd-brainstorm <feature> -- notes`** — Round 0 (flow type + base
   branch), ≥2 Q&A rounds, codebase research + Code Context, ≥3 options, a
   recommendation, parallelism assessment; commits
   `sdd/proposals/<feature>.brainstorm.md` (`status: exploration`).
2. **Review/refine** the brainstorm options; pick the recommendation.
3. **`/sdd-spec <feature>`** — consumes the brainstorm (carry-forward rules in
   §3.2), builds §6 contract, syncs base, commits the spec; mark `approved`.
4. **`/sdd-task …spec.md`** → tasks + worktree.
5. **`/sdd-start` / `sdd-worker` / `sdd-autopilot`** → implementation.
6. **`/sdd-done FEAT-<ID>`** → verify, merge to `dev`, cleanup. (Add
   `/sdd-tojira` at any point if you later want a Jira record; add
   `--resolve-jira` to `/sdd-done` if linked.)

For a **hotfix**, set `type: hotfix` / `base_branch: main` in the brainstorm
frontmatter. Then `/sdd-spec` and `/sdd-task` base on `main`, and `/sdd-done`
**refuses to merge** — it prints a `gh pr create --base main` snippet. After
you merge that PR, `sync-down.yml` (or `/sdd-done <ID> --sync-down`) propagates
the fix to `staging` and `dev`.

---

## 8. Quick reference

```
Exploration:   /sdd-brainstorm   /sdd-fromjira   /sdd-proposal
Specify:       /sdd-spec         /sdd-tojira
Decompose:     /sdd-task
Execute:       /sdd-start        (agents: sdd-worker, sdd-autopilot)
Track:         /sdd-status       /sdd-next
Verify/ship:   /sdd-codereview   /sdd-done
Understand:    /sdd-explain
Scripts:       close_task.sh   heal_orphans.sh   sdd_meta.py
```

**Golden rules** (enforced across the suite):

- Commit every artifact to `base_branch` before a worktree needs it.
- Stage *only* the files you produced — never `git add .` / `-A`.
- Features never base on `main`; hotfixes only reach `main` via a manual PR.
- Every code reference traces to a verified, path-anchored Codebase Contract
  entry; "Does NOT Exist" is the strongest anti-hallucination tool.
- Closing a task is a *move* — always via `close_task.sh`, never a hand-rolled
  copy.
```
