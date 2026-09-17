---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: `/sdd-fix` — Ledger-Driven Fix Lane

**Date**: 2026-09-18
**Author**: Jesus Lara (drafted with Claude)
**Status**: accepted
**Recommended Option**: Option B

---

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

## Options Explored

### Option A: Markdown-only command (three twins, CLI orchestration)

`/sdd-fix` ships as prose in the three twin files. It shells out to
`wikitoolkit ledger ready`, sorts and groups the output, applies the lane rule, and
drives `ensure_worktree` / `/sdd-spec` / git — all described in markdown, exactly as
`/sdd-done` and `/sdd-next` do today.

✅ **Pros:**
- Zero new Python surface; matches how every existing SDD command is built.
- Ships fast; no package release needed for iteration.
- The agent sees the whole procedure inline, no hidden behaviour.

❌ **Cons:**
- **The interesting logic becomes untestable prose.** Severity ordering, connected-component
  grouping and the lane predicate are deterministic algorithms; expressing them as
  markdown bullets means three natural-language copies with no unit test behind any of them.
- Guaranteed twin drift. `test_ledger_workflow_twins.py` checks *semantic* parity of
  fields and procedures, not that three prose descriptions of a clustering algorithm
  produce the same clusters.
- Every consumer re-implements the parse of `ledger ready`'s plain-text output.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | pure markdown + existing CLI |

🔗 **Existing Code to Reuse:**
- `.claude/commands/sdd-done.md` — the blockers-gate and snapshot procedure to mirror
- `.claude/commands/sdd-next.md:96-107` — the existing "Ready ledger issues" section

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

### Option C: Extend `/sdd-next` and `--from-issue`, no new command

Add `--by-severity` to `ledger ready`, and teach `/sdd-task --from-issue` to mint a new
spec when the parent index is `completed_at`. No `/sdd-fix` exists; the ledger lane stays
a variation of the task lane.

✅ **Pros:**
- Smallest possible surface; nothing new to learn or document.
- Automatically inherits every future `/sdd-next` and `/sdd-task` improvement.

❌ **Cons:**
- **Overloads `/sdd-task` with a second identity.** It would decompose a spec *and*
  conditionally author one, deciding on its own when a parent index counts as closed.
- No home for the fast lane: `/sdd-task` always produces a task, so the comment-deletion
  case keeps its ~6 commits of ceremony.
- Grouping has nowhere to live — `--from-issue` takes exactly one issue id.
- Leaves selection to the human every time; nothing becomes automatable.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:**
- `.claude/commands/sdd-task.md:234-241` — the existing `--from-issue` seeding block

---

### Option D: `FixFlow` — the ledger as a dev-loop DAG *(unconventional)*

Model the fix lane as an `AgentsFlow` DAG under `parrot/flows/fix_loop/`, mirroring
`parrot/flows/dev_loop/`: nodes for `SelectNode → ClaimNode → ContextNode → LaneRouterNode →
(FastFixNode | SddPipelineNode) → QANode → CloseNode`, dispatching `sdd-coder` seats per
group. `/sdd-fix` becomes a thin entrypoint over `run_flow(ctx)`.

✅ **Pros:**
- Unattended tech-debt burndown for free — point it at the ledger and let it drain
  overnight across a seat roster.
- Reuses the whole dev-loop investment: judge panel, feedback router, QA report,
  suspensions, `coder_*` MCP tools.
- Per-node telemetry via `on_node_event` gives a real audit trail of the fix lane.

❌ **Cons:**
- **Enormous for v1.** The dev-loop is the most complex subsystem in the repo; coupling
  the fix lane to it means inheriting its whole failure surface before the lane has ever
  drained one issue.
- An autonomous loop that *closes* ledger issues is precisely where a wrong `resolved_by`
  becomes systemic: the ledger would lie at scale.
- Answers a question nobody has asked yet — the immediate need is picking one issue and
  fixing it, not draining fifteen unattended.

📊 **Effort:** High

🔗 **Existing Code to Reuse:**
- `parrot/flows/dev_loop/` — `definition.py` + `factories.py` + `nodes/` + `runner.py` as
  the template for a new domain flow (per `.agent/CONTEXT.md`)

---

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

## Feature Description

### User-Facing Behavior

**Interactive (no arguments)** — `/sdd-fix` prints the plan, groups first by maximum
severity in the group, then by group size:

```
🔧 Ledger fix plan — 15 open issues → 7 groups

  1. [major]  sdd-coder engine                              3 issues · 3 files · lane=SDD
       bd1c792a major feature_gap  render_suspension_history() has no caller
       c1e28856 minor bug          end_execution builds an invalid Attempt
       700660c7 minor tech_debt    engine.py reaches into ExecutionPool private state
       → engine.py, pool.py, coder_suspensions.py

  2. [major]  MSTeams integration shutdown                  1 issue  · 2 files · lane=SDD
       a9514c92 major bug          aiohttp sessions never closed on shutdown
       → wrapper.py, manager.py

  3. [minor]  dev-loop pool exclusivity                     5 issues · 3 files · lane=SDD
  4. [minor]  MSTeams formdesigner submit                   3 issues · 3 files · lane=SDD
  5. [minor]  roster.py comment                             1 issue  · 1 file  · lane=FAST
  6. [minor]  codex dispatcher test                         1 issue  · 1 file  · lane=FAST
  7. [low]    execution pool integration test               1 issue  · 1 file  · lane=FAST

Pick a group (1-7), an issue id, or `q`:
```

Choosing a group claims every issue in it, prints the `ledger context` for the affected
files, and enters the routed lane. `--lane fast|sdd` overrides the routing; `--kind
tech_debt` and `--severity major` filter the plan.

**Non-interactive** — `/sdd-fix issue:a9514c9232ad` or `/sdd-fix --top 1 --kind bug`
selects without prompting and runs to completion. Intended for `sdd-worker` and an
unattended burndown.

**Fast lane** — branch `fix/<issue-short-id>-<slug>` off `origin/dev` in the main
checkout (no worktree, per `worktree-management.md` §2: "skip the worktree entirely for
docs-only changes and single-commit fixes"), edit, run the affected package's tests,
commit, push, open a PR against `dev`, and close each issue with
`--resolved-by commit:<sha>`.

**SDD lane** — reuse the parent spec when its per-spec index has **no** `completed_at`;
otherwise reserve a fresh `FEAT-<NNN>`, author a spec from the group, decompose it, and
create `feat-FEAT-<NNN>-<slug>` via `ensure_worktree`. `/sdd-done <FEAT-ID>` then closes
it out unchanged.

### Internal Behavior

1. **Plan** — `LedgerService.ready_work()` → `fix_planner.plan_fix_batch()`:
   extract each issue's files from `about` (`sym:<path>#<qualname>` → `<path>`), build
   the issue↔file bipartite graph, take connected components, sort issues within a group
   by `SEVERITY_ORDER` and groups by `(min severity, -size)`, then label each group with
   the lane predicate. Pure, synchronous, no I/O.
2. **Select** — interactive picker or deterministic argument resolution.
3. **Claim** — `LedgerService.claim(issue_id, actor="agent:sdd-fix")` per issue in the
   group. A `False` return means another session won the race: drop that issue from the
   group, report it, continue with the rest. An empty group after claiming aborts.
4. **Prime** — `LedgerService.get_context(files, max_tokens=3000)` renders the open
   issues touching those files into the working context.
5. **Route** — fast lane or SDD lane per the label (or `--lane`).
6. **Close selectively by evidence — two keys, fail-closed.** An issue is closed only when
   *both* hold: (a) the implementing agent explicitly asserts that issue id as resolved in
   its final report, **and** (b) at least one of that issue's `about` files appears in the
   final diff. Assertion alone cannot close (an agent could claim anything); file overlap
   alone cannot close either (7 of 15 current issues share a file with another, so overlap
   over-claims). Each close carries `resolved_by=commit:<sha>` (fast lane) or
   `resolved_by=task:TASK-<NNN>` (SDD lane). Issues failing either key are **not** closed
   and **not** left claimed — they are released with a new `issue.unclaimed` event
   (`claimed → open`, `claimed_by` cleared) so they reappear in the next plan.

### Edge Cases & Error Handling

- **Claim race** — `claim_issue()` returns `False` without appending
  (`index.py:391-393`); the issue is reported as taken and skipped, never retried in a loop.
- **`WikiStoreBusy`** — the log write is durable and the index reconciles on the next
  `sync` (FEAT-566 §2.2). The planner degrades to the snapshot in
  `sdd/ledger/issues.jsonl` rather than failing.
- **Read-only ledger** (sandbox / `EROFS`) — mirror `/sdd-codereview`'s discipline: do not
  request broader filesystem access, do not create a worktree-local ledger; report
  `(NOT filed: shared ledger is read-only)` and exit non-zero without claiming.
- **Partial group fix** — see "close selectively by evidence"; a group is never closed
  wholesale on merge.
- **An issue is already fixed** — close with `--reason "already fixed"` and
  `resolved_by=commit:<sha>` of the commit found to contain it. Never a silent close.
- **`about` points at a non-code file** — one issue today lists
  `sym:sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`. Spec/doc paths must not create
  a code group edge; they are carried as context only.
- **Empty `about`** — the issue cannot be grouped; it forms its own single-issue group
  and always routes to the SDD lane (no file scope ⇒ no evidence for triviality).
- **Critical severity** — always the SDD lane, never `--lane fast`, because a critical
  also participates in `merge_blockers`. `/sdd-fix` never calls `acknowledge`, which stays
  human-only (`service.py:213-234`).
- **Stale group** — an issue closed by another session between plan and claim is dropped
  silently; the plan is advisory, the claim is authoritative.

---

## Capabilities

### New Capabilities
- `ledger-fix-planner`: deterministic severity ordering, connected-component grouping and
  lane routing over open ledger issues, exposed as `wikitoolkit ledger plan-fix --json`.
- `sdd-fix-command`: the three-twin `/sdd-fix` command — interactive picker plus
  non-interactive selection — executing the fast and SDD lanes.
- `ledger-evidence-close`: `resolved_by` plumbed through `LedgerService.close_issue()` and
  `wikitoolkit ledger close --resolved-by`, making a closed issue falsifiable.
- `ledger-unclaim-event`: a new `issue.unclaimed` event kind reverting `claimed → open` and
  clearing `claimed_by`, so a claimed-but-unfixed issue returns to the ready pool without
  losing its id. Additive by design — `apply_event` already ignores unknown kinds
  (`index.py:120-122`).

### Modified Capabilities
- `sdd-work-ledger` (`sdd/specs/sdd-work-ledger.spec.md`, FEAT-566) — adds the planner, the
  `resolved_by` service path, and **one new event kind** (`issue.unclaimed`) with its
  reduction rule. The `LedgerEventKind` Literal grows from 11 to 12 members; no existing
  kind, payload or stored shape changes, and `IssueStatus` is untouched (the new event only
  moves an issue between two statuses that already exist).
- `/sdd-next` — its "Ready ledger issues" section (`sdd-next.md:96-107`) points at
  `/sdd-fix` instead of `/sdd-task --from-issue`, and shows severity-ordered groups.
- `/sdd-task --from-issue` — deprecated as the ledger entry point per the Round-2
  decision; behaviour retained for one cycle with a pointer to `/sdd-fix`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/knowledge/wiki/ledger/fix_planner.py` | new | pure planner; no I/O, fully unit-testable |
| `parrot/knowledge/wiki/ledger/service.py:235` | modifies | `close_issue(..., resolved_by=None)` + new `unclaim()` |
| `parrot/knowledge/wiki/ledger/events.py:7` | modifies | `LedgerEventKind` += `"issue.unclaimed"` (11 → 12) |
| `parrot/knowledge/wiki/ledger/index.py:102` | modifies | `apply_event` branch + `_apply_issue_unclaimed` |
| `parrot/knowledge/wiki/cli.py:2730` | modifies | `ledger close --resolved-by` |
| `parrot/knowledge/wiki/cli.py` (`ledger` group) | extends | new `plan-fix` subcommand |
| `.claude/commands/sdd-fix.md` | new | Claude twin |
| `.agent/workflows/sdd-fix.md` | new | Antigravity twin |
| `.agents/skills/sdd-fix/SKILL.md` | new | Codex twin |
| `.claude/commands/sdd-next.md:96-107` (+2 twins) | modifies | retarget to `/sdd-fix` |
| `.claude/commands/sdd-task.md:234-241` (+2 twins) | modifies | deprecation pointer |
| `tests/sdd/test_ledger_workflow_twins.py` | extends | a `TestFixTwins` class |
| `scripts/sdd/ensure_worktree.py` | depends on | unchanged; SDD lane calls `ensure()` |
| `scripts/sdd/reserve_ids.py` | depends on | unchanged; SDD lane reserves `FEAT-<NNN>` |
| `.claude/commands/sdd-done.md` | unchanged | blockers gate and snapshot keep working as-is |

**Breaking changes:** none. **New dependencies:** none.

---

## Code Context

### User-Provided Code

None — the user described the feature in prose; all references below were read from the
working tree on `dev` at 2026-09-18.

### Verified Codebase References

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:96
class LedgerService:
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None: ...  # :99
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService": ...                       # :114
    async def open_issue(...) -> str: ...                                                      # :166
    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]: ...     # :199
    async def claim(self, issue_id: str, actor: str) -> bool: ...                              # :209
    async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool: ...           # :213
    async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool: ...           # :235
    async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str: ...     # :247
    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]: ...               # :280
    async def export_snapshot(self, dest: Path) -> bool: ...                                   # :325
    async def compact(self, older_than_days: int = 30) -> int: ...                             # :353
    async def audit(self) -> dict[str, Any]: ...                                               # :357

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:78
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:
    # keys: issue_id, title, status, kind, severity, acknowledged,
    #       discovered_from, about, claimed_by, closed_by, closed_reason, resolved_by

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:85
class LedgerIndex:
    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool: ...   # :384 — atomic, first-claim-wins
    async def sync(self, conn: "aiosqlite.Connection | None" = None) -> int: ...  # :245
    async def rebuild(self) -> int: ...                                        # :335

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py:21
IssueKind = Literal["bug", "tech_debt", "feature_gap", "vulnerability"]        # :21
IssueSeverity = Literal["critical", "major", "minor", "low"]                   # :22

class IssueClosedPayload(BaseModel):                                           # :49
    reason: str                                                                # :50
    closed_by: str                                                             # :51
    resolved_by: str | None = None   # e.g. task:TASK-3205                     # :52

class IssueAcknowledgedPayload(BaseModel):                                     # :39
    acknowledged_by: str   # Must be a human actor, e.g. human:jesus           # :45
    reason: str                                                                # :46

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:170
class WorktreePlan(BaseModel):
    name: str
    path: str
    base_ref: str

def plan_worktree(                                                             # :178
    meta: FlowMeta, *, slug: str, feature_id: str | None = None, jira_key: str | None = None
) -> WorktreePlan: ...

# From scripts/sdd/ensure_worktree.py:48
def ensure(
    plan: WorktreePlan, *, repo_root: Path, sync: bool = True,
    require_paths: Sequence[str] = (), dry_run: bool = False,
) -> tuple[Path, bool]: ...

# From scripts/sdd/reserve_ids.py:468
def reserve_ids(...) -> ...: ...       # CLI: --kind task|feature --count N --base-branch B --label L
```

#### Verified Imports

```python
# Confirmed to resolve in the current tree:
from parrot.knowledge.wiki.ledger.service import LedgerService        # ledger/service.py:96
from parrot.knowledge.wiki.ledger.index import LedgerIndex            # ledger/index.py:85
from parrot.knowledge.wiki.ledger.events import (                     # ledger/events.py:21,22,49
    IssueKind, IssueSeverity, IssueClosedPayload, LedgerEvent,
)
from parrot.knowledge.wiki.ledger.sdd_meta import plan_worktree, WorktreePlan  # ledger/sdd_meta.py:170,178
from scripts.sdd.sdd_meta import plan_worktree, WorktreePlan          # compat shim re-export, scripts/sdd/sdd_meta.py:10-20
from parrot.knowledge.wiki.project import find_shared_root            # used at mcp_server.py:184
```

#### Key Attributes & Constants

- `IssueSeverity` → `Literal["critical","major","minor","low"]` (`ledger/events.py:22`)
- `IssueKind` → `Literal["bug","tech_debt","feature_gap","vulnerability"]` (`ledger/events.py:21`)
- `_issue_dict(...)["about"]` → `list[str]` of `sym:<repo-relative-path>#<qualname>` ids
  (`ledger/service.py:88`; verified against all 15 rows of `sdd/ledger/issues.jsonl` —
  **every** entry uses the `sym:` prefix, none uses `file:`)
- Claim transition: `_apply_issue_claimed` sets `state["status"] = "claimed"`
  (`ledger/index.py:195`), which is why `ready_work()`'s `status == "open"` filter does
  correctly exclude claimed issues despite testing only `status`.
- Ledger MCP tools already registered: `LedgerOpenTool`, `LedgerReadyTool`,
  `LedgerClaimTool`, `LedgerCloseTool`, `LedgerContextTool`
  (`knowledge/wiki/tools.py:626,661,684,703,722`; wired at `tools.py:777-781`).
- Ledger is mounted as a read-only federated namespace with
  `overlay_prefixes=["issue","task","spec","insight"]` (`knowledge/wiki/mcp_server.py:186-200`),
  so `wiki_query` already surfaces issues — **no `ledger_query` tool is needed.**

#### Measured ground truth (2026-09-18, `dev`)

Connected components over the issue↔file graph of `sdd/ledger/issues.jsonl`
(15 issues → **7 groups**; 7 issues touch >1 file, so file buckets are not a partition):

| # | Max severity | Issues | Files | Files |
|---|---|---|---|---|
| 1 | major | 3 | 3 | `engine.py`, `pool.py`, `coder_suspensions.py` |
| 2 | major | 1 | 2 | `wrapper.py`, `manager.py` |
| 3 | minor | 5 | 3 | `development.py`, `task_scheduler.py`, `*.spec.md` |
| 4 | minor | 3 | 3 | `formdesigner_submit.py`, `models.py`, `test_formdesigner_roundtrip.py` |
| 5 | minor | 1 | 1 | `roster.py` |
| 6 | minor | 1 | 1 | `test_codex_dispatcher.py` |
| 7 | low | 1 | 1 | `test_execution_pool_integration.py` |

Parent-spec closure (why "reuse the parent spec" almost always falls through today):

| Feature | Spec `**Status**` | Index `completed_at` |
|---|---|---|
| FEAT-551 | `approved` | `2026-09-15T13:46:35+00:00` |
| FEAT-559 | `approved` | `2026-09-16T09:21:54+00:00` |
| FEAT-560 | `approved` | `2026-09-15T23:44:12+00:00` |

Across the repo: 443 specs read `**Status**: approved` and only 7 read `implemented`,
while **373 of 458** per-spec indexes carry `completed_at`. The closure test must key on
the **index's `completed_at`**, never on the spec's `Status` field.

### Does NOT Exist (Anti-Hallucination)

- ~~`/sdd-fix`~~ — no `.claude/commands/sdd-fix.md`, no `.agent/workflows/sdd-fix.md`,
  no `.agents/skills/sdd-fix/SKILL.md`. This feature creates all three.
- ~~`wikitoolkit ledger plan-fix`~~ — not a subcommand. The `ledger` group at
  `cli.py:2639` has exactly: `open`, `ready`, `claim`, `acknowledge`, `close`, `context`,
  `blockers`, `export`, `sync`, `rebuild`, `ingest-sdd`, `compact`, `audit`.
- ~~`parrot.knowledge.wiki.ledger.fix_planner`~~ — the module does not exist. The `ledger/`
  package contains: `__init__.py`, `coder_feedback.py`, `coder_reviews.py`,
  `coder_suspensions.py`, `events.py`, `index.py`, `log.py`, `sdd_ingest.py`,
  `sdd_meta.py`, `service.py`, `store.py`.
- ~~`LedgerService.close_issue(..., resolved_by=...)`~~ — **the parameter does not exist.**
  `service.py:235-246` builds `payload={"reason": reason, "closed_by": actor}` and drops
  `resolved_by` even though `IssueClosedPayload` (`events.py:52`) and
  `_apply_issue_closed` (`index.py:209-219`) both support it. This is a real gap to close.
- ~~`wikitoolkit ledger close --resolved-by`~~ — no such flag (`cli.py:2730-2746`).
- ~~severity ordering in `ready_work()`~~ — `service.py:199-207` applies no sort; there is
  **no `SEVERITY_ORDER` constant anywhere** in `ledger/`.
- ~~`claimed_by` filtering in `ready_work()`~~ — the docstring says "unclaimed" but the
  predicate tests only `status == "open"`. It is correct *because* claiming flips
  `status` to `"claimed"`, not because `claimed_by` is checked. Do not "fix" it.
- ~~`issue.unclaimed` event kind~~ — **not in `LedgerEventKind`**, which is a closed
  `Literal` of exactly 11 members (`events.py:7-19`): `issue.opened`, `issue.claimed`,
  `issue.acknowledged`, `issue.closed`, `issue.superseded`, `issue.linked`, `task.started`,
  `task.closed`, `spec.registered`, `insight.recorded`, `insight.superseded`. There is also
  no `_apply_issue_unclaimed` reducer. This feature adds both. Note `issue.superseded`
  exists but is **not** a release — it sets `status="superseded"`, a terminal state.
- ~~`LedgerService.unclaim()`~~ — no such method (`service.py` has `claim` at :209 and
  `close_issue` at :235, nothing in between releases a claim).
- ~~`wikitoolkit ledger related`~~ — deliberately absent (FEAT-566 §2.3: "There is no
  separate `wikitoolkit ledger related` traverser"). Use `wiki_related` / `wiki_query`.
- ~~`sdd/fixes/`~~ — no such directory or artifact type; the SDD lane reuses
  `sdd/specs/` + `sdd/tasks/index/`.
- ~~`ledger_blockers` / `ledger_acknowledge` MCP tools~~ — only five ledger tools are
  registered (`tools.py:777-781`); `blockers` and `acknowledge` are CLI-only today.
- ~~`parrot/` at the repo root~~ — this is a uv workspace; core source is
  `packages/ai-parrot/src/parrot/`.

---

## Parallelism Assessment

- **Internal parallelism**: high. Four independent tracks: (1) `fix_planner.py` + its unit
  tests — pure, no dependencies; (2) the `resolved_by` service/CLI plumbing — two small
  diffs in `service.py` and `cli.py`; (3) `ledger plan-fix` wiring; (4) the three twin
  markdown files + `TestFixTwins`. Tracks 1 and 2 touch disjoint files and can run
  concurrently; 3 depends on 1; 4 depends on 3 for the JSON contract.
- **Cross-feature independence**: good, with one watch item. `cli.py` and `service.py` are
  shared with any in-flight FEAT-566 follow-up; nothing else in `sdd/specs/` currently
  targets `ledger/`. The twin markdown files are exclusively owned by this feature. No
  in-flight spec touches `fix_planner.py` (it is new).
- **Recommended isolation**: `per-spec` — one worktree, tasks sequential.
- **Rationale**: the parallel tracks are small (a pure module, two one-line-ish plumbing
  diffs, three markdown twins) and two of them converge on `cli.py`'s `ledger` group.
  Coordination cost across sub-worktrees would exceed the wall-clock saved, and the twin
  parity test needs all three twins present in one tree to pass.

---

## Open Questions

<!-- Convention: [x] = resolved, answer appended after the final `:` on the owner line. -->

- [x] Flow type and base branch — *Owner: Jesus*: `type: feature`, `base_branch: dev`.
- [x] Does `/sdd-fix` always run the full SDD pipeline? — *Owner: Jesus*: no — triage by
  weight, with a deterministic predicate routing trivial issues to a fast lane.
- [x] Relationship to `/sdd-next` + `/sdd-task --from-issue` — *Owner: Jesus*: `/sdd-fix`
  **replaces** `--from-issue` as the ledger entry point; `/sdd-next` retargets to it.
- [x] One issue per invocation or grouped? — *Owner: Jesus*: grouped by file/symbol;
  measured as 7 connected components over today's 15 issues.
- [x] Which artifacts does the SDD lane generate? — *Owner: Jesus*: reuse the parent spec
  when it exists and is still open; mint a new `FEAT-<NNN>` only when the parent is closed.
- [x] Who decides the lane? — *Owner: Jesus*: a deterministic predicate with a `--lane`
  override.
- [x] Partial group fix — *Owner: Jesus*: selective close by evidence; unfixed issues
  return to selectable state.
- [x] Interactive only, or agent-consumable? — *Owner: Jesus*: both — interactive picker
  by default, deterministic non-interactive selection for unattended use.
- [x] **Closure test for "parent spec still open"** — *Owner: Jesus*: the test is
  `sdd/tasks/index/<slug>.json` → `completed_at is None`, **never** the spec's `**Status**`
  field (a dead signal: 443 `approved` vs 7 `implemented`, while 373/458 indexes carry
  `completed_at`). A closed parent is **never reopened** — `/sdd-done` already stamped and
  merged it, its worktree is gone, and re-opening a finished index would require re-running
  the whole closure. The group mints a fresh `FEAT-<NNN>` instead, and its spec cites the
  parent in Motivation. Accepted consequence: on today's ledger all three parent specs
  (FEAT-551/559/560) are closed, so **every current group takes the new-FEAT path** — the
  reuse branch exists for issues discovered against a feature still in flight, which is the
  steady state once `/sdd-fix` runs continuously.
- [x] **Exact lane predicate thresholds** — *Owner: Jesus*: ship the proposed rule
  unchanged, evaluated per **group** (not per issue) on the group's maximum severity:
  `critical | major → SDD`; `kind == vulnerability` at any severity `→ SDD`; empty `about`
  `→ SDD`; `(minor | low) AND every issue kind == tech_debt AND |files| <= 1 → FAST`;
  everything else `→ SDD`. Not widened to `|files| <= 2` and `bug` does not qualify for
  FAST: the cost of a wrong FAST route (a real fix landing without a spec or review) is
  strictly higher than the cost of a wrong SDD route (ceremony). On today's data this
  routes groups 5, 6 and 7 — 3 of 15 issues — to the fast lane. Thresholds live in the
  planner as named constants so retuning is a one-line diff plus a test, never a prose edit.
- [x] **How is "fixed" attributed to an individual issue** — *Owner: Jesus*: two keys,
  fail-closed — explicit per-issue assertion by the implementing agent **AND** at least one
  of that issue's `about` files present in the final diff. Neither key alone may close an
  issue. Rejected (a)-alone as unfalsifiable and (b)-alone as over-claiming: 7 of 15 current
  issues share a file with another issue, so file overlap would close neighbours that were
  never touched. Per-commit-per-issue (option c) was rejected as a constraint on how the
  fix is authored rather than on what is proven.
- [x] **What returns a claimed-but-unfixed issue to selectable state** — *Owner: Jesus*:
  add an `issue.unclaimed` event kind (`claimed → open`, `claimed_by` cleared). This is the
  additive path the ledger was designed for — `apply_event` ignores unknown kinds precisely
  "so replay never breaks on a future event kind it doesn't own yet" (`index.py:120-122`),
  and `IssueStatus` already contains both endpoints, so nothing about the stored shape
  changes. Rejected close-and-reopen (loses the deterministic `compute_issue_id` identity
  and pollutes the closed set with non-fixes) and leaving it claimed with a note (a crashed
  session would strand the issue out of `ready_work()` forever, which is exactly today's
  stall in a new form).
- [x] **Deprecation window for `/sdd-task --from-issue`** — *Owner: Jesus*: keep it working
  for one cycle with a pointer to `/sdd-fix` in all three twins; do not remove it in this
  feature. Removing a documented flag in the same change that introduces its replacement
  gives operators no overlap, and `/sdd-fix`'s lane routing is a heuristic that may need a
  tuning pass before it is the only door. Removal is a separate, trivial follow-up.
- [x] **Should `ledger blockers` / `ledger acknowledge` become MCP tools here** — *Owner:
  Jesus*: no — out of scope for this feature. `/sdd-fix` runs from the CLI and needs
  neither: it never acknowledges (human-only, `service.py:213-234`) and never gates a merge
  (that stays `/sdd-done`'s job). Bundling MCP surface into the fix lane would couple two
  unrelated risks — and any `acknowledge` tool must first carry
  `routing_meta["requires_confirmation"]` (the `ObsidianToolkit` precedent at
  `mcp_server.py:218`), or an agent could un-gate its own merge. Tracked as a separate
  ledger-MCP-surface proposal.

### Deferred to `/sdd-spec`

Not blocking, but the spec must settle them:

- [ ] Exact JSON schema of `FixPlan` / `FixGroup` (the twin↔planner contract).
- [ ] Group naming for the SDD lane's slug — derived from the dominant file's module, or
  authored by the agent from the group's titles? — *Owner: spec*
- [ ] Whether the fast lane opens a PR or pushes straight to `dev` for a one-line comment
  deletion, given `worktree-management.md` §5 requires a PR for the ad-hoc lane. — *Owner: spec*
