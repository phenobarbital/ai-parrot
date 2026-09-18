---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: `/sdd-fix` — Ledger-Driven Fix Lane

**Feature ID**: FEAT-572
**Date**: 2026-09-18
**Author**: Jesus Lara (drafted with Claude)
**Status**: approved
**Target version**: next minor of `ai-parrot`

---

## 1. Motivation & Business Requirements

### Problem Statement

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

Every one was discovered by a feature that has since merged and closed: `FEAT-551`
(`completed_at: 2026-09-15T13:46:35Z`), `FEAT-559` (`2026-09-16T09:21:54Z`), `FEAT-560`
(`2026-09-15T23:44:12Z`). Their worktrees are gone and their per-spec indexes are stamped.

Four mechanisms cause the stall:

1. **No severity ordering.** `LedgerService.ready_work()` (`ledger/service.py:199-207`)
   filters `status == "open"` and returns rows in index order; `wikitoolkit ledger ready`
   prints that order verbatim (`cli.py:2681-2695`). A `low` "leftover comment" can print
   above a `major` aiohttp session leak.
2. **The only promotion path needs a live parent spec.** `/sdd-next` suggests
   `/sdd-task --from-issue <issue-id> <spec.md>` (`sdd-next.md:107`), which seeds a task
   *inside an existing spec's* per-spec index (`sdd-task.md:234-241`). For all 15 current
   issues the parent index already carries `completed_at`, so the suggestion would append
   a task to a finished feature. **Orphaned issues have no route at all.**
3. **Uniform ceremony for non-uniform work.** The pipeline is right for
   `issue:a9514c9232ad` (unclosed aiohttp sessions across two files) and absurd for
   `issue:337359a3ec81` ("Leftover exploratory comment in `RecentActivityCache.seen()`").
   Facing ~6 SDD commits to delete one comment, an operator does neither.
4. **Closing an issue loses the evidence.** `IssueClosedPayload` carries
   `resolved_by: str | None` (`ledger/events.py:52`) and `_apply_issue_closed` persists it
   (`ledger/index.py:209-219`) — but `LedgerService.close_issue()` (`service.py:235-246`)
   builds `{"reason": ..., "closed_by": actor}` and **never passes `resolved_by`**; the CLI
   (`cli.py:2730-2746`) has no `--resolved-by` flag. A close is an unfalsifiable assertion.

### Goals

- Order ready ledger issues by a canonical severity order, with the ordering defined **once**
  in Python rather than restated in each of three workflow twins.
- Group related issues into one unit of work by **connected components** over the
  issue↔file graph derived from each issue's `about` symbol ids — 15 issues collapse to
  **7 groups** on today's data.
- Route each group to a lane by a **deterministic predicate** with an explicit `--lane`
  override, so that trivial debt costs a branch and a commit while substantial work keeps
  the full SDD pipeline.
- Give an orphaned issue (parent feature closed) a first-class route to a fix.
- Make a closed issue **falsifiable**: every close records `resolved_by`.
- Let a claimed-but-unfixed issue return to the ready pool without losing its identity.
- Serve both an interactive operator and an unattended agent from the same plan.

### Non-Goals (explicitly out of scope)

- **Exposing `ledger blockers` / `ledger acknowledge` as MCP tools.** `/sdd-fix` runs from
  the CLI and needs neither; `acknowledge` is human-only (`service.py:213-234`) and any
  MCP form must first carry `routing_meta["requires_confirmation"]` (the `ObsidianToolkit`
  precedent, `mcp_server.py:218`). Tracked separately.
- **An autonomous burndown flow.** Modelling the fix lane as an `AgentsFlow` DAG under
  `parrot/flows/` was rejected in brainstorm — see
  `sdd/proposals/sdd-fix-ledger-lane.brainstorm.md` Option D. The `--json` plan this spec
  produces is the input such a flow would later consume.
- **Changing the merge gate.** `/sdd-done`'s `ledger blockers` call and the
  human-only `acknowledge` path are untouched.
- **A new artifact type.** A `sdd/fixes/<id>.fix.md` kind was rejected in brainstorm
  (Option B discussion) — the SDD lane reuses `sdd/specs/` + `sdd/tasks/index/`.
- **Removing `/sdd-task --from-issue`** in this feature (one deprecation cycle; see §8).
- Multi-machine ledger sync, new storage backends, or any change to FEAT-566's
  `events.jsonl` durability model.

---

## 2. Architectural Design

### Overview

Everything algorithmic lives in one **pure** module,
`parrot/knowledge/wiki/ledger/fix_planner.py`, and nothing I/O-shaped does. It owns a
canonical `SEVERITY_ORDER`, the connected-component grouping, and the lane predicate, and
it returns a `FixPlan` Pydantic model. It is exposed as
`wikitoolkit ledger plan-fix --json`, which the three `/sdd-fix` twins call and parse —
so the twins may drift in wording without drifting in behaviour, because all three execute
the same binary over the same contract.

Three surgical additions to the existing ledger close the gaps the lane needs:

- a twelfth event kind, `issue.unclaimed`, reverting `claimed → open` and clearing
  `claimed_by` — additive by construction, because `apply_event` already ignores unknown
  kinds "so replay never breaks on a future event kind it doesn't own yet"
  (`index.py:120-122`);
- `LedgerService.unclaim()` to emit it, and `LedgerService.close_issue(..., resolved_by=)`
  to finally populate the field the payload has always had;
- `wikitoolkit ledger close --resolved-by` and `wikitoolkit ledger unclaim` to reach both
  from the command layer.

The lane predicate is evaluated **per group**, on the group's maximum severity:

```
critical | major                                              → SDD
kind == vulnerability  (any severity)                         → SDD
about empty (no file scope)                                   → SDD
(minor | low) AND every issue kind == tech_debt AND |files|<=1 → FAST
otherwise                                                     → SDD
```

Asymmetric on purpose: a wrong FAST route lands a real fix without spec or review; a wrong
SDD route only costs ceremony. Thresholds are named constants in the planner, so retuning
is a one-line diff plus a test — never a prose edit in three files.

**Fast lane — always a PR.** Branch `fix/<issue-short-id>-<slug>` off `origin/dev` in the
main checkout (no worktree; `worktree-management.md` §2 explicitly excludes single-commit
fixes), edit, run the affected package's tests, commit, push, then
`gh pr create --base dev`. There is **no direct-push path**, not even for a one-line
comment deletion: `worktree-management.md` §5 requires a PR for the ad-hoc lane, and the
repository already lands exactly this branch shape that way (`fix/ci-test-core-drift`
PR #1408, `fix/ci-test-core-arxiv-annotations` PR #1414). Issues close with
`--resolved-by commit:<merge-sha>`.

**SDD lane** — reuse the parent spec when its per-spec index has **no** `completed_at`;
otherwise reserve a fresh `FEAT-<NNN>`, author a spec from the group, decompose it, and
create `feat-FEAT-<NNN>-<slug>` via `ensure_worktree`. `/sdd-done <FEAT-ID>` closes it out
unchanged. The twin never reads `sdd/tasks/index/` itself — the plan already carries
`FixGroup.parents[].open`, resolved once by the CLI (below).

**Purity boundary.** The planner is pure, so every filesystem fact reaches it as an
argument. The CLI resolves the two it needs and passes them down: per-parent
`completed_at` (via a new `LedgerService.feature_index_status()`, sibling to
`_feature_task_ids`, `service.py:311`), and — for the slug — the planner emits a
*deterministic* `suggested_slug` derived from the group's dominant file, while
**collision suffixing against existing `sdd/specs/*.spec.md` happens in the CLI**, because
listing that directory is I/O. A slug is therefore reproducible from the plan's input
alone; only its uniqueness depends on the working tree.

**A group schedules work; every issue opens, closes and releases individually.** A
connected component proves shared anchors, not a shared root cause — the group exists to
co-locate edits and avoid conflicting diffs, never to authorize a bulk close (S8).

**The plan is a snapshot; the claim is authoritative.** `ready_work()` is a best-effort
read (`service.py:200`) while `claim_issue()` is the atomic check inside one
`ledger.claim` transaction (`index.py:384-445`). `/sdd-fix` claims immediately before
executing, drops any issue whose claim returns `False` and continues with the rest, and
**never closes an issue merely because an earlier plan listed it** (S3).

**Closing is two keys, fail-closed.** An issue closes only when the implementing agent
explicitly asserts that issue id as resolved **and** at least one of the issue's `about`
files appears in the final diff. Assertion alone is unfalsifiable; file overlap alone
over-claims — 7 of today's 15 issues share a file with another issue. Issues failing
either key are released with `issue.unclaimed`, not closed and not left claimed.

### Component Diagram

```
        ┌──────────────────────── main checkout ─────────────────────────┐
        │                                                                │
  /sdd-fix (3 twins)                                                     │
   .claude/commands/sdd-fix.md                                           │
   .agent/workflows/sdd-fix.md   ──┐                                     │
   .agents/skills/sdd-fix/SKILL.md │  subprocess + JSON                   │
                                   ▼                                     │
                    wikitoolkit ledger plan-fix --json                   │
                                   │                                     │
                                   ▼                                     │
              ┌────────────────────────────────────────┐                 │
              │  fix_planner.py   (PURE — no I/O)      │                 │
              │   SEVERITY_ORDER                       │                 │
              │   group_issues()   → connected comps   │                 │
              │   decide_lane()    → "fast" | "sdd"    │                 │
              │   plan_fix_batch() → FixPlan           │                 │
              └───────────────▲────────────────────────┘                 │
                              │ list[dict] from ready_work()             │
              ┌───────────────┴────────────────────────┐                 │
              │  LedgerService  (existing facade)      │                 │
              │   ready_work · claim · get_context     │                 │
              │   close_issue(resolved_by=…)   NEW arg │                 │
              │   unclaim()                    NEW     │                 │
              └───────────────▲────────────────────────┘                 │
                              │                                          │
         ┌────────────────────┴───────────────────┐                      │
         │ events.jsonl (durable)  ledger.db      │                      │
         │  + kind "issue.unclaimed"  (12th)      │                      │
         │  + _apply_issue_unclaimed reducer      │                      │
         └────────────────────────────────────────┘                      │
                                                                         │
   lane=fast → branch fix/<id>-<slug> ─────────────┐                      │
   lane=sdd  → reserve_ids → /sdd-spec → /sdd-task │→ ensure_worktree     │
        └────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LedgerService` (`ledger/service.py:96`) | extends | new `unclaim()`; `close_issue` gains `resolved_by` |
| `LedgerService.ready_work()` (`:199`) | uses | sole input to the planner; unchanged |
| `LedgerService.get_context()` (`:247`) | uses | primes the lane with issues touching the group's files |
| `LedgerIndex.apply_event()` (`index.py:102`) | modifies | one new `elif` branch |
| `LedgerEventKind` (`events.py:7-19`) | modifies | 11 → 12 members |
| `wikitoolkit ledger` group (`cli.py:2639`) | extends | `plan-fix`, `unclaim`, `close --resolved-by` |
| `scripts/sdd/ensure_worktree.py:48` | uses | SDD lane worktree creation (unchanged) |
| `scripts/sdd/reserve_ids.py:468` | uses | SDD lane `FEAT-<NNN>` reservation (unchanged) |
| `plan_worktree()` (`ledger/sdd_meta.py:178`) | uses | canonical worktree naming (unchanged) |
| `/sdd-next` (+2 twins) | modifies | "Ready ledger issues" retargets to `/sdd-fix` |
| `/sdd-task --from-issue` (+2 twins) | modifies | deprecation pointer only |
| `/sdd-done` | unchanged | blockers gate and snapshot keep working as-is |

### Data Models

```python
# parrot/knowledge/wiki/ledger/events.py  (modifies — S6: shared, not planner-local)
SEVERITY_ORDER: Final[dict[IssueSeverity, int]] = {
    "critical": 0, "major": 1, "minor": 2, "low": 3,
}

# parrot/knowledge/wiki/ledger/fix_planner.py  (new)
PLANNER_VERSION: Final[str] = "1"          # S2 — bump on any contract change
FAST_LANE_MAX_FILES: Final[int] = 1
FAST_LANE_KINDS: Final[frozenset[IssueKind]] = frozenset({"tech_debt"})
FAST_LANE_SEVERITIES: Final[frozenset[IssueSeverity]] = frozenset({"minor", "low"})
ALWAYS_SDD_KINDS: Final[frozenset[IssueKind]] = frozenset({"vulnerability"})
CODE_PATH_EXCLUDE_PREFIXES: Final[tuple[str, ...]] = ("sdd/", "docs/")

Lane = Literal["fast", "sdd"]


class FixIssue(BaseModel):
    """One ledger issue as the planner sees it (a projection of `_issue_dict`)."""

    issue_id: str
    title: str
    kind: IssueKind
    severity: IssueSeverity
    discovered_from: str | None = None
    about: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class ParentFeature(BaseModel):
    """A feature that discovered issues in this group, and whether it is still open.

    `completed_at` is the per-spec index's stamp, NOT the spec's `**Status**`
    field — 443 specs read `approved` while only 7 read `implemented`, whereas
    373 of 458 indexes carry `completed_at`. `open` is exactly
    `completed_at is None` and is what the SDD lane branches on.
    """

    feature_id: str
    completed_at: str | None = None
    open: bool = False


class FixGroup(BaseModel):
    """A connected component of issues sharing at least one code file."""

    group_id: str
    issues: list[FixIssue]
    files: list[str]
    max_severity: IssueSeverity
    lane: Lane
    lane_reason: str
    suggested_slug: str
    parents: list[ParentFeature] = Field(default_factory=list)


class FixPlan(BaseModel):
    """The full, ordered plan the twins render and execute.

    `groups` is deterministic: two runs over the same input produce a
    byte-identical `groups` serialization. `generated_at` is provenance and is
    the only non-deterministic field — consumers comparing plans exclude it
    (S2). `planner_version` bumps on any change to the contract's shape or to
    the ordering/lane rules, so a consumer can refuse a plan it cannot read.
    """

    planner_version: str = PLANNER_VERSION
    generated_at: str
    total_open: int
    groups: list[FixGroup]
    filters: dict[str, str | None] = Field(default_factory=dict)
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/ledger/fix_planner.py
def plan_fix_batch(
    issues: Sequence[Mapping[str, Any]],
    *,
    kind: IssueKind | None = None,
    severity: IssueSeverity | None = None,
    lane_override: Lane | None = None,
    generated_at: str | None = None,
) -> FixPlan: ...

# parrot/knowledge/wiki/ledger/service.py
async def unclaim(self, issue_id: str, reason: str, actor: str) -> bool: ...
async def close_issue(
    self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None
) -> bool: ...
```

CLI surface:

```
wikitoolkit ledger plan-fix [--kind K] [--severity S] [--lane fast|sdd] [--json]
wikitoolkit ledger unclaim <issue-id> --reason TEXT [--actor A]
wikitoolkit ledger close <issue-id> --reason TEXT [--actor A] [--resolved-by REF]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: fix_planner | yes | All models, constants and function signatures fixed in §2; pure, no I/O; union-find over `(issue, file)` edges | — |
| M2: unclaimed event + severity order | yes | Literal member, reducer name, state transition, edge and `SEVERITY_ORDER` placement all fixed below | — |
| M3: service methods | yes | Both signatures fixed; payload shapes come from existing Pydantic models | — |
| M4: CLI + MCP close | yes | Flags, output shape and `_run` pattern fixed; the MCP tool change is one arg on an existing signature | — |
| M5: `/sdd-fix` twins | no | Prose authored per platform; the *procedure* is fixed but the wording is not mechanical | — |
| M6: twin parity tests | yes | Test class shape mirrors `TestCodereviewTwins` exactly | — |

### Module 1: Fix planner (pure)
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py` (new)
- **Responsibility**: Severity ordering, file extraction from `about`, connected-component
  grouping, lane decision, `FixPlan` assembly. No I/O, no async, no store access.
- **Depends on**: `ledger/events.py` (`IssueKind`, `IssueSeverity`) only.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py  (new)
  from parrot.knowledge.wiki.ledger.events import IssueKind, IssueSeverity  # verified: ledger/events.py:21,22

  def files_for(about: Sequence[str]) -> list[str]:
      """Extract repo-relative code paths from `about` symbol ids.

      This is the ONLY grouping contract. `LedgerService.get_context()` matches
      by bidirectional substring (`any(target in scope or scope in target ...)`,
      verified: ledger/service.py:271) — fine for priming a superset of context,
      unusable for grouping. Pass this function's output (full repo-relative
      paths) to `get_context`, never a bare basename (S1).

      `sym:<path>#<qualname>` → `<path>`; a bare `sym:<path>` → `<path>`.
      Paths under CODE_PATH_EXCLUDE_PREFIXES are dropped (a spec or doc is
      context, never a grouping edge — one live issue lists
      `sym:sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`). Ids without the
      `sym:` prefix are ignored. Result is sorted and deduplicated.
      """

  def group_issues(issues: Sequence[FixIssue]) -> list[FixGroup]:
      """Partition issues into connected components of the issue↔file graph.

      Two issues share a component when they share at least one file, directly
      or transitively. An issue with no files forms its own singleton component.
      Issues inside a group are sorted by SEVERITY_ORDER then issue_id; groups
      are sorted by (SEVERITY_ORDER[max_severity], -len(issues), group_id).
      `lane`/`lane_reason` are left to `decide_lane`.
      """

  def decide_lane(group: FixGroup, *, override: Lane | None = None) -> tuple[Lane, str]:
      """Return the lane for one group plus a one-line human-readable reason.

      `override` short-circuits the heuristic and reports `"forced by --lane"`,
      but it is never a safety bypass (S7). `override == "fast"` raises
      ValueError when the group's max_severity is "critical" (a critical also
      participates in merge_blockers — verified: ledger/service.py:280-310) or
      when any issue in it has kind "vulnerability" — both are unconditional
      SDD kinds in the predicate, so an override must not be the one door
      around review.
      """

  def suggest_slug(group: FixGroup) -> str:
      """Derive a deterministic, kebab-case slug from the group's dominant file.

      Dominant file = the one appearing in the most issues; ties break on the
      sorted path, so the result never depends on iteration order. The stem and
      its parent directory form the base (`.../dev_loop/nodes/development.py` →
      `dev-loop-development`), suffixed by the group's dominant issue kind
      (`tech_debt` → `-tech-debt`, `bug`/`feature_gap`/`vulnerability` →
      `-fixes`). A group with no files falls back to its `group_id`.

      This is PURE and therefore NOT unique: collision suffixing against
      existing `sdd/specs/*.spec.md` is the CLI's job (listing that directory
      is I/O). Same input ⇒ same slug, always.
      """

  def plan_fix_batch(
      issues: Sequence[Mapping[str, Any]],
      *,
      kind: IssueKind | None = None,
      severity: IssueSeverity | None = None,
      lane_override: Lane | None = None,
      parent_index_status: Mapping[str, str | None] | None = None,
      generated_at: str | None = None,
  ) -> FixPlan:
      """Build the ordered, lane-labelled plan from `ready_work()` output.

      `issues` are `_issue_dict` mappings (verified: ledger/service.py:78-93).
      Rows missing `issue_id` or carrying an unknown severity/kind are skipped,
      never raised on — the planner must not be the thing that breaks when the
      ledger grows a field. `generated_at` defaults to an ISO-8601 UTC stamp.

      `parent_index_status` maps `FEAT-<NNN>` → the per-spec index's
      `completed_at` (or None when still open), resolved by the caller because
      reading `sdd/tasks/index/` is I/O. Parent ids come from each issue's
      `discovered_from` (`spec:FEAT-551`, `task:TASK-…`, `review:TASK-…`);
      only the `spec:` form yields a feature id directly. A parent absent from
      the mapping is reported with `completed_at=None, open=False` — unknown is
      NOT treated as open, so a missing index can never silently reopen a
      finished feature.
      """
  ```

### Module 2: `issue.unclaimed` event kind, reducer, and shared severity order
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py` (modifies :7-19,
  :22), `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` (modifies :102-122),
  `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (modifies :199-207)
- **Responsibility**: Add the twelfth event kind, its payload model, and its reduction
  rule; define `SEVERITY_ORDER` beside the `IssueSeverity` Literal it orders and apply it
  in `ready_work()` (S6).
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py  (modifies ledger/events.py:7-19)
  LedgerEventKind = Literal[
      "issue.opened", "issue.claimed", "issue.acknowledged", "issue.closed",
      "issue.superseded", "issue.unclaimed",          # NEW — 12th member
      "issue.linked", "task.started", "task.closed",
      "spec.registered", "insight.recorded", "insight.superseded",
  ]

  class IssueUnclaimedPayload(BaseModel):            # new, mirrors IssueClaimedPayload:35
      """Release a claim so the issue returns to the ready pool."""
      unclaimed_by: str = Field(description="Actor releasing the claim, e.g. agent:sdd-fix")
      reason: str

  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py  (modifies ledger/events.py:22)
  SEVERITY_ORDER: Final[dict[IssueSeverity, int]] = {"critical": 0, "major": 1, "minor": 2, "low": 3}
  """Canonical severity order. Defined HERE, beside the Literal it orders, so
  ready_work(), the planner, `ledger ready` and the MCP ledger_ready tool all
  share one key — S6. Never redefine it in a consumer."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py  (modifies ledger/service.py:199)
  class LedgerService:
      async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:
          """Return unclaimed, open issues sorted by (SEVERITY_ORDER, issue_id).

          The filter predicate is unchanged (verified: ledger/service.py:203-207);
          only the ordering is new. `ledger ready`, `/sdd-next` and the MCP
          ledger_ready tool inherit it for free — leaving them in database-row
          order would preserve the very defect this feature exists to fix (S6).
          """

  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py  (modifies ledger/index.py:102)
  class LedgerIndex:
      async def _apply_issue_unclaimed(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:
          """Revert `claimed → open` and clear `claimed_by`; any other status is a no-op.

          Mirrors _apply_issue_claimed (verified: ledger/index.py:188-197) in
          reverse: reads state via _read_issue, returns without writing unless
          status == "claimed", then writes via _write_issue
          (verified: ledger/index.py:131) and asserts an "unclaimed-by" edge
          through store.add_edges_in (verified: ledger/store.py add_edges_in).
          """
  ```

### Module 3: Service methods — `unclaim()` and evidence-carrying close
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` (modifies :235-246)
- **Responsibility**: Emit `issue.unclaimed`; plumb `resolved_by` into `issue.closed`.
- **Depends on**: Module 2 (the event kind must exist before the service may emit it).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py  (modifies ledger/service.py:235)
  class LedgerService:
      async def close_issue(
          self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None
      ) -> bool:
          """Close an issue, recording the resolver and the evidence reference.

          `resolved_by` is e.g. `commit:<sha>` (fast lane) or `task:TASK-<NNN>`
          (SDD lane) and is carried into IssueClosedPayload.resolved_by
          (verified: ledger/events.py:52), which _apply_issue_closed already
          persists (verified: ledger/index.py:209-219). Default None keeps
          every existing caller behaviourally unchanged.

          Returns False WITHOUT appending when the issue does not exist or its
          status is not in ("open", "claimed") — S5. Today this method appends
          and returns True unconditionally (verified: ledger/service.py:239-246)
          while _apply_issue_closed silently returns for a missing issue
          (verified: ledger/index.py:211-212), so a close of a nonexistent id
          reports success and leaves a permanent event that reduces to nothing.
          Closing an already-closed issue is likewise a no-op returning False,
          which makes double-close detectable instead of silent.
          """

      async def feature_index_status(self, feature_ids: Collection[str]) -> dict[str, str | None]:
          """Map each `FEAT-<NNN>` to its per-spec index `completed_at`, or None if open.

          Sibling of _feature_task_ids (verified: ledger/service.py:311-324) and
          reads the same directory, `self.shared_root / "sdd" / "tasks" / "index"`,
          with the same tolerance: an unreadable or malformed index file is
          skipped, never raised on. A feature with no index file is ABSENT from
          the result — the caller distinguishes "open" (present, None) from
          "unknown" (absent). Scans the directory once for all ids, not once
          per id.
          """

      async def unclaim(self, issue_id: str, reason: str, actor: str) -> bool:
          """Append `issue.unclaimed`, returning the issue to the ready pool.

          Follows the same shape as close_issue (verified: ledger/service.py:235-246):
          build a LedgerEvent, `await asyncio.to_thread(self.log.append, event)`,
          then `await self._sync_best_effort()`. The log write is the durable
          step; index reconciliation is best-effort, exactly as for every other
          issue.* event.
          """
  ```

### Module 4: CLI and MCP close surface
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` (extends the `ledger`
  group at :2639; modifies `ledger close` at :2730-2746),
  `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` (modifies `LedgerCloseInput` and
  `LedgerCloseTool` at :703-719)
- **Responsibility**: `plan-fix`, `unclaim`, and `close --resolved-by` — on **every** close
  surface, the MCP tool included (S4).
- **Depends on**: Module 1 (plan), Module 3 (unclaim/close).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (modifies cli.py:2639 group)
  @ledger.command("plan-fix")
  @click.option("--kind", type=click.Choice(["bug", "tech_debt", "feature_gap", "vulnerability"]), default=None)
  @click.option("--severity", type=click.Choice(["critical", "major", "minor", "low"]), default=None)
  @click.option("--lane", type=click.Choice(["fast", "sdd"]), default=None, help="Force the lane for every group.")
  @click.option("--json", "as_json", is_flag=True, help="Emit the FixPlan as JSON.")
  def ledger_plan_fix(kind: str | None, severity: str | None, lane: str | None, as_json: bool) -> None:
      """Plan a fix batch: severity-ordered, file-grouped, lane-labelled.

      Mirrors `ledger ready` (verified: cli.py:2681-2695): LedgerService.from_root(),
      `_run(...)`, and a WikiStoreBusy guard that degrades to the committed
      snapshot at sdd/ledger/issues.jsonl instead of failing. `--json` prints
      `FixPlan.model_dump_json(indent=2)`; the default prints the human table.

      This command owns BOTH filesystem lookups the pure planner cannot do:

      1. collect the `spec:FEAT-<NNN>` parents out of the ready rows, resolve
         them through `LedgerService.feature_index_status()`, and pass the
         result as `parent_index_status=`;
      2. after planning, de-duplicate each group's `suggested_slug` against the
         existing `sdd/specs/*.spec.md` stems, appending `-2`, `-3`, … in group
         order so the suffixing is itself deterministic.

      Neither lookup is fatal: an unreadable index directory yields an empty
      mapping (every parent then reports `open=False`), and an unreadable specs
      directory skips de-duplication rather than failing the plan.
      """

  @ledger.command("unclaim")
  @click.argument("issue_id")
  @click.option("--reason", required=True, help="Why the claim is being released.")
  @click.option("--actor", default="agent:cli", help="Actor releasing the claim.")
  def ledger_unclaim(issue_id: str, reason: str, actor: str) -> None:
      """Release a claim so the issue returns to `ledger ready`."""

  # modifies cli.py:2730 — one new option, no behaviour change when absent
  @ledger.command("close")
  @click.option("--resolved-by", default=None, help="Evidence ref: commit:<sha> or task:TASK-<NNN>.")
  def ledger_close(issue_id: str, reason: str, actor: str, resolved_by: str | None) -> None:
      """Close an issue with a reason and, when known, the evidence that resolved it."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/tools.py  (modifies tools.py:703-719)
  class LedgerCloseInput(BaseModel):
      issue_id: str
      reason: str
      resolved_by: str | None = None    # NEW — S4

  class LedgerCloseTool(AbstractTool):
      async def _execute(self, issue_id: str, reason: str, resolved_by: str | None = None) -> ToolResult:
          """Close a ledger issue, carrying the evidence reference through.

          Today this calls close_issue(issue_id, reason, "agent:mcp") with no
          resolved_by (verified: tools.py:714-716), so every agent-driven MCP
          close is unverifiable even once the service and CLI are fixed. The
          actor stays "agent:mcp"; only the evidence argument is added.
          """
  ```

### Module 5: `/sdd-fix` command twins and retargeting
- **Path**: `.claude/commands/sdd-fix.md` (new), `.agent/workflows/sdd-fix.md` (new),
  `.agents/skills/sdd-fix/SKILL.md` (new); modifies `.claude/commands/sdd-next.md:96-107`,
  `.claude/commands/sdd-task.md:234-241` and their two twins each.
- **Responsibility**: The operator-facing procedure — call `plan-fix --json`, render the
  picker, claim, prime with `ledger context`, execute the routed lane, close by evidence,
  release the rest.
- **Depends on**: Module 4.
- **Interface Skeleton** *(markdown contract, not Python)*:
  ```markdown
  # /sdd-fix — Ledger-Driven Fix Lane
  ## Usage
  /sdd-fix                         # interactive picker, severity-ordered
  /sdd-fix <issue-id>              # non-interactive, single issue (+ its group)
  /sdd-fix --top N                 # non-interactive, first N groups
  /sdd-fix ... --kind K --severity S --lane fast|sdd
  ## Steps
  1. Plan      — wikitoolkit ledger plan-fix --json   (never parse `ledger ready` text)
  2. Select    — picker, or deterministic resolution from the arguments
  3. Claim     — one `ledger claim` per issue; a False return drops that issue and continues
  4. Prime     — wikitoolkit ledger context <files…> --max-tokens 3000
  5. Route     — fast lane: branch fix/<id>-<slug> → commit → push → `gh pr create --base dev`
                 (ALWAYS a PR; there is no direct-push path)
               — SDD lane: reuse parent when group.parents[].open, else reserve FEAT-<NNN>;
                 slug comes from the plan, never re-derived in the twin
  6. Close     — two keys, fail-closed; `ledger close --resolved-by`
  7. Release   — `ledger unclaim` for every claimed-but-unfixed issue
  ```

### Module 6: Twin parity and lifecycle tests
- **Path**: `tests/sdd/test_ledger_workflow_twins.py` (extends), plus new
  `tests/knowledge/wiki/test_ledger_fix_planner.py` and
  `tests/knowledge/wiki/test_cli_plan_fix.py`
- **Responsibility**: Assert the three twins exist and agree; assert the planner's
  behaviour against real ledger fixtures.
- **Depends on**: Modules 1 and 5.
- **Interface Skeleton**:
  ```python
  # tests/sdd/test_ledger_workflow_twins.py  (extends tests/sdd/test_ledger_workflow_twins.py:38)
  class TestFixTwins:
      """Mirrors TestCodereviewTwins (verified: tests/sdd/test_ledger_workflow_twins.py:38-45)."""
      CLAUDE = ".claude/commands/sdd-fix.md"
      ANTIGRAVITY = ".agent/workflows/sdd-fix.md"
      CODEX = ".agents/skills/sdd-fix/SKILL.md"

      def test_workflow_files_exist(self) -> None: ...
      def test_all_twins_call_plan_fix_json(self) -> None: ...
      def test_all_twins_document_both_lanes(self) -> None: ...
      def test_all_twins_require_resolved_by_on_close(self) -> None: ...
      def test_all_twins_release_unfixed_issues(self) -> None: ...
  ```

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_files_for_strips_sym_prefix_and_qualname` | M1 | `sym:a/b.py#C.m` → `a/b.py` |
| `test_files_for_drops_spec_and_doc_paths` | M1 | `sym:sdd/specs/x.spec.md` yields no file (real case: `issue:27a665e3773c`) |
| `test_files_for_ignores_non_sym_ids` | M1 | a `file:`-prefixed or bare id is ignored, not crashed on |
| `test_severity_order_is_total_and_canonical` | M1 | all four `IssueSeverity` members ordered critical→low |
| `test_group_issues_merges_transitively` | M1 | A↔f1, B↔{f1,f2}, C↔f2 collapse into ONE group |
| `test_group_issues_singleton_when_no_files` | M1 | empty `about` ⇒ its own group |
| `test_group_ordering_is_severity_then_size` | M1 | groups sorted by max severity, then descending size, then id |
| `test_decide_lane_major_goes_sdd` | M1 | severity gate |
| `test_decide_lane_vulnerability_always_sdd` | M1 | `issue:bcd04b2170a0` (minor vulnerability) ⇒ SDD |
| `test_decide_lane_mixed_kind_group_goes_sdd` | M1 | a minor `tech_debt` grouped with a `bug` ⇒ SDD |
| `test_decide_lane_fast_requires_single_file` | M1 | two files ⇒ SDD even when minor tech_debt |
| `test_decide_lane_override_forces_lane` | M1 | `--lane sdd` on a FAST group |
| `test_decide_lane_override_cannot_force_critical_to_fast` | M1 | raises `ValueError` |
| `test_plan_fix_batch_skips_malformed_rows` | M1 | a row with no `issue_id` / unknown severity is dropped, not raised |
| `test_plan_fix_batch_filters_by_kind_and_severity` | M1 | filter arguments applied before grouping |
| `test_unclaimed_reverts_status_and_clears_claimed_by` | M2 | `claimed → open`, `claimed_by is None` |
| `test_unclaimed_on_open_issue_is_noop` | M2 | status untouched, nothing written |
| `test_unclaimed_on_closed_issue_is_noop` | M2 | terminal states unaffected |
| `test_unknown_event_kind_still_ignored` | M2 | regression on `index.py:120-122`'s contract |
| `test_close_issue_persists_resolved_by` | M3 | `resolved_by="commit:abc123"` readable via `_issue_dict` |
| `test_close_issue_without_resolved_by_unchanged` | M3 | back-compat for every existing caller |
| `test_unclaim_appends_event_and_syncs` | M3 | log append + `_sync_best_effort` |
| `test_cli_plan_fix_json_matches_fixplan_schema` | M4 | `--json` round-trips into `FixPlan` |
| `test_cli_plan_fix_busy_falls_back_to_snapshot` | M4 | `WikiStoreBusy` ⇒ snapshot, exit 0 |
| `test_cli_close_accepts_resolved_by` | M4 | flag reaches the service |
| `test_cli_unclaim_roundtrip` | M4 | claim → unclaim → appears in `ready` again |
| `test_mcp_ledger_close_passes_resolved_by` | M4 | `LedgerCloseTool` forwards the evidence ref (S4) |
| `test_mcp_ledger_close_without_resolved_by_unchanged` | M4 | default `None` keeps current behaviour |
| `test_ready_work_is_severity_ordered` | M2 | `ready_work()` returns critical→low, ties by issue_id (S6) |
| `test_ledger_ready_cli_prints_severity_order` | M2 | `ledger ready` inherits the order |
| `test_close_issue_rejects_unknown_issue` | M3 | returns False, appends nothing (S5) |
| `test_close_issue_rejects_already_closed` | M3 | double-close is detectable, not silent (S5) |
| `test_plan_groups_are_byte_deterministic` | M1 | two runs ⇒ identical `groups` JSON, `generated_at` excluded (S2) |
| `test_plan_carries_planner_version` | M1 | `FixPlan.planner_version == PLANNER_VERSION` (S2) |
| `test_decide_lane_override_cannot_force_vulnerability_to_fast` | M1 | raises `ValueError` (S7) |
| `test_suggest_slug_is_deterministic_for_same_input` | M1 | two runs ⇒ identical slug |
| `test_suggest_slug_uses_dominant_file_and_breaks_ties_by_path` | M1 | 4-of-5 `development.py` wins; ties sort by path |
| `test_suggest_slug_falls_back_to_group_id_without_files` | M1 | empty `about` group still gets a slug |
| `test_parents_open_flag_from_index_status` | M1 | `completed_at=None` ⇒ `open=True`; a stamp ⇒ `open=False` |
| `test_parent_absent_from_mapping_is_not_open` | M1 | unknown ≠ open — a missing index cannot reopen a finished feature |
| `test_parents_only_from_spec_prefixed_discovered_from` | M1 | `task:`/`review:` forms yield no parent feature id |
| `test_feature_index_status_scans_index_dir_once` | M3 | one glob for N ids; malformed file skipped |
| `test_feature_index_status_omits_features_without_index` | M3 | absent ≠ present-with-None |
| `test_cli_plan_fix_dedupes_slug_against_existing_specs` | M4 | colliding stem ⇒ `-2`, deterministic in group order |
| `test_cli_plan_fix_survives_unreadable_index_dir` | M4 | empty mapping, plan still emitted |

### Integration Tests

| Test | Description |
|---|---|
| `test_plan_over_committed_snapshot_yields_seven_groups` | `sdd/ledger/issues.jsonl` as fixture ⇒ exactly 7 groups, max severity `major` first |
| `test_claim_group_then_unclaim_returns_all_to_ready` | full claim/release cycle over a multi-issue group |
| `test_partial_close_releases_the_remainder` | 3 of 5 closed with `resolved_by`, 2 unclaimed and visible in the next plan |
| `test_concurrent_plan_and_claim_race` | two claimants, exactly one wins (extends `TestAtomicClaim`, `tests/knowledge/wiki/test_ledger_index.py`) |
| `test_stale_plan_cannot_close_a_reclaimed_issue` | plan → another actor claims and closes → the stale lane closes nothing (S3) |
| `test_all_sdd_next_twins_point_at_sdd_fix` | the three `/sdd-next` twins name `/sdd-fix`, not `--from-issue`, as the ledger entry point (S9) |
| `test_all_twins_require_a_pr_on_the_fast_lane` | no twin documents a direct push to `dev`; all three name `gh pr create --base dev` |
| `test_sdd_lane_reuses_open_parent_and_mints_on_closed` | `open=True` ⇒ no `reserve_ids` call; `open=False` ⇒ a fresh `FEAT-<NNN>` |

### Test Data / Fixtures

```python
# tests/knowledge/wiki/test_ledger_fix_planner.py
@pytest.fixture
def snapshot_issues() -> list[dict]:
    """The committed ledger snapshot — a real, non-synthetic 15-issue corpus."""
    path = Path(__file__).resolve().parents[2] / "sdd" / "ledger" / "issues.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
```

> **Test tree note.** Ledger tests live in the **repo-root `tests/`** tree
> (`tests/knowledge/wiki/`, `tests/sdd/`), which is what `testpaths = ["tests"]` in the
> root `pyproject.toml` collects. `packages/ai-parrot/tests/` contains no ledger tests.
> This is a deliberate, pre-existing deviation from `codebase-conventions.md`'s "tests live
> next to their distribution" — follow the ledger's actual convention, do not relocate.
> The fixture resolves its path from `__file__`, never the process CWD: importing parrot
> modules chdir()s the process (see the same gotcha at
> `tests/sdd/test_ledger_workflow_twins.py:17-24`).

---

## 5. Acceptance Criteria

- [ ] `wikitoolkit ledger plan-fix --json` over the committed snapshot emits a `FixPlan`
      with exactly **7 groups**, the two `major` groups first.
- [ ] `plan-fix` never parses `ledger ready`'s text output; the twins never re-implement
      ordering, grouping or lane logic.
- [ ] `SEVERITY_ORDER` is defined exactly once in the codebase — in `ledger/events.py`,
      beside the `IssueSeverity` Literal — and `ready_work()`, `ledger ready`, `/sdd-next`
      and the MCP `ledger_ready` tool all reflect that order (S6).
- [ ] Two `plan-fix --json` runs over identical input produce byte-identical `groups`
      serializations; `FixPlan.planner_version` is present (S2).
- [ ] A group whose issues include a `vulnerability` cannot be forced to the fast lane
      (`ValueError`) (S7).
- [ ] `close_issue()` returns `False` without appending for an unknown issue or one whose
      status is not `open`/`claimed`; a double close is detectable (S5).
- [ ] The MCP `ledger_close` tool accepts and forwards `resolved_by`; omitting it leaves
      current behaviour unchanged (S4).
- [ ] A stale plan cannot close an issue that another actor has since claimed or closed (S3).
- [ ] `plan_fix_batch` performs **no filesystem access**: every parent `completed_at` and
      the slug arrive as arguments or are derived from the input rows alone.
- [ ] `FixGroup.suggested_slug` is byte-identical across runs over identical input;
      collision suffixes are applied by the CLI and are deterministic in group order.
- [ ] A parent feature with no per-spec index reports `open=False` — an unknown parent
      never causes a finished feature to be reopened.
- [ ] No `/sdd-fix` twin documents a direct push to `dev`; the fast lane always opens a PR
      against `dev` with `gh pr create`.
- [ ] `LedgerService.feature_index_status()` scans `sdd/tasks/index/` once per call
      regardless of how many feature ids are requested.
- [ ] A group whose `max_severity` is `critical` cannot be forced to the fast lane
      (`ValueError`), and `/sdd-fix` never calls `ledger acknowledge`.
- [ ] `LedgerService.close_issue(..., resolved_by="commit:<sha>")` persists `resolved_by`,
      readable back through `_issue_dict`.
- [ ] Existing `close_issue` callers are behaviourally unchanged when `resolved_by` is omitted.
- [ ] `issue.unclaimed` reverts `claimed → open` and clears `claimed_by`; it is a no-op on
      `open`, `closed` and `superseded`.
- [ ] `LedgerEventKind` has 12 members; an unknown kind is still ignored by `apply_event`.
- [ ] A partially fixed group closes only the issues satisfying **both** evidence keys and
      releases the rest via `issue.unclaimed`.
- [ ] `/sdd-fix` exists as all three twins and `TestFixTwins` passes.
- [ ] `/sdd-next`'s "Ready ledger issues" section points at `/sdd-fix` in all three twins.
- [ ] `/sdd-task --from-issue` still works and carries a deprecation pointer in all three twins.
- [ ] `/sdd-done`'s blockers gate and snapshot behaviour are byte-unchanged.
- [ ] A read-only ledger (`EROFS`) makes `/sdd-fix` report and exit non-zero without
      claiming — it never creates a worktree-local ledger.
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_ledger_fix_planner.py
      tests/knowledge/wiki/test_cli_plan_fix.py tests/sdd/test_ledger_workflow_twins.py
      tests/knowledge/wiki/test_ledger_index.py tests/knowledge/wiki/test_ledger_service.py -v`
- [ ] `ruff check` and `black --check -l 120` clean on every changed file.
- [ ] `docs/` gains a short `/sdd-fix` section; `sdd/WORKFLOW.md`'s command table lists it.
- [ ] No new runtime dependency.

---

## 6. Codebase Contract

### Verified Imports

```python
from parrot.knowledge.wiki.ledger.service import LedgerService          # verified: ledger/service.py:96
from parrot.knowledge.wiki.ledger.index import LedgerIndex              # verified: ledger/index.py:85
from parrot.knowledge.wiki.ledger.store import LedgerStore              # verified: ledger/store.py
from parrot.knowledge.wiki.ledger.log import LedgerLog                  # verified: ledger/log.py
from parrot.knowledge.wiki.ledger.events import (                       # verified: ledger/events.py:7,21,22,35,49
    LedgerEvent, LedgerEventKind, IssueKind, IssueSeverity, IssueStatus,
    IssueClaimedPayload, IssueClosedPayload,
)
from parrot.knowledge.wiki.ledger.sdd_meta import plan_worktree, WorktreePlan  # verified: ledger/sdd_meta.py:170,178
from scripts.sdd.sdd_meta import plan_worktree, WorktreePlan            # compat shim: scripts/sdd/sdd_meta.py:10-20
from parrot.knowledge.wiki.project import find_shared_root              # verified: used at mcp_server.py:184
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
class LedgerService:                                                                     # line 96
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None:  # 99
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService":                     # 114
    async def _sync_best_effort(self) -> None:                                           # 143
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]:                     # 150
    async def open_issue(...) -> str:                                                    # 166
    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:   # 199
    async def claim(self, issue_id: str, actor: str) -> bool:                            # 209
    async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool:         # 213
    async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool:         # 235
    async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str:   # 247
    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]:             # 280
    def _feature_task_ids(self, feature_id: str) -> list[str]:                           # 311
    async def export_snapshot(self, dest: Path) -> bool:                                 # 325
    async def compact(self, older_than_days: int = 30) -> int:                           # 353
    async def audit(self) -> dict[str, Any]:                                             # 357

def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:                 # 78
    # keys: issue_id, title, status, kind, severity, acknowledged, discovered_from,
    #       about, claimed_by, closed_by, closed_reason, resolved_by            # 80-93

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:                                                                       # 85
    async def apply_event(self, event: LedgerEvent, conn: "aiosqlite.Connection") -> None:  # 102
    # dispatch chain 109-119; unknown kinds deliberately ignored              # 120-122
    async def _read_issue(self, conn, issue_id: str) -> dict[str, Any] | None:           # 123
    async def _write_issue(self, conn, issue_id: str, state: dict[str, Any],
                           actor: str, ts: str) -> None:                                 # 131
    async def _apply_issue_claimed(self, event, conn) -> None:                           # 188
        # status != "open" ⇒ return; else status="claimed", claimed_by=payload.claimed_by,
        # then store.add_edges_in(conn, [(subject, claimed_by, "claimed-by", "asserted")])
    async def _apply_issue_closed(self, event, conn) -> None:                            # 209
        # sets status/closed_by/closed_reason/resolved_by from IssueClosedPayload
    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:                 # 384

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
LedgerEventKind = Literal[...]   # 11 members                                            # 7-19
IssueKind      = Literal["bug", "tech_debt", "feature_gap", "vulnerability"]             # 21
IssueSeverity  = Literal["critical", "major", "minor", "low"]                            # 22
IssueStatus    = Literal["open", "claimed", "closed", "superseded"]                      # 23
class IssueClaimedPayload(BaseModel):  claimed_by: str                                   # 35-36
class IssueClosedPayload(BaseModel):   reason: str; closed_by: str; resolved_by: str | None = None  # 49-52
class LedgerEvent(BaseModel):  event_id, kind, subject, actor, ts, payload                # 83-92

# packages/ai-parrot/src/parrot/knowledge/wiki/tools.py
class LedgerCloseTool(AbstractTool):                                                     # 703
    name = "ledger_close"; args_schema = LedgerCloseInput                                # 706-708
    async def _execute(self, issue_id: str, reason: str) -> ToolResult:                  # 714
        # calls close_issue(issue_id, reason, "agent:mcp") — NO resolved_by          # 716
# registered with LedgerOpen/Ready/Claim/Context at tools.py:777-781

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py — get_context matching
    #   any(any(target in scope or scope in target for target in file_paths)         # 271
    #       for scope in about)
    # Bidirectional SUBSTRING match. Priming only — never a grouping contract.

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py
class LedgerLog:
    def append(self, event: LedgerEvent) -> tuple[str, int]:
        # single O_APPEND os.write + fsync; raises ValueError above 4 KiB.
        # The RETURNED byte offset is best-effort only under concurrent writers.

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore):
    @asynccontextmanager
    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]: ...
    async def read_cursor(self) -> tuple[int, str | None]: ...
    async def upsert_pages_in(self, conn, pages: list[WikiPageRecord]) -> None: ...
    async def add_edges_in(self, conn, edges: list[tuple]) -> None: ...

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
class WorktreePlan(BaseModel): name: str; path: str; base_ref: str                       # 170
def plan_worktree(meta: FlowMeta, *, slug: str, feature_id: str | None = None,
                  jira_key: str | None = None) -> WorktreePlan:                          # 178

# scripts/sdd/ensure_worktree.py
def ensure(plan: WorktreePlan, *, repo_root: Path, sync: bool = True,
           require_paths: Sequence[str] = (), dry_run: bool = False) -> tuple[Path, bool]:  # 48
# CLI: --slug --feature-id [--jira-key] [--base-branch] [--type] [--no-sync] [--dry-run] [--json]  # 234-247

# scripts/sdd/reserve_ids.py
def existing_feature_id(root: Path, label: str) -> tuple[str, str] | None:               # 420
def reserve_ids(...) -> ...                                                              # 468
# CLI: --kind task|feature --count N --base-branch B --label L [--max-retries]           # 629-633
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `plan_fix_batch()` | `LedgerService.ready_work()` | consumes its `list[dict]` | `ledger/service.py:199` |
| `plan_fix_batch()` | `_issue_dict` key shape | field names `issue_id`/`kind`/`severity`/`about` | `ledger/service.py:78-93` |
| `files_for()` | `IssueOpenedPayload.about` | `sym:<path>#<qualname>` ids | `ledger/events.py:32` |
| `LedgerService.unclaim()` | `LedgerLog.append` | `asyncio.to_thread(self.log.append, event)` | `ledger/service.py:238-245` |
| `_apply_issue_unclaimed` | `LedgerIndex._write_issue` | state upsert in caller's txn | `ledger/index.py:131` |
| `_apply_issue_unclaimed` | `LedgerStore.add_edges_in` | `"unclaimed-by"` asserted edge | `ledger/store.py` |
| `ledger plan-fix` | `LedgerService.from_root()` | same pattern as `ledger ready` | `cli.py:2683` |
| `/sdd-fix` SDD lane | `ensure_worktree.ensure()` | `python -m scripts.sdd.ensure_worktree` | `scripts/sdd/ensure_worktree.py:225` |
| `/sdd-fix` SDD lane | `reserve_ids` | `python -m scripts.sdd.reserve_ids --kind feature` | `scripts/sdd/reserve_ids.py:616` |
| `TestFixTwins` | `read_workflow_file()` | module-level helper | `tests/sdd/test_ledger_workflow_twins.py:27` |

### Does NOT Exist (Anti-Hallucination)

- ~~`/sdd-fix`~~ — no `.claude/commands/sdd-fix.md`, no `.agent/workflows/sdd-fix.md`, no
  `.agents/skills/sdd-fix/SKILL.md`. This feature creates all three.
- ~~`wikitoolkit ledger plan-fix`~~ / ~~`ledger unclaim`~~ — not subcommands. The `ledger`
  group (`cli.py:2639`) has exactly: `open`, `ready`, `claim`, `acknowledge`, `close`,
  `context`, `blockers`, `export`, `sync`, `rebuild`, `ingest-sdd`, `compact`, `audit`.
- ~~`parrot.knowledge.wiki.ledger.fix_planner`~~ — the module does not exist. The `ledger/`
  package contains exactly: `__init__.py`, `coder_feedback.py`, `coder_reviews.py`,
  `coder_suspensions.py`, `events.py`, `index.py`, `log.py`, `sdd_ingest.py`, `sdd_meta.py`,
  `service.py`, `store.py`.
- ~~`issue.unclaimed`~~ — **not** in `LedgerEventKind` (`events.py:7-19`), a closed Literal
  of exactly 11 members. There is no `_apply_issue_unclaimed` reducer and no
  `IssueUnclaimedPayload`. This feature adds all three. Note `issue.superseded` exists but
  is **not** a release — it sets a terminal `status="superseded"`.
- ~~`LedgerService.unclaim()`~~ — no such method (`claim` at :209, `close_issue` at :235,
  nothing between them releases a claim).
- ~~`LedgerService.close_issue(..., resolved_by=...)`~~ — the parameter does not exist;
  `service.py:239-244` builds `payload={"reason": reason, "closed_by": actor}`.
- ~~`wikitoolkit ledger close --resolved-by`~~ — no such flag (`cli.py:2730-2746`).
- ~~`SEVERITY_ORDER`~~ — no canonical severity ordering constant exists anywhere in
  `ledger/`; `ready_work()` applies no sort at all.
- ~~`claimed_by` filtering in `ready_work()`~~ — the docstring says "unclaimed" but the
  predicate tests only `status == "open"`. It is correct *because* `_apply_issue_claimed`
  flips `status` to `"claimed"` (`index.py:195`), not because `claimed_by` is checked.
  **Do not "fix" it.**
- ~~`wikitoolkit ledger related`~~ — deliberately absent (FEAT-566 §2.3).
- ~~`sdd/fixes/`~~ — no such directory or artifact type.
- ~~`ledger_blockers` / `ledger_acknowledge` MCP tools~~ — only five ledger tools are
  registered (`tools.py:777-781`: Open, Ready, Claim, Close, Context).
- ~~`packages/ai-parrot/src/parrot/knowledge/wiki/structural.py`~~ — it is a **package**,
  `structural/tools.py:225` (`create_structural_tools`), not a module file.
- ~~`packages/ai-parrot/tests/knowledge/wiki/test_ledger_*.py`~~ — no ledger tests live
  there; they are all in the repo-root `tests/knowledge/wiki/` tree.
- ~~`parrot/` at the repo root~~ — this is a uv workspace; core source is
  `packages/ai-parrot/src/parrot/`.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **The planner is pure.** No `async`, no store access, no filesystem, no clock except the
  injectable `generated_at`. Everything it needs arrives as a `Sequence[Mapping]`. This is
  what makes it testable against the committed snapshot.
- Pydantic v2 models for `FixIssue` / `FixGroup` / `FixPlan`; Google-style docstrings and
  strict type hints on every function (`.claude/rules/codebase-conventions.md`).
- CLI commands mirror their siblings in `cli.py`: `LedgerService.from_root()`, the
  module-level `_run(...)` helper, `click.echo`, and a `WikiStoreBusy` guard.
- `logging.getLogger(__name__)` — never `print` outside `click.echo` in CLI bodies.
- `black -l 120` formats; `ruff check` is the gate (TID251 bans `requests`/`httpx`/
  LangChain — none are needed here).
- New service methods follow `close_issue`'s exact shape: build `LedgerEvent`, append to
  the log via `asyncio.to_thread`, then `_sync_best_effort()`.

### Known Risks / Gotchas

- **Claim race.** `claim_issue()` returns `False` without appending (`index.py:391-393`).
  The twins must drop that issue and continue, never retry in a loop.
- **`WikiStoreBusy`.** The log write is durable and the index reconciles on the next
  `sync` (FEAT-566 §2.2). `plan-fix` degrades to `sdd/ledger/issues.jsonl` rather than
  failing.
- **Read-only ledger (`EROFS`).** Mirror `/sdd-codereview`'s discipline
  (`sdd-codereview.md:8-11`): do not request broader filesystem access, do not create a
  worktree-local ledger; report and exit.
- **`about` is not purely code.** One live issue lists
  `sym:sdd/specs/dev-loop-pool-exclusive-tasks.spec.md`. Spec/doc paths must not create a
  grouping edge — otherwise two unrelated features sharing a spec reference would merge.
- **Grouping is transitive, and that is load-bearing.** 7 of 15 issues touch more than one
  file, so `development.py` and `task_scheduler.py` merge into a single 5-issue group via
  `issue:8f46e2c1eed1`. Anyone "simplifying" this to a per-file bucket changes the output.
- **Empty `about` ⇒ SDD.** No file scope means no evidence for triviality and no second
  evidence key at close time.
- **`resolved_by` is a default-None addition.** Every existing `close_issue` caller must
  keep compiling and behaving identically.
- **Parent-spec closure is read from `completed_at`, never from the spec's `**Status**`.**
  Across the repo 443 specs read `approved` and only 7 `implemented`, while 373 of 458
  per-spec indexes carry `completed_at`. A closed parent is **never reopened**.
- **Test CWD.** Importing parrot modules chdir()s the process (navconfig side effect);
  fixtures must resolve paths from `__file__`
  (`tests/sdd/test_ledger_workflow_twins.py:17-24`).
- **Worktree test imports.** The shared `.venv` is editable-installed against the main
  checkout, so a bare `pytest` inside a worktree imports the wrong branch. Prefix with
  `PYTHONPATH=packages/ai-parrot/src`; never `uv sync` inside a worktree
  (`worktree-management.md` §4).
- **`close_issue` is currently unconditional.** It appends and returns `True` for any id
  (`service.py:239-246`), and `_apply_issue_closed` returns silently for a missing issue
  (`index.py:211-212`). Adding the existence/status check is a deliberate behaviour change
  to a FEAT-566 API; audit callers (the CLI, the MCP tool, `/sdd-fix`) — note that
  `/sdd-task --from-issue` explicitly never calls close (`sdd-task.md:241`).
- **Ordering `ready_work()` changes existing output.** `ledger ready`, `/sdd-next` and the
  MCP `ledger_ready` tool all start printing severity-ordered. That is the point, but any
  test asserting the old row order must be updated rather than worked around.
- **The purity boundary is load-bearing, and it is easy to erode.** Two filesystem facts
  the planner needs — parent `completed_at` and slug uniqueness — are deliberately resolved
  by the CLI. Moving either into `fix_planner.py` "for convenience" breaks
  `test_plan_groups_are_byte_deterministic` and the snapshot fixtures with it.
- **`discovered_from` only sometimes names a feature.** It is `spec:FEAT-<NNN>`,
  `task:TASK-<NNN>` or `review:TASK-<NNN>` (verified: `ledger/events.py:31`). Only the
  `spec:` form yields a feature id directly; a `task:`/`review:` issue has no parent
  feature in the plan and therefore always takes the new-`FEAT` path.
- **Unknown parent ≠ open parent.** `feature_index_status()` omits features with no index
  file, and the planner reports those as `open=False`. Inverting that default would let a
  missing or renamed index file silently append tasks to a merged feature.
- **Three twins, one behaviour.** Any behavioural statement added to one twin must be added
  to all three, or `TestFixTwins` fails — which is the point.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| — | — | **None.** `pydantic`, `click`, `pytest`, `pytest-asyncio` are already project dependencies. |

---

## 8. Open Questions

- [x] Flow type and base branch — *Resolved in brainstorm*: `type: feature`, `base_branch: dev`.
- [x] Does `/sdd-fix` always run the full SDD pipeline? — *Resolved in brainstorm*: no —
      triage by weight with a deterministic predicate. → §2 Overview, §3 M1.
- [x] Relationship to `/sdd-next` + `/sdd-task --from-issue` — *Resolved in brainstorm*:
      `/sdd-fix` **replaces** `--from-issue` as the ledger entry point. → §3 M5, §5.
- [x] One issue per invocation or grouped? — *Resolved in brainstorm*: grouped by
      file/symbol; 7 connected components over today's 15 issues. → §3 M1 `group_issues`.
- [x] Which artifacts does the SDD lane generate? — *Resolved in brainstorm*: reuse the
      parent spec when still open, else mint a fresh `FEAT-<NNN>`. → §2 Overview, §7.
- [x] Who decides the lane? — *Resolved in brainstorm*: deterministic predicate with a
      `--lane` override. → §2 Overview, §3 M1 `decide_lane`.
- [x] Partial group fix — *Resolved in brainstorm*: selective close by evidence; the rest
      released. → §2 Overview, §3 M2/M3, §5.
- [x] Interactive only, or agent-consumable? — *Resolved in brainstorm*: both. → §3 M5.
- [x] Closure test for "parent spec still open" — *Resolved in brainstorm*:
      `sdd/tasks/index/<slug>.json` → `completed_at is None`, never the spec's `**Status**`;
      a closed parent is never reopened. → §7 Known Risks.
- [x] Exact lane predicate thresholds — *Resolved in brainstorm*: the rule in §2 Overview,
      unchanged; not widened to `|files| <= 2`; `bug` does not qualify for FAST. → §2, §3 M1.
- [x] How is "fixed" attributed to an individual issue — *Resolved in brainstorm*: two keys,
      fail-closed (explicit assertion AND `about`-file present in the diff). → §2 Overview, §5.
- [x] What returns a claimed-but-unfixed issue to selectable state — *Resolved in
      brainstorm*: a new `issue.unclaimed` event kind. → §3 M2/M3.
- [x] MCP surface for `ledger blockers` / `acknowledge` — *Resolved in brainstorm*: out of
      scope, separate proposal. → §1 Non-Goals.
- [x] **Exact JSON schema of `FixPlan` / `FixGroup`** — *Owner: Jesus*: the twins need two
      fields beyond the draft, and both are resolved by the **CLI**, keeping the planner
      pure. `FixGroup.parents: list[ParentFeature]` carries `{feature_id, completed_at,
      open}` from a new `LedgerService.feature_index_status()` (sibling of
      `_feature_task_ids`, `service.py:311`), so no twin ever globs `sdd/tasks/index/`
      itself; and `FixGroup.suggested_slug` carries the name. Rejected having the twin read
      the index (the same logic duplicated in three markdown files — exactly what Option B
      exists to prevent) and having the planner do the I/O (breaks the determinism the
      snapshot fixtures rely on). → §2 Data Models, §3 M1/M3/M4, §5.
- [x] **Group slug naming for the SDD lane** — *Owner: Jesus*: derived deterministically by
      the planner from the group's dominant file (most issues; ties break on the sorted
      path), as `<parent-dir>-<stem>-<dominant-kind>`. Agent-authored slugs were rejected
      because they are not reproducible and would break
      `test_plan_groups_are_byte_deterministic`. **Uniqueness is separate from derivation**:
      collision suffixing against existing `sdd/specs/*.spec.md` stems is the CLI's job,
      since listing that directory is I/O. → §3 M1 `suggest_slug`, §3 M4, §5.
- [x] **Fast lane: PR or direct push to `dev`?** — *Owner: Jesus*: **always a PR**, no
      exception and no `--no-pr` escape. `worktree-management.md` §5 requires it for the
      ad-hoc lane, and the repository already lands this exact branch shape that way —
      `fix/ci-test-core-drift` (PR #1408) and `fix/ci-test-core-arxiv-annotations`
      (PR #1414). Confirms design research S10, which was escalated rather than decided:
      "The open question about pushing directly to `dev` conflicts with existing workflow
      rules: `/sdd-done` defaults to a PR, hotfixes targeting `main` must use a PR, and
      worktrees use canonical branch/base naming." → §2 Overview, §3 M5, §5.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc**
> (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.154.0, reasoning_effort=high)
> · Status: completed · Transcript: `sdd/state/FEAT-572/design_research/`
> The brief carried the accepted brainstorm plus 19 verified code anchors — no spec draft,
> no author reasoning. All 33 `affected_paths` entries passed repo containment and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define canonical file extraction from `about` anchors (architecture) | CONFIRM | Already the design (`files_for`), but its claim that `get_context()` matches by substring is true and material — `service.py:271` does `any(target in scope or scope in target ...)`. Harmless for priming, unusable as a grouping contract; the distinction is now stated, and `files_for` output (full repo-relative paths) is what may be passed to `get_context`, never a bare basename. | §3 M1, §7 |
| S2 | Version the FixPlan JSON contract and make it deterministic (api) | CONFIRM (partial) | Adopted `planner_version`; rejected removing `generated_at`, which is real provenance. Determinism is instead pinned where it matters: `groups` must be byte-identical across runs over the same input, and an acceptance criterion asserts it with `generated_at` excluded from the comparison. | §2 Data Models, §5 |
| S3 | Treat planning as a snapshot, never as a claim (risk) | CONFIRM | The plan/claim split was already stated, but only as a claim-race note. Strengthened into a rule: never close an issue because an earlier plan listed it; a `False` claim drops that issue and the group continues. | §2 Overview, §7 |
| S4 | Propagate `resolved_by` through every close surface (api) | CONFIRM | Verified and materially new: `LedgerCloseTool._execute(issue_id, reason)` calls `close_issue(..., "agent:mcp")` with no `resolved_by`, and `LedgerCloseInput` has no such field (`tools.py:714-717`). Fixing only service + CLI would leave every agent-driven MCP close unverifiable. Module 4 now covers the MCP tool too. | §2 Integration Points, §3 M4, §5, §6 |
| S5 | Prevent arbitrary or duplicate closure in the fix lane (risk) | CONFIRM | Verified: `close_issue()` appends and returns `True` unconditionally (`service.py:239-246`), while `_apply_issue_closed` silently returns when the issue does not exist (`index.py:211-212`) — so closing a nonexistent issue reports success and leaves a permanent no-op event. `close_issue` now verifies existence and `status in ("open","claimed")`, and the fix lane closes as the claimant. | §3 M3, §5, §7 |
| S6 | Share severity ordering with `ready_work` and all consumers (architecture) | CONFIRM | The strongest finding. The spec's own goal is a canonical order, yet putting `SEVERITY_ORDER` in the planner alone leaves `ledger ready`, `/sdd-next` and the MCP `ledger_ready` tool in database-row order — the exact defect being fixed, still visible on the path most operators use. The constant moves to `events.py` beside the Literal it orders, and `ready_work()` sorts by it. | §2 Data Models, §3 M2, §5 |
| S7 | Make fast-lane overrides subject to hard safety constraints (risk) | CONFIRM | The draft guarded only `critical` against `--lane fast`. Extended to `vulnerability` at any severity: it is already an unconditional SDD kind in the predicate, so letting an override bypass it would make the flag the one way to route a security issue around review. | §3 M1 `decide_lane`, §5 |
| S8 | Use groups for scheduling, not bulk closure (alternative) | CONFIRM | Agrees with the two-key close already specified; adopted as an explicit invariant rather than an emergent property — "a group schedules work; every issue opens, closes and releases individually" is now stated where a reader looking for a bulk-close shortcut would find it. | §2 Overview |
| S9 | Test the complete twin contract and concurrent paths (testing) | CONFIRM (partial) | Golden planner tests over real ledger rows, CLI exit-code tests and the three-file twin matrix were already specified. Added what was missing: twins asserted to *invoke* `plan-fix --json` (not merely mention it), a concurrent-claim integration test, and `/sdd-next` twin retarget assertions. | §4 |
| S10 | Resolve fast-lane delivery semantics before implementation (risk) | ESCALATE | Correctly identifies that "push straight to `dev`" conflicts with the ad-hoc lane's PR requirement. It is already §8 Q3 and it is the user's call, not the reviewer's — its argument is recorded verbatim in that question rather than silently decided. The adjacent point (the plan should carry flow/base-branch metadata and reuse `plan_worktree()`/`ensure()`) is folded regardless. | §8 Q3 — since RESOLVED in favour of its position: always a PR, §2 Overview |

Summary: **9** confirmed · **0** rejected · **1** escalated.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree for this spec —
  `.claude/worktrees/feat-FEAT-572-sdd-fix-ledger-lane`, created from `origin/dev` via
  `python -m scripts.sdd.ensure_worktree --slug sdd-fix-ledger-lane --feature-id FEAT-572`.
  The `sdd-coder` engine gives each task its own sub-worktree inside it.

- **Module dependency graph**:
  ```
  M1 fix_planner ──────────────┐
                               ├──→ M4 CLI ──→ M5 twins ──→ M6 tests
  M2 unclaimed ──→ M3 service ─┘
  ```
  - `M3 → M2` — `LedgerService.unclaim()` emits `LedgerEvent(kind="issue.unclaimed")`, and
    `kind` is typed `LedgerEventKind` (`events.py:87`), so the Literal must grow first or
    Pydantic rejects the event at construction.
  - `M1 → M2` — the planner imports `SEVERITY_ORDER` from `events.py` (S6), so M2 must
    land first. This is a NEW edge introduced by design research; M1 and M2 are no longer
    concurrent.
  - `M4 → M1` — `ledger plan-fix` imports `plan_fix_batch`.
  - `M4 → M3` — `ledger unclaim` / `close --resolved-by` call the new service methods.
  - `M5 → M4` — the twins shell out to `plan-fix --json`.
  - `M6 → M5` — `TestFixTwins` reads the three twin files.
  - The graph is now a chain through M2: `M2 → {M1, M3} → M4 → M5 → M6`. M1 and M3 have
    no edge between them and are expected to run concurrently once M2 lands — M1 is a new
    file, M3 touches only `service.py`.

- **Shared files**: `service.py` is touched by **M2** (`ready_work()` ordering, S6) and
  **M3** (`unclaim`, `close_issue`) — their tasks are serialized by the `M3 → M2` edge, and
  the two edits are in non-adjacent methods (:199-207 vs :235-246). `events.py` and
  `index.py` belong to M2 alone; `cli.py` and `tools.py` to M4; the three twin markdown files to M5;
  `tests/sdd/test_ledger_workflow_twins.py` to M6. The tightest coupling is M2→M3 across
  two different files, which the dependency edge already serializes.

- **Exclusive resources**: none. No extension rebuild, no lockfile change, no migration —
  `ledger.db` is rebuildable from `events.jsonl` and no schema DDL changes (the new event
  kind writes through the existing `pages`/`edges` tables via `_write_issue`).

- **Cross-feature dependencies**: none blocking. FEAT-566 (`sdd-work-ledger`) is merged and
  is this feature's base. Watch `expose-local-mcp-tools` and `wikitoolkit-http-mcp`
  (FEAT ids reserved on `dev` on 2026-09-17, no spec committed yet): if either lands a
  change to `cli.py`'s `ledger` group or `tools.py`'s tool registration, M4 may need a
  rebase. Nothing in this spec touches `mcp_server.py` or `tools.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-18 | Jesus Lara (with Claude) | Initial draft from accepted brainstorm |
| 0.2 | 2026-09-18 | Jesus Lara (with Claude) | Resolved all three open questions: CLI-resolved `parents`/`suggested_slug` (planner stays pure), deterministic dominant-file slug, fast lane always opens a PR |
