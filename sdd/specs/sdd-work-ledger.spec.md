---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: SDD Work Ledger — Discovered Work, Spec Graph and Insights on the LLM Wiki Plane

**Feature ID**: FEAT-566
**Date**: 2026-09-14
**Author**: Jesus Lara (drafted with Claude & Codex)
**Status**: approved
**Target version**: 0.4.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

The SDD pipeline (`/sdd-brainstorm → /sdd-proposal → /sdd-spec → /sdd-task → /sdd-start → /sdd-done`) tracks *planned* work systematically through per-spec task indexes under `sdd/tasks/index/<slug>.json`, a deterministic `close_task.sh`, and `/sdd-next` computing task readiness from dependencies. What it does not track is everything an agent discovers or learns **while** executing a task:

1. **Discovered work is dropped.** When a worker spots an out-of-scope bug mid-task, or `/sdd-codereview` confirms a 🟡 Major or 🔴 Critical finding that is left unfixed because it is outside the task's scoped files, there is no structured, durable sink. The review report template has no "Deferred findings" section, persisting the review report is optional and uncommitted, and `done-with-issues` is a terminal status whose context lives only in free-form commit text. Because nothing aggregates these findings, nothing ever prioritizes or schedules them.
2. **Specs and tasks are files, not queryable graph nodes.** `spec:` ↔ `task:` ↔ code relationships exist only implicitly in file paths and task markdown headers. It is currently impossible to query "Which open specs touch `BaseWikiStore.upsert_pages`?" or calculate the codebase blast radius of a planned feature.
3. **Insights have no durable provenance.** `wiki_remember` creates memory pages (`mem-<hash>`, `origin="memory"`), but linkage to *where* the insight originated (task, spec, review finding, code symbol) is optional and usually omitted; graph-scoped context injection (`bd prime`-style) is impossible without explicit provenance edges.
4. **The wiki plane is absent inside linked worktrees.** `find_project_root()` resolves the linked worktree root (its `.git` file satisfies `.exists()`), `.parrot/*` is gitignored, and `DevLoopWikiSearch.from_project()` returns `None` inside every `.claude/worktrees/<name>` directory. Any write from a worktree must resolve to the **main worktree's** `.parrot/`, never to isolated per-worktree copies requiring git merge or manual reconciliation.

### Goals

- Establish a **shared ledger plane** located at `<main_worktree>/.parrot/ledger/` accessible to all concurrent worktree agents on the host.
- Provide a dual-layer architecture:
  - **`events.jsonl`**: Append-only event log as durable source of truth (< 4 KiB per line, single `write()` call with `O_APPEND`, lock-free, zero database contention).
  - **`ledger.db`**: Rebuildable SQLite index powered by `SQLiteWikiStore` (`issue:`, `task:`, `spec:`, `insight:` nodes; `discovered-from`, `derived-from`, `about`, `implements`, `blocks`, `touches` edges).
- Build `ledger.db` entirely on FEAT-557's SQLite store policy (see *Hard Prerequisite* and Module 2) — no ledger-specific timeout, pragma, transaction, or migration machinery.
- Support atomic issue claim (`ledger claim`) as one writer transaction against the ledger index.
- Extend `wiki_remember` and memory tools with first-class, general-purpose provenance fields (`derived_from`, `about`).
- Integrate seamlessly into SDD workflows across all three platform twins (Claude, Codex, Antigravity):
  - Mandatory *Deferred findings* table in `/sdd-codereview` backed by `ledger_open`.
  - Emission of `task.started` in `/sdd-start` and `task.closed` in `scripts/sdd/close_task.sh`.
  - Automatic ingestion of `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` into the graph.
  - Exposure of ready tasks AND open ledger issues in `/sdd-next`, with promotion via `/sdd-task --from-issue <id>`.
  - Scoped context injection (`ledger_context`) in `/sdd-start` priming the worker with relevant open issues and insights intersecting the task's file/symbol scope.
  - Safe landing in `/sdd-done`: gate `--merge` on the feature's unacknowledged open critical findings, and regenerate + commit the `sdd/ledger/issues.jsonl` snapshot on every `/sdd-done` (PR and `--merge` flows) on `base_branch`.
- Guard the structural plane: worktrees read the shared base-branch structural plane; hooks and sync edits skip structural writes when executed in linked worktrees.

### Non-Goals (explicitly out of scope)

- Multi-machine ledger synchronization, distributed Consensus, or hosted tracker services (v1 is single-host, concurrent local worktrees).
- Migrating the primary wiki retrieval plane to PostgreSQL or ArangoDB (the ledger index is SQLite-first; alternative backends remain possible via `BaseWikiStore`).
- Per-worktree structural plane overlays (linked worktrees consume the shared base-branch structural plane snapshot).
- Modifying provider client wrappers (`AbstractClient`) or dev-loop agent execution graphs outside the wiki/search context.
- Reimplementing SQLite timeout, transaction, migration, source-manager, or factory-policy work owned by FEAT-557.

### Hard Prerequisite

**FEAT-557 — `wikitoolkit-sqlite-optimizations` (TASK-3216–TASK-3226) must be complete and merged into `dev` before any FEAT-566 task starts.** It is the single owner of SQLite connection policy for every wiki plane, `ledger.db` included. What FEAT-566 consumes from it, and how, is specified once in **Module 2**; the rest of this spec refers to that module instead of restating the policy. FEAT-566 must not modify `store.py`, `sources.py`, or FEAT-557's config/factory plumbing (`sqlite_busy_timeout`, `sqlite_performance_pragmas`, `sqlite_policy_from_config`, `create_wiki_store(sqlite_policy=…)`).

---

## 2. Architectural Design

### Overview

The solution adopts **Option B (Shared root + separate ledger plane)**:
1. **Shared Root Resolution**: Centralize worktree root resolution into `parrot.knowledge.wiki.project:find_shared_root()`, which walks Git's common directory (`commondir` pointer or `git rev-parse --git-common-dir`) to locate the main checkout, respecting an optional `PARROT_SHARED_ROOT` environment override.
2. **Dual-Layer Ledger Plane**:
   - **Log Layer (`events.jsonl`)**: Atomic, append-only JSON Lines event stream located at `<main>/.parrot/ledger/events.jsonl`. Writing an event never takes a database lock and cannot fail due to index contention. Each event carries an immutable SHA-1 hash identifier `sha1(kind|subject|actor|ts|payload)[:12]`.
   - **Index Layer (`ledger.db`)**: An instance of `SQLiteWikiStore` situated at `<main>/.parrot/ledger/ledger.db` that reduces events into `WikiPageRecord`s and directed edges with provenance. Write operations are write-through: append event to log, then apply to index in one FEAT-557 writer transaction (Module 2). If index write is contended (`WikiStoreBusy`), the log write remains durable, and subsequent `sync` or `rebuild` reconciles the index. The index persists a **sync cursor** (byte offset + last applied `event_id`) in a `ledger_state` table so `sync()` resumes from the tail instead of rescanning the log. Because v1 never rewrites `events.jsonl` (compaction is index-only, see §7), the byte offset is stable; a cursor whose `event_id` does not match the line at its offset triggers a full `rebuild()`.
3. **Federation Read Integration (overlay namespace)**: The ledger plane is mounted as a namespace (`ledger`) in `FederatedWikiStore` with `overlay_prefixes=["issue", "task", "spec", "insight"]`. An overlay namespace changes routing in three ways (Module 13):
   - **Bare-id routing**: an unqualified id whose kind prefix is in `overlay_prefixes` (`issue:3f8a1c9e`) routes to the ledger store — callers never need the `ledger::` prefix. Returned rows stay canonically qualified (`ledger::issue:3f8a1c9e`); a qualified id is accepted too.
   - **Outgoing edges to the code plane**: a ledger-owned edge destination whose kind is *not* an overlay prefix (`sym:…`, `file:…`) addresses the local plane — it is returned unqualified and hydrated from `wiki.db`, never re-homed as `ledger::sym:…`.
   - **Incoming edges from the ledger**: `neighbors(<local id>, direction="in"|"both")` also asks every overlay namespace for its incoming edges, so `wiki_related sym:…#FederatedWikiStore.neighbors` lists the issues/tasks/specs that touch it.
   Status-aware questions (only open issues, severity filters, token-budgeted context) are answered by `LedgerService` / `ledger context`, not by generic federation traversal. There is no separate `wikitoolkit ledger related` traverser.
4. **Structural Plane Policy**: Structural pages (`sym:`, `file:`) represent the base branch checkout. Post-commit hooks and AST edit listeners check `is_linked_worktree(root)` and no-op if true. The policy covers **structural** writes only: `wiki_remember` / `wiki_note` from a linked worktree still write memory pages (`origin="memory"`) into the shared `<main>/.parrot/wiki/wiki.db`, serialized by the FEAT-557 store policy (Module 2); FEAT-566 adds no busy handling of its own for `wiki.db`.

### Component Diagram

```
Linked Worktree A                   Main Checkout                  Linked Worktree B
(feat-FEAT-566-*)                 (dev / main)                    (feat-FEAT-567-*)
        │                               │                                 │
        │ find_shared_root()             │                                 │ find_shared_root()
        ▼                               ▼                                 ▼
┌───────────────────────────────────────────────────────────────────────────────────┐
│                           Main Checkout .parrot/                                  │
│                                                                                   │
│  ┌─────────────────────────────┐         ┌─────────────────────────────────────┐  │
│  │   events.jsonl (DURABLE)    │         │       wiki.db (STRUCTURAL)          │  │
│  │  - O_APPEND single-write    │         │  - Base-branch snapshot (sym:, etc) │  │
│  │  - Lock-free, unblocked     │         │  - Read-only from worktrees         │  │
│  └──────────────┬──────────────┘         └──────────────────┬──────────────────┘  │
│                 │ write-through / sync                      │                     │
│                 ▼                                           │                     │
│  ┌─────────────────────────────┐                            │                     │
│  │   ledger.db (INDEX)         │                            │                     │
│  │  - SQLiteWikiStore          │                            │                     │
│  │  - issue:, task:, spec:     │                            │                     │
│  │  - LedgerStore (_write)     │                            │                     │
│  │  - FEAT-557 policy (15s)    │                            │                     │
│  └──────────────┬──────────────┘                            │                     │
│                 │                                           │                     │
│                 └───────────────┐           ┌───────────────┘                     │
│                                 ▼           ▼                                     │
│                     ┌───────────────────────────────────┐                         │
│                     │  FederatedWikiStore (READ-ONLY)   │                         │
│                     │  - fans out wiki_query/related    │                         │
│                     │  - qualifies "ledger::issue:*"    │                         │
│                     └───────────────────────────────────┘                         │
│                                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐  │
│  │                       LedgerService Facade & CLI                            │  │
│  │  open() · ready() · claim() · close() · link() · context() · compact()     │  │
│  └─────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.wiki.project` | extends | Add `find_shared_root`, `resolve_git_common_dir`, `is_linked_worktree`, and `WikiProjectConfig.ledger_path`. |
| `parrot.knowledge.wiki.store.SQLiteWikiStore` | subclasses (`LedgerStore`) | Store policy consumed from FEAT-557 exactly as listed in Module 2 §2.1; `store.py` is not modified. |
| `parrot.knowledge.wiki.tools` | extends | Register MCP tools (`ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, `ledger_context`); add `derived_from` and `about` to `WikiRememberTool`. |
| `parrot.knowledge.wiki.federation.FederatedWikiStore` | modifies | Overlay-namespace routing: bare-id prefix routing in `_route`, local-plane destinations in `neighbors`, incoming overlay edges for local seeds (Module 13). |
| `parrot.knowledge.wiki.context` | modifies | Add `issue`, `task`, `spec`, `insight` to `_ID_KINDS` so id-prefix parsing and title elision recognise ledger kinds. |
| `parrot.knowledge.wiki.project.WikiNamespaceConfig` | extends | Add `overlay_prefixes: list[str] = []` (non-empty ⇒ overlay namespace). |
| `parrot.knowledge.wiki.mcp_server` | extends | Mount `ledger` namespace automatically in `create_wiki_mcp_server` with `overlay_prefixes=["issue", "task", "spec", "insight"]`, as a read-only foreign SQLite store through FEAT-557's federation policy path (Module 2 §2.1). Ledger write tools use their own `LedgerService`, never the federated read store. |
| `parrot.knowledge.wiki.cli` | extends | Add `@wiki.group(name="ledger")` providing CLI commands. |
| `parrot.knowledge.wiki.claude_code.assets` | modifies | Update `git_hook_block` to skip structural upserts when inside a linked worktree; install `post-merge` hook. |
| `parrot.flows.dev_loop.wiki_search` | extends | `DevLoopWikiSearch` resolves shared root and enriches research context with scoped ledger items. |
| `scripts/sdd/close_task.sh` | modifies | Emit `task.closed` event to `events.jsonl` upon verified task completion. |
| SDD Lifecycle Commands & Twins | modifies | Add deferred findings recording in `/sdd-codereview`, prime injection in `/sdd-start`, ledger display in `/sdd-next`, and merge validation in `/sdd-done`. |

### Data Models

```python
# parrot/knowledge/wiki/ledger/events.py
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, Field

LedgerEventKind = Literal[
    "issue.opened",
    "issue.claimed",
    "issue.acknowledged",
    "issue.closed",
    "issue.superseded",
    "issue.linked",
    "task.started",
    "task.closed",
    "spec.registered",
    "insight.recorded",
    "insight.superseded",
]

IssueKind = Literal["bug", "tech_debt", "feature_gap", "vulnerability"]
IssueSeverity = Literal["critical", "major", "minor", "low"]
IssueStatus = Literal["open", "claimed", "closed", "superseded"]


class LedgerEvent(BaseModel):
    """Immutable single-line event serialized into events.jsonl."""

    event_id: str = Field(description="SHA-1 hash hex digest (first 12 chars)")
    kind: LedgerEventKind
    subject: str = Field(description="Target identifier, e.g. issue:3f8a1c9e, task:TASK-1234, spec:FEAT-566")
    actor: str = Field(description="Author identifier, e.g. agent:codex, human:jesus")
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = Field(default_factory=dict)


class IssueOpenedPayload(BaseModel):
    title: str
    body: str
    kind: IssueKind = "bug"
    severity: IssueSeverity = "minor"
    discovered_from: str = Field(description="Source task/spec/review, e.g. task:TASK-3200, review:TASK-3200")
    about: list[str] = Field(default_factory=list, description="Target code symbols/files, e.g. sym:pkg/mod.py#Func")


class IssueClaimedPayload(BaseModel):
    claimed_by: str = Field(description="Agent or task claiming work, e.g. task:TASK-3205")


class IssueAcknowledgedPayload(BaseModel):
    """Explicit acceptance that an open critical issue must not block a merge.

    Does NOT change `status`; the index sets `acknowledged=True` on the issue page.
    """

    acknowledged_by: str = Field(description="Must be a human actor, e.g. human:jesus")
    reason: str


class IssueClosedPayload(BaseModel):
    reason: str
    closed_by: str
    resolved_by: str | None = None  # e.g. task:TASK-3205


class InsightRecordedPayload(BaseModel):
    fact: str
    title: str
    category: str = "note"
    derived_from: str = Field(description="Originating task, review, or spec id")
    about: list[str] = Field(default_factory=list, description="Related symbol or file ids")
```

### New Public Interfaces

```python
# parrot/knowledge/wiki/ledger/log.py
class LedgerLog:
    """Thread- and process-safe append-only event log manager."""

    def __init__(self, log_path: Path, max_event_bytes: int = 4096) -> None: ...
    def append(self, event: LedgerEvent) -> tuple[str, int]:
        """Append one event with a single atomic O_APPEND write.

        Returns (event_id, end_offset). Raises ValueError when the serialized line exceeds max_event_bytes.
        """
        ...

    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:
        """Yield (event, end_offset) from a byte offset; skips corrupted/partial lines with a logged warning."""
        ...


# parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:
    """Materialized SQLite view and query engine over events.jsonl."""

    def __init__(self, store: SQLiteWikiStore, log: LedgerLog) -> None: ...
    async def apply_event(self, event: LedgerEvent, conn: aiosqlite.Connection) -> None:
        """Reduce one event into pages and edges on a connection yielded by LedgerStore.ledger_transaction()."""
        ...

    async def sync(self, conn: aiosqlite.Connection | None = None) -> int:
        """Apply events after the persisted cursor up to the log tip; advance the cursor. Returns count applied."""
        ...

    async def rebuild(self) -> int:
        """Truncate index tables, reset the cursor and replay all events from offset 0. Returns count applied."""
        ...

    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:
        """Atomically claim an open issue. Returns True if claimed, False if already claimed/closed."""
        ...

    async def compact(self, older_than_days: int = 30) -> int:
        """Fold closed/superseded issues older than N days into summary pages. Never touches events.jsonl."""
        ...


# parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    """High-level service coordinating log, index, and SDD integration."""

    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService": ...
    async def open_issue(
        self,
        title: str,
        body: str,
        kind: IssueKind = "bug",
        severity: IssueSeverity = "minor",
        discovered_from: str = "",
        about: list[str] | None = None,
        actor: str = "agent:sdd",
    ) -> str: ...
    async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]: ...
    async def claim(self, issue_id: str, actor: str) -> bool: ...
    async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool: ...
    async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool: ...
    async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str: ...
    async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]: ...
    async def export_snapshot(self, dest: Path) -> bool: ...
    async def compact(self, older_than_days: int = 30) -> int: ...
    async def audit(self) -> dict[str, Any]: ...
```

---

## 3. Module Breakdown

> Define the discrete modules that will be implemented.
> These directly map to Task Artifacts in Phase 2.

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Project Shared Root | yes | Reuses Git `commondir` resolution from `graph_search.py` and `installer.py`; returns `Path`. | — |
| M2: SQLite Concurrency Policy | no | External hard prerequisite: FEAT-557 TASK-3216–TASK-3226 must be merged into `dev`; FEAT-566 consumes its finalized policy and typed busy error. | Owned by FEAT-557; no FEAT-566 task may modify the shared SQLite policy. |
| M3: Ledger Events Schema | yes | Pydantic v2 event models, deterministic SHA-1 IDs, fixed string literals. | — |
| M4: Append-Only Event Log | yes | Standard POSIX `os.open` with `O_APPEND \| O_WRONLY \| O_CREAT`, single `write()`, < 4 KiB validator. | — |
| M5: Ledger Materialized Index | no | `LedgerStore` over FEAT-557 `_write`/`_read`, atomic claim, sync cursor, event reducer state machine. | Core state machine logic. |
| M6: Ledger Service Facade | yes | Facade wrapping Log + Index + `SQLiteWikiStore` queries. | — |
| M7: SDD Artifacts Ingestion | yes | Markdown and JSON parsing of `sdd/specs/` and `sdd/tasks/index/` into `WikiPageRecord`s. | — |
| M8: Wiki MCP Tools Extension | yes | Standard `AbstractTool` implementations wrapping `LedgerService` and extended `WikiRememberTool`. | — |
| M9: Ledger CLI Group | yes | Standard Click command group `@wiki.group(name="ledger")` wrapping `LedgerService`. | — |
| M10: Claude Code Hook Worktree Guard | yes | Check `is_linked_worktree(root)`; skip `upsert --changed` in worktrees; install `post-merge`. | — |
| M11: DevLoop Wiki Context Injection | yes | Extend `DevLoopWikiSearch` to fetch `ledger_context` and append to research context. | — |
| M12: SDD Command Integration | no | Modifications across Claude, Codex, and Antigravity workflow scripts, gates, and `close_task.sh`. | Cross-platform workflow sync. |
| M13: Federation Overlay Routing | no | Changes `_route` / `neighbors` semantics in `FederatedWikiStore`. | Subtle id-homing rules with FEAT-450 / FEAT-532 regression surface. |

---

### Module 1: Project Shared Root & Worktree Detection
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/project.py`
- **Responsibility**: Provide deterministic resolution of the main checkout root from any linked worktree or plain repository, and define ledger storage paths.
- **Depends on**: Existing `project.py` constants and path helpers.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/project.py (modifies project.py:640)
  def resolve_git_common_dir(start: Path) -> Path | None:
      """Resolve the git common directory (main checkout's .git) across gitdir / commondir pointers.
      Returns None if start is not within a git repository.
      """

  def is_linked_worktree(start: Path | None = None) -> bool:
      """Return True if start (or CWD) is a linked git worktree (i.e. git-dir != git-common-dir)."""

  def find_shared_root(start: Path | None = None) -> Path:
      """Resolve the main checkout root where shared .parrot/ state lives.
      Honours PARROT_SHARED_ROOT environment variable, else walks git common dir,
      falling back to find_project_root(). Never raises.
      """

  # Extension to WikiProjectConfig
  class WikiProjectConfig(BaseModel):
      def ledger_path(self, root: Path) -> Path:
          """Return <root>/.parrot/ledger path for ledger log and index."""
          return root / PARROT_DIR / "ledger"
  ```

---

### Module 2: SQLite Concurrency Policy Prerequisite (FEAT-557)
- **Owner**: FEAT-557 — `wikitoolkit-sqlite-optimizations` (TASK-3216 through TASK-3226).
- **Required state**: Its complete feature branch is merged into `dev` and its SQLite concurrency/regression suite has passed before FEAT-566 work begins.
- **This module is the canonical FEAT-557 ↔ FEAT-566 boundary.** It produces no FEAT-566 task; it constrains Modules 5, 6, 8, 9, 13 and the test plan.

#### 2.1 Consumed FEAT-557 symbols (do not re-implement)

| FEAT-557 symbol | Delivered by | FEAT-566 consumer | Use |
|---|---|---|---|
| `WikiProjectConfig.sqlite_busy_timeout` / `sqlite_performance_pragmas` | TASK-3222 | M6 | The ledger honours the **same** project settings as `wiki.db`. No `ledger_busy_timeout` or other ledger-specific SQLite key is added. |
| `sqlite_policy_from_config(config)` (`project.py`) | TASK-3223 | M6 | `LedgerService.from_root` builds `LedgerStore(ledger_db, wiki_name="ledger", sqlite_policy=sqlite_policy_from_config(config))`. |
| `SQLiteWikiStore(..., sqlite_policy=, persistent_writer=)` | TASK-3217 | M5 | `LedgerStore` forwards both kwargs unchanged; `persistent_writer` stays at its default (`False`). |
| `SQLiteWikiStore._write(operation)` / `_read()` | TASK-3217, TASK-3219 | M5 | All ledger index writes run inside `_write`; all ledger reads inside `_read`. FEAT-566 never issues `BEGIN`, `COMMIT`, `ROLLBACK`, or `PRAGMA` itself. |
| Read-first latched migration | TASK-3218 | M5 | Covers the wiki schema of `ledger.db`. The ledger's own `ledger_state` DDL runs only inside `_write`; read paths treat a missing `ledger_state` as cursor offset 0 and never create it (preserving FEAT-557's "pure reads issue zero write statements"). |
| `WikiStoreBusy(db_path, operation, waited_seconds)` | TASK-3216 | M5, M6, M8, M9 | The only busy signal FEAT-566 handles; raw `sqlite3.OperationalError` busy codes are never caught by ledger code. |
| `SQLiteWikiStore.checkpoint(truncate=True)` | TASK-3220 | M9 | Called (non-fatal) after the ledger's long writers, `ledger rebuild` and `ledger ingest-sdd`, mirroring FEAT-557's build/ingest rule; never after `open`/`claim`/`close`/`sync`. |
| `SQLiteWikiStore.sqlite_settings()` | TASK-3225 | M6 (`audit`) | `ledger audit` embeds the effective `ledger.db` settings from this method instead of querying pragmas itself. |
| `create_wiki_store(sqlite_policy=…)` + read-only foreign-store timeout in `federation.py` | TASK-3223 | M8, M13 | The `ledger` namespace mounted in the MCP read store is a read-only foreign SQLite store and gets its timeout-only policy through FEAT-557's federation path. M13's overlay edits in `federation.py` are rebased on top of TASK-3223's change there. |
| `slow` pytest marker, `_peer_writer` helper (`tests/knowledge/wiki/test_store_concurrency.py`) | TASK-3226 | §4 | Reused for ledger busy tests; the marker is not re-registered and the peer-writer helper is not duplicated (promote it to `conftest.py` if it is not importable). |

#### 2.2 `WikiStoreBusy` behaviour per ledger entry point

Aligned with FEAT-557's precedent (`upsert` soft-skips; MCP tools return actionable guidance):

| Entry point | Event already durable in `events.jsonl`? | On `WikiStoreBusy` |
|---|---|---|
| `ledger open` / `close` / `acknowledge`, `ledger_open` / `ledger_close` tools, `close_task.sh`, `/sdd-start` `task.started` | yes (appended before the index transaction) | Soft success: exit 0 / tool success with `index_pending=true` and "recorded; run `wikitoolkit ledger sync`". |
| `ledger claim` / `ledger_claim` tool | no (claim appends only inside the transaction) | Retryable failure: exit 2 / tool error with FEAT-557's `db_path`, `operation`, `waited_seconds`. Never reported as `False` ("already claimed"). |
| `ledger sync` / `rebuild` / `ingest-sdd` / `compact` | n/a | Exit 2 with FEAT-557's message; the cursor is unchanged (the whole batch rolled back). |
| `ledger ready` / `context` / `blockers` / `export` / `audit` | n/a (reads) | Not applicable — `_read()` never takes the writer lock. A stale index is reported as `index_lag=<events>` rather than synced implicitly. |
| `wiki_remember` / `wiki_note` provenance writes to `wiki.db` | n/a | Unchanged FEAT-557 behaviour; FEAT-566 adds nothing. |

#### 2.3 Prohibited changes
- FEAT-566 does not modify `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`, `sources.py`, FEAT-557's SQLite fields or helper in `project.py`, or the `create_wiki_store` policy plumbing.
- FEAT-566 does not add its own contention test for generic SQLite writers; FEAT-557's `test_build_and_remember_multiprocess_contention` owns that guarantee.

---

### Module 3: Ledger Event Schema & Models
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py`
- **Responsibility**: Define immutable Pydantic models for all event kinds, validation constraints, and deterministic ID hashing.
- **Depends on**: Pydantic v2
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py (new)
  def compute_event_id(kind: str, subject: str, actor: str, ts: str, payload: dict[str, Any]) -> str:
      """Calculate sha1(f'{kind}|{subject}|{actor}|{ts}|{json_dumps(payload)}')[:12]."""

  def compute_issue_id(kind: str, title: str, discovered_from: str) -> str:
      """Calculate deterministic issue identifier issue:<hash> for deduplication."""

  class LedgerEvent(BaseModel):
      """Validated event schema for events.jsonl."""
  ```

---

### Module 4: Append-Only Event Log
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py`
- **Responsibility**: Manage atomic append writes to `events.jsonl` using POSIX file semantics and provide streaming iteration.
- **Depends on**: Module 3 (`events.py`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py (new)
  class LedgerLog:
      """Append-only, lock-free log file manager."""
      def __init__(self, log_path: Path, max_event_bytes: int = 4096) -> None:
          """Initialize log at log_path."""

      def append(self, event: LedgerEvent) -> tuple[str, int]:
          """Serialize to UTF-8 JSON line; verify len <= max_event_bytes; write via os.open(O_APPEND).
          Returns (event.event_id, end_offset). Raises ValueError if event exceeds max_event_bytes.
          """

      def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:
          """Yield (event, end_offset) for every valid line at or after from_offset."""
  ```

---

### Module 5: Materialized Ledger Index
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
- **Path (store adapter)**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py`
- **Responsibility**: Project events from `events.jsonl` into `ledger.db` as `WikiPageRecord`s and relations, and handle atomic claim transactions.
- **Depends on**: FEAT-557 completion, Module 3 (`events.py`), Module 4 (`log.py`)
- **Transaction boundary (no `store.py` changes)**: FEAT-557's public writers (`upsert_pages`, `add_edges`, …) each open their own `_write` transaction, so they cannot compose sync + check + append + apply atomically. `LedgerStore` subclasses `SQLiteWikiStore` inside the ledger package and composes the protected `_write(operation)` (Module 2 §2.1) with the connection-scoped helpers `_upsert_pages_conn` and `_insert_edges_conn`, which FEAT-557's call-site sweep (TASK-3219) leaves intact. If FEAT-557 lands `_write` under a different name or shape, Module 5 adapts to it; it never re-implements transaction or busy handling.
- **Write-through always syncs to tip**: every index write (`open`, `close`, `acknowledge`, `task.*`, `claim`) applies via `sync(conn)` — cursor → current log tip, which includes the caller's own freshly appended event — never by applying the caller's single event alone. The cursor therefore only moves forward over a contiguous prefix of the log, and an event appended concurrently by another worktree is never skipped.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py (new)
  class LedgerStore(SQLiteWikiStore):
      """SQLiteWikiStore specialisation for ledger.db: ledger_state table + composable write transactions."""

      @asynccontextmanager
      async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]:
          """Yield a connection inside FEAT-557's `_write(operation)`; creates `ledger_state` on first use.
          Propagates WikiStoreBusy unchanged."""

      async def read_cursor(self) -> tuple[int, str | None]:
          """Read (offset, last_event_id) through `_read()`; a missing ledger_state table reads as (0, None)."""

      async def upsert_pages_in(self, conn: aiosqlite.Connection, pages: list[WikiPageRecord]) -> None:
          """Delegate to _upsert_pages_conn on the caller's transaction."""

      async def add_edges_in(self, conn: aiosqlite.Connection, edges: list[tuple]) -> None:
          """Delegate to _insert_edges_conn on the caller's transaction."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py (new)
  class LedgerIndex:
      """Materialized query view over the event log backed by LedgerStore."""
      def __init__(self, store: LedgerStore, log: LedgerLog) -> None:
          """Initialize index with underlying wiki store and event log."""

      async def apply_event(self, event: LedgerEvent, conn: aiosqlite.Connection) -> None:
          """Apply event reduction rules inside an existing connection/transaction."""

      async def sync(self, conn: aiosqlite.Connection | None = None) -> int:
          """Read cursor (offset, event_id) from ledger_state; apply events from offset to tip;
          advance cursor in the same transaction. Cursor/event_id mismatch -> rebuild(). Returns applied count.
          """

      async def rebuild(self) -> int:
          """Wipe pages/edges and ledger_state in ledger store and replay entire event log from offset 0."""

      async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:
          """Execute atomic claim, all under ONE store.ledger_transaction("ledger.claim"):
          1. sync(conn)  -- catch up with events other writers appended since our last read
          2. check status == 'open'  -- else return False
          3. append issue.claimed to the log
          4. apply_event(conn) + advance cursor, commit
          WikiStoreBusy follows Module 2 §2.2 (retryable, nothing appended, never False).
          """

      async def compact(self, older_than_days: int = 30) -> int:
          """Fold closed/superseded issues older than N days into summary pages; never rewrites events.jsonl."""
  ```
- **Reducer rules (replay determinism)**:
  - `issue.claimed` on an issue that is not `open` at that point in log order is a no-op, so the first claim in log order wins on every replay — including a claim appended by a process that crashed before committing its index transaction.
  - `issue.opened` for an existing `issue_id` (dedup via `compute_issue_id`) is a no-op except for appending a `discovered-from` edge.
  - `issue.acknowledged` sets `acknowledged=True` without changing `status`; it is ignored on closed/superseded issues.
  - Only `LedgerIndex.claim_issue` may emit `issue.claimed`; shell writers (`close_task.sh`) emit only `task.*` events.

---

### Module 6: Ledger Service Facade
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
- **Responsibility**: Unified programmatic facade for SDD commands, tools, and CLI.
- **Depends on**: Module 1 (`project.py`), Module 4 (`log.py`), Module 5 (`index.py`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py (new)
  class LedgerService:
      """Public API for interacting with the work ledger."""
      @classmethod
      def from_root(cls, root: Path | None = None) -> "LedgerService":
          """Initialize service pointing at find_shared_root(root).

          Opens LedgerStore(<shared>/.parrot/ledger/ledger.db, sqlite_policy=sqlite_policy_from_config(config))
          with the shared root's WikiProjectConfig (Module 2 §2.1) — no ledger-specific SQLite settings.
          """

      async def open_issue(
          self,
          title: str,
          body: str,
          kind: IssueKind = "bug",
          severity: IssueSeverity = "minor",
          discovered_from: str = "",
          about: list[str] | None = None,
          actor: str = "agent:sdd",
      ) -> str:
          """Record new issue in log and index. Returns issue_id."""

      async def ready_work(self, kind: IssueKind | None = None) -> list[dict[str, Any]]:
          """Return list of unblocked, unclaimed issues and tasks."""

      async def claim(self, issue_id: str, actor: str) -> bool:
          """Delegate to LedgerIndex.claim_issue."""

      async def acknowledge(self, issue_id: str, reason: str, actor: str) -> bool:
          """Record issue.acknowledged. Rejects non-human actors (actor must start with 'human:')."""

      async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool:
          """Close an issue with reason."""

      async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str:
          """Retrieve graph-scoped open issues and insights touching the given files."""

      async def merge_blockers(self, feature_id: str) -> list[dict[str, Any]]:
          """Open/claimed, severity='critical', acknowledged=False issues whose discovered_from
          is the feature's spec (spec:FEAT-NNN), one of its tasks (task:TASK-NNN) or their reviews (review:TASK-NNN).
          Critical issues discovered by OTHER features never block this feature's merge.
          """

      async def export_snapshot(self, dest: Path) -> bool:
          """Write sdd/ledger/issues.jsonl deterministically (see Snapshot format). Returns True if content changed."""

      async def compact(self, older_than_days: int = 30) -> int:
          """Delegate to LedgerIndex.compact."""

      async def audit(self) -> dict[str, Any]:
          """Log size, event counts per kind, cursor lag, broken edges, and `sqlite` = store.sqlite_settings()
          (FEAT-557); warns when events.jsonl > 50 MiB."""
  ```
- **Snapshot format (`sdd/ledger/issues.jsonl`)**: one JSON object per issue with status `open`, `claimed`, or closed/superseded but not yet compacted; keys sorted, rows sorted by `issue_id`, no volatile fields (no `ts` of the export itself), so regenerating from the same ledger state is byte-identical. Insights are excluded (they live as wiki memory pages).

---

### Module 7: SDD Artifacts Ingestion
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py`
- **Responsibility**: Scan `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` in the main checkout and project them into the wiki/ledger graph.
- **Depends on**: Module 5 (`index.py`, `store.py` → `LedgerStore`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py (new)
  class SDDGraphIngest:
      """Parses SDD specs and task indexes into graph pages and edges."""
      def __init__(self, store: LedgerStore, shared_root: Path) -> None: ...
      async def ingest_all(self) -> dict[str, int]:
          """Ingest all specs, tasks, and dependency/file edges. Returns {'specs': N, 'tasks': M, 'edges': E}."""
  ```

---

### Module 8: MCP Tools & Provenance Extension
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/tools.py` & `mcp_server.py`
- **Responsibility**: Expose `ledger_*` tools to MCP agents and update `WikiRememberTool` to accept `derived_from` and `about` arguments.
- **Depends on**: Module 6 (`service.py`), `WikiRememberTool`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/tools.py (modifies tools.py:130, 272)
  class WikiRememberInput(BaseModel):
      fact: str
      category: str = "note"
      title: str | None = None
      link_page_id: str | None = None
      rel: str | None = "references"
      derived_from: str | None = Field(default=None, description="Originating task, review, or spec id")
      about: list[str] | None = Field(default=None, description="Target symbol or file ids")

  class LedgerOpenTool(AbstractTool): ...
  class LedgerReadyTool(AbstractTool): ...
  class LedgerClaimTool(AbstractTool): ...
  class LedgerCloseTool(AbstractTool): ...
  class LedgerContextTool(AbstractTool): ...
  ```
- **Provenance edges from `wiki.db`**: `derived_from` / `about` targets that name a ledger kind (`task:TASK-3200`, `spec:FEAT-566`) are stored as foreign-qualified destinations (`ledger::task:TASK-3200`) through the existing `_assert_local_or_foreign_destination` path; code-plane targets (`sym:`, `file:`) stay unqualified.
- **No `ledger_acknowledge` MCP tool**: acknowledging a critical is a human decision, exposed only through the CLI (Module 9).

---

### Module 9: Ledger CLI Interface
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: Provide `@wiki.group(name="ledger")` with subcommands `open`, `ready`, `claim`, `acknowledge`, `close`, `context`, `blockers`, `export`, `sync`, `rebuild`, `ingest-sdd`, `compact`, and `audit`.
  - `acknowledge <issue_id> --reason … --actor human:<name>` — refuses non-`human:` actors.
  - `blockers <FEAT-ID>` — prints `merge_blockers()`; exit code 1 when non-empty (consumed by `/sdd-done`).
  - `export [--dest sdd/ledger/issues.jsonl]` — exit code 0 always; prints `changed` / `unchanged`.
  - `compact [--older-than 30]` — manual only, index-only; never invoked by any SDD command.
  - `rebuild` and `ingest-sdd` call FEAT-557's `store.checkpoint(truncate=True)` after success, non-fatally (a reader-blocked truncate is logged, not an error); no other ledger command checkpoints.
  - `WikiStoreBusy` exit codes and messages follow Module 2 §2.2; the CLI renders FEAT-557's `db_path` / `operation` / `waited_seconds` rather than composing its own busy text.
- **Depends on**: Module 6 (`service.py`), Module 7 (`sdd_ingest.py`), Click
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/cli.py (modifies cli.py:2118+)
  @wiki.group(name="ledger")
  def ledger_group() -> None:
      """Manage the SDD work ledger, discovered work, and spec graph."""

  @ledger_group.command(name="open")
  @click.option("--kind", type=click.Choice(["bug", "tech_debt", "feature_gap", "vulnerability"]), default="bug")
  @click.option("--severity", type=click.Choice(["critical", "major", "minor", "low"]), default="minor")
  @click.option("--discovered-from", required=True)
  @click.option("--about", multiple=True)
  @click.option("--title", required=True)
  @click.option("--body", required=True)
  def ledger_open(kind, severity, discovered_from, about, title, body) -> None: ...
  ```

---

### Module 10: Claude Code Hook & Worktree Guard
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` & `installer.py`
- **Responsibility**: Guard Git hooks so `upsert --changed` does not attempt structural plane writes from linked worktrees, install `post-merge` hook in the main checkout, and auto-register the ledger namespace.
- **Depends on**: Module 1 (`project.py`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py (modifies assets.py:166)
  def git_hook_block(root: Path) -> str:
      """Build post-commit hook checking is_linked_worktree before upsert."""
  ```

---

### Module 11: DevLoop Research Context Injection
- **Path**: `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py`
- **Responsibility**: Ensure `DevLoopWikiSearch` resolves `find_shared_root()`, making wiki context available inside worktrees, and append relevant ledger context to research summaries.
- **Depends on**: Module 1 (`project.py`), Module 6 (`service.py`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py (modifies wiki_search.py:38, 91)
  class DevLoopWikiSearch:
      @classmethod
      def from_project(cls, root: Path | None = None) -> Optional["DevLoopWikiSearch"]:
          """Use find_shared_root() to open the shared wiki plane even inside worktrees."""
  ```

---

### Module 12: SDD Command Integration & Lifecycle Scripts
- **Path**: `scripts/sdd/close_task.sh`, `.claude/commands/sdd-*.md`, `.agent/workflows/sdd-*.md`, `.agents/skills/sdd-*/SKILL.md`
- **Responsibility**: Wire ledger emission and consumption into SDD lifecycle commands across Claude, Codex, and Antigravity:
  - `close_task.sh`: append `task.closed` event with task status and verification.
  - `/sdd-codereview`: require *Deferred findings* table; file unfixed 🔴/🟡 findings via `ledger open`.
  - `/sdd-start`: inject `ledger context` before code implementation; emit `task.started`.
  - `/sdd-next`: query both unblocked tasks and ready ledger issues; support promotion via `/sdd-task --from-issue <id>`.
  - `/sdd-done`: refuse `--merge` when `wikitoolkit ledger blockers <FEAT-ID>` exits non-zero (the PR flow prints the blockers into the PR body instead of refusing). Resolution is `ledger close` or a human `ledger acknowledge`.
  - `/sdd-done` snapshot (every run, PR **and** `--merge` flows, feature type only):
    1. After the merge step (`--merge`) or after pushing the feature branch (PR flow), `git fetch origin <base_branch>` and create a **throwaway detached worktree** at `origin/<base_branch>` (`.claude/worktrees/_ledger-snapshot-<pid>`). The snapshot is never committed on the feature branch (concurrent features would conflict on it) and never by switching branches in the shared main checkout (other sessions may have uncommitted work there).
    2. In that worktree run `wikitoolkit ledger export` (it reads the shared ledger via `find_shared_root()`); if it prints `unchanged`, go to step 5.
    3. `git commit -m "sdd: ledger snapshot for <FEAT-ID>" -- sdd/ledger/issues.jsonl`.
    4. `git push origin HEAD:<base_branch>`. On rejection: `git fetch` + `git reset --hard origin/<base_branch>` *inside the throwaway worktree only*, re-run `ledger export` (a fresh export from the shared ledger supersedes both sides), commit, push again — max 3 attempts, then warn and continue without failing `/sdd-done`.
    5. `git worktree remove --force` the throwaway worktree.
    6. `type: hotfix` skips the snapshot entirely (`/sdd-done` never pushes to `main`); the next feature `/sdd-done` re-exports full state.
- **Depends on**: Module 6 (`service.py`), Module 9 (`cli.py`)

---

### Module 13: Federation Overlay Routing
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/federation.py`, `context.py`, `project.py`
- **Responsibility**: Make an overlay namespace (the ledger) addressable by bare id and traversable in both directions against the local code plane, without changing behaviour for existing (non-overlay) namespaces.
- **Depends on**: FEAT-557 TASK-3223 (already edits `federation.py` to give read-only foreign stores the busy timeout — M13 builds on that file state and must not touch store construction or policy); consumed by Module 8's ledger mount.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/context.py (modifies context.py:39)
  _ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page|sym|issue|task|spec|insight"

  # packages/ai-parrot/src/parrot/knowledge/wiki/project.py (extends WikiNamespaceConfig, project.py:175)
  class WikiNamespaceConfig(BaseModel):
      overlay_prefixes: list[str] = Field(
          default_factory=list,
          description="Id kinds owned by this namespace; non-empty makes it an overlay over the local plane",
      )

  # packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
  class FederatedWikiStore(BaseWikiStore):
      def _route(self, page_id: str) -> tuple[NamespaceHandle | None, str, bool]:
          """(modifies federation.py:849) Unqualified id whose kind is in exactly one overlay's
          overlay_prefixes routes to that overlay. Two overlays claiming the same prefix is a
          configuration error raised at construction time."""

      async def neighbors(self, concept_id: str, rel: str | None = None, direction: str = "both") -> list[dict[str, Any]]:
          """(modifies federation.py:913)
          - Seed in an overlay: neighbor ids whose kind is NOT in its overlay_prefixes are local-plane
            references — returned unqualified and hydrated from the local store (never `ledger::sym:`).
          - Seed in the local plane, direction in ('in', 'both'): also fold in each overlay's
            store.neighbors(local_id, direction='in'), qualified with the overlay name."""
  ```
- **Invariant**: with no overlay namespace configured, every existing `tests/knowledge/wiki/test_federation.py` and `tests/knowledge/wiki/roblox/test_reference_routing.py` test passes unchanged.

---

## 4. Test Specification

### Concurrency & Atomicity Spike (Mandatory Gate)

Before finalizing implementation of Modules 5 and 6, execute a deterministic test script verifying:
1. **Concurrent Log Appends**: Run 8 parallel processes each appending 100 events to `events.jsonl` using `O_APPEND`. Verify that:
   - Exactly 800 valid, non-interleaved JSON lines are present.
   - Zero lines are corrupted or interleaved.
2. **Log survives index contention** (ledger-specific; generic "no raw `database is locked`" is already proven by FEAT-557's `test_build_and_remember_multiprocess_contention` and is NOT re-tested here): hold the `ledger.db` writer with FEAT-557's `_peer_writer` helper and a short `SQLitePragmaPolicy(busy_timeout_s=1.0)`, run 8 concurrent `open_issue` calls from separate processes. Verify every call returns `index_pending=true`, `events.jsonl` holds all 8 events, and after releasing the peer one `sync()` makes the index contain all 8 issues with the cursor at the log tip.
3. **Atomic Claim**: Have 5 concurrent agents attempt to claim the same open issue simultaneously. Verify that exactly ONE succeeds and 4 receive `False` (already claimed).
4. **Atomic Claim over a stale index**: Append an `issue.claimed` event through a *second* process's `LedgerIndex`, then — without calling `sync()` — attempt a claim from the first process. Verify it returns `False` (the in-transaction `sync()` observed the foreign claim).

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_git_common_dir_plain` | Module 1 | Returns repo root for plain git checkout |
| `test_resolve_git_common_dir_worktree` | Module 1 | Traverses `gitdir:` and `commondir` from linked worktree |
| `test_is_linked_worktree` | Module 1 | Correctly distinguishes worktree vs main checkout |
| `test_event_id_determinism` | Module 3 | Verifies SHA-1 event ID calculation |
| `test_event_oversize_rejection` | Module 4 | Rejects events > 4 KiB |
| `test_log_append_and_iter` | Module 4 | Writes events and reads them back sequentially |
| `test_index_replay_idempotence` | Module 5 | Replaying the same log multiple times produces identical state |
| `test_atomic_claim_transition` | Module 5 | Claiming an already claimed or closed issue fails |
| `test_sync_cursor_resume` | Module 5 | `sync()` applies only events past the persisted offset; a cursor/event_id mismatch triggers `rebuild()` |
| `test_replay_first_claim_wins` | Module 5 | Two `issue.claimed` events in the log: replay marks the first claimant only |
| `test_claim_busy_propagates_without_append` | Module 5 | With FEAT-557's `_peer_writer` holding `ledger.db`: `claim_issue` raises `WikiStoreBusy`, returns no `False`, and `events.jsonl` gains no `issue.claimed` line (`@pytest.mark.slow`, marker registered by FEAT-557) |
| `test_write_through_syncs_foreign_events` | Module 5 | Process B appends an event after A's cursor; A's `open_issue` applies both B's and its own event and the cursor ends at the tip |
| `test_ledger_reads_issue_no_writes` | Module 5 | On a fresh `ledger.db` without `ledger_state`, `read_cursor()` / `ready_work()` return offset 0 / empty and issue zero write statements (FEAT-557's SQL-trace pattern) |
| `test_service_uses_project_sqlite_policy` | Module 6 | `sqlite_busy_timeout=30` in `.parrot/wiki.json` reaches the `LedgerStore` connection via `sqlite_policy_from_config`; no ledger-specific key exists |
| `test_rebuild_and_ingest_checkpoint_only` | Module 9 | `ledger rebuild` / `ingest-sdd` call `checkpoint()`; `open` / `claim` / `sync` do not |
| `test_ledger_open_busy_is_soft_success` | Module 9 | `WikiStoreBusy` during `ledger open` exits 0 with `index_pending`; during `ledger claim` exits 2 |
| `test_compact_index_only` | Module 5 | `compact()` folds old closed issues; `events.jsonl` bytes and sync cursor are unchanged |
| `test_acknowledge_requires_human_actor` | Module 6 | `acknowledge(..., actor="agent:codex")` is rejected; `human:` succeeds and status stays `open` |
| `test_merge_blockers_scoped_to_feature` | Module 6 | A critical discovered by another feature does not block; an acknowledged one does not block |
| `test_export_snapshot_deterministic` | Module 6 | Two exports of the same state are byte-identical; second returns `changed=False` |
| `test_route_bare_overlay_prefix` | Module 13 | `get_page("issue:x")` routes to the ledger overlay and returns `ledger::issue:x` |
| `test_overlay_outgoing_local_destination` | Module 13 | `neighbors("ledger::issue:x")` returns `sym:…` unqualified and hydrated from the local plane |
| `test_local_seed_incoming_overlay_edges` | Module 13 | `neighbors("sym:…", direction="in")` includes `ledger::issue:x` |
| `test_overlay_prefix_collision_rejected` | Module 13 | Two overlays claiming `issue` raise at `FederatedWikiStore` construction |
| `test_wiki_remember_with_provenance` | Module 8 | Memory page created with `derived-from` and `about` edges |
| `test_hook_block_worktree_guard` | Module 10 | Hook script exits early when inside linked worktree |

### Integration Tests

| Test | Description |
|---|---|
| `test_ledger_full_lifecycle` | Open issue → list ready → claim → close → verify log and index consistency |
| `test_sdd_task_close_emits_event` | `close_task.sh` appends `task.closed` to shared `events.jsonl` |
| `test_ledger_context_retrieval` | Retrieve context for modified files; assert relevant open issues and insights returned |
| `test_sdd_graph_ingestion` | Run `ingest-sdd`; assert spec and task nodes created with correct edges in `ledger.db` |
| `test_federated_query_across_planes` | Federated query searches both `wiki.db` (code) and `ledger.db` (issues) |
| `test_wiki_related_symbol_lists_open_issue` | Open an issue `about` a `sym:` id via `LedgerService`; `wiki_related` on that symbol through the MCP read store lists it |
| `test_federation_unchanged_without_overlay` | Existing `test_federation.py` / `roblox/test_reference_routing.py` suites pass with no overlay configured |

### Test Data / Fixtures

```python
# tests/knowledge/wiki/conftest.py
@pytest.fixture
def temp_ledger_dir(tmp_path: Path):
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    return ledger_dir

@pytest.fixture
def sample_issue_event():
    return LedgerEvent(
        event_id="e1a2b3c4d5e6",
        kind="issue.opened",
        subject="issue:f1a2b3c4d5e6",
        actor="agent:codex",
        ts="2026-09-14T00:00:00Z",
        payload={
            "title": "Overlay neighbors drop hydration for unreachable namespace",
            "body": "_hydrate_foreign_neighbors leaves a raw stub without a diagnostic row.",
            "kind": "bug",
            "severity": "major",
            "discovered_from": "task:TASK-3210",
            "about": ["sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore._hydrate_foreign_neighbors"],
        },
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `find_shared_root()` resolves the main checkout root from both plain checkouts and `.claude/worktrees/*` without relying on CWD assumptions.
- [ ] `events.jsonl` appends are atomic and validated under concurrency tests with zero line interleaving.
- [ ] FEAT-566 makes no changes to `store.py`, `sources.py`, or FEAT-557's SQLite config/factory plumbing, and its diff contains no `BEGIN`, `COMMIT`, `ROLLBACK`, `PRAGMA`, `busy_timeout`, or `timeout=` for SQLite (all via Module 2 §2.1).
- [ ] `ledger.db` is opened with `sqlite_policy_from_config(<shared root config>)`; no ledger-specific SQLite configuration key exists.
- [ ] `WikiStoreBusy` handling matches Module 2 §2.2 for every ledger CLI command and MCP tool; ledger read paths issue zero write statements.
- [ ] `ledger rebuild` and `ledger ingest-sdd` checkpoint through FEAT-557's `checkpoint()`; `ledger audit` reports `sqlite_settings()`.
- [ ] `ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, and `ledger_context` are available as MCP tools and CLI commands; `acknowledge`, `blockers`, `export`, `sync`, `rebuild`, `ingest-sdd`, `compact`, and `audit` are available as CLI commands.
- [ ] `claim_issue` syncs the index inside its single `_write` transaction; the stale-index spike scenario returns `False`; every write-through applies via `sync(conn)` to the log tip.
- [ ] `sync()` resumes from a persisted `ledger_state` cursor; `compact` never rewrites `events.jsonl` and is never invoked automatically by any SDD command.
- [ ] `wiki_page issue:<id>` resolves without a `ledger::` prefix, and `wiki_related sym:<id>` lists ledger issues/tasks/specs that point at the symbol; ledger→code neighbors are never returned as `ledger::sym:…`.
- [ ] `wiki_remember` supports `derived_from` and `about` parameters, generating corresponding graph edges.
- [ ] `wikitoolkit ledger ingest-sdd` indexes all `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` into `spec:` and `task:` nodes with `implements`, `blocks`, and `touches` edges.
- [ ] `scripts/sdd/close_task.sh` appends a `task.closed` event to `events.jsonl`.
- [ ] `/sdd-codereview` includes a mandatory *Deferred findings* table filing unfixed findings via `ledger_open`.
- [ ] `/sdd-start` injects scoped ledger context before code implementation and records `task.started`.
- [ ] `/sdd-next` displays both pending tasks and open ledger issues.
- [ ] `/sdd-done --merge` blocks when `ledger blockers <FEAT-ID>` is non-empty (critical, open/claimed, unacknowledged, discovered by this feature); the PR flow lists them in the PR body.
- [ ] Every feature `/sdd-done` (PR and `--merge`) regenerates `sdd/ledger/issues.jsonl` deterministically and commits it to `base_branch` from a throwaway worktree only when it changed; hotfixes skip it.
- [ ] Workflow documents and scripts are updated across Claude (`.claude/commands/`), Codex (`.agents/skills/`), and Antigravity (`.agent/workflows/`).
- [ ] All unit and integration tests pass (`pytest packages/ai-parrot/tests/knowledge/wiki/ -v`).
- [ ] No regressions in existing wiki functionality (`wikitoolkit query`, `page`, `related`, `build`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
from parrot.knowledge.wiki.project import (
    find_project_root,
    load_project_config,
    WikiProjectConfig,
    wiki_write_lock,
    PARROT_DIR,
    CONFIG_FILENAME,
    LOCK_FILENAME,
)  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/project.py:34-40, 65, 398, 640

from parrot.knowledge.wiki.store import (
    SQLiteWikiStore,
    WikiPageRecord,
    create_wiki_store,
    register_wiki_backend,
    SCHEMA_VERSION,
)  # verified 2026-09-14 (post PR #1381): store.py:774, 362, 1940, 464, 50

# Available only AFTER the FEAT-557 prerequisite merges (Module 2 §2.1) — verify with grep before use:
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy  # FEAT-557 TASK-3216
from parrot.knowledge.wiki.project import sqlite_policy_from_config  # FEAT-557 TASK-3223

from parrot.knowledge.wiki.federation import (
    FederatedWikiStore,
    open_namespace_store,
    resolve_namespaces,
)  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:337, 599

from parrot.knowledge.wiki.federation import NamespaceHandle  # verified: federation.py:85
from parrot.knowledge.wiki.context import (
    NS_SEPARATOR,
    split_namespaced_id,
    qualify_id,
)  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/context.py:29, 53, 81
from parrot.knowledge.wiki.project import WikiNamespaceConfig  # verified: project.py:175 (model_config extra="forbid")

from parrot.knowledge.wiki.tools import (
    WikiRememberTool,
    WikiRememberInput,
    WikiNoteTool,
    create_wiki_tools,
)  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/tools.py:130, 272, 354, 544

from parrot.flows.dev_loop.wiki_search import DevLoopWikiSearch  # verified: packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:26
from parrot.tools.repo.graph_search import resolve_plane_root, open_plane  # verified: packages/ai-parrot/src/parrot/tools/repo/graph_search.py:42, 96
from parrot.knowledge.wiki.claude_code.installer import _git_hook_path  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py:619
from parrot.knowledge.wiki.claude_code.assets import git_hook_block, GIT_HOOK_BEGIN, GIT_HOOK_END  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py:47-48, 166
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
class WikiProjectConfig(BaseModel):
    wiki_name: str = "codebase"  # line 398
    storage_dir: str = ".parrot/wiki"  # line 399
    backend: Literal["sqlite", "memory", "arangodb"] = "sqlite"  # line 400
    def storage_path(self, root: Path) -> Path: ...  # line 472
    def db_path(self, root: Path) -> Path: ...  # line 477
    def is_built(self, root: Path) -> bool: ...  # line 481

def find_project_root(start: Path | None = None) -> Path | None: ...  # line 640
def wiki_write_lock(store_dir: Path, timeout: float = 0.0) -> Iterator[bool]: ...  # line 65

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class WikiPageRecord(BaseModel):
    concept_id: str  # line 284
    node_id: Optional[str]
    title: str = ""
    category: str = "concept"
    summary: str = ""
    body: str = ""
    source_id: Optional[str] = None
    token_count: int = 0
    origin: str = "ingest"  # line 287
    asserted_by: Optional[str] = None  # line 288

class SQLiteWikiStore(BaseWikiStore):  # line 774 — current tree, BEFORE FEAT-557
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False) -> None: ...  # line 822
    def _assert_writable(self) -> None: ...  # line 874
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]: ...  # line 888 — DELETED by FEAT-557 TASK-3219; never reference it
    async def _migrate(self, conn: aiosqlite.Connection) -> None: ...  # line 1109 — made read-first/latched by TASK-3218
    async def _upsert_pages_conn(self, conn: aiosqlite.Connection, pages: list[WikiPageRecord]) -> None: ...  # line 1223 — kept by TASK-3219
    async def _insert_edges_conn(self, conn: aiosqlite.Connection, edges: list[tuple]) -> None: ...  # line 1267 — kept by TASK-3219
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # line 1288
    async def add_edges(self, edges: list[tuple]) -> int: ...  # line 1308
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...  # line 1724
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]: ...  # line 1817
    async def broken_edges(self) -> list[dict[str, Any]]: ...  # line 1918

# SQLiteWikiStore AFTER FEAT-557 (contract from sdd/specs/wikitoolkit-sqlite-optimizations.spec.md §2–§3; line numbers TBD at merge)
class SQLiteWikiStore(BaseWikiStore):
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False,
                 sqlite_policy: SQLitePragmaPolicy | None = None, persistent_writer: bool = False) -> None: ...
    async def _read(self) -> AsyncIterator[aiosqlite.Connection]: ...  # asynccontextmanager; never migrates or writes
    async def _write(self, operation: str) -> AsyncIterator[aiosqlite.Connection]: ...  # asynccontextmanager; BEGIN IMMEDIATE, commit/rollback once, WikiStoreBusy
    async def checkpoint(self, truncate: bool = True) -> dict[str, int | bool]: ...  # TASK-3220
    async def sqlite_settings(self) -> dict[str, Any]: ...  # TASK-3225

class SQLitePragmaPolicy(BaseModel):
    busy_timeout_s: float = 15.0  # ge=1.0, le=120.0
    performance_pragmas: bool = False
    journal_size_limit: int = 67_108_864

class WikiStoreBusy(sqlite3.OperationalError):
    def __init__(self, db_path: Path, operation: str, waited_seconds: float) -> None: ...

def sqlite_policy_from_config(config: WikiProjectConfig) -> SQLitePragmaPolicy: ...  # project.py (TASK-3223)

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
class FederatedWikiStore(BaseWikiStore):
    def __init__(self, local: BaseWikiStore, local_name: str = "local", handles: list[NamespaceHandle] | None = None, skipped=None, *, qualify_local: bool = False, origin_local=None): ...  # line 599
    def _route(self, page_id: str) -> tuple[NamespaceHandle | None, str, bool]: ...  # line 849 — unqualified id ALWAYS routes to local today
    async def get_page(self, concept_id: str, include_body: bool = True) -> dict[str, Any] | None: ...  # line 897
    async def neighbors(self, concept_id: str, rel: str | None = None, direction: str = "both") -> list[dict[str, Any]]: ...  # line 913 — qualifies every row with the SEED's namespace (line 950)
    async def _hydrate_foreign_neighbors(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]: ...  # line 966
    async def _local_incoming_references(self, qualified_seed: str, *, rel: str | None) -> list[dict[str, Any]]: ...  # line 1010 — local→foreign only; no foreign→local incoming lookup exists
    def _assert_local_or_foreign_destination(self, page_id: str) -> str: ...  # line 1131

def _qualify_row(row: dict[str, Any], namespace: str | None) -> dict[str, Any]: ...  # federation.py:551

# packages/ai-parrot/src/parrot/knowledge/wiki/context.py
_ID_KINDS = "file|dir|mod|pkg|doc|func|class|concept|page|sym"  # line 39 — no ledger kinds yet

@dataclass
class NamespaceHandle:  # federation.py:85
    name: str
    store: BaseWikiStore
    config: WikiNamespaceConfig
    origin: Literal["repo", "global"] = "repo"
    storage_dir: Path | None = None
    read_only: bool = True

# packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py
class DevLoopWikiSearch:
    @classmethod
    def from_project(cls, root: Optional[Path] = None) -> Optional["DevLoopWikiSearch"]: ...  # line 38
    async def build_research_context(self, query: str, budget_tokens: int = 4000) -> Optional[str]: ...  # line 91
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `find_shared_root` | `resolve_plane_root` pattern | git common-dir traversal | `packages/ai-parrot/src/parrot/tools/repo/graph_search.py:42` |
| `LedgerStore` | `SQLiteWikiStore` | subclass; `_write` / `_read` (FEAT-557) + `_upsert_pages_conn` / `_insert_edges_conn` | `store.py:774`, `store.py:1223`, `store.py:1267` (+ FEAT-557 `_write`/`_read`) |
| `LedgerService.from_root` | `sqlite_policy_from_config` | config → policy for `ledger.db` | FEAT-557 TASK-3223 (`project.py`) |
| `create_wiki_mcp_server` | `FederatedWikiStore` | namespace registration of `ledger` | `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:148` |
| `close_task.sh` | `events.jsonl` | file append on verified completion | `scripts/sdd/close_task.sh:91-100` |
| `DevLoopWikiSearch` | `find_shared_root` | shared plane resolution | `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:65` |

### Does NOT Exist (Anti-Hallucination)

- ~~`wikitoolkit lint`~~ — does not exist; lint operations (`broken_edges`) have no dedicated CLI command today.
- ~~`find_shared_root` / `is_linked_worktree` in `project.py`~~ — does not exist yet; must be implemented in Module 1.
- ~~`SQLitePragmaPolicy` / `WikiStoreBusy` / `_read` / `_write` / `checkpoint` / `sqlite_settings` / `sqlite_policy_from_config`~~ — not present until the FEAT-557 prerequisite lands; FEAT-566 must consume, not implement, those symbols.
- ~~`SQLiteWikiStore(timeout=…)` / `transaction_immediate()` / ledger-specific SQLite config keys~~ — never existed and must not be introduced; the policy kwarg is FEAT-557's `sqlite_policy`.
- ~~`SQLiteWikiStore._connect()` after FEAT-557~~ — removed by TASK-3219; any FEAT-566 reference to it is a bug.
- ~~"Deferred findings" section in `/sdd-codereview`~~ — does not exist in any command template today.
- ~~Atomic task claim via locking / leasing in `/sdd-start`~~ — does not exist; claiming is currently a direct `jq` file modification.
- ~~`sdd/state/<ID>/state.json` as execution state~~ — does not exist for task running; that directory is exclusively for proposal research state.
- ~~`WikiToolkit.note()`~~ — does not exist; notes are handled via `WikiNoteTool` and CLI `wikitoolkit note`.
- ~~Per-worktree `.parrot/` provisioning in dev-loop~~ — does not exist; dev-loop instances currently find no wiki inside linked worktrees.
- ~~Overlay namespaces / `WikiNamespaceConfig.overlay_prefixes`~~ — do not exist; must be implemented in Module 13.
- ~~Bare `issue:` / `task:` id routing to a namespace~~ — does not exist; `_route` sends every unqualified id to the local plane.
- ~~`wikitoolkit ledger related`~~ — intentionally NOT created; traversal goes through `wiki_related` (Module 13).
- ~~`issue.acknowledged` event / `ledger acknowledge` / `ledger blockers` / `ledger export`~~ — do not exist yet; Modules 3, 6, 9.
- ~~`/sdd-done` step that commits `sdd/ledger/issues.jsonl`~~ — does not exist; Module 12. `/sdd-done` defaults to the PR flow; `--merge` is opt-in (`.claude/commands/sdd-done.md:240, 276`).

---

## 7. Implementation Notes & Constraints

### Worktree Strategy: Mixed

- **External prerequisite**: FEAT-557 is completed and merged into `dev` before this feature starts. Its store-policy task chain is not part of FEAT-566.
- **Phase 1 (Sequential Foundation)**: Module 1 (`project.py` shared root) is developed and verified first. The ledger spike (§4) exercises only ledger-specific guarantees on top of FEAT-557's merged store policy.
- **Phase 2 (Parallel Feature Lanes)**: Once the ledger foundation is in `dev`:
  - **Lane A**: Ledger Core (Modules 3, 4, 5, 6, 7, 13, 8, 9) — event log, index, service, federation overlay routing (before the Module 8 mount), MCP tools, and CLI.
  - **Lane B**: SDD Commands & Twins (Module 12) — updates to `close_task.sh`, Claude commands, Antigravity workflows, and Codex skills.
  - **Lane C**: Hooks & DevLoop Integration (Modules 10, 11) — hook worktree guard and `DevLoopWikiSearch` shared root resolution.

### Patterns to Follow

- **Async-First**: All I/O operations in python must use `async def` and `await`; no synchronous blocking calls on event loops.
- **Strict Separation of Storage**: Main checkout owns `.parrot/`; worktrees are read consumers of structural data, append writers for events, and writers of memory pages only (never structural pages).
- **Compaction is manual and index-only (v1)**: `wikitoolkit ledger compact` is never called by hooks or SDD commands and never rewrites `events.jsonl`. Rewriting the log would race lock-free `O_APPEND` writers (an event appended between the compactor's read and its rename is lost) unless every appender took a lock — which would break the log's lock-free guarantee. Log rotation is deferred until `ledger audit` reports `events.jsonl` > 50 MiB in practice.
- **Pydantic v2**: Strict models for all event schemas and tool parameters with type hints.
- **Logging**: Use `self.logger` (`logging.getLogger(__name__)`), never `print()`.

### Known Risks & Mitigations

- **Risk: SQLite Locking Contention under N Worktree Writers**
  - *Mitigation*: Bounded acquisition is FEAT-557's (Module 2). The ledger-specific part is ordering: `events.jsonl` is written before index application, so a busy `ledger.db` leaves the event durable and `wikitoolkit ledger sync` / `rebuild` reconciles it.
- **Risk: FEAT-557 Lands a Different Shape**
  - *Mitigation*: Module 2 §2.1 names every consumed symbol and its task; before the first FEAT-566 task starts, re-verify those symbols on `dev` and update §2.1 and the Codebase Contract instead of adapting code silently.
- **Risk: Event Log Interleaving**
  - *Mitigation*: Event lines are kept strictly under 4096 bytes (POSIX `PIPE_BUF` atomic write guarantee) and written in a single `write()` system call.
- **Risk: Structural Plane Contamination from Feature Branches**
  - *Mitigation*: Linked worktrees never write to `wiki.db`. Post-commit hook and AST edit listeners check `is_linked_worktree()` and immediately skip execution.
- **Risk: Double Claim over a Stale Index**
  - *Mitigation*: `claim_issue` runs `sync()` inside the same `_write` transaction before checking status, and the reducer makes the first `issue.claimed` in log order win on replay.
- **Risk: Snapshot Commit Conflicts from Concurrent `/sdd-done`**
  - *Mitigation*: the snapshot is committed from a throwaway worktree at `origin/<base_branch>`, never on feature branches or in the shared checkout; the export is deterministic, so a rejected push is resolved by resetting the throwaway worktree and re-exporting.
- **Risk: Federation Regression for Existing Namespaces**
  - *Mitigation*: overlay behaviour is gated on non-empty `overlay_prefixes`; existing federation suites must pass unchanged (Module 13 invariant).
- **Risk: Workflow Drift Across Agent Platforms**
  - *Mitigation*: Update all three command twins (`.claude/commands/`, `.agent/workflows/`, and `.agents/skills/`) together in Module 12 with matching acceptance checks.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiosqlite` | `>=0.17` (existing, `packages/ai-parrot/pyproject.toml:172`) | Used only through FEAT-557's `SQLiteWikiStore`; no direct connection handling in ledger code. |
| `pydantic` | `>=2.0.0` | Already installed; schema validation for events and tool parameters. |
| `click` | `>=8.0.0` | Already installed; CLI framework for `wikitoolkit ledger` commands. |

---

## 8. Open Questions

### Resolved (from Exploration & Proposal)

- [x] **What deployment boundary does v1 support?** — *Resolved*: Shared worktrees on a single host. Multi-machine / distributed backends are explicitly deferred.
- [x] **Is provenance restricted to SDD contexts?** — *Resolved*: No. `derived_from` and `about` are general-purpose additions to `WikiRememberTool` available to all agents.
- [x] **Which workflow variants must be updated?** — *Resolved*: Claude, Codex, and Antigravity workflow twins are updated simultaneously for full feature parity.
- [x] **Should structural plane writes occur from worktrees?** — *Resolved*: No. Worktrees are read-only consumers of the main checkout's structural plane snapshot.
- [x] **Who owns shared SQLite timeout and transaction policy?** — *Resolved*: FEAT-557. The consumption boundary (symbols, busy behaviour per entry point, checkpoint/settings reuse, test reuse) is specified once in Module 2.
- [x] **FEAT-557 redundancy audit (2026-09-14)** — after reading the full FEAT-557 spec and TASK-3216–3226, removed or redirected every FEAT-566 restatement of the SQLite policy: the goal, overview, AC, risks and §8 now point to Module 2; the generic SQLite-writer spike was dropped (FEAT-557's multiprocess contention test owns it) in favour of a ledger-specific log-survives-contention scenario; `ledger.db` uses `sqlite_policy_from_config` (no ledger SQLite keys); `ledger rebuild`/`ingest-sdd` reuse `checkpoint()`; `ledger audit` reuses `sqlite_settings()`; the ledger namespace mount uses FEAT-557's read-only federation policy; the Codebase Contract drops `_connect` (deleted by TASK-3219) and refreshes stale `store.py` line numbers; fixtures no longer use `_connect` as an example symbol.

### Resolved (Owner decisions, 2026-09-14)

- [x] **Federation ID prefixing** — *Resolved: hybrid overlay namespace.* Investigation showed plain namespace mounting cannot answer the feature's core question: `_route` (`federation.py:849`) sends every unqualified id to the local plane, `neighbors` re-homes ledger→code destinations as `ledger::sym:…` (`federation.py:950`), and no lookup exists for ledger edges pointing *into* a local seed. Decision: `issue:`/`task:`/`spec:`/`insight:` ids are queryable without prefix, ledger→code neighbors resolve to the local plane, and local seeds see incoming ledger edges (new Module 13). Status-aware queries go through `LedgerService`; no `wikitoolkit ledger related` traverser. — *Owner: Jesus*
- [x] **Snapshotted issue export frequency** — *Resolved: every `/sdd-done`.* Regenerated on every feature `/sdd-done` in both the PR (default) and `--merge` flows — not only `--merge`, which is opt-in and would miss most features. Committed to `base_branch` from a throwaway worktree only when the deterministic export changed; hotfixes skip it (Module 12). — *Owner: Jesus*
- [x] **Compaction thresholds** — *Resolved: manual, index-only.* `wikitoolkit ledger compact --older-than 30` stays an explicit CLI operation, folds only index pages, and never rewrites `events.jsonl` (rewriting races lock-free `O_APPEND` writers). `ledger audit` warns above 50 MiB; log rotation deferred (§7). — *Owner: Jesus*

### Resolved (Spec consistency pass, 2026-09-14)

- [x] **"Unacknowledged critical findings" was undefined** — added `issue.acknowledged` (human actors only, status unchanged) and `merge_blockers(feature_id)`, scoped to criticals discovered by the feature being merged.
- [x] **Claim over a stale index** — `claim_issue` now syncs inside its single `_write` transaction; first claim in log order wins on replay; spike scenario 4 added.
- [x] **Sync cursor unmodelled** — `ledger_state` table with byte offset + last `event_id`; mismatch forces `rebuild()`.
- [x] **Naming drift** — index file is `ledger.db` everywhere; §2 interfaces now match Modules 4–6 (`from_root`, `ready_work`, `get_context`, `apply_event`, `append(event)`).
- [x] **Worktree writes to `wiki.db`** — structural writes are forbidden from linked worktrees; memory pages from `wiki_remember` / `wiki_note` are allowed.
- [x] **Atomic claim transaction after FEAT-557 took over Module 2** — the removed `transaction_immediate()` is replaced by a ledger-package `LedgerStore(SQLiteWikiStore)` that composes FEAT-557's `_write(operation)` with the existing `_upsert_pages_conn` / `_insert_edges_conn` helpers, so sync + check + append + apply share one `BEGIN IMMEDIATE` without modifying `store.py`. `WikiStoreBusy` propagates (retryable) and is never reported as "already claimed".

### Unresolved

- None.

---

## 9. Design Research Cross-Check

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Dual-layer log + index architecture (architecture) | CONFIRM | Solves locking contention and provides durable auditability. | §2 Overview, §3 Modules 4-5 |
| S2 | Single shared root in main checkout via git common-dir (architecture) | CONFIRM | Satisfies owner constraint without per-worktree DB merge conflicts. | §2 Overview, §3 Module 1 |
| S3 | Mandatory concurrency validation spike before indexing (testing) | CONFIRM | Validates `O_APPEND` atomicity, log-before-index durability and atomic claim under N writers; generic SQLite writer contention is validated by FEAT-557. | §4 Test Specification |
| S4 | Synchronize Claude, Codex, and Antigravity command twins (process) | CONFIRM | Prevents platform divergence across agent execution modes. | §3 Module 12, §5 Criteria |
| S5 | Stand up PostgreSQL/ArangoDB as default ledger backend in v1 (architecture) | REJECT | Over-scoped for local dev-loop; offline SQLite in `.parrot/` is core requirement. | §1 Non-Goals |
| S6 | Allow worktrees to upsert structural plane AST symbols (architecture) | REJECT | Risk of corrupting base branch structural graph with in-progress feature changes. | §1 Non-Goals, §2 Overview |

Summary: **4** confirmed · **2** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-14 | Jesus Lara | Initial draft specification created from FEAT-566 proposal and brainstorm. |
| 0.2 | 2026-09-14 | Codex | Made FEAT-557 a merge-first prerequisite and removed duplicate SQLite hardening from FEAT-566. |
| 0.3 | 2026-09-14 | Jesus Lara | Resolved §8 open questions (overlay federation → new Module 13; snapshot on every `/sdd-done`; manual index-only compaction). Consistency pass: `issue.acknowledged` + `merge_blockers`, in-transaction sync for claims, persisted sync cursor, unified names/timeouts, memory writes from worktrees; `LedgerStore` composes FEAT-557's `_write()` for the atomic claim. |
| 0.4 | 2026-09-14 | Jesus Lara | FEAT-557 redundancy audit against its full spec + TASK-3216–3226: Module 2 rewritten as the single consumption boundary (symbol table, `WikiStoreBusy` per entry point); reuse of `sqlite_policy_from_config`, `checkpoint()`, `sqlite_settings()`, read-only federation policy and `_peer_writer`/`slow` test helpers; dropped duplicate SQLite contention spike; write-through syncs to log tip; Codebase Contract refreshed (no `_connect`, current line numbers). |
