---
id: FEAT-566
title: Shared SDD work ledger
slug: sdd-work-ledger
type: feature
mode: enrichment
status: review
source:
  kind: file
  jira_key: null
  jira_url: null
  fetched_at: 2026-09-14
  summary_oneline: Create a shared, event-sourced SDD work ledger on the LLM Wiki plane.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-566/
created: 2026-09-14
updated: 2026-09-14
---

# FEAT-566 — Shared SDD work ledger

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `file: sdd/proposals/sdd-work-ledger.brainstorm.md`
> **Audit**: [`sdd/state/FEAT-566/`](../state/FEAT-566/)

---

## 0. Origin

The request proposes a shared, event-sourced ledger for work discovered while
executing SDD tasks: deferred review findings, out-of-scope bugs, provenance
for durable insights, and graph-linked context for later tasks. The full,
verbatim source is preserved at `sdd/state/FEAT-566/source.md`.

> “The SDD pipeline … tracks *planned* work well … What it does not track is
> everything an agent learns **while** executing a task and decides not to act
> on.”

**Initial signals** (extracted, not interpreted):

- Verbs: record, claim, close, ingest, compact, audit.
- Named entities: LLM Wiki, SQLite, wikitoolkit, SDD, worktree, ledger.
- Acceptance criteria provided: yes — the source defines user-facing behavior,
  failure handling, integration points, and a validation-first spike.

---

## 1. Synthesis Summary

The feature should introduce a single-host, shared-worktree ledger rooted at
the main checkout's `.parrot/` area, with an append-only event log as durable
truth and a rebuildable index for graph-aware retrieval. The repository already
has an async Git-common-directory resolver in
`packages/ai-parrot/src/parrot/tools/repo/graph_search.py`, reusable SQLite
page/edge/FTS contracts in `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`,
and federated read behavior in `federation.py`; the feature must consolidate
these seams rather than recreate them. [F002, F003, F004]

SQLite concurrency needs an explicit validation spike because the inspected
store opens normal connections without a configured busy timeout, runs a
migration write path on each connection, and has no explicit immediate
transaction in that file. [F003] The proposed ledger fills concrete workflow
gaps: `/sdd-next` only computes task readiness from indexes, code-review report
persistence is optional, and `/sdd-done` can close partial tasks as
`done-with-issues` without a structured deferred-work record. [F006]

---

## 2. Codebase Findings

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot/src/parrot/tools/repo/graph_search.py` | `resolve_plane_root` | 31-81 | Resolves a linked worktree to the main checkout via Git's common directory. | F002 |
| 2 | `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` | `WikiProjectConfig.storage_path` | 472-496 | Resolves local or absolute storage for a wiki plane. | F002 |
| 3 | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` | `SQLiteWikiStore` | 875-1805 | Page, edge, FTS, neighbor and dangling-edge storage contract. | F003 |
| 4 | `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py` | `FederatedWikiStore` | 599-950 | Fans out reads across planes and qualifies foreign identifiers. | F004 |
| 5 | `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` | `WikiRememberTool` | 272-327 | Current durable-memory page and asserted-edge write surface. | F005 |
| 6 | `.claude/commands/sdd-start.md` | command workflow | 38-105 | Validates readiness, provisions a worktree and marks a task in progress. | F006 |
| 7 | `scripts/sdd/close_task.sh` | lifecycle script | 3-115 | Deterministically completes a task and updates its per-spec index. | F006 |

### 2.2 Constraints Discovered

- **One shared-root algorithm.** `resolve_plane_root()` already resolves
  `git rev-parse --git-common-dir` asynchronously and returns the main
  checkout. `WikiProjectConfig.storage_path()` supports absolute storage. The
  ledger must reuse or promote this behavior rather than create a second
  common-directory implementation. *Evidence*: F002

- **Durability before index availability.** The current store supplies page,
  provenance-edge, FTS, neighbor and broken-edge primitives, but its inspected
  connection and migration path needs concurrency validation before it backs an
  atomic claim operation. *Evidence*: F003

- **Federation is a read integration.** Federated reads fan out, but generic
  writes are intentionally local or explicitly namespace-targeted. Ledger
  writes therefore need a direct ledger-plane service, not generic federation
  mutation. *Evidence*: F004

- **Provenance is general-purpose.** `wiki_remember` currently accepts an
  optional `link_page_id` and relation. The approved direction is to extend
  provenance capability for SDD and non-SDD contexts, without making it an
  SDD-only rule. *Evidence*: F005; product decision 2026-09-14

- **Workflow parity is required.** SDD commands have Claude, Codex and
  Antigravity variants. The approved rollout updates all three platform twins,
  not just the Claude command documents researched here. *Evidence*: F006;
  product decision 2026-09-14

### 2.3 Recent History

Recent commits include active wiki installer/namespace work and recent SDD
worktree-ownership changes. The feature should remain narrowly scoped and
avoid unrelated refactors in these active surfaces. *Evidence*: F007

---

## 3. Probable Scope

### What's New

- **Shared ledger root and storage contract** — resolve the main checkout for
  ledger state and place v1 state beneath its `.parrot/` directory. The
  supported deployment is multiple linked worktrees on one host; multi-machine
  synchronization is explicitly out of scope. *Evidence*: F002; product
  decision 2026-09-14

- **Append-only event log plus rebuildable ledger index** — durable work events
  are written first; a separate index exposes issues, insights, provenance and
  scoped context through existing page/edge query patterns. *Evidence*: F003

- **Ledger CLI and tool service** — provide direct ledger-plane operations for
  opening, listing ready work, claiming, closing, linking, context lookup,
  compaction, audit, synchronization and rebuild. Federation remains a read
  discovery mechanism. *Evidence*: F003, F004

- **General provenance fields for durable knowledge** — support source and
  subject relations beyond SDD while preserving compatibility for callers that
  only use the present optional link. *Evidence*: F005; product decision
  2026-09-14

### What Changes

- **`WikiProjectConfig` and worktree-plane resolution** — centralize the
  shared-root decision and add a ledger storage location. *Evidence*: F002

- **`SQLiteWikiStore` configuration and write paths** — validate and, if the
  spike proves necessary, add bounded lock waiting and explicit transaction
  policy without breaking other backends. *Evidence*: F003

- **`FederatedWikiStore` registration and wiki tools** — mount the ledger for
  read discovery and expose provenance-aware memory behavior. *Evidence*:
  F004, F005

- **SDD lifecycle commands and twins** — file deferred review findings, emit
  task state events, display ledger work in next-task selection, inject scoped
  context before task work, and apply the critical-open-work merge gate in the
  Claude, Codex and Antigravity variants. *Evidence*: F006; product decision
  2026-09-14

### What's Untouched (Non-Goals)

- Multi-machine ledger synchronization, a hosted tracker, PostgreSQL or Arango
  as the v1 ledger backend.
- Replacing the current wiki retrieval plane or its non-SQLite backends.
- Provider client behavior and unrelated agent execution code.
- Per-worktree structural-plane overlays; linked worktrees may read the shared
  main-checkout structural plane in v1. *Evidence*: F002

### Patterns to Follow

- Keep the index rebuildable and use `WikiPageRecord`, asserted edges,
  `search_fts`, `neighbors` and `broken_edges` instead of inventing a parallel
  graph model. *Evidence*: F003

- Treat federation as concurrent read composition and direct a mutation to one
  chosen plane. *Evidence*: F004

- Follow `/sdd-start` and `close_task.sh` lifecycle boundaries for task events;
  preserve their idempotency and index discipline. *Evidence*: F006

### Integration Risks

- **Concurrent writes:** append success and index success must be independently
  observable so a lock never loses discovered work. The mandatory spike must
  prove concurrent appends, index replay, and atomic claim behavior. *Evidence*:
  F003

- **Shared-root drift:** duplicating `resolve_plane_root` would create
  inconsistent resolution between readers and ledger writers. Mitigate by
  selecting one canonical API owner in the specification. *Evidence*: F002

- **Platform drift:** the three workflow variants can diverge. Mitigate with
  one acceptance matrix covering the corresponding Claude, Codex and
  Antigravity documents. *Evidence*: F006; product decision 2026-09-14

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | A linked worktree can resolve the main checkout's wiki plane through `resolve_plane_root`. | F002 | high | Direct source confirmation of the Git common-directory algorithm. |
| C2 | The SQLite wiki store can represent ledger pages, provenance edges, lexical search, adjacency and dangling-edge audit. | F003 | high | Direct source confirmation of all named primitives. |
| C3 | A concurrency spike is required before the current SQLite path can underpin atomic ledger claims. | F003 | medium | The proposed controls are absent in the inspected store, but no load test was run. |
| C4 | A separate ledger plane can participate in existing federation reads. | F004 | medium | Read behavior is proven; direct write semantics remain new design work. |
| C5 | The ledger targets real gaps in current review, readiness and completion workflows. | F006 | high | Command documents directly show the lifecycle boundaries and optional review persistence. |

Distribution: **3** high, **2** medium, **0** low. Overall confidence is
**medium** because the ledger's concurrency and write-contract design still
requires a validation spike.

---

## 5. Open Questions

### Resolved

- [x] **What deployment boundary does v1 support?** — *Resolved*: shared
  worktrees on one host only; it is not a multi-machine feature. *Resolves
  claims*: C3, C4

- [x] **Is provenance restricted to SDD contexts?** — *Resolved*: no; it may
  be used in other contexts too. *Resolves claims*: C5

- [x] **Which workflow variants must change?** — *Resolved*: update the
  Claude, Codex and Antigravity command twins together. *Resolves claims*: C5

### Unresolved (defer to specification)

None. The specification must select the canonical module owner for shared-root
resolution and specify the event schema, but those are design decisions within
the approved scope rather than product questions.

---

## 6. Recommended Next Step

**`$sdd-spec sdd-work-ledger`** — the product boundary, rollout scope and
provenance policy are now resolved. The specification should begin with the
mandatory single-host concurrency/atomicity spike, then formalize the ledger
event and direct-write contract before SDD command integration.

### Alternatives

- **`$sdd-brainstorm sdd-work-ledger`** — only if you want to reopen the
  append-log-plus-index architecture or deployment boundary.
- **Manual review** — if the proposed general-purpose provenance extension
  needs compatibility review before specification work.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-566/state.json` |
| Source (raw) | `sdd/state/FEAT-566/source.md` |
| Research plan | `sdd/state/FEAT-566/research_plan.json` |
| Findings | `sdd/state/FEAT-566/findings/F001-*.md` through `F007-*.md` |
| Synthesis | `sdd/state/FEAT-566/synthesis.json` |

**Budget consumed**:

- Files read: 13 / 40
- Grep calls: 7 / 25
- Git calls: 2 / 10
- Wall time: 180 / 300 seconds
- Truncated: **no**

**Mode determination**: `auto` → `enrichment`, because the source describes
new ledger, context and provenance capabilities.

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `$sdd-proposal` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Codex with user decisions recorded 2026-09-14 |
