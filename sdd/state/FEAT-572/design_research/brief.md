<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
## Problem Statement

FEAT-566 built the SDD Work Ledger: `/sdd-codereview` files every confirmed-but-unfixed
finding via `wikitoolkit ledger open`, and those findings accumulate at
`<main>/.parrot/ledger/` with a committed snapshot at `sdd/ledger/issues.jsonl`.
**The ledger fills, but it never drains.**

Measured on `dev` at 2026-09-18 — 15 open issues, **0 claimed, 0 closed**:

| Severity | Count | Kinds |
|---|---|---|
| critical | 0 | — |
| major | 2 | `bug`, `feature_gap` |
| minor | 9 | `tech_debt` ×6, `feature_gap`, `vulnerability`, `bug` |
| low | 4 | `tech_debt` ×4 |

Every one of them was discovered by a feature that has since **merged and closed**:
`FEAT-551` (`completed_at: 2026-09-15T13:46:35Z`), `FEAT-559`
(`2026-09-16T09:21:54Z`), `FEAT-560` (`2026-09-15T23:44:12Z`). Their worktrees are
gone and their per-spec indexes are stamped.

Four concrete mechanisms cause the stall:

1. **No severity ordering.** `LedgerService.ready_work()`
   (`ledger/service.py:199-207`) filters `status == "open"` and returns rows in
   index order. `wikitoolkit ledger ready` prints that order verbatim
   (`cli.py:2681-2695`). A `low` "leftover exploratory comment" can print above a
   `major` aiohttp session leak. Nothing tells an operator what to pick up first.
2. **The only promotion path needs a live parent spec.** `/sdd-next` suggests
   `/sdd-task --from-issue <issue-id> <spec.md>` (`sdd-next.md:107`), which seeds a
   task *inside an existing spec's* per-spec index (`sdd-task.md:234-241`). For all
   15 current issues the parent spec's index already carries `completed_at`, so the
   suggested command would append a task to a finished feature — reopening a merged
   index, with no worktree and a `/sdd-done` that already ran. **Orphaned issues have
   no route at all.**
3. **Uniform ceremony for non-uniform work.** The pipeline
   (`/sdd-spec → /sdd-task → worktree → /sdd-done`) is right for
   `issue:a9514c9232ad` (unclosed aiohttp sessions across two files) and absurd for
   `issue:337359a3ec81` ("Leftover exploratory comment in `RecentActivityCache.seen()`").
   Facing ~6 SDD commits to delete one comment, an operator does neither.
4. **Closing an issue loses the evidence.** `IssueClosedPayload` carries
   `resolved_by: str | None` (`ledger/events.py:52`) and `_apply_issue_closed` persists
   it (`ledger/index.py:209-219`) — but `LedgerService.close_issue()`
   (`service.py:235-246`) builds its payload as
   `{"reason": ..., "closed_by": actor}` and **never passes `resolved_by`**. The CLI
   (`cli.py:2730-2746`) has no `--resolved-by` flag either. Today a close is an
   unfalsifiable assertion: nothing links the issue to the commit or task that fixed it.

### Who is affected

Developers and autonomous agents (`sdd-worker`, dev-loop) that produce ledger issues as
a by-product of every code review, and the operator who wants a tech-debt burndown lane
that is as cheap as the debt is small.

---

### Constraints and goals
## Constraints & Requirements

- **Must not weaken the merge gate.** `/sdd-done` calls `wikitoolkit ledger blockers
  <FEAT-ID>` (`sdd-done.md:250`), which exits `1` on unacknowledged criticals scoped to
  the feature (`service.py:280-310`). `acknowledge` rejects any non-`human:` actor
  (`service.py:213-234`). `/sdd-fix` must never acquire a way to un-gate a merge.
- **Claim must stay atomic.** `LedgerIndex.claim_issue()` (`index.py:384-445`) is a
  single `ledger.claim` transaction where first-claim-in-log-order wins and a
  `WikiStoreBusy` appends nothing. Concurrent `/sdd-fix` sessions on the same host must
  keep losing races cleanly, not double-claim.
- **The ledger resolves to the main checkout**, never a worktree-local copy
  (`find_shared_root`, FEAT-566 §2.1). `/sdd-fix` runs from the main checkout; its
  worktrees read the shared plane.
- **Three workflow twins are mandatory and tested.** `tests/sdd/test_ledger_workflow_twins.py`
  asserts semantic parity across `.claude/commands/<n>.md`, `.agent/workflows/<n>.md`,
  and `.agents/skills/<n>/SKILL.md`. A twin-less command is a test failure.
- **Severity/kind vocabularies are closed Literals** — `IssueSeverity =
  Literal["critical","major","minor","low"]`, `IssueKind =
  Literal["bug","tech_debt","feature_gap","vulnerability"]` (`events.py:21-22`). No
  canonical *ordering* constant exists yet; one must be introduced.
- **Both interactive and non-interactive.** No-args = interactive picker; explicit
  issue-id or `--top N` = deterministic, promptless, safe for an unattended loop.
- **Deterministic lane rule with override.** The lane decision must be reproducible and
  auditable, not a per-invocation model judgement; `--lane fast|sdd` forces it.
- **`uv` + venv, aiohttp, Pydantic v2, Google docstrings, `black -l 120`, `ruff`** per
  `.claude/rules/codebase-conventions.md`.

---

### Recommended option / probable scope
## Recommendation

**Option B** — deterministic Python planner behind `wikitoolkit ledger plan-fix --json`,
with three thin twin commands executing the chosen lane.

The decision turns on where the *non-obvious* logic lives. Three of this feature's four
mechanisms are algorithms, not procedures:

- severity ordering is a total order over a closed `Literal`;
- grouping is **connected components over a bipartite graph** — not the clean per-file
  partition it looks like. On today's 15 issues, **7 of them touch more than one file**,
  so file-level buckets overlap: `issue:8f46e2c1eed1` sits in both `development.py` and
  `task_scheduler.py` and transitively merges them into one 5-issue group. A markdown
  description of "group by file" (Option A) produces a different answer per reader;
- the lane predicate is a boolean expression over `(severity, kind, |files|)`.

Prose cannot be regression-tested, and `test_ledger_workflow_twins.py` only checks that
the twins *say* equivalent things. Putting the algorithm in Python and the orchestration
in markdown puts each half where it can be verified — and `--json` is what turns the same
work into something `sdd-worker` or a nightly burndown can consume, which is the honest
path toward Option D later.

**What this trades away:** Option A would ship this week; Option B needs a package change
and a test suite first. It also introduces a heuristic lane predicate that *will*
mis-route some issues — accepted, because `--lane` overrides it and a mis-route costs one
extra flag, whereas an untestable clustering rule costs correctness on every invocation.

**Option D is not rejected, it is sequenced.** Option B's `--json` plan is exactly the
input a `FixFlow` would consume; building B first means D becomes a consumer rather than
a rewrite.

---

### Option B: Deterministic Python planner + thin twin commands  ⭐

A new pure module `parrot/knowledge/wiki/ledger/fix_planner.py` owns everything
algorithmic and nothing I/O-shaped:

- a canonical `SEVERITY_ORDER` and a stable sort;
- **grouping as connected components** over the bipartite issue↔file graph derived from
  each issue's `about` symbol ids;
- the **lane predicate** (`fast` vs `sdd`) as one pure function over an issue group.

It is exposed as `wikitoolkit ledger plan-fix [--kind] [--top N] [--lane] --json`, which
emits a `FixPlan` Pydantic model. The three twin commands become thin: call `plan-fix
--json`, render the picker, then execute the chosen lane using machinery that already
exists (`ensure_worktree`, `reserve_ids`, `/sdd-spec`, `ledger claim/close`).

Two small, surgical gaps in the existing service are closed alongside:
`close_issue(..., resolved_by=...)` and `ledger close --resolved-by`.

✅ **Pros:**
- **The algorithm is unit-testable** against `sdd/ledger/issues.jsonl` fixtures; the
  twins can drift in wording without drifting in behaviour, because all three call the
  same binary and parse the same JSON.
- `--json` makes the plan consumable by `sdd-worker`, the dev-loop, and an unattended
  burndown cron with no markdown parsing.
- Reuses the `LedgerService` facade wholesale — no new storage, no new event kinds, no
  schema migration.
- `resolved_by` finally gets populated, making "closed" falsifiable.

❌ **Cons:**
- Touches the `ai-parrot` package, so the fix lane's evolution is coupled to a release
  (mitigated: the repo runs the editable install).
- Two surfaces to keep coherent (Python planner + markdown execution), not one.
- The lane predicate is a heuristic; it will mis-route some issues and need tuning.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | `FixPlan` / `FixGroup` models | v2, already the project standard |
| `click` | `ledger plan-fix` subcommand | already the `wikitoolkit` CLI framework |
| `pytest` / `pytest-asyncio` | planner unit tests | already in the test stack |

🔗 **Existing Code to Reuse:**
- `parrot/knowledge/wiki/ledger/service.py:96` — `LedgerService` facade (`ready_work`,
  `claim`, `close_issue`, `get_context`)
- `parrot/knowledge/wiki/ledger/sdd_meta.py:178` — `plan_worktree()` for canonical naming
- `scripts/sdd/ensure_worktree.py:48` — idempotent `ensure()`
- `scripts/sdd/reserve_ids.py:468` — `reserve_ids()` for the SDD lane's `FEAT-<NNN>`
- `parrot/knowledge/wiki/structural/tools.py:225` — `create_structural_tools` / `wiki_blast_radius` to size a fix before routing it

---

### Verified code anchors (paths only — open them yourself)
.claude/commands/sdd-codereview.md
.claude/commands/sdd-done.md
.claude/commands/sdd-next.md
.claude/commands/sdd-task.md
packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py
packages/ai-parrot/src/parrot/knowledge/wiki/structural/tools.py
packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
scripts/sdd/close_task.sh
scripts/sdd/ensure_worktree.py
scripts/sdd/reserve_ids.py
scripts/sdd/sdd_meta.py
sdd/ledger/issues.jsonl
sdd/specs/sdd-work-ledger.spec.md
tests/sdd/test_ledger_workflow_twins.py

### Questions still open in the exploration document
- [ ] Exact JSON schema of `FixPlan` / `FixGroup` (the twin↔planner contract).
- [ ] Group naming for the SDD lane's slug — derived from the dominant file's module, or
- [ ] Whether the fast lane opens a PR or pushes straight to `dev` for a one-line comment

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
