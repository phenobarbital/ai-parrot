---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [ledger, arangodb, wikitoolkit, multi-machine, query-plane]
---

# Brainstorm: ArangoDB-backed SDD work ledger (`wikitoolkit-ledger-arangodb`)

**Date**: 2026-10-21
**Author**: Jesus
**Status**: exploration
**Recommended Option**: Option B

---

## Problem Statement

FEAT-569 (`wikitoolkit-http-mcp`) deferred "porting `LedgerStore` to ArangoDB" as a follow-up
feature named `wikitoolkit-ledger-arangodb`. That follow-up was never written down as a
brainstorm, spec or proposal, so the idea has been re-surfacing as a ledger issue instead of
being decided. This document closes `issue:88e6dbc8759e` by making the decision explicit.

**The original motivation is gone.** `issue:b8c3c8ff93c6` framed this as a *correctness* problem
— the committed `sdd/ledger/issues.jsonl` snapshot was last-writer-wins across machines, and
118 of 279 historical issues (49 major, 8 critical) had been silently dropped. Both halves of
that harm have since been fixed:

- **FEAT-671 / TASK-4295** made `export_snapshot` reconcile instead of overwrite — rows for
  `issue_id`s with no local events are carried forward unchanged, and
  `wikitoolkit ledger export --no-reconcile` is the explicit destructive opt-out.
- **FEAT-694** (`ledger-shared-event-log`, merged 2026-10-16) made the *event log itself*
  git-synced. `sdd/ledger/events.jsonl` is committed and propagated by four managed
  `parrot-ledger` hooks (`post-checkout`, `post-merge`, `post-rewrite`, `pre-commit`), with
  `wikitoolkit ledger export-log` / `import-log`. The snapshot is no longer the cross-machine
  source of truth.

So this is **no longer a fix**. What remains is an *optimisation* with three candidate drivers,
and it must be justified on those terms or not built:

1. **Live cross-machine sharing** — today sharing has a git round-trip: a claim is only visible
   to another machine after a commit, a push and a pull. `/sdd-fix` claims are therefore
   advisory, and a concurrent-duplicate race is a known, recurring failure.
2. **Query power for a consumer that already exists** — `wiki_standup` and `/sdd-insight`
   aggregate across the ledger today and are constrained by what SQLite + a JSONL replay make
   cheap. This is the one driver with a *named, existing* consumer.
3. **Event-log scale** — `sdd/ledger/events.jsonl` is 1,184 events / ~682 KB and only grows.
   Rotation into `sdd/ledger/archive/` exists, but every `ledger rebuild` replays the log, so
   replay cost rises monotonically.

**Who is affected**: SDD agents and the humans driving them (`/sdd-fix`, `/sdd-done`,
`/sdd-status`, `wiki_standup`), on every machine that runs the workflow.

## Constraints & Requirements

These were settled interactively during discovery and are binding on any option below.

- **The event log stays canonical.** `sdd/ledger/events.jsonl` (`LedgerLog`) remains the source
  of truth. Any store backend is a *materialised index* of that log, and switching backends is
  `wikitoolkit ledger rebuild`. This matches the decision already recorded in FEAT-670's
  TASK-4381 and must not be reopened by this feature.
- **The index may be shared.** Several machines may point at **one** Arango instance for derived
  state, while the canonical log stays per-machine-plus-git. "Shared index, canonical log."
- **Offline is a hard requirement.** ArangoDB in this environment needs VPN. `/sdd-fix` and
  `/sdd-done` must keep working when Arango is unreachable, by degrading to the local SQLite
  index. Arango is an accelerator, never a dependency for correctness.
- **This feature owns the store seam.** The backend-neutral `LedgerTxn` / `LedgerReader`
  protocols do not exist yet; they are specified by FEAT-670's TASK-4380 (pending). This feature
  builds that seam first, and FEAT-670's `HelixLedgerStore` later rides it. TASK-4380 must
  consequently be rewritten or dropped — see Open Questions.
- No new ledger behaviour: issue kinds, severities, the fix-planner contract
  (`planner_version == "1"`) and the two-key close rule are unchanged.
- `black` line-length 120, Google docstrings, strict typing, `aiohttp` only — no `requests` /
  `httpx` in any new client path.

---

## Options Explored

### Option A: Backend dispatch only — per-machine Arango index

Build the `LedgerTxn` / `LedgerReader` seam, add an `ArangoLedgerStore`, and let
`WikiProjectConfig.backend == "arangodb"` select it in `LedgerService.from_root` / `from_dir`.
Each machine points at **its own** Arango instance (or none). Arango replaces SQLite as that
machine's index; the canonical log is untouched.

This is the literal reading of "port `LedgerStore` to ArangoDB", and the exact shape FEAT-670
already plans for HelixDB.

✅ **Pros:**
- Smallest conceptual change; mirrors FEAT-670's design one-for-one, so the two backends stay
  symmetric and reviewable against each other.
- No concurrency question at all — one writer per index, exactly as today.
- `ArangoDBWikiStore` already exists and is complete (FEAT-400, 7/7 tasks done), so the store
  layer is largely assembly rather than new code.

❌ **Cons:**
- **Delivers none of driver 1.** A per-machine index is not shared; cross-machine visibility
  still goes through git at exactly today's latency.
- Buys query power at the cost of making every ledger operation VPN-dependent, unless the
  fallback work from Option B is done anyway.
- Hard to justify: it is strictly more operational burden than SQLite for a single machine.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-arango` | ArangoDB driver | already a dependency of `ArangoDBWikiStore` (FEAT-400) |
| `aiosqlite` | existing SQLite path | unchanged; stays the default backend |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` — `ArangoDBWikiStore`, the
  finished Arango implementation of `BaseWikiStore`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py` — `LedgerStore`, the SQLite
  specialisation whose `ledger_transaction()` contract the seam must preserve.
- `packages/ai-parrot/src/parrot/knowledge/wiki/project.py` — `WikiProjectConfig`, which already
  accepts an `arangodb` backend value.

---

### Option B: Shared Arango query plane with a local SQLite mirror (dual-plane, log-canonical)

Build the same seam as Option A, but run **both** stores rather than choosing one. The local
SQLite index is always written and is what every command reads when it needs a guaranteed
answer. A **shared** Arango instance is written best-effort and serves aggregate/graph reads for
`wiki_standup` and `/sdd-insight`. On reconnect, divergence is repaired by replaying
`events.jsonl` — the canonical log makes reconciliation total rather than a merge heuristic.

Because the log is canonical and append-only, a lost Arango write is never data loss: it is a
stale index that the next rebuild fixes.

✅ **Pros:**
- The only option that serves **all three** drivers: shared visibility (driver 1), a real query
  plane for the named consumer (driver 2), and a place to aggregate without replaying the whole
  log (driver 3).
- Satisfies the offline constraint by construction — SQLite is always present and always
  authoritative for correctness, so `/sdd-fix` and `/sdd-done` never become VPN-dependent.
- Degradation is observable: a best-effort write that fails is a logged, countable event, not a
  silent divergence.
- Keeps FEAT-670's canonicity decision intact, so the Helix backend can adopt the same pattern.

❌ **Cons:**
- **Two write paths is the most complex option here**, and the complexity is permanent, not
  transitional. Every ledger write has a success/degraded outcome to reason about.
- Two machines writing derived state into one Arango instance need a locking or
  last-event-wins rule; the log makes this *recoverable* but not *free*. Unresolved — see Open
  Questions.
- A shared index invites exactly the mistake this design forbids: someone will eventually read
  Arango as if it were canonical. Needs an explicit, enforced invariant and a loud docstring.
- Does not make `ledger claim` atomic across machines. Live visibility shrinks the duplicate-claim
  race window but does not close it; a real distributed claim needs a lock this design does not
  introduce.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-arango` | shared index reads/writes | reused from FEAT-400 |
| `aiosqlite` | local authoritative index | unchanged |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` — `export_events`,
  `import_events`, `is_shareable`, `rotate_events`; the FEAT-694 sync whose semantics the
  reconcile path must mirror rather than reinvent.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` — `LedgerLog`, the canonical log.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py` — `LedgerIndex`, the replay
  target that defines what "materialised" means here.
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` — `ArangoDBWikiStore`.

---

### Option C: Use FEAT-569's remote wikitoolkit server as the shared ledger

Write no new store code. FEAT-569 already ships an HTTP/MCP wikitoolkit server whose server-side
ledger is shared by construction. Point the machines that want live sharing at that server and
treat the local SQLite ledger as the offline mode.

✅ **Pros:**
- By far the cheapest path to driver 1 — the sharing problem is already solved by shipped code.
- No new backend, no new canonicity question, no dual-write.
- Fails cleanly: either you are talking to the server or you are local.

❌ **Cons:**
- Does nothing for drivers 2 and 3. The server's ledger is still SQLite underneath, so the query
  plane and the replay cost are unchanged.
- Moves the availability problem rather than solving it: the server is now a single point of
  failure for shared state, with the same VPN exposure.
- Operationally this is a deployment decision, not a feature — there may be nothing to build,
  which makes it a poor fit for an SDD feature but an excellent fit for a documented recommendation.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| — | none | configuration and documentation only |

🔗 **Existing Code to Reuse:**
- `sdd/specs/wikitoolkit-http-mcp.spec.md` — FEAT-569, the shipped server and its ledger surface.

---

### Option D (unconventional): One-way analytics projection — refuse to make Arango a backend

Leave the ledger exactly as it is: SQLite index, canonical `events.jsonl`, FEAT-694 git sync, no
seam, no dispatch, no fallback. Add a single one-way exporter —
`wikitoolkit ledger project --to arangodb` — that pushes events into Arango purely as an
**analytics sink** that nothing in the SDD workflow ever reads.

The unconventional move is declining the framing: the issue asks to port the *store*, and this
option argues the store was never the problem. Only the *reporting* was.

✅ **Pros:**
- Serves driver 2 — the only driver with an existing consumer — at a fraction of the cost.
- Zero risk to `/sdd-fix` and `/sdd-done`: there is no read path, so there is no fallback
  question, no VPN dependency and no canonicity confusion to police.
- Does not collide with FEAT-670 at all. TASK-4380 and TASK-4381 proceed untouched.
- Trivially reversible — deleting the exporter leaves no trace in the ledger core.

❌ **Cons:**
- Delivers nothing for driver 1. Cross-machine sharing stays at git latency, permanently.
- A second, divergent representation of ledger state that no invariant keeps honest; it is
  "right as of the last projection run" and nothing enforces that it ran.
- If sharing later becomes a real requirement, this is throwaway work.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-arango` | write-only sink | reused from FEAT-400 |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` — `read_raw_events`,
  `shared_log_files` for reading the committed log without a store.
- `packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py` — `ArangoDBWikiStore`.

---

## Recommendation

**Option B** is recommended, and the recommendation is explicitly conditional.

It is the only option that satisfies all three constraints settled in discovery — shared index,
canonical log, mandatory offline degradation — while serving all three drivers. Options A and C
each drop a driver outright: A delivers query power but not sharing, C delivers sharing but not
query power. Option B's local SQLite mirror is what makes the VPN dependency acceptable, and
FEAT-694's canonical log is what makes a best-effort shared write safe, because any divergence is
repairable by replay rather than by merge.

**What is being traded away, honestly:**

- **Permanent complexity.** Two write paths, forever, in the subsystem `/sdd-fix` and `/sdd-done`
  depend on. This is the single biggest cost and it does not amortise.
- **A collision with FEAT-670.** Building the seam here means TASK-4380 is rewritten or dropped
  and TASK-4381 rebases onto this feature's protocols. That is a real cost imposed on another
  feature's plan, accepted deliberately during discovery.
- **Sharing is improved, not solved.** A shared index narrows the duplicate-claim window but
  does not make `ledger claim` atomic across machines. Anyone expecting this feature to end
  concurrent-claim races will be disappointed; that needs a distributed lock, which is out of scope.

**The dissent worth recording:** if the honest trigger turns out to be only `wiki_standup` and
`/sdd-insight` — the one driver with an existing consumer — then **Option D delivers that driver
at Low effort with none of the above costs**, and Option B is over-built. The deciding question is
whether live cross-machine sharing is a requirement or an aspiration. It was selected as a
motivation during discovery, but no workflow currently *fails* for lack of it, because FEAT-694
closed the data-loss hole. This is logged as the first Open Question and should be answered before
`/sdd-spec` is run, not after.

---

## Feature Description

### User-Facing Behavior

Operators see no change by default. SQLite remains the default backend and every existing
`wikitoolkit ledger` command behaves identically.

Opting in is configuration-only, in `.parrot/wiki.json`: setting the ledger backend to
`arangodb` with connection parameters enables the shared query plane. Once enabled:

- `wikitoolkit ledger list|show|ready|plan-fix` answer from the local SQLite index exactly as
  today — same latency, same output, VPN or no VPN.
- `wiki_standup` and `/sdd-insight` answer from Arango when it is reachable, gaining cross-machine
  aggregates (what every machine is working on, not just this one).
- Every command prints a one-line degraded notice when Arango was unreachable, naming what was
  skipped. Degradation is never silent.
- `wikitoolkit ledger rebuild` repoints and rebuilds both indexes from the canonical log.

### Internal Behavior

`LedgerService.from_root` / `from_dir` construct a composite store. Writes go to SQLite inside the
existing `ledger_transaction(operation)` contract and commit there first; the Arango write is
attempted afterwards, outside the SQLite transaction, and its failure is recorded rather than
raised. Reads are routed by intent: correctness-critical reads (claim checks, the fix planner,
`/sdd-done`'s closing keys) read SQLite unconditionally; aggregate reads prefer Arango and fall
back to SQLite.

The `LedgerTxn` / `LedgerReader` protocols introduced here are what make this expressible: today
`ledger_transaction()` yields a raw `aiosqlite.Connection` and callers issue SQL against it
directly, so no second backend can exist until that is cut. The seam is a pure refactor for
SQLite — `_write(operation)` busy-timeout semantics and `WikiStoreBusy` propagation must be
byte-for-byte unchanged, because `/sdd-fix` and `/sdd-done` depend on them.

Reconciliation is replay, not merge: on reconnect the service replays `events.jsonl` (local plus
anything FEAT-694's `import_events` has pulled in) into Arango, skipping event IDs already
present. Because events are append-only and carry stable IDs, this is idempotent.

### Edge Cases & Error Handling

- **Arango unreachable at startup** — construct SQLite-only, log once at INFO, continue. Never
  raise.
- **Arango fails mid-write** — SQLite has already committed; record the failure, mark the Arango
  index stale, continue. The next rebuild or reconnect repairs it.
- **Two machines write derived state concurrently** — last event wins by event timestamp; the
  canonical log makes the result reproducible. This is the weakest point of the design and is an
  Open Question, not a settled answer.
- **Arango ahead of local** — impossible to trust; the local log is canonical, so a rebuild
  overwrites the Arango projection rather than importing from it. This invariant must be
  enforced in code and stated in the module docstring.
- **A `ledger claim` while degraded** — proceeds against SQLite and succeeds. It is advisory
  across machines exactly as today; this feature does not change that, and must not be described
  as if it does.
- **Malformed events in the committed log** — already handled by `shared_log.read_raw_events`,
  which skips unparseable lines; the projection reuses that behaviour rather than failing.

---

## Capabilities

### New Capabilities
- `ledger-store-seam`: backend-neutral `LedgerTxn` / `LedgerReader` protocols plus the SQLite
  implementation, replacing raw `aiosqlite.Connection` access across the ledger.
- `ledger-arango-store`: an `ArangoLedgerStore` built on the existing `ArangoDBWikiStore`.
- `ledger-query-plane`: the shared, best-effort aggregate read path used by `wiki_standup` and
  `/sdd-insight`, with mandatory SQLite fallback.

### Modified Capabilities
- `sdd-work-ledger` — store access is rewritten onto the new protocols.
- `helixdb-provider` (FEAT-670) — TASK-4380 is superseded by `ledger-store-seam`; TASK-4381
  rebases onto these protocols.
- `ledger-shared-event-log` (FEAT-694) — unchanged in behaviour, but becomes the reconciliation
  source for the Arango projection.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `wiki/ledger/store.py` | modifies | adds the protocols + SQLite implementations; hard cut |
| `wiki/ledger/index.py` | modifies | retyped off `aiosqlite.Connection` onto `LedgerTxn` |
| `wiki/ledger/service.py` | modifies | backend dispatch, composite store, degraded reporting |
| `wiki/ledger/sdd_ingest.py` | modifies | same retyping as `index.py` |
| `wiki/ledger/arango_store.py` *(new)* | extends | `ArangoLedgerStore(ArangoDBWikiStore)` |
| `wiki/project.py` | depends on | `WikiProjectConfig` already accepts `arangodb` |
| `wiki/ledger/fix_planner.py` | depends on | must keep reading the authoritative index; `planner_version` unchanged |
| FEAT-670 TASK-4380 / TASK-4381 | **conflicts** | same files, same hard cut — must be reconciled before either starts |
| `/sdd-fix`, `/sdd-done` | depends on | correctness paths must remain SQLite-backed and offline-safe |
| Deployment | new | an Arango instance + VPN reachability for opt-in users only |

---

## Code Context

### User-Provided Code

None — this brainstorm was driven by interactive discovery, not pasted code.

### Verified Codebase References

All references below were machine-verified by the `sdd-contract-probe` agent against HEAD
`4fe053de8` on 2026-10-21. Four dotted-name checks the probe's fixed command cannot express
(`LedgerStore.ledger_transaction`, `LedgerService.from_root` / `.from_dir` / `.export_snapshot`)
were verified inline and are marked accordingly.

#### Classes & Signatures

```python
# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py:24
class LedgerStore(SQLiteWikiStore):
    # line 54 — verified inline; THIS is the signature the hard cut must replace:
    # it yields a raw aiosqlite.Connection, which is why no second backend can exist today.
    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
        ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:149
class LedgerService:
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService":  # line 167 (inline)
        ...
    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService":  # line 197 (inline)
        ...
    # line 532 (inline) — `reconcile=True` is FEAT-671's fix for issue:62038221413a
    async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool:
        ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:697
class BaseWikiStore(ABC):
    ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/store.py:1092
class SQLiteWikiStore(BaseWikiStore):
    ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/arango_store.py:137
class ArangoDBWikiStore(BaseWikiStore):
    ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py:86
class LedgerIndex:
    ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py:10
class LedgerLog:
    ...

# From packages/ai-parrot/src/parrot/knowledge/wiki/project.py:574
class WikiProjectConfig(BaseModel):
    ...

# FEAT-694 shared-log surface the reconcile path must mirror:
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
def is_shareable(event: LedgerEvent) -> bool:  # line 71
    ...
def export_events(local: LedgerLog, repo_root: Path) -> SharedLogExportReport:  # line 136
    ...
def import_events(
    local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False
) -> tuple[SharedLogImportReport, list[LedgerEvent]]:  # line 165
    ...
def rotate_events(
    repo_root: Path, *, older_than_days: int = ROTATION_DAYS_DEFAULT, now: datetime | None = None
) -> SharedLogRotateReport:  # line 230
    ...
```

#### Verified Imports

```python
# These imports have been confirmed to resolve:
from parrot.knowledge.wiki.store import BaseWikiStore       # store.py:697
from parrot.knowledge.wiki.store import SQLiteWikiStore     # store.py:1092
from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore  # arango_store.py:137
```

#### Key Attributes & Constants
- `LedgerStore` → subclasses `SQLiteWikiStore` (ledger/store.py:24)
- `ArangoDBWikiStore` → subclasses `BaseWikiStore`, **not** `SQLiteWikiStore`
  (arango_store.py:137) — an `ArangoLedgerStore` therefore cannot inherit `LedgerStore`'s
  SQLite behaviour and must satisfy the new protocols directly.
- `WikiProjectConfig` is a Pydantic `BaseModel` (project.py:574) and **already accepts an
  `arangodb` backend value** — covered by `tests/knowledge/wiki/test_config_arango.py:15`
  (`TestWikiProjectConfigArango`). No config change is needed to select the backend.
- `LedgerService.export_snapshot(..., reconcile: bool = True)` (service.py:532) — the FEAT-671
  reconcile guard; must not regress.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/fix_planner.py` — 272 lines; emits the
  `planner_version == "1"` contract `/sdd-fix` depends on.
- Colliding task anchors, both verified present:
  `sdd/tasks/active/TASK-4380-ledger-txn-hard-cut.md:1` ("Ledger hard cut — LedgerTxn /
  LedgerReader protocols") and `sdd/tasks/active/TASK-4381-helix-ledger-store.md:8`
  (`**Depends-on**: TASK-4377, TASK-4379, TASK-4380`).

### Does NOT Exist (Anti-Hallucination)

Verified absent across `packages/ai-parrot/src/parrot/knowledge/wiki/` (and the `ledger/`
subtree) at HEAD `4fe053de8`:

- ~~`ArangoLedgerStore`~~ — does not exist anywhere. This feature creates it.
- ~~`HelixLedgerStore`~~ — does not exist yet; it is only *planned* by FEAT-670's TASK-4381.
- ~~`LedgerTxn`~~ — the protocol does **not** exist. It is specified by TASK-4380 (pending) and
  nothing implements it today.
- ~~`LedgerReader`~~ — same; does not exist.
- ~~`ledger/helix_store.py`~~ — the file does not exist.
- ~~`wikitoolkit ledger import`~~ — there is no such command. Cross-machine flow is
  `ledger export-log` / `ledger import-log` (FEAT-694) plus `ledger rebuild`; do not assume a
  bare `import` subcommand.

**Implication for implementers**: every `conn: aiosqlite.Connection` call site in
`ledger/index.py`, `ledger/service.py` and `ledger/sdd_ingest.py` is still raw SQLite today.
The protocols are a *greenfield* part of this feature, not something to import.

---

## Parallelism Assessment

- **Internal parallelism**: Low early, moderate late. The `LedgerTxn` / `LedgerReader` hard cut
  touches `store.py`, `index.py`, `service.py` and `sdd_ingest.py` simultaneously and must land as
  one exclusive task before anything else starts. After it, the Arango store, the degraded-reporting
  path, the CLI surface and docs can proceed in parallel.
- **Cross-feature independence**: **Not independent.** FEAT-670's TASK-4380 performs the identical
  hard cut on the identical files, and TASK-4381 adds a sibling backend through the same dispatch
  point. These cannot both proceed. FEAT-670 currently has 26 pending tasks and has not started,
  so the collision is schedulable rather than live — but it is a hard blocker, not a merge conflict.
- **Recommended isolation**: `per-spec`
- **Rationale**: the exclusive hard cut serialises the feature's opening move, and every later task
  depends on the protocols it introduces. One worktree, sequential tasks, is the correct shape;
  sub-worktrees would only contend on the same four files.

---

## Open Questions

- [ ] Is live cross-machine sharing a **requirement** or an **aspiration**? If only
      `wiki_standup` / `/sdd-insight` genuinely need this, Option D delivers that driver at Low
      effort and Option B should be rejected as over-built. Answer this before `/sdd-spec`. — *Owner: Jesus*
- [ ] Does FEAT-670's TASK-4380 get **rewritten or dropped** once this feature owns the seam, and
      who updates `sdd/tasks/index/helixdb-provider.json` and TASK-4381's `Depends-on`? — *Owner: Jesus*
- [ ] Which ArangoDB instance hosts the shared ledger index, and is VPN-only reachability
      acceptable for every machine expected to opt in? — *Owner: Jesus*
- [ ] Concurrent derived-state writes from two machines into one Arango instance: is
      last-event-wins by timestamp sufficient, or is an explicit lock required? — *Owner: unassigned*
- [ ] Should shipping be gated on a measurable trigger (e.g. N active machines, or
      `events.jsonl` replay exceeding X ms) rather than built speculatively? — *Owner: Jesus*
- [x] Does the backend become the source of truth? — *Owner: Jesus*: No. `events.jsonl` stays
      canonical; any backend is a materialised index and switching is `ledger rebuild`. Matches
      FEAT-670's recorded decision.
- [x] What happens when Arango is unreachable? — *Owner: Jesus*: Hard requirement to degrade to the
      local SQLite index. Arango is an accelerator; `/sdd-fix` and `/sdd-done` must never become
      VPN-dependent.
- [x] Shared instance or per-machine instance? — *Owner: Jesus*: Shared index, canonical log —
      many machines may point at one Arango instance for derived state.
- [x] Which consumer justifies the query plane? — *Owner: Jesus*: `wiki_standup` and
      `/sdd-insight`, which already aggregate across the ledger.
