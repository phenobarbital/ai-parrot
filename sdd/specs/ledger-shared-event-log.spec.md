---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, docs]
tags: [ledger, wikitoolkit, git-hooks, multi-machine, sdd-tooling]
---

# Feature Specification: Shared Ledger Event Log (cross-machine sync via git hooks)

**Feature ID**: FEAT-694
**Date**: 2026-10-16
**Author**: Jesus Lara (with Claude)
**Status**: approved
**Target version**: 0.30.0

---

## 1. Motivation & Business Requirements

### Problem Statement

The SDD work ledger is **per machine**. `wikitoolkit ledger list|ready|show|claim|close`
read and write `<main>/.parrot/ledger/ledger.db`, which is materialised only from that
machine's git-ignored `<main>/.parrot/ledger/events.jsonl`. The only artifact that travels
through git is `sdd/ledger/issues.jsonl`, a **one-way export of state** written by
`/sdd-done` step 9.1 (`LedgerService.export_snapshot`, FEAT-566/FEAT-671). Nothing ever
reads it back: `ledger sync` and `ledger rebuild` replay the local event log only, and
FEAT-671 explicitly listed "cross-machine synchronisation of `events.jsonl`" and
"importing carried-forward rows into the local index" as non-goals.

Measured on 2026-10-16 on one of the maintainer's two machines:

| Committed snapshot `sdd/ledger/issues.jsonl` | rows |
|---|---|
| total | 308 |
| unknown to this machine's event log | 142 |
| open majors shown here that the other machine never sees | 23 |

Consequences the maintainer hit:

- `ledger list` / `ledger ready` show different work on each machine; the two `claimed`
  majors on one machine do not exist on the other.
- An issue can only be closed on the machine that opened it. Closing "major" issues on
  machine B, committing and pushing, changes nothing on machine A.
- Explicit commands ("run `ledger export` after closing", "run `ledger import` after
  pulling") are forgotten, so any fix that relies on the user remembering a step will not
  hold.

### Goals

- G1. The **event log** (`events.jsonl`), not just the state snapshot, travels through git
  as an append-only, union-mergeable file: `sdd/ledger/events.jsonl`.
- G2. **Zero explicit commands** in the steady state: managed git hooks export local
  events on `pre-commit` (staging the file into whatever commit the user is making) and
  import committed events on `post-merge`, `post-checkout` and `post-rewrite`
  (`git pull`, `git pull --rebase`, branch switches, worktree creation).
- G3. Import is **append-only**: foreign events are appended to the local log in committed
  order, the sync cursor stays valid, and only the incremental `sync()` runs — never the
  auto-rebuild path, which would wipe the non-event-sourced `spec:`/`task:` graph
  (`cli.py:3634-3640`).
- G4. Concurrent appends on two machines merge **without git conflicts**
  (`.gitattributes` → `merge=union`) and without duplicates (dedup by content-addressed
  `event_id`, `events.py:88`).
- G5. The existing `issues.jsonl` snapshot keeps working unchanged (it becomes derivable
  from the shared log, but `/sdd-done` 9.1 still writes it for humans and `jq`).
- G6. A `claim` made on two machines for the same issue before either pulled is
  **surfaced** (hook output + `ledger audit`), never silently resolved differently per
  machine without a trace.
- G7. The "is the committed file newer than what I imported?" check uses a content
  marker under `.parrot/ledger/`, never `ORIG_HEAD` (the known-broken pattern of
  `issue:7f50ee6aaa74`).
- G8. `wikitoolkit ledger claim` (and the `ledger_claim` MCP path through the same service
  method) imports the committed log **before** reclaiming, so the window for a
  concurrent claim shrinks to "both machines claim between their last pull and now";
  the residual conflict is still reported (G6). The reducer rule stays "first claim in
  local log order wins" (§8 Q1).
- G9. The committed log is **rotated** by `/sdd-done` step 9.1 only: shareable lines older
  than 30 days whose subject is terminal move, deterministically, to
  `sdd/ledger/archive/events-<YYYY-MM>.jsonl`. Import and export treat `events.jsonl` +
  `archive/*.jsonl` as one logical log, so a fresh clone still rebuilds every issue and
  export never re-adds a rotated line (§8 Q3).

### Non-Goals (explicitly out of scope)

- Deterministic cross-machine resolution of **concurrent claims** (e.g. earliest `ts`
  wins, `claimed_at` in the reducer). Decided against for v1 (§8 Q1): the reducer keeps
  "first claim in *local* log order wins" (`index.py:191-200`); mitigation is G8 + G6.
- Rotation of the **local** `.parrot/ledger/events.jsonl`: never rewritten (the index cursor
  is a byte offset into it, `index.py:252-260`); `ledger compact` stays index-only
  (`index.py:529-535`). Only the committed copy rotates (G9).
- Rotation triggered from hooks: `rotate-log` runs exclusively inside `/sdd-done` 9.1's
  throwaway worktree on the base branch (single serialized writer), never from
  `pre-commit`, so feature commits only ever *add* lines.
- Sharing the sdd-coder **seat suspension** records (`insight.recorded` with
  `category == "coder_suspension"`, `coder_suspensions.py:42`): those describe a machine's
  runtime seat state and stay local (§2 filter).
- Any change to the MCP server (`wikitoolkit serve`, `LedgerService.from_dir`), to the
  `TOOL_REGISTRY`, or new MCP tools. Hooks only need the CLI.
- Changing `LedgerLog.append()` locking or the lock-free append design (`log.py:21-81`).
- Reconciling the `issues.jsonl` snapshot from the shared log (FEAT-671's carry-forward
  stays as is; it becomes redundant but harmless).
- Repairing the stale `post-commit` hook content observed on the maintainer's machine
  (old block without the FEAT-566 worktree guard) — `parrot claude install` already
  reports "already installed" for it; out of scope.

---

## 2. Architectural Design

### Overview

Two directions, both automatic, both append-only, both idempotent:

1. **Export (local → repo)** — `wikitoolkit ledger export-log --stage`, run by the managed
   `pre-commit` block. Reads the local `<shared>/.parrot/ledger/events.jsonl`, computes the
   set of `event_id`s already present in `<checkout>/sdd/ledger/events.jsonl` **and**
   `<checkout>/sdd/ledger/archive/*.jsonl`, appends the missing **shareable** local lines
   verbatim (raw bytes, local order) to `events.jsonl`, and `git add`s that file. The committed file is therefore a strict superset over time: lines are never
   reordered or removed, so every diff is a pure addition and `merge=union` applies.
2. **Import (repo → local)** — `wikitoolkit ledger import-log`, run by the managed
   `post-merge`, `post-checkout` and `post-rewrite` blocks. Fast path: if the digest of
   the committed files (archives + current, see below) equals the marker in
   `<shared>/.parrot/ledger/shared_log.marker`, exit 0 with no work. Otherwise append every
   committed line whose `event_id` is not in the local log — archives first, then the
   current file, each in file order — through the same O_APPEND + fsync + 4 KiB path the
   writers use, then run the incremental `LedgerIndex.sync()`; finally compare each
   imported `issue.claimed` against the index and report claim conflicts.

Because `event_id = sha1(kind|subject|actor|ts|payload)[:12]` (`events.py:88-93`) and
`issue_id = sha1(kind|title|discovered_from)[:12]` (`events.py:96-100`) are both
content-addressed, dedup is exact and the same issue opened on two machines folds into one
page (`_apply_issue_opened` dedup, `index.py:164-168`).

Causality is preserved by construction: a machine can only act on a foreign issue after
importing its `issue.opened`, and that line is then in the merge base of any later
3-way merge, so git's union driver can only interleave *independent* lines. Each side's
own lines keep their relative order under `merge=union`.

3. **Claim pre-import (G8)** — `LedgerService.claim()` calls `import_shared_log()` first
   (fast path when the marker matches, so the cost is one SHA-256 of the committed files
   in the common case), then delegates to `LedgerIndex.claim_issue` unchanged. A claim
   that lost to an already-imported foreign claim therefore returns `False` with the
   existing "already claimed" message instead of creating a conflict.
4. **Rotation (G9)** — `wikitoolkit ledger rotate-log --older-than-days 30`, run only by
   `/sdd-done` 9.1 in its throwaway base-branch worktree. It replays the committed file's
   own events per issue subject, and moves a line to `sdd/ledger/archive/events-<YYYY-MM>.jsonl`
   (month of the event's `ts`, appended in file order) when `ts < now − 30 d` **and** the
   subject is terminal: `issue.*` whose final state in the file is `closed`/`superseded`
   and whose closing event is itself older than 30 days; `task.*`, `spec.*`, `insight.*`
   regardless of subject state. Every event of a non-terminal issue stays, whatever its
   age, so a fresh clone materialises every open/claimed issue from the archive + current
   file. Archive files are append-only and carry `merge=union` too. The rotation output is
   deterministic for a given `(input bytes, now)`; `--now` is an explicit option for tests.

The "logical shared log" read by import and export is the ordered list
`sorted(archive/*.jsonl) + [events.jsonl]`; the import marker digests that whole list
(`sha256` over each file's `(relative path, sha256)`), so a rotation also invalidates the
fast path once and then settles.

Hooks never fail a git operation (`|| true`, stdout/stderr to `/dev/null`); the CLI
commands carry the diagnostics for humans running them by hand.

### Component Diagram

```
 machine A                                        git (origin/dev)                                   machine B
 ───────────                                      ────────────────                                   ───────────
 .parrot/ledger/events.jsonl ──pre-commit──▶ sdd/ledger/events.jsonl ──(merge=union)──▶ sdd/ledger/events.jsonl
        ▲      (export-log --stage)                   ▲        ▲                                   │
        │                                             │        │                     post-merge /  │ (import-log)
        │ post-merge / post-checkout / post-rewrite   │        └─ pre-commit from B                 ▼
        └────────────────── (import-log) ◀────────────┘                                 .parrot/ledger/events.jsonl
                                 │                                                                  │
                                 ▼  LedgerIndex.sync() (incremental; cursor stays valid)            ▼
                        .parrot/ledger/ledger.db                                           .parrot/ledger/ledger.db
                        .parrot/ledger/shared_log.marker (sha256 of last imported committed file)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LedgerLog` (`ledger/log.py`) | extends | new `append_line(raw: str) -> int` reusing the O_APPEND + fsync + 4 KiB path; `iter_events` reused for id scans |
| `LedgerIndex.sync()` (`ledger/index.py:263`) | uses | import appends only → cursor `(offset, last_event_id)` stays valid → incremental apply; never hits the auto-rebuild branch (`index.py:321-331`) |
| `LedgerService` (`ledger/service.py`) | extends | `export_shared_log()`, `import_shared_log()`, `audit()` gains a `shared_log` block |
| `wikitoolkit ledger` click group (`cli.py:3222`) | extends | `export-log`, `import-log` commands next to `export` (`cli.py:3593`) |
| `claude_code/assets.py` | extends | `LEDGER_HOOK_BEGIN/END`, `ledger_hook_block(root, hook_name)` |
| `claude_code/installer.py` | extends | `_install_ledger_hooks(root)` on the four hook events, under the existing `git_hook` flag; uninstall strips the block |
| `/sdd-done` §9.1 (`.claude/commands/sdd-done.md:412-470`) | modifies | the throwaway-worktree snapshot commit also exports, **rotates** and stages `sdd/ledger/events.jsonl` + `sdd/ledger/archive/*.jsonl`; `issues.jsonl` keeps being written (Q2) |
| `wikitoolkit ledger claim` (`cli.py:3422-3444`) / `LedgerService.claim` (`service.py:372`) | modifies | `claim()` runs `import_shared_log()` before `LedgerIndex.claim_issue` (G8); CLI text unchanged |
| `.gitattributes` (new, repo root) | creates | `sdd/ledger/events.jsonl merge=union` and `sdd/ledger/archive/*.jsonl merge=union` |
| `sdd/ledger/events.jsonl` (new, committed) | creates | bootstrapped once from the implementing machine's local log |
| `sdd/ledger/archive/` (new, committed) | creates (lazily) | written by the first rotation that has something to move; no `.gitkeep` |
| `scripts/sdd/install_hooks.py` (FEAT-577) | coexists | its `sdd-intake-prune` block and ours chain in the same hook files; neither strips the other |

### Data Models

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py  (new)
from pathlib import Path
from pydantic import BaseModel, Field

SHARED_LOG_REL_PATH: Path = Path("sdd/ledger/events.jsonl")
ARCHIVE_REL_DIR: Path = Path("sdd/ledger/archive")
ARCHIVE_FILENAME_FMT: str = "events-{yyyy_mm}.jsonl"        # e.g. events-2026-09.jsonl
MARKER_FILENAME: str = "shared_log.marker"
ROTATION_DAYS_DEFAULT: int = 30
TERMINAL_ISSUE_STATUSES: frozenset[str] = frozenset({"closed", "superseded"})
LOCAL_ONLY_INSIGHT_CATEGORIES: frozenset[str] = frozenset({"coder_suspension"})  # == CODER_SUSPENSION_CATEGORY


class SharedLogRotateReport(BaseModel):
    current: Path
    moved: int                         # lines moved out of current
    kept: int                          # lines left in current
    archives_touched: list[Path] = Field(default_factory=list)
    cutoff: str                        # ISO-8601 UTC of now − older_than_days


class ClaimConflict(BaseModel):
    """An imported ``issue.claimed`` that lost to a different local claimant."""
    issue_id: str
    local_claimed_by: str
    foreign_claimed_by: str
    foreign_event_id: str


class SharedLogExportReport(BaseModel):
    dest: Path
    created: bool                      # dest did not exist before
    added: int                         # lines appended
    skipped_local_only: int            # filtered by is_shareable()
    total_committed: int               # lines in dest after the export


class SharedLogImportReport(BaseModel):
    files: list[Path]                  # sorted(archive/*.jsonl) + [events.jsonl], existing ones only
    fast_path: bool                    # marker matched; nothing read
    added: int
    skipped_known: int
    skipped_unparseable: int
    synced_events: int                 # LedgerIndex.sync() applied count (0 when busy)
    index_busy: bool                   # WikiStoreBusy on sync — log is durable, index pending
    claim_conflicts: list[ClaimConflict] = Field(default_factory=list)
```

### New Public Interfaces

```python
# CLI (wikitoolkit ledger …)
wikitoolkit ledger export-log [--repo-root PATH] [--stage] [--quiet]
wikitoolkit ledger import-log [--repo-root PATH] [--force] [--quiet]
wikitoolkit ledger rotate-log [--repo-root PATH] [--older-than-days 30] [--now ISO8601] [--stage] [--quiet]
wikitoolkit ledger claim <issue> [--actor …]      # unchanged surface; now imports first (G8)
# audit output gains:
#   Shared log: <events.jsonl> (+K archives) · local-only events: N · committed-unknown events: M · marker: ok|stale|missing

# Service
class LedgerService:
    async def export_shared_log(self, repo_root: Path | None = None) -> SharedLogExportReport: ...
    async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> SharedLogImportReport: ...
    async def rotate_shared_log(self, repo_root: Path | None = None, *, older_than_days: int = 30, now: datetime | None = None) -> SharedLogRotateReport: ...
    async def claim(self, issue_id: str, actor: str) -> bool:   # modified: import_shared_log() first, then LedgerIndex.claim_issue
```

`repo_root` is the checkout whose `sdd/ledger/` is read/written: the CLI passes
`git rev-parse --show-toplevel` of the cwd (so a `pre-commit` running inside a linked
worktree stages *that* worktree's file); the service defaults to `self.shared_root` for
programmatic callers. The logical shared log under a `repo_root` is
`sorted((repo_root / ARCHIVE_REL_DIR).glob("events-*.jsonl")) + [repo_root / SHARED_LOG_REL_PATH]`,
existing files only.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: shared-log core | yes | pure functions over `LedgerLog`; raw-line verbatim copy; dedup by `event_id`; filter `is_shareable`; SHA-256 marker; models above | — |
| M2: service + CLI | yes | method names/signatures fixed in §2; click options fixed; exit codes mirror `ledger sync` (0 ok, 2 on `WikiStoreBusy` for import) | — |
| M3: hook assets + installer | yes | marker strings, hook events tuple, block text and installer action strings fixed below; chaining rules identical to `_install_managed_git_hook` | — |
| M4: gitattributes, bootstrap, `/sdd-done` 9.1, docs | yes | exact file contents and anchors in §6 | — |
| M5: rotation + claim pre-import | yes | rotation predicate, archive naming, determinism contract and `claim()` ordering fixed in §2/§3; `--now` for tests | — |

### Module 1: Shared-log core
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` (new) + `ledger/log.py` (modify)
- **Responsibility**: append-only export/import between a `LedgerLog` and a committed JSONL file; shareability filter; marker fast path; claim-conflict detection input.
- **Depends on**: `LedgerLog`, `LedgerEvent`, `CODER_SUSPENSION_CATEGORY`.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py  (modifies log.py:83 — insert before iter_events)
  class LedgerLog:
      def append_line(self, line: str) -> int:
          """Append one already-serialized event line verbatim (adds the trailing newline if missing).

          Same guarantees as :meth:`append` (log.py:21): single ``os.write`` under
          ``O_APPEND``, ``os.fsync`` before close, ``ValueError`` when the encoded line
          exceeds 4096 bytes. Used by the shared-log import so a foreign line keeps its
          exact bytes (and therefore its ``event_id``) on every machine.
          Returns the start byte offset (informational, see the caveat on :meth:`append`).
          """

  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py  (new)
  from parrot.knowledge.wiki.ledger.coder_suspensions import CODER_SUSPENSION_CATEGORY  # verified: coder_suspensions.py:42
  from parrot.knowledge.wiki.ledger.events import LedgerEvent                          # verified: events.py:103
  from parrot.knowledge.wiki.ledger.log import LedgerLog                              # verified: log.py:10

  SHARED_LOG_REL_PATH: Path
  MARKER_FILENAME: str
  LOCAL_ONLY_INSIGHT_CATEGORIES: frozenset[str]

  def is_shareable(event: LedgerEvent) -> bool:
      """True unless ``event.kind.startswith("insight.")`` and
      ``event.payload.get("category") in LOCAL_ONLY_INSIGHT_CATEGORIES``."""

  def read_raw_events(path: Path) -> list[tuple[str, LedgerEvent]]:
      """Return ``(raw_line_without_newline, event)`` for every parseable line of ``path``
      in file order; ``[]`` when missing. Unparseable lines are logged at WARNING with
      their 1-based line number and skipped (mirrors ``_read_snapshot_rows``, service.py:52)."""

  def shared_log_files(repo_root: Path) -> list[Path]:
      """``sorted((repo_root / ARCHIVE_REL_DIR).glob("events-*.jsonl")) + [repo_root / SHARED_LOG_REL_PATH]``,
      existing files only (may be empty)."""

  def read_shared_event_ids(files: list[Path]) -> set[str]:
      """Union of ``event_id`` over every parseable line of ``files``."""

  def export_events(local: LedgerLog, repo_root: Path) -> SharedLogExportReport:
      """Append to ``repo_root / SHARED_LOG_REL_PATH`` every shareable local event whose
      ``event_id`` is not in :func:`read_shared_event_ids(shared_log_files(repo_root))`
      (archives included — a rotated line is never re-added), verbatim and in local order;
      create the file (and parents) when missing. Never rewrites, reorders or removes a
      line. Blocking — callers wrap in ``asyncio.to_thread``."""

  def import_events(local: LedgerLog, repo_root: Path, marker: Path, *, force: bool = False) -> tuple[SharedLogImportReport, list[LedgerEvent]]:
      """Append to ``local`` every event of :func:`shared_log_files(repo_root)` (archives
      first, then current, each in file order) whose ``event_id`` is unknown locally, via
      :meth:`LedgerLog.append_line`. Fast path: when ``not force`` and ``marker`` holds
      :func:`digest_files` of the current file list, return ``fast_path=True`` without
      reading ``local``. Writes the new digest to ``marker`` (atomic: tmp + ``os.replace``)
      only after all appends succeeded. Returns the report plus the list of imported
      ``issue.claimed`` events for the service's conflict check. Blocking."""

  def digest_files(files: list[Path]) -> str:
      """SHA-256 hex over the concatenation of ``f"{rel_path}\\0{sha256(bytes)}\\n"`` for each
      file in order; ``""`` for an empty list."""

  def rotate_events(repo_root: Path, *, older_than_days: int = ROTATION_DAYS_DEFAULT, now: datetime | None = None) -> SharedLogRotateReport:
      """Move rotatable lines of ``repo_root / SHARED_LOG_REL_PATH`` to
      ``repo_root / ARCHIVE_REL_DIR / ARCHIVE_FILENAME_FMT`` (month of the event's ``ts``),
      appending to the archive in file order and rewriting the current file with the kept
      lines in their original order (atomic: tmp + ``os.replace``). A line is rotatable iff
      ``ts < cutoff`` and (``kind`` not in ``issue.*``, or the subject's final status after
      replaying the current file's own ``issue.*`` events is in ``TERMINAL_ISSUE_STATUSES``
      and the terminal event's ``ts < cutoff``). Unparseable lines are kept in place.
      Deterministic for a given ``(file bytes, now)``; ``now`` defaults to
      ``datetime.now(timezone.utc)``. Blocking."""
  ```

### Module 2: Service + CLI + audit
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: async facade over M1 (sync after import, claim-conflict detection, audit block) and the two click commands the hooks call.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py  (modifies service.py:560 — insert before compact)
  class LedgerService:
      async def export_shared_log(self, repo_root: Path | None = None) -> SharedLogExportReport:
          """``asyncio.to_thread(export_events, self.log, repo_root or self.shared_root)``.
          Never touches the index. Never raises on an unparseable local line (skipped, logged)."""

      async def import_shared_log(self, repo_root: Path | None = None, *, force: bool = False) -> SharedLogImportReport:
          """``asyncio.to_thread(import_events, self.log, repo_root or self.shared_root,
          marker=Path(self.log.path).parent / MARKER_FILENAME, force=force)`` then, when
          ``added > 0``, ``self.index.sync()`` (incremental; ``WikiStoreBusy`` → ``index_busy=True``,
          ``synced_events=0``, exit path identical to ``_sync_best_effort``, service.py:212). Then for
          every imported ``issue.claimed`` whose index state is ``status == "claimed"`` with
          ``claimed_by != payload.claimed_by`` append a ``ClaimConflict``. Fast path returns
          immediately with ``fast_path=True``."""

      async def rotate_shared_log(self, repo_root: Path | None = None, *, older_than_days: int = 30, now: datetime | None = None) -> SharedLogRotateReport:
          """``asyncio.to_thread(rotate_events, repo_root or self.shared_root, …)``. Never touches
          the local log or the index."""

      async def claim(self, issue_id: str, actor: str) -> bool:        # modifies service.py:372-374
          """G8: ``await self.import_shared_log()`` first (its ``WikiStoreBusy`` is already soft —
          ``index_busy=True`` — and any other exception is logged at WARNING and swallowed so a
          broken checkout never blocks a claim), then ``return await self.index.claim_issue(issue_id, actor)``.
          ``LedgerService.from_dir`` instances (no checkout) skip the import when
          ``shared_root / SHARED_LOG_REL_PATH`` does not exist."""

      async def audit(self) -> dict[str, Any]:   # modifies service.py:564-591
          """Existing keys unchanged; adds ``"shared_log": {"path": str, "exists": bool,
          "local_only_events": int, "committed_unknown_events": int, "marker": "ok"|"stale"|"missing"}``."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/cli.py  (modifies cli.py:3613 — insert before @ledger.command("sync"))
  @ledger.command("export-log")
  @click.option("--repo-root", default=None, help="Checkout whose sdd/ledger/ is written; default: git toplevel of cwd")
  @click.option("--stage", is_flag=True, default=False, help="git add the file when it changed")
  @click.option("--quiet", is_flag=True, default=False)
  @remote_cli.remote_aware(proxied=False)   # verified: cli.py:3601 (same decorator as ledger export)
  def ledger_export_log(repo_root: str | None, stage: bool, quiet: bool) -> None:
      """Append this machine's shareable ledger events to the committed sdd/ledger/events.jsonl.
      Prints ``Exported <path> (+N events)`` or ``(unchanged)``; with --stage runs
      ``git -C <repo_root> add -- sdd/ledger/events.jsonl`` only when ``added > 0 or created``.
      Exit 0 always except an OSError on the log (exit 1 via ClickException)."""

  @ledger.command("import-log")
  @click.option("--repo-root", default=None)
  @click.option("--force", is_flag=True, default=False, help="Ignore the marker fast path")
  @click.option("--quiet", is_flag=True, default=False)
  @remote_cli.remote_aware(proxied=False)
  def ledger_import_log(repo_root: str | None, force: bool, quiet: bool) -> None:
      """Append committed events (archives + current) unknown to this machine into
      .parrot/ledger/events.jsonl and sync. Prints ``Imported +N events (M known)`` /
      ``(up to date)``; one ``⚠️ claim conflict …`` line per conflict; exit 2 when the index is
      busy (log durable, next sync catches up — same contract as ``ledger sync``,
      cli.py:3613-3626); exit 0 otherwise, including no-op."""

  @ledger.command("rotate-log")
  @click.option("--repo-root", default=None)
  @click.option("--older-than-days", default=30, show_default=True, type=click.IntRange(min=1))
  @click.option("--now", default=None, help="ISO-8601 UTC override of 'now' (tests / reproducible runs)")
  @click.option("--stage", is_flag=True, default=False, help="git add current + touched archives when anything moved")
  @click.option("--quiet", is_flag=True, default=False)
  @remote_cli.remote_aware(proxied=False)
  def ledger_rotate_log(repo_root: str | None, older_than_days: int, now: str | None, stage: bool, quiet: bool) -> None:
      """Move terminal events older than N days from sdd/ledger/events.jsonl to sdd/ledger/archive/.
      Prints ``Rotated N events into K archive file(s)`` or ``(nothing to rotate)``; exit 0."""
  ```

  `ledger_claim` (`cli.py:3422-3444`) is **not** edited: the pre-import lives in
  `LedgerService.claim` so the MCP `ledger_claim` tool and the dev-loop get it too.
  `_git_toplevel(cwd: Path) -> Path` helper in `cli.py`: `git rev-parse --show-toplevel`,
  falling back to `find_shared_root(cwd)` (`project.py:1519`) when git is unavailable.

### Module 3: Hook assets + installer
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`, `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
- **Responsibility**: a second managed block (`parrot-ledger`) installed on four hook events by `parrot claude install`, removed by `parrot claude uninstall`.
- **Depends on**: Module 2 (command names only — can be implemented in parallel once §2 names are fixed).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py  (modifies assets.py:48 and :208)
  LEDGER_HOOK_BEGIN = "# >>> parrot-ledger >>>"
  LEDGER_HOOK_END = "# <<< parrot-ledger <<<"
  LEDGER_HOOK_EVENTS: tuple[str, ...] = ("pre-commit", "post-merge", "post-checkout", "post-rewrite")

  def ledger_hook_block(root: Path, hook_name: str) -> str:
      """Managed block for one hook event. ``pre-commit`` →
      ``<wt_bin> ledger export-log --stage --quiet >/dev/null 2>&1 || true``; the other three →
      ``<wt_bin> ledger import-log --quiet >/dev/null 2>&1 || true``. NO linked-worktree guard
      (unlike git_hook_block, assets.py:180): the ledger lives in the shared root and the
      pre-commit must stage the file of the checkout being committed. ``wt_bin`` via
      resolve_wikitoolkit_bin (assets.py:88). Raises ValueError for an unknown hook_name."""

  def ledger_hook_new_file(root: Path, hook_name: str) -> str:
      """``"#!/bin/sh\\n" + ledger_hook_block(root, hook_name)``."""

  # packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py  (modifies installer.py:902, :952, :1060, :1203)
  def _install_managed_git_hook(root: Path, hook_name: str, label: str, *,
                                block: str | None = None, new_file: str | None = None,
                                begin_marker: str | None = None) -> str:
      """Backward-compatible: the three new kwargs default to the wiki block/markers
      (assets.git_hook_block / git_hook_new_file / GIT_HOOK_BEGIN) so existing callers and
      tests (test_installer_worktree_guard.py) are unchanged. Same chaining/shebang/chmod rules."""

  def _install_ledger_hooks(root: Path) -> list[str]:
      """One action string per event in LEDGER_HOOK_EVENTS:
      ``"git <event> ledger hook — created|chained into existing hook|already installed|skipped (…)"``."""

  def _uninstall_ledger_hooks(root: Path) -> list[str]:
      """Strip the parrot-ledger block from each of the four hooks via _remove_marker_block
      (installer.py:72); delete the file when only the shebang remains; never touch other blocks."""
  ```
  `install_claude_integration` (`installer.py:1055-1061`): under the same `git_hook` flag,
  append `"; ".join(_install_ledger_hooks(root))` as **one** additional action entry (so the
  existing "action count" assertions move by exactly one; update them in the same task).
  `uninstall_claude_integration` (`installer.py:1190-1203`): call `_uninstall_ledger_hooks`
  before the `if not actions:` fallback.

### Module 4: `.gitattributes`, bootstrap, `/sdd-done` 9.1, docs
- **Path**: `.gitattributes` (new), `sdd/ledger/events.jsonl` (new, generated), `.claude/commands/sdd-done.md`, `docs/wiki/cheatsheet.md`, `docs/sdd/WORKFLOW.md`
- **Responsibility**: make git merge the shared log by union, seed the committed log once, keep the `/sdd-done` snapshot commit carrying both files, document the model.
- **Depends on**: Module 2 (bootstrap runs the real `export-log`), Module 3 (docs name the hooks).
- **Interface Skeleton** (file contents, not code):
  ```gitattributes
  # .gitattributes  (new, repo root)
  # FEAT-694: the shared ledger event log is append-only on every machine; take both sides.
  sdd/ledger/events.jsonl merge=union
  sdd/ledger/archive/*.jsonl merge=union
  ```
  ```bash
  # .claude/commands/sdd-done.md §9.1  (modifies sdd-done.md:446-453)
  EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)            # issues.jsonl keeps being written (Q2)
  LOG_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export-log 2>&1)
  ROTATE_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger rotate-log --older-than-days 30 2>&1)
  if [[ "$EXPORT_OUTPUT" != *"(changed)"* && "$LOG_OUTPUT" != *"(+"* && "$ROTATE_OUTPUT" != *"Rotated"* ]]; then … unchanged … fi
  git -C "$TEMP_WORKTREE" add sdd/ledger/issues.jsonl sdd/ledger/events.jsonl sdd/ledger/archive
  # cleanup/restore lines: `git restore --staged --worktree -- sdd/ledger` (whole directory) in both places
  ```
  Rotation runs **only here**: 9.1 is the single serialized writer on `base_branch`, so
  the line deletions it produces never race a feature branch's tail appends in the same
  hunk.

### Module 5: Rotation + claim pre-import
- **Path**: `ledger/shared_log.py` (`rotate_events`, shared with M1), `ledger/service.py`
  (`rotate_shared_log`, `claim`), `cli.py` (`rotate-log`), `.claude/commands/sdd-done.md` (9.1)
- **Responsibility**: keep the committed log bounded (G9) and shrink the concurrent-claim
  window (G8). Listed as its own module so `/sdd-task` can schedule it after M1/M2 land
  (it edits the same three files — tasks serialize on them).
- **Depends on**: Module 1 (`shared_log_files`, `read_raw_events`), Module 2
  (`import_shared_log`, CLI group).
- **Interface Skeleton**: see `rotate_events` (M1), `rotate_shared_log` / `claim` (M2) and
  `ledger_rotate_log` (M2) above — no further names.
  Bootstrap: the implementing task runs `wikitoolkit ledger export-log` once in the feature
  worktree and commits the resulting `sdd/ledger/events.jsonl` (~1 150 lines / ~0.8 MB on
  the authoring machine) with `git add` (path is not git-ignored; no `-f` needed).

---

## 4. Test Specification

Tests go in the **root** tree `tests/knowledge/wiki/` (the one CI runs; the
`packages/ai-parrot/tests/knowledge/wiki/` tree is separate and not touched here).

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_append_line_verbatim_and_fsync` | M1 | `append_line` writes exact bytes + newline; `iter_events` yields the same `event_id`; >4096 bytes → `ValueError` |
| `test_is_shareable_filters_suspension_only` | M1 | `issue.*`, `task.*`, `insight.recorded{coder_review,coder_feedback}` → True; `coder_suspension` → False |
| `test_export_creates_then_appends_only` | M1 | first export creates dest with all shareable lines in local order; second export → `added == 0`, bytes identical; a new local event → exactly one new trailing line |
| `test_export_never_rewrites_dest` | M1 | pre-existing foreign lines in dest are untouched and keep their position |
| `test_import_appends_unknown_in_src_order` | M1 | local has {a,b}, src has {a,c,d} → local becomes a,b,c,d; `added == 2`, `skipped_known == 1` |
| `test_import_marker_fast_path_and_force` | M1 | second import with same src → `fast_path=True`, no read of local; `force=True` bypasses; marker written only after appends |
| `test_import_skips_unparseable_line` | M1 | one garbage line in src → `skipped_unparseable == 1`, others imported, WARNING with line number |
| `test_import_keeps_cursor_valid` | M2 | after import `LedgerIndex.sync()` applies exactly `added` events and `read_cursor()` points at the last imported line — never `rebuild` (spy on `_rebuild_locked_with_cursor`) |
| `test_import_detects_claim_conflict` | M2 | local claim by `agent:a`, foreign claim by `agent:b` on same issue → one `ClaimConflict`, index still `claimed_by == agent:a` |
| `test_import_index_busy_is_soft` | M2 | `WikiStoreBusy` from sync → `index_busy=True`, log contains the lines, CLI exits 2 |
| `test_audit_reports_shared_log_block` | M2 | `local_only_events`, `committed_unknown_events`, `marker` states |
| `test_cli_export_log_stage_runs_git_add` | M2 | in a `tmp_path` git repo (`git init`): `--stage` leaves the file in the index (`git diff --cached --name-only`); no `--stage` → untracked |
| `test_cli_import_log_outputs_and_exit_codes` | M2 | `(up to date)`, `Imported +N`, conflict line, exit 2 on busy |
| `test_ledger_hooks_installed_on_four_events` | M3 | `_install_ledger_hooks` creates `pre-commit`, `post-merge`, `post-checkout`, `post-rewrite`; idempotent ("already installed"); chains into an unrelated existing hook and into a hook already carrying the `parrot-wiki` / `sdd-intake-prune` blocks without touching them |
| `test_ledger_hook_runs_without_worktree_guard` | M3 | stub `wikitoolkit` (pattern of `test_installer_worktree_guard.py:31`) is invoked both when `.git` is a dir and when it is a file; records the subcommand (`export-log --stage` on pre-commit, `import-log` elsewhere) |
| `test_uninstall_strips_only_ledger_block` | M3 | other blocks byte-identical; file deleted when only the shebang remains |
| `test_install_claude_integration_action_count` | M3 | exactly one more action entry than before under `git_hook=True`; unchanged with `git_hook=False` |
| `test_export_skips_ids_present_in_archive` | M1/M5 | a local event whose line already sits in `archive/events-2026-08.jsonl` is not re-appended to `events.jsonl` |
| `test_import_reads_archives_then_current` | M1/M5 | fresh local log + `archive/events-2026-08.jsonl` (opened) + `events.jsonl` (closed) → local order is open then close; index shows `closed` |
| `test_rotate_moves_only_terminal_and_old` | M5 | with `--now` fixed: closed-45d-ago issue → both its lines move to `events-<month>.jsonl`; open-60d-ago issue → stays entirely; `task.closed` 40d → moves; `issue.closed` 10d → stays; kept lines keep order |
| `test_rotate_is_deterministic_and_idempotent` | M5 | same `(bytes, now)` twice → byte-identical outputs; second run `moved == 0` |
| `test_rotate_keeps_unparseable_lines` | M5 | garbage line stays in current, counted in `kept` |
| `test_marker_invalidated_by_rotation` | M5 | after rotation the import fast path misses once, imports `added == 0`, then hits again |
| `test_claim_imports_first` | M5 | foreign claim committed but not yet imported → `claim()` returns `False`, index shows the foreign claimant, no `ClaimConflict`; with an unreadable checkout the import failure is logged and the claim proceeds |
| `test_cli_rotate_log_stage_adds_archive` | M5 | in a `tmp_path` git repo `--stage` stages `events.jsonl` and every touched archive file |

### Integration Tests
| Test | Description |
|---|---|
| `test_two_machines_converge_via_shared_file` | Two isolated ledgers A and B (`LedgerService.from_dir`, pattern of `test_ledger_export_snapshot.py:36`) and one shared file: A opens+claims, A export → B import → B sees the issue claimed; B closes, B export → A import → `A.list_issues(status="closed")` contains it; a second round trip is a no-op on both (`added == 0`, `fast_path=True`) |
| `test_git_union_merge_has_no_conflict` | Real `git init` repo with the `.gitattributes` line: two branches each append distinct lines to `sdd/ledger/events.jsonl` → `git merge` exits 0, both lines present, no conflict markers, each side's lines keep relative order |
| `test_rebuild_not_triggered_by_import_e2e` | After import + sync, `spec:`/`task:` pages previously written by `SDDGraphIngest` are still present (proves G3) |
| `test_fresh_clone_after_rotation_sees_everything` | Machine A exports, rotation archives the old closed issues, a brand-new machine C imports → C lists the same open/claimed/closed set as A (archives + current), and C's export is a no-op |

### Test Data / Fixtures
```python
@pytest.fixture
def two_ledgers(tmp_path: Path) -> tuple[LedgerService, LedgerService, Path]:
    """A/B services over tmp_path/'a'/.parrot/ledger and tmp_path/'b'/.parrot/ledger plus the shared
    file tmp_path/'repo'/sdd/ledger/events.jsonl (policy: SQLitePragmaPolicy(busy_timeout_ms=200))."""

def _event(kind: str, subject: str, actor: str, **payload) -> LedgerEvent: ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC1. `wikitoolkit ledger export-log` on a fresh checkout creates `sdd/ledger/events.jsonl` containing every shareable local event, verbatim, in local order; running it again reports `(unchanged)` and leaves the file byte-identical.
- [ ] AC2. `wikitoolkit ledger import-log` appends only events whose `event_id` is unknown locally, in committed order, and never rewrites, reorders or truncates `.parrot/ledger/events.jsonl`.
- [ ] AC3. After an import, `LedgerIndex.sync()` applies exactly the imported events incrementally; the auto-rebuild branch (`index.py:321-331`) is never entered and `spec:`/`task:` pages survive (integration test).
- [ ] AC4. Issues opened, claimed or closed on machine B are visible with the same status in `ledger list|ready|show` on machine A after A pulls — with no command typed by the user (hooks only). Proven by the two-ledger integration test plus a manual run on the maintainer's two machines recorded in the Completion Note.
- [ ] AC5. `insight.recorded` events with `category == "coder_suspension"` never appear in `sdd/ledger/events.jsonl`; `coder_review` / `coder_feedback` insights do.
- [ ] AC6. `.gitattributes` declares `sdd/ledger/events.jsonl merge=union`; two branches appending different lines merge with exit 0 and no conflict markers.
- [ ] AC7. `parrot claude install` installs the `parrot-ledger` block on `pre-commit`, `post-merge`, `post-checkout`, `post-rewrite`; re-running reports "already installed" per event; `parrot claude uninstall` removes only that block; the `parrot-wiki` and `sdd-intake-prune` blocks are byte-identical before/after.
- [ ] AC8. The ledger hook block has no linked-worktree guard and runs inside a linked worktree (stub-binary test).
- [ ] AC9. The import fast path is driven by a SHA-256 marker file under `.parrot/ledger/`; `ORIG_HEAD` is not referenced anywhere in the feature.
- [ ] AC10. A concurrent claim on the same issue from two machines produces a `ClaimConflict` in the import report, a `⚠️ claim conflict` line in CLI output and is counted in `ledger audit`; the local claimant stays the winner locally (no silent override).
- [ ] AC11. `/sdd-done` §9.1 commits `sdd/ledger/events.jsonl` together with `issues.jsonl` in the throwaway worktree and restores both on cleanup.
- [ ] AC12. Hooks never fail a git operation: every hook line ends in `|| true` and redirects output; a missing `wikitoolkit` binary leaves `git commit`/`git pull` exit codes unchanged (test with a non-existent `wt_bin`).
- [ ] AC13. `docs/wiki/cheatsheet.md` §5 and `docs/sdd/WORKFLOW.md` describe the shared log, the four hooks, and the two commands; the FEAT-671 non-goal is marked superseded by FEAT-694 in this spec's §1 (the old spec file is not edited).
- [ ] AC14. All new tests pass under `pytest tests/knowledge/wiki/ -q -k "shared_log or ledger_hooks or import_log or export_log or rotate_log"`; `ruff check` clean on touched files; existing `tests/knowledge/wiki/test_installer_worktree_guard.py`, `test_cli_ledger.py`, `test_ledger_service.py` still pass.
- [ ] AC15. `LedgerService.claim()` imports the committed log before `LedgerIndex.claim_issue`; a claim already present in the committed log (not yet imported) makes the local claim return `False` with the existing "already claimed" CLI message; an import failure other than `WikiStoreBusy` is logged and does not block the claim.
- [ ] AC16. `wikitoolkit ledger rotate-log --older-than-days 30` moves exactly the lines matching the §2 predicate into `sdd/ledger/archive/events-<YYYY-MM>.jsonl`, keeps every event of a non-terminal issue regardless of age, keeps order on both sides, is byte-deterministic for a fixed `--now`, and reports `(nothing to rotate)` on a second run.
- [ ] AC17. Export never re-adds a rotated line (dedup covers `archive/*.jsonl`); import reads archives before the current file; a fresh clone materialises the same issue set as a machine that never rotated (integration test).
- [ ] AC18. `/sdd-done` §9.1 runs `export`, `export-log` and `rotate-log` in the throwaway worktree, stages `sdd/ledger/issues.jsonl`, `sdd/ledger/events.jsonl` and `sdd/ledger/archive/`, and restores the whole `sdd/ledger` directory on cleanup; `issues.jsonl` keeps being produced (Q2). No hook ever runs `rotate-log`.

---

## 6. Codebase Contract

> Verified against commit `b5fce0a0d` (anchors) on 2026-10-16; spec committed on top of
> `1b913c607` (FEAT-694 reservation). `/sdd-task` re-runs every `grep -c`.

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.events import LedgerEvent, LedgerEventKind, compute_event_id, compute_issue_id  # verified: ledger/events.py:7,88,96,103
from parrot.knowledge.wiki.ledger.log import LedgerLog                                   # verified: ledger/log.py:10
from parrot.knowledge.wiki.ledger.index import LedgerIndex, _decode_issue_body            # verified: ledger/index.py:86,62 (service.py:29 imports both)
from parrot.knowledge.wiki.ledger.store import LedgerStore                               # verified: ledger/store.py:24
from parrot.knowledge.wiki.ledger.service import LedgerService, normalize_issue_id       # verified: cli.py:127
from parrot.knowledge.wiki.ledger.coder_suspensions import CODER_SUSPENSION_CATEGORY     # verified: ledger/coder_suspensions.py:42
from parrot.knowledge.wiki.store import SQLitePragmaPolicy, WikiStoreBusy, estimate_tokens  # verified: service.py:37
from parrot.knowledge.wiki.project import find_shared_root, load_effective_config, sqlite_policy_from_config  # verified: service.py:32-36
from parrot.knowledge.wiki import remote_cli                                             # verified: cli.py:104
from parrot.knowledge.wiki.claude_code import assets                                     # verified: claude_code/installer.py:33
from parrot.knowledge.wiki.claude_code.installer import _git_hook_path, _install_git_hook, _install_post_merge_hook  # verified: tests/knowledge/wiki/test_installer_worktree_guard.py:18-22
from parrot.knowledge.wiki.cli import ledger, wiki                                       # verified: tests/knowledge/wiki/test_cli_ledger.py:18
from parrot.knowledge.wiki.ledger.sdd_ingest import SDDGraphIngest                      # verified: cli.py:3644 (lazy import inside ledger_rebuild)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/events.py
LedgerEventKind = Literal["issue.opened", "issue.claimed", "issue.acknowledged", "issue.closed", "issue.superseded",
                          "issue.unclaimed", "issue.linked", "task.started", "task.closed", "spec.registered",
                          "insight.recorded", "insight.superseded"]                     # line 7-20
def compute_event_id(kind: str, subject: str, actor: str, ts: str, payload: dict[str, Any]) -> str  # line 88 (sha1[:12])
def compute_issue_id(kind: str, title: str, discovered_from: str) -> str                 # line 96 ("issue:" + sha1[:12])
class LedgerEvent(BaseModel):                                                            # line 103
    event_id: str = Field(default="")   # line 106 — filled by model_post_init (line 113) when empty
    kind: LedgerEventKind; subject: str; actor: str; ts: str (UTC isoformat, line 110); payload: dict[str, Any]

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py
class LedgerLog:                                                                         # line 10
    def __init__(self, path: str) -> None                                                # line 13 — self.path is a str
    def append(self, event: LedgerEvent) -> tuple[str, int]                              # line 21 — O_APPEND|O_WRONLY|O_CREAT (60), 4096-byte cap (56), os.fsync (77)
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]      # line 83 — skips malformed lines with WARNING (116-121)

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:                                                                       # line 86
    def __init__(self, store: "LedgerStore", log: LedgerLog) -> None                     # line 89
    async def apply_event(self, event: LedgerEvent, conn) -> None                        # line 103 — only issue.* kinds reduced; others ignored (122-124)
    async def _apply_issue_claimed(self, event, conn) -> None                            # line 191 — no-op unless status == "open" (195-196): first claim in log order wins
    async def _apply_issue_closed(self, event, conn) -> None                             # line 212 — no status precondition
    async def _write_cursor(conn, line_start: int, event_id: str) -> None                # line 252 (staticmethod)
    async def sync(self, conn=None) -> int                                               # line 263
    async def _apply_from(self, conn, offset: int, last_event_id: str | None)            # line 291 — cursor mismatch ⇒ _rebuild_locked_with_cursor (321-331); appended tail ⇒ incremental (337-345)
    async def rebuild(self) -> int                                                       # line 353 — DELETE FROM pages/edges/ledger_state (375-377)

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/store.py
class LedgerStore(SQLiteWikiStore):                                                      # line 24
    def __init__(self, db_path: str, wiki_name: str = "", *, read_only=False, sqlite_policy=None, persistent_writer=False)  # line 27
    async def ledger_transaction(self, operation: str) -> AsyncIterator[aiosqlite.Connection]  # line 54
    async def read_cursor(self) -> tuple[int, str | None]                                # line 75

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool                     # line 42
def _read_snapshot_rows(dest: Path) -> list[dict[str, Any]]                              # line 52 (WARNING + skip pattern for bad lines)
def _scan_log_for_audit(log: LedgerLog, cursor_offset: int) -> tuple[dict[str,int], int, int, int]  # line 81
def normalize_issue_id(raw: str) -> str                                                  # line 110
class LedgerService:
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None  # line 144
    @classmethod from_root(cls, root: Path | None = None) -> LedgerService               # line 159 — ledger_dir = config.ledger_path(shared_root) (179); log at ledger_dir/"events.jsonl" (184)
    @classmethod from_dir(cls, ledger_dir: Path, *, sqlite_policy=None) -> LedgerService # line 189
    async def _sync_best_effort(self) -> None                                            # line 212 — swallows WikiStoreBusy with a WARNING
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]                      # line 219
    async def open_issue(...) -> str                                                     # line 235 — appends via asyncio.to_thread(self.log.append, event) (264)
    async def claim(self, issue_id: str, actor: str) -> bool                             # line 372-374 — pure delegate to self.index.claim_issue (G8 inserts the import here)
    async def close_issue(self, issue_id, reason, actor, resolved_by=None) -> bool       # line 405
    async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool       # line 515
    async def compact(self, older_than_days: int = 30) -> int                            # line 560
    async def audit(self) -> dict[str, Any]                                              # line 564 — returns keys log_size_bytes, event_counts, total_events, cursor_offset, cursor_lag_events, broken_edges, sqlite (583-591)

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
_run(coro) -> Any                                                                        # line 579
_cli_logger = logging.getLogger("wikitoolkit.cli")                                       # line 132
def ledger() -> None  (click group `wikitoolkit ledger`)                                 # line 3222
@ledger.command("claim")   … def ledger_claim(issue_id: str, actor: str) -> None          # line 3422-3444 — calls service.claim(); exit 1 "already claimed or closed", exit 2 busy; remote-proxied to MCP ledger_claim (3425)
@ledger.command("export")  … def ledger_export(dest: str, no_reconcile: bool) -> None     # line 3593-3610 — prints "Exported <p> (changed|unchanged)"
@ledger.command("sync")    … def ledger_sync() -> None                                   # line 3613-3626 — exit 2 on WikiStoreBusy
@ledger.command("rebuild") … def ledger_rebuild() -> None                                # line 3629-3658 — re-runs SDDGraphIngest after replay (spec/task pages are NOT event-sourced)
@ledger.command("audit")   … prints "Log size: …", "Total events: …", "Event counts by kind:"  # line 3691-3706

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
GIT_HOOK_BEGIN = "# >>> parrot-wiki post-commit >>>"; GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"  # line 47-48
def resolve_wikitoolkit_bin(root: Path) -> str                                           # line 88 (venv → which → bare)
def git_hook_block(root: Path) -> str                                                    # line 180 — carries the `if [ ! -f .git ]` linked-worktree guard (200)
def git_hook_new_file(root: Path) -> str                                                 # line 208

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _remove_marker_block(text: str, begin: str, end: str) -> str                         # line 72
def _git_hook_path(root: Path, hook_name: str = "post-commit") -> Optional[Path]          # line 832 — resolves the COMMON hooks dir for linked worktrees (852-862)
_SH_FAMILY: frozenset[str]                                                               # line 868
def _shebang_is_sh_compatible(first_line: str) -> bool                                   # line 882
def _install_managed_git_hook(root: Path, hook_name: str, label: str) -> str             # line 902 — "created" | "chained into existing hook" | "already installed" | "skipped (…)"
def _install_git_hook(root) -> str; def _install_post_merge_hook(root) -> str            # line 947 / 952
def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True, approve_mcp=True, compaction=False, typesafe_api_key=None, plugin_cli=True, remote=None) -> list[str]  # line 983; hook branch 1055-1061 (ONE folded action entry)
def uninstall_claude_integration(root: Path) -> list[str]                                # line 1075; post-commit block removal 1190-1200; fallback `if not actions:` 1202

# packages/ai-parrot/src/parrot/knowledge/wiki/project.py
def is_linked_worktree(git_dir: Path) -> bool                                            # line 1507
def find_shared_root(start: Path | None = None) -> Path | None                           # line 1519
class WikiProjectConfig: def ledger_path(self, root: Path) -> Path                       # line 738 → <root>/.parrot/ledger

# scripts/sdd/install_hooks.py (FEAT-577 — reference pattern only, NOT modified)
MARKER_BEGIN = "# >>> sdd-intake-prune >>>"; HOOK_EVENTS = ("post-checkout", "post-merge", "post-commit")  # line 18-20
def hooks_dir(repo_root) -> Path (git rev-parse --git-path hooks); def primary_checkout(repo_root) -> Path  # line 24 / 33
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `shared_log.import_events` | `LedgerLog.append_line` (new) → same fd path as `append` | method call | `log.py:60-79` |
| `shared_log.read_raw_events` | `LedgerEvent(**json.loads(line))` | model validation | `log.py:112-115` |
| `LedgerService.import_shared_log` | `LedgerIndex.sync()` | `await self.index.sync()` inside try/except `WikiStoreBusy` | `index.py:263`, `service.py:212-217` |
| `LedgerService.import_shared_log` | `LedgerService._all_issues()` for conflict check | method call | `service.py:219` |
| `ledger_import_log` (CLI) | `LedgerService.from_root()` | classmethod | `service.py:159` |
| `ledger_export_log --stage` | `git -C <toplevel> add -- sdd/ledger/events.jsonl` | `subprocess.run([...], check=True)` | pattern `scripts/sdd/install_hooks.py:26-28` |
| `ledger_hook_block` | `resolve_wikitoolkit_bin(root)` | function call | `assets.py:88` |
| `_install_ledger_hooks` | `_install_managed_git_hook(..., block=, new_file=, begin_marker=)` | kwargs added in M3 | `installer.py:902` |
| `install_claude_integration` | `_install_ledger_hooks(root)` | appended as one action under `git_hook` | `installer.py:1055-1061` |
| `/sdd-done` §9.1 | `wikitoolkit ledger export-log` in `$TEMP_WORKTREE` | bash | `.claude/commands/sdd-done.md:446-453` |

### Does NOT Exist (Anti-Hallucination)
- ~~`wikitoolkit ledger import`~~, ~~`ledger pull`~~, ~~`ledger push`~~ — no import command of any name exists today (`wikitoolkit ledger --help` lists acknowledge, audit, blockers, claim, close, compact, context, export, ingest-sdd, list, open, plan-fix, ready, rebuild, show, sync, unclaim).
- ~~`LedgerService.import_snapshot()`~~ / ~~`LedgerService.import_shared_log()`~~ / ~~`export_shared_log()`~~ — not yet; `export_snapshot` (state rows) is the only export.
- ~~`LedgerLog.append_line()`~~ / ~~`LedgerLog.append_raw()`~~ — only `append(event)` exists.
- ~~`parrot.knowledge.wiki.ledger.shared_log`~~ — module does not exist.
- ~~`.gitattributes`~~ at the repo root — absent (`git check-attr merge sdd/ledger/issues.jsonl` → `unspecified`).
- ~~`sdd/ledger/events.jsonl`~~, ~~`sdd/ledger/archive/`~~ — absent; only `sdd/ledger/issues.jsonl` is committed.
- ~~`wikitoolkit ledger rotate-log`~~ / ~~`LedgerService.rotate_shared_log()`~~ — absent; `ledger compact` (`service.py:560`) is index-only and unrelated.
- ~~`assets.LEDGER_HOOK_BEGIN`~~, ~~`assets.ledger_hook_block`~~, ~~`installer._install_ledger_hooks`~~ — absent.
- ~~`.git/hooks/pre-commit`~~, ~~`post-checkout`~~, ~~`post-rewrite`~~ — not installed by any parrot tool today (only `post-commit`, `post-merge`).
- ~~`LedgerIndex` reducers for `insight.*` / `task.*` / `spec.*`~~ — `apply_event` ignores them (`index.py:122-124`); `coder_*.py` scan the log directly; `spec:`/`task:` pages come from `SDDGraphIngest`, not events.
- ~~`LedgerEvent.machine_id`~~ / ~~origin field~~ — events carry no machine identity; dedup is by `event_id` only.
- ~~`ORIG_HEAD`-based change detection~~ — must not be used (G7).
- ~~MCP tools `ledger_import` / `ledger_export`~~ — none, and none are added (no `TOOL_REGISTRY` regeneration in this feature).
- ~~`LedgerStore` file lock on `events.jsonl`~~ — appends are lock-free by design; `fcntl` is used elsewhere in the wiki package (`repo_cache.py`, `operations.py`, `project.py`) but not by the ledger.

### Edit Sites (Blueprint Anchors)

Verified against: `b5fce0a0d`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py` | MODIFY | `    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:` | `log.py:83` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `    async def compact(self, older_than_days: int = 30) -> int:` | `service.py:560` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `            "broken_edges": broken_edges,` (inside `audit()` return dict) | `service.py:589` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `        return await self.index.claim_issue(issue_id, actor)` (body of `claim`, G8) | `service.py:374` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `@ledger.command("sync")` | `cli.py:3613` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `    click.echo(f"Total events: {audit['total_events']}")` | `cli.py:3704` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `GIT_HOOK_END = "# <<< parrot-wiki post-commit <<<"` | `assets.py:48` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `def git_hook_new_file(root: Path) -> str:` | `assets.py:208` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `def _install_managed_git_hook(root: Path, hook_name: str, label: str) -> str:` | `installer.py:902` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `def _install_post_merge_hook(root: Path) -> str:` | `installer.py:952` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `        merge_action = _install_post_merge_hook(root)` | `installer.py:1060` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | `        actions.append("nothing to remove — integration not installed")` | `installer.py:1203` | 1 |
| `.gitattributes` | CREATE | — | — | — |
| `sdd/ledger/events.jsonl` | CREATE (generated by `ledger export-log`) | — | — | — |
| `sdd/ledger/archive/events-<YYYY-MM>.jsonl` | CREATE (generated lazily by `ledger rotate-log` from `/sdd-done` 9.1; nothing committed by the feature itself unless the bootstrap already has 30-day-old terminal events) | — | — | — |
| `.claude/commands/sdd-done.md` | MODIFY | `    git -C "$TEMP_WORKTREE" add sdd/ledger/issues.jsonl` | `sdd-done.md:452` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `        git -C "$TEMP_WORKTREE" restore --staged --worktree -- sdd/ledger/issues.jsonl >/dev/null 2>&1` — **2 occurrences**: line 438 inside `cleanup_snapshot_worktree() {` and line 461 after `# Rejected push: re-sync the throwaway worktree only, re-export, retry.`; change both | `sdd-done.md:438,461` | 2 |
| `docs/wiki/cheatsheet.md` | MODIFY | `wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> [--no-reconcile] · wikitoolkit ledger compact` | `cheatsheet.md:253` | 1 |
| `docs/sdd/WORKFLOW.md` | MODIFY | `` | `sdd/ledger/issues.jsonl` | Committed snapshot of the work ledger (written by `/sdd-done`) | `` | `WORKFLOW.md:27` | 1 |
| `tests/knowledge/wiki/test_ledger_shared_log.py` | CREATE | — | — | — |
| `tests/knowledge/wiki/test_ledger_shared_log_service.py` | CREATE | — | — | — |
| `tests/knowledge/wiki/test_cli_ledger_shared_log.py` | CREATE | — | — | — |
| `tests/knowledge/wiki/test_installer_ledger_hooks.py` | CREATE | — | — | — |
| `tests/knowledge/wiki/test_ledger_shared_log_integration.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- **Raw-line verbatim copy.** Export and import move the original line bytes, never
  re-serialize through `model_dump_json()`; `event_id` is recomputed only to validate.
  This keeps the same event byte-identical on every machine so `merge=union` dedups
  identical lines that both sides carry.
- **Blocking file I/O off-loop.** M1 functions are synchronous; the service wraps them in
  `asyncio.to_thread` exactly like `export_snapshot` (`service.py:548,558`) and
  `_apply_from` (`index.py:316-318`).
- **Soft index failure.** Import appends to the log first; a `WikiStoreBusy` on `sync()` is
  a soft success (`index_busy=True`, CLI exit 2) — identical contract to `ledger sync`
  (`cli.py:3613-3626`) and to `open_issue` (`service.py:247-249`).
- **Marker written last, atomically** (`tmp` + `os.replace`) so a crash mid-import re-runs
  the import (idempotent by `event_id` dedup) instead of skipping it.
- **Hook blocks**: same marker-delimited, shebang-checked, `chmod +x` chaining as
  `_install_managed_git_hook`; generalise with kwargs, do not duplicate the function.
- **`git add` in `pre-commit`** is the standard "format-and-stage" hook pattern; only the
  one path is added and only when the file changed.
- **No `[ ! -f .git ]` guard** in the ledger block — the guard exists to protect the
  base-branch `wiki.db`; the ledger is shared and the pre-commit must see the worktree's
  own `sdd/ledger/events.jsonl`.
- Tests mirror existing files: `test_installer_worktree_guard.py` (stub binary + marker
  file), `test_ledger_export_snapshot.py` (`from_dir` fixture), `test_cli_ledger.py`
  (`CliRunner`, `patch("…cli.LedgerService.from_root")`).

### Known Risks / Gotchas
- **Auto-rebuild wipes the SDD graph.** `_apply_from` falls back to a full rebuild when
  the cursor's line changed (`index.py:321-331`), and that rebuild does NOT re-run
  `SDDGraphIngest` (only the CLI `ledger rebuild` does, `cli.py:3644-3650`). Import must
  therefore be append-only, never a rewrite/sort of the local log. AC3's test exists to
  pin this.
- **Concurrent claims diverge per machine.** "First claim in local log order wins"; after
  a round trip each machine may show a different `claimed_by`. v1 surfaces this (AC10).
  Resolution rule deferred to §8 Q1.
- **Concurrent local append during import.** `LedgerLog.append` is lock-free; an import
  appending lines while another process appends is safe (each line is one atomic
  O_APPEND write under 4 KiB) — order between the two is arbitrary but both land.
- **`pre-commit` on commits made by tooling.** `reserve_ids.py` builds commits with
  plumbing (no hooks), `/sdd-done` 9.1 commits in a throwaway worktree (hooks fire —
  which is why 9.1 also stages the file explicitly, so the behaviour is the same with or
  without the hook installed). `git commit --no-verify` skips the export; the next commit
  catches up.
- **PR noise.** Every commit may carry appended ledger lines; reviewers see pure
  additions in `sdd/ledger/events.jsonl`. Accepted (same class of noise as the existing
  `issues.jsonl` snapshot commits).
- **Growth.** ~0.8 MB today, ≤ 4 KiB/line. The committed file is bounded by the 30-day
  rotation (G9); the local log is not rotated (cursor stability) and `ledger audit` keeps
  warning above 50 MiB (`service.py:572-573`).
- **Rotation deletes lines from a file otherwise treated as append-only.** Safe because:
  (1) it runs only in `/sdd-done` 9.1 on the base branch, so the deletion commit is
  serialized with every other base-branch writer; (2) a feature branch's appends live in
  the tail hunk, the rotation's deletions in earlier hunks — a normal 3-way merge keeps
  both; (3) if two rotations with different `now` ever race, `merge=union` keeps the
  lines either side kept (no duplicates, nothing lost — the next rotation finishes the
  job); (4) import dedups by `event_id`, so a line that resurfaces is a no-op.
- **Rotation must never move an event of a non-terminal issue**, or a fresh clone would
  miss an open issue's `issue.opened` and silently drop every later event on it
  (`_apply_issue_claimed/closed` are no-ops on an unknown subject, `index.py:194-196,215-217`).
  The predicate replays the current file's own `issue.*` events per subject; AC16 pins it.
- **`claim()` now does I/O on the checkout.** A broken or missing `sdd/ledger/` must not
  block claims: the pre-import swallows everything except `WikiStoreBusy` (already soft)
  with a WARNING. `from_dir` services (MCP `serve`) skip it when the file is absent.
- **Stale local hooks.** Hooks are per-clone; a machine that never re-runs
  `parrot claude install` keeps working in the old per-machine mode (nothing breaks, it
  just does not sync). The cheatsheet tells users to re-run the installer once.
- **`post-checkout` fires on file checkouts too** (`git checkout -- path`, flag `0`); the
  marker fast path makes that a sub-millisecond no-op.
- **Union merge ordering is "somewhat arbitrary"** per git docs for the conflicting hunk
  only; each side's own lines keep relative order, which is all causality needs (§2).
- **Two managed-hook mechanisms** already exist (`parrot claude install` and
  `scripts/sdd/install_hooks.py`). This feature extends the former because the commands
  are `wikitoolkit` commands; it must chain cleanly after the FEAT-577 block in the same
  file (AC7).
- **Bootstrap commit size.** The first `sdd/ledger/events.jsonl` is ~0.8 MB; commit it
  alone in its own commit inside the feature branch so later diffs stay readable.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none new; `git >= 2.x` for `merge=union` (host has 2.43.0); `pydantic` v2 and `click` already present |

---

## 8. Open Questions

- [x] Share the **event log** rather than importing the state snapshot? — *Resolved in
  conversation (2026-10-16)*: yes; snapshot import is lossy and keeps "only the opener can
  close", which is the exact pain point.
- [x] Explicit commands vs automatic? — *Resolved in conversation*: automatic via git hooks;
  "al usuario se le olvidan" los comandos explícitos.
- [x] Conflict handling in git? — *Resolved in conversation*: `.gitattributes merge=union` on
  the append-only file + dedup by `event_id`.
- [x] Change detection? — *Resolved in conversation*: content marker under `.parrot/ledger/`,
  not `ORIG_HEAD` (issue:7f50ee6aaa74).
- [x] Import strategy: rewrite local log in committed order vs append-only? — *Resolved by
  spec author*: append-only, because a rewrite invalidates the cursor and the auto-rebuild
  silently drops the non-event-sourced `spec:`/`task:` pages (`cli.py:3634-3640`).
- [x] Which `insight.recorded` categories travel? — *Resolved by spec author, flagged for
  review*: `coder_review` (331 events) and `coder_feedback` (91) are shared;
  `coder_suspension` (26) stays local because it encodes a machine's seat runtime state.
  Overturn by editing `LOCAL_ONLY_INSIGHT_CATEGORIES` before `/sdd-task`.
- [x] Q1. Deterministic cross-machine claim resolution (earliest `ts` wins, `claimed_at`
  in the reducer)? — *Resolved by Jesus, 2026-10-16*: **no reducer change**. Keep "first
  claim in local log order wins"; `ledger claim` imports the committed log first (G8,
  AC15) and residual conflicts are reported (G6, AC10). The `ts`-ordered rule was
  rejected because it needs per-subject replay reordering to keep `unclaim` semantics
  correct — revisit only if a conflict is ever observed in practice.
- [x] Q2. Should `/sdd-done` keep writing `issues.jsonl`? — *Resolved by Jesus,
  2026-10-16*: **yes**, it keeps being written (G5, AC18); it stays the human/`jq` view and
  FEAT-671's carry-forward stays untouched.
- [x] Q3. Rotation of the committed log? — *Resolved by Jesus, 2026-10-16*: **yes, 30 days**
  — `ledger rotate-log --older-than-days 30` from `/sdd-done` 9.1 into
  `sdd/ledger/archive/events-<YYYY-MM>.jsonl` (G9, M5, AC16–AC18). The local log is not
  rotated.

---

## Worktree Strategy

- **Isolation**: one feature worktree for FEAT-694 (`feat-FEAT-694-ledger-shared-event-log`,
  from `origin/dev`); the `sdd-coder` engine gives each task its own sub-worktree inside it.
- **Module dependency graph** (evidence in §3):
  - M2 → M1: `service.py` imports `export_events` / `import_events` / `digest_files` from
    `shared_log.py`; `cli.py` calls the M2 service methods.
  - M3 → M2 (names only): the hook block text embeds `ledger export-log --stage --quiet`
    and `ledger import-log --quiet`; M3 can be implemented concurrently with M2 once the
    §2 command names are frozen (they are).
  - M5 → M1 + M2: `rotate_events` builds on `shared_log_files` / `read_raw_events`;
    `claim()` calls `import_shared_log()`.
  - M4 → M2 + M3 + M5: the bootstrap runs the real `export-log`; `/sdd-done` 9.1 calls
    `export-log` and `rotate-log`; docs name the hooks.
- **Shared files** (their tasks serialize): `ledger/shared_log.py` (M1, M5),
  `ledger/service.py` (M2, M5), `cli.py` (M2, M5), `.claude/commands/sdd-done.md` (M4, M5).
- **Exclusive resources**: the M4 bootstrap task reads the **live** `<main>/.parrot/ledger/events.jsonl`
  of the implementing machine and commits a ~0.8 MB file — `parallel: false`, and it must
  run last, after every code task, so the generated file reflects the final filter.
- **Cross-feature dependencies**: none to merge first. `scripts/sdd/install_hooks.py`
  (FEAT-577) is not modified, only coexisted with (AC7).

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc**. Model: — · Status: skipped (no accepted exploration document: this spec was
> written directly from a diagnosed incident and a conversation, with no
> brainstorm/proposal in `sdd/proposals/`) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-16 | Jesus Lara / Claude | Initial draft from the per-machine ledger diagnosis (142/308 snapshot rows unknown locally) |
| 0.2 | 2026-10-16 | Jesus Lara / Claude | Q1–Q3 resolved: claim pre-import (G8, M5, AC15), 30-day rotation of the committed log into `sdd/ledger/archive/` (G9, M5, AC16–18), `issues.jsonl` kept; archives folded into export/import/marker; Worktree Strategy added; **approved** |
