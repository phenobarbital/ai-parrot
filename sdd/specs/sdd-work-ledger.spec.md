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
**Status**: draft
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
- Harden SQLite access across both `wiki.db` and `ledger.db` (`busy_timeout`, `BEGIN IMMEDIATE`, read-before-write in `_migrate()`) proven by a validation spike.
- Support atomic issue claim (`--claim`) enforced inside `BEGIN IMMEDIATE` transactions against the ledger index.
- Extend `wiki_remember` and memory tools with first-class, general-purpose provenance fields (`derived_from`, `about`).
- Integrate seamlessly into SDD workflows across all three platform twins (Claude, Codex, Antigravity):
  - Mandatory *Deferred findings* table in `/sdd-codereview` backed by `ledger_open`.
  - Emission of `task.started` in `/sdd-start` and `task.closed` in `scripts/sdd/close_task.sh`.
  - Automatic ingestion of `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` into the graph.
  - Exposure of ready tasks AND open ledger issues in `/sdd-next`, with promotion via `/sdd-task --from-issue <id>`.
  - Scoped context injection (`ledger_context`) in `/sdd-start` priming the worker with relevant open issues and insights intersecting the task's file/symbol scope.
  - Safe merge landing in `/sdd-done`: gate `--merge` on open critical findings and export `sdd/ledger/issues.jsonl` snapshot on merge.
- Guard the structural plane: worktrees read the shared base-branch structural plane; hooks and sync edits skip structural writes when executed in linked worktrees.

### Non-Goals (explicitly out of scope)

- Multi-machine ledger synchronization, distributed Consensus, or hosted tracker services (v1 is single-host, concurrent local worktrees).
- Migrating the primary wiki retrieval plane to PostgreSQL or ArangoDB (the ledger index is SQLite-first; alternative backends remain possible via `BaseWikiStore`).
- Per-worktree structural plane overlays (linked worktrees consume the shared base-branch structural plane snapshot).
- Modifying provider client wrappers (`AbstractClient`) or dev-loop agent execution graphs outside the wiki/search context.

---

## 2. Architectural Design

### Overview

The solution adopts **Option B (Shared root + separate ledger plane)**:
1. **Shared Root Resolution**: Centralize worktree root resolution into `parrot.knowledge.wiki.project:find_shared_root()`, which walks Git's common directory (`commondir` pointer or `git rev-parse --git-common-dir`) to locate the main checkout, respecting an optional `PARROT_SHARED_ROOT` environment override.
2. **Dual-Layer Ledger Plane**:
   - **Log Layer (`events.jsonl`)**: Atomic, append-only JSON Lines event stream located at `<main>/.parrot/ledger/events.jsonl`. Writing an event never takes a database lock and cannot fail due to index contention. Each event carries an immutable SHA-1 hash identifier `sha1(kind|subject|actor|ts|payload)[:12]`.
   - **Index Layer (`ledger.db`)**: An instance of `SQLiteWikiStore` situated at `<main>/.parrot/ledger/wiki.db` that reduces events into `WikiPageRecord`s and directed edges with provenance. Write operations are write-through: append event to log, then apply to index under `BEGIN IMMEDIATE`. If index write is contended, the log write remains durable, and subsequent `sync` or `rebuild` reconciles the index.
3. **Federation Read Integration**: The ledger plane is mounted as a namespace (`ledger`) in `FederatedWikiStore`, allowing `wiki_query`, `wiki_page`, and `wiki_related` to traverse across code symbols, documentation, and ledger items transparently.
4. **Structural Plane Policy**: Structural pages (`sym:`, `file:`) represent the base branch checkout. Post-commit hooks and AST edit listeners check `is_linked_worktree(root)` and no-op if true.

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
│  │  - BEGIN IMMEDIATE          │                            │                     │
│  │  - busy_timeout=5000ms      │                            │                     │
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
| `parrot.knowledge.wiki.store.SQLiteWikiStore` | modifies | Add `timeout` (`busy_timeout`), `BEGIN IMMEDIATE` for mutations, and read-first check in `_migrate()`. |
| `parrot.knowledge.wiki.tools` | extends | Register MCP tools (`ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, `ledger_context`); add `derived_from` and `about` to `WikiRememberTool`. |
| `parrot.knowledge.wiki.mcp_server` | extends | Mount `ledger` namespace automatically in `create_wiki_mcp_server`. |
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
    def append(self, kind: LedgerEventKind, subject: str, actor: str, payload: dict[str, Any]) -> LedgerEvent:
        """Append one event with atomic O_APPEND write. Returns the recorded LedgerEvent."""
        ...

    def iter_events(self, start_id: str | None = None) -> Iterator[LedgerEvent]:
        """Yield events sequentially; skips corrupted/partial lines with a logged warning."""
        ...


# parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:
    """Materialized SQLite view and query engine over events.jsonl."""

    def __init__(self, store: SQLiteWikiStore, log: LedgerLog) -> None: ...
    async def apply(self, event: LedgerEvent) -> bool:
        """Reduce one event into pages and edges under BEGIN IMMEDIATE."""
        ...

    async def sync(self) -> int:
        """Catch up index with any unindexed events in the log. Returns count applied."""
        ...

    async def rebuild(self) -> int:
        """Truncate index tables and replay all events from the log. Returns count applied."""
        ...

    async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:
        """Atomically claim an open issue. Returns True if claimed, False if already claimed/closed."""
        ...


# parrot/knowledge/wiki/ledger/service.py
class LedgerService:
    """High-level service coordinating log, index, and SDD integration."""

    @classmethod
    def from_project(cls, root: Path | None = None) -> "LedgerService": ...
    async def open_issue(
        self,
        title: str,
        body: str,
        kind: IssueKind,
        severity: IssueSeverity,
        discovered_from: str,
        about: list[str] | None = None,
        actor: str = "agent:sdd",
    ) -> str: ...
    async def ready_issues(self, kind: IssueKind | None = None) -> list[dict[str, Any]]: ...
    async def claim(self, issue_id: str, actor: str) -> bool: ...
    async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool: ...
    async def get_context_for_scope(self, scope_files: list[str], limit_tokens: int = 3000) -> str: ...
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
| M2: SQLite Concurrency Hardening | no | Requires concurrency spike validation before freezing transaction pragmas and migration flow. | Needs empirical validation under N-writer load. |
| M3: Ledger Events Schema | yes | Pydantic v2 event models, deterministic SHA-1 IDs, fixed string literals. | — |
| M4: Append-Only Event Log | yes | Standard POSIX `os.open` with `O_APPEND \| O_WRONLY \| O_CREAT`, single `write()`, < 4 KiB validator. | — |
| M5: Ledger Materialized Index | no | Atomic claim logic, `BEGIN IMMEDIATE`, event reducer state machine, and error recovery. | Core state machine logic. |
| M6: Ledger Service Facade | yes | Facade wrapping Log + Index + `SQLiteWikiStore` queries. | — |
| M7: SDD Artifacts Ingestion | yes | Markdown and JSON parsing of `sdd/specs/` and `sdd/tasks/index/` into `WikiPageRecord`s. | — |
| M8: Wiki MCP Tools Extension | yes | Standard `AbstractTool` implementations wrapping `LedgerService` and extended `WikiRememberTool`. | — |
| M9: Ledger CLI Group | yes | Standard Click command group `@wiki.group(name="ledger")` wrapping `LedgerService`. | — |
| M10: Claude Code Hook Worktree Guard | yes | Check `is_linked_worktree(root)`; skip `upsert --changed` in worktrees; install `post-merge`. | — |
| M11: DevLoop Wiki Context Injection | yes | Extend `DevLoopWikiSearch` to fetch `ledger_context` and append to research context. | — |
| M12: SDD Command Integration | no | Modifications across Claude, Codex, and Antigravity workflow scripts, gates, and `close_task.sh`. | Cross-platform workflow sync. |

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

### Module 2: SQLite Concurrency Hardening
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/store.py`
- **Responsibility**: Harden `SQLiteWikiStore` for concurrent access from multiple processes across worktrees: configure `busy_timeout`, apply `BEGIN IMMEDIATE` on write paths, and eliminate unneeded write locks during connection migration.
- **Depends on**: `store.py:SQLiteWikiStore`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/store.py (modifies store.py:819-905, 1041-1064)
  class SQLiteWikiStore(BaseWikiStore):
      def __init__(
          self,
          db_path: str | Path,
          wiki_name: str = "",
          *,
          read_only: bool = False,
          timeout: float = 10.0,  # 10s default busy_timeout
      ) -> None:
          """Store initialized with configurable busy timeout."""

      @asynccontextmanager
      async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
          """Opens aiosqlite connection with timeout=self._timeout; skips schema write if present."""

      async def _migrate(self, conn: aiosqlite.Connection) -> None:
          """Read schema_version before executing UPDATE; avoid acquiring write lock on read paths."""

      @asynccontextmanager
      async def transaction_immediate(self) -> AsyncIterator[aiosqlite.Connection]:
          """Context manager issuing 'BEGIN IMMEDIATE' for atomic compare-and-swap operations."""
  ```

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

      def append(self, event: LedgerEvent) -> str:
          """Serialize to UTF-8 JSON line; verify len <= max_event_bytes; write via os.open(O_APPEND).
          Returns event.event_id. Raises ValueError if event exceeds max_event_bytes.
          """

      def iter_events(self, after_event_id: str | None = None) -> Iterator[LedgerEvent]:
          """Yield all valid events in log, starting after after_event_id if specified."""
  ```

---

### Module 5: Materialized Ledger Index
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py`
- **Responsibility**: Project events from `events.jsonl` into `ledger.db` as `WikiPageRecord`s and relations, and handle atomic claim transactions.
- **Depends on**: Module 2 (`store.py`), Module 3 (`events.py`), Module 4 (`log.py`)
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py (new)
  class LedgerIndex:
      """Materialized query view over the event log backed by SQLiteWikiStore."""
      def __init__(self, store: SQLiteWikiStore, log: LedgerLog) -> None:
          """Initialize index with underlying wiki store and event log."""

      async def apply_event(self, event: LedgerEvent, conn: aiosqlite.Connection) -> None:
          """Apply event reduction rules inside an existing connection/transaction."""

      async def sync(self) -> int:
          """Replay events from last indexed event up to current log tip. Returns applied count."""

      async def rebuild(self) -> int:
          """Wipe pages/edges in ledger store and replay entire event log from start."""

      async def claim_issue(self, issue_id: str, claimed_by: str) -> bool:
          """Execute atomic claim: check status=='open' under transaction_immediate(),
          append issue.claimed event to log, and update index.
          """
  ```

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
          """Initialize service pointing at find_shared_root(root)."""

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

      async def ready_work(self) -> list[dict[str, Any]]:
          """Return list of unblocked, unclaimed issues and tasks."""

      async def close_issue(self, issue_id: str, reason: str, actor: str) -> bool:
          """Close an issue with reason."""

      async def get_context(self, file_paths: list[str], max_tokens: int = 3000) -> str:
          """Retrieve graph-scoped open issues and insights touching the given files."""
  ```

---

### Module 7: SDD Artifacts Ingestion
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py`
- **Responsibility**: Scan `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` in the main checkout and project them into the wiki/ledger graph.
- **Depends on**: Module 5 (`index.py`), `SQLiteWikiStore`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py (new)
  class SDDGraphIngest:
      """Parses SDD specs and task indexes into graph pages and edges."""
      def __init__(self, store: SQLiteWikiStore, shared_root: Path) -> None: ...
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

---

### Module 9: Ledger CLI Interface
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: Provide `@wiki.group(name="ledger")` with subcommands `open`, `ready`, `claim`, `close`, `context`, `sync`, `rebuild`, `ingest-sdd`, `compact`, and `audit`.
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
  - `/sdd-done`: refuse `--merge` when unacknowledged critical findings exist; export `sdd/ledger/issues.jsonl` snapshot on merge.
- **Depends on**: Module 6 (`service.py`), Module 9 (`cli.py`)

---

## 4. Test Specification

### Concurrency & Atomicity Spike (Mandatory Gate)

Before finalizing implementation of Modules 5 and 6, execute a deterministic test script verifying:
1. **Concurrent Log Appends**: Run 8 parallel processes each appending 100 events to `events.jsonl` using `O_APPEND`. Verify that:
   - Exactly 800 valid, non-interleaved JSON lines are present.
   - Zero lines are corrupted or interleaved.
2. **Concurrent SQLite Writers**: Run 8 parallel async tasks against `ledger.db` with `busy_timeout = 10000ms` and `BEGIN IMMEDIATE`. Verify zero `database is locked` unhandled exceptions.
3. **Atomic Claim**: Have 5 concurrent agents attempt to claim the same open issue simultaneously. Verify that exactly ONE succeeds and 4 receive `False` (already claimed).

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
            "title": "Uncaught OperationalError in SQLite store",
            "body": "Connection timeout is missing in _connect.",
            "kind": "bug",
            "severity": "major",
            "discovered_from": "task:TASK-3210",
            "about": ["sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#SQLiteWikiStore._connect"],
        },
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `find_shared_root()` resolves the main checkout root from both plain checkouts and `.claude/worktrees/*` without relying on CWD assumptions.
- [ ] `events.jsonl` appends are atomic and validated under concurrency tests with zero line interleaving.
- [ ] `SQLiteWikiStore` uses `busy_timeout` (default 10s), `BEGIN IMMEDIATE` for mutation transactions, and does not acquire write locks during read-only `_migrate()`.
- [ ] `ledger_open`, `ledger_ready`, `ledger_claim`, `ledger_close`, and `ledger_context` are available as MCP tools and CLI commands.
- [ ] `wiki_remember` supports `derived_from` and `about` parameters, generating corresponding graph edges.
- [ ] `wikitoolkit ledger ingest-sdd` indexes all `sdd/specs/*.spec.md` and `sdd/tasks/index/*.json` into `spec:` and `task:` nodes with `implements`, `blocks`, and `touches` edges.
- [ ] `scripts/sdd/close_task.sh` appends a `task.closed` event to `events.jsonl`.
- [ ] `/sdd-codereview` includes a mandatory *Deferred findings* table filing unfixed findings via `ledger_open`.
- [ ] `/sdd-start` injects scoped ledger context before code implementation and records `task.started`.
- [ ] `/sdd-next` displays both pending tasks and open ledger issues.
- [ ] `/sdd-done --merge` blocks on unacknowledged critical findings and exports `sdd/ledger/issues.jsonl`.
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
)  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/store.py:49, 299, 711, 1795

from parrot.knowledge.wiki.federation import (
    FederatedWikiStore,
    open_namespace_store,
    resolve_namespaces,
)  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/federation.py:337, 599

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

class SQLiteWikiStore(BaseWikiStore):
    def __init__(self, db_path: str | Path, wiki_name: str = "", *, read_only: bool = False) -> None: ...  # line 759
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]: ...  # line 820
    async def _migrate(self, conn: aiosqlite.Connection) -> None: ...  # line 1041
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> None: ...  # line 1134
    async def add_edges(self, edges: list[tuple[str, str, str] | tuple[str, str, str, str]]) -> None: ...  # line 1156
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[WikiSearchResult]: ...  # line 1582
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]: ...  # line 1672
    async def broken_edges(self) -> list[tuple[str, str, str]]: ...  # line 1773

# packages/ai-parrot/src/parrot/knowledge/wiki/federation.py
class FederatedWikiStore(BaseWikiStore):
    def __init__(self, local: BaseWikiStore, local_name: str = "local", handles: list[NamespaceHandle] | None = None, skipped=None, *, qualify_local: bool = False, origin_local=None): ...  # line 599

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
| `LedgerIndex` | `SQLiteWikiStore` | store instantiation & page/edge upserts | `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:759` |
| `create_wiki_mcp_server` | `FederatedWikiStore` | namespace registration of `ledger` | `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py:148` |
| `close_task.sh` | `events.jsonl` | file append on verified completion | `scripts/sdd/close_task.sh:91-100` |
| `DevLoopWikiSearch` | `find_shared_root` | shared plane resolution | `packages/ai-parrot/src/parrot/flows/dev_loop/wiki_search.py:65` |

### Does NOT Exist (Anti-Hallucination)

- ~~`wikitoolkit lint`~~ — does not exist; lint operations (`broken_edges`) have no dedicated CLI command today.
- ~~`find_shared_root` / `is_linked_worktree` in `project.py`~~ — does not exist yet; must be implemented in Module 1.
- ~~`PRAGMA busy_timeout` / `BEGIN IMMEDIATE` in `store.py`~~ — not present in existing codebase; must be added in Module 2.
- ~~"Deferred findings" section in `/sdd-codereview`~~ — does not exist in any command template today.
- ~~Atomic task claim via locking / leasing in `/sdd-start`~~ — does not exist; claiming is currently a direct `jq` file modification.
- ~~`sdd/state/<ID>/state.json` as execution state~~ — does not exist for task running; that directory is exclusively for proposal research state.
- ~~`WikiToolkit.note()`~~ — does not exist; notes are handled via `WikiNoteTool` and CLI `wikitoolkit note`.
- ~~Per-worktree `.parrot/` provisioning in dev-loop~~ — does not exist; dev-loop instances currently find no wiki inside linked worktrees.

---

## 7. Implementation Notes & Constraints

### Worktree Strategy: Mixed

- **Phase 1 (Sequential Foundation)**: Module 1 (`project.py` shared root) and Module 2 (`store.py` SQLite hardening) are developed and verified first in a dedicated worktree. This includes executing the mandatory concurrency spike.
- **Phase 2 (Parallel Feature Lanes)**: Once the foundation is in `dev`:
  - **Lane A**: Ledger Core (Modules 3, 4, 5, 6, 7, 8, 9) — event log, index, service, MCP tools, and CLI.
  - **Lane B**: SDD Commands & Twins (Module 12) — updates to `close_task.sh`, Claude commands, Antigravity workflows, and Codex skills.
  - **Lane C**: Hooks & DevLoop Integration (Modules 10, 11) — hook worktree guard and `DevLoopWikiSearch` shared root resolution.

### Patterns to Follow

- **Async-First**: All I/O operations in python must use `async def` and `await`; no synchronous blocking calls on event loops.
- **Strict Separation of Storage**: Main checkout owns `.parrot/`; worktrees remain purely read consumers for structural data and append writers for events.
- **Pydantic v2**: Strict models for all event schemas and tool parameters with type hints.
- **Logging**: Use `self.logger` (`logging.getLogger(__name__)`), never `print()`.

### Known Risks & Mitigations

- **Risk: SQLite Locking Contention under N Worktree Writers**
  - *Mitigation*: The event log `events.jsonl` is written with `O_APPEND` without touching SQLite. If `ledger.db` write encounters a lock, the event is already safely persisted on disk. The index is disposable and rebuildable via `wikitoolkit ledger sync` / `rebuild`.
- **Risk: Event Log Interleaving**
  - *Mitigation*: Event lines are kept strictly under 4096 bytes (POSIX `PIPE_BUF` atomic write guarantee) and written in a single `write()` system call.
- **Risk: Structural Plane Contamination from Feature Branches**
  - *Mitigation*: Linked worktrees never write to `wiki.db`. Post-commit hook and AST edit listeners check `is_linked_worktree()` and immediately skip execution.
- **Risk: Workflow Drift Across Agent Platforms**
  - *Mitigation*: Update all three command twins (`.claude/commands/`, `.agent/workflows/`, and `.agents/skills/`) together in Module 12 with matching acceptance checks.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `aiosqlite` | `>=0.19.0` | Already installed; asynchronous SQLite driver for ledger index. |
| `pydantic` | `>=2.0.0` | Already installed; schema validation for events and tool parameters. |
| `click` | `>=8.0.0` | Already installed; CLI framework for `wikitoolkit ledger` commands. |

---

## 8. Open Questions

### Resolved (from Exploration & Proposal)

- [x] **What deployment boundary does v1 support?** — *Resolved*: Shared worktrees on a single host. Multi-machine / distributed backends are explicitly deferred.
- [x] **Is provenance restricted to SDD contexts?** — *Resolved*: No. `derived_from` and `about` are general-purpose additions to `WikiRememberTool` available to all agents.
- [x] **Which workflow variants must be updated?** — *Resolved*: Claude, Codex, and Antigravity workflow twins are updated simultaneously for full feature parity.
- [x] **Should structural plane writes occur from worktrees?** — *Resolved*: No. Worktrees are read-only consumers of the main checkout's structural plane snapshot.

### Unresolved (Design decisions during implementation)

- [ ] **Federation ID prefixing**: `FederatedWikiStore` qualifies foreign IDs as `ns::<id>`. Should `issue:` and `task:` IDs be directly queryable in `wiki_related` without prefix, or should `wikitoolkit ledger related` provide a specialized traverser? — *Owner: Jesus*
- [ ] **Snapshotted issue export frequency**: Should `sdd/ledger/issues.jsonl` be regenerated and committed on every `/sdd-done --merge`, or only when preparing a formal release? — *Owner: Jesus*
- [ ] **Compaction Thresholds**: Should compaction fold closed issues older than 30 days automatically during `/sdd-done`, or remain an explicit manual CLI operation (`wikitoolkit ledger compact`)? — *Owner: Jesus*

---

## 9. Design Research Cross-Check

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Dual-layer log + index architecture (architecture) | CONFIRM | Solves locking contention and provides durable auditability. | §2 Overview, §3 Modules 4-5 |
| S2 | Single shared root in main checkout via git common-dir (architecture) | CONFIRM | Satisfies owner constraint without per-worktree DB merge conflicts. | §2 Overview, §3 Module 1 |
| S3 | Mandatory concurrency validation spike before indexing (testing) | CONFIRM | Empirically validates SQLite behavior and `O_APPEND` atomicity under N writers. | §4 Test Specification |
| S4 | Synchronize Claude, Codex, and Antigravity command twins (process) | CONFIRM | Prevents platform divergence across agent execution modes. | §3 Module 12, §5 Criteria |
| S5 | Stand up PostgreSQL/ArangoDB as default ledger backend in v1 (architecture) | REJECT | Over-scoped for local dev-loop; offline SQLite in `.parrot/` is core requirement. | §1 Non-Goals |
| S6 | Allow worktrees to upsert structural plane AST symbols (architecture) | REJECT | Risk of corrupting base branch structural graph with in-progress feature changes. | §1 Non-Goals, §2 Overview |

Summary: **4** confirmed · **2** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-14 | Jesus Lara | Initial draft specification created from FEAT-566 proposal and brainstorm. |
