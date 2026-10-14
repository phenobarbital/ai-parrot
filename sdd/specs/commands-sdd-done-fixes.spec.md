---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling]
tags: [ledger, sdd-done, snapshot, sdd-fix]
---

# Feature Specification: Reconciling Ledger Snapshot Export

**Feature ID**: FEAT-671
**Date**: 2026-10-14
**Author**: Jesus Lara (via `/sdd-fix issue:62038221413a`)
**Status**: approved
**Target version**: next

> Ledger fix lane. Source issue: `issue:62038221413a` (group `fixgroup:17fe5de32cd8`,
> `major` / `bug`, lane `sdd`). Supersedes `issue:1e13dd5b188b`.

---

## 1. Motivation & Business Requirements

### Problem Statement

`LedgerService.export_snapshot()` (`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py:424`)
rebuilds `sdd/ledger/issues.jsonl` **only** from the issues this checkout's local ledger
(`.parrot/ledger/events.jsonl` → SQLite index) has ever seen, and writes the result over
`dest` unconditionally (`_write_snapshot_if_changed` reads the existing file solely to
short-circuit a byte-identical rewrite).

The event log is machine-local and never git-synced; only the derived snapshot is
committed. Therefore any machine whose log is behind — every machine except the one that
opened a given issue — silently **drops other people's issues** when it exports. `/sdd-done`
step 9.1 (`.claude/commands/sdd-done.md:412-464`, twin `.agent/workflows/sdd-done.md:306`)
runs exactly this export from a throwaway worktree at `origin/<base_branch>` and pushes the
result to `base_branch` on every feature `/sdd-done`.

Evidence (2026-10-14):

- On this machine the committed snapshot has **279** rows, the local export yields **102**:
  a `/sdd-done` run here would delete **184** issues (many `open`, several `major`/`critical`).
- `a029275b9 sdd: ledger — restore 118 issues lost to snapshot overwrites` had to walk all
  249 historical versions of the snapshot to recover 118 issues (56 open, 8 critical) that
  earlier `/sdd-done` runs had dropped, including 26 lost by `ccbfef606` (FEAT-586).
- The ledger has **no delete command** and no `issue.deleted` event, so a row disappearing
  from the snapshot is never intentional.

A flat row-level merge by `issue_id` against the committed file is **not** a correct fix:
`issues.jsonl` is a derived *state* snapshot, not raw events, so for an `issue_id` present
on both sides there is no principled way to pick a winner from the snapshot alone (it could
resurrect a locally closed issue or keep a stale `claimed`).

### Goals

- `export_snapshot()` reconciles against the snapshot already at `dest`: rows for issues the
  local ledger has **never seen** are carried forward unchanged; rows for issues the local
  ledger **knows** are regenerated from local state (local is authoritative — it includes
  every `claim`/`close` this machine applied); only a locally closed-and-compacted issue
  disappears.
- The export stays deterministic: same local state + same `dest` content ⇒ byte-identical
  output, second run returns `changed=False`.
- A deliberate full rebuild from the local view remains possible, but only by explicit
  opt-in (`reconcile=False` / `wikitoolkit ledger export --no-reconcile`).
- `/sdd-done` step 9.1 keeps working unchanged (same `(changed)` / `(unchanged)` contract);
  its prose documents the new invariant.

### Non-Goals (explicitly out of scope)

- Cross-machine synchronisation of `events.jsonl` (there is no shared event transport).
- Importing carried-forward rows *into* the local index (they stay snapshot-only; the owning
  machine remains the single writer for their state).
- Any change to compaction, claim/close semantics, the snapshot schema, or step 9.1's
  worktree/push/retry mechanics.
- Repairing historical snapshots (already done by `a029275b9`).

---

## 2. Architectural Design

### Overview

Add a reconciliation pre-pass to `export_snapshot()`: before building `new_content`, read
the rows already in `dest`, keep the ones whose `issue_id` is **absent from
`_all_issues()`**, and union them with the locally derived rows prior to the deterministic
sort. Because `LedgerIndex.compact()` only flags `compacted: True` and never deletes an issue
page (`index.py:532-579`), "absent from `_all_issues()`" is exactly "this ledger has never
recorded an event for it" — a locally compacted issue is still *known*, is excluded by the
existing status filter, and is **not** carried forward, so it disappears from the snapshot
exactly when its owning machine exports.

In `/sdd-done` step 9.1 the export runs with `cwd` = throwaway worktree at
`origin/<base_branch>`, so `dest` *is* the committed snapshot: reconciling against `dest`
needs no git plumbing.

### Component Diagram

```
LedgerService.export_snapshot(dest, reconcile=True)
   │
   ├─ _sync_best_effort()  → _all_issues()            (local, authoritative)
   │        └─ known = {issue_id}
   ├─ _read_snapshot_rows(dest)   [reconcile only]     (committed snapshot rows)
   │        └─ carried = rows whose issue_id ∉ known
   ├─ rows = local rows (status filter unchanged) ∪ carried → sort by issue_id
   └─ _write_snapshot_if_changed(dest, content) → bool  (unchanged)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `LedgerService.export_snapshot` (`service.py:424`) | modifies | new keyword `reconcile: bool = True`, carry-forward pre-pass |
| `_write_snapshot_if_changed` (`service.py:41`) | uses | unchanged |
| `LedgerIndex.compact` (`index.py:532`) | relies on | compaction flags, never deletes → "unknown" is well-defined |
| CLI `ledger export` (`cli.py:3420`) | modifies | new `--no-reconcile` flag; output format unchanged |
| `/sdd-done` §9.1 (`.claude/commands/sdd-done.md:412`, `.agent/workflows/sdd-done.md:306`) | docs | prose only — script unchanged |
| `docs/wiki/cheatsheet.md:253` | docs | mention `--no-reconcile` |

### Data Models

No new models. Snapshot row shape is unchanged (`_issue_dict`, `service.py:80`): the 12
keys `issue_id, title, status, kind, severity, acknowledged, discovered_from, about,
claimed_by, closed_by, closed_reason, resolved_by`, keys sorted, one JSON object per line.
Carried-forward rows are re-serialised through the same `json.dumps(row, sort_keys=True)`
so formatting stays canonical.

### New Public Interfaces

```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool: ...
```

```
wikitoolkit ledger export [--dest sdd/ledger/issues.jsonl] [--no-reconcile]
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Reconciling export | yes | signatures below; helper + keyword; logging contract fixed | — |
| M2: CLI flag | yes | one click option, `reconcile=not no_reconcile` | — |
| M3: Docs | yes | exact paragraphs to replace are anchored in §6 | — |
| M4: Tests | yes | test names + fixtures fixed in §4 | — |

### Module 1: Reconciling export
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
- **Responsibility**: carry forward snapshot rows for issues unknown to the local ledger; keep
  local state authoritative for known issues; keep determinism and the `bool` return.
- **Depends on**: existing `_all_issues`, `_issue_dict`, `_write_snapshot_if_changed`.
- **Interface Skeleton** *(signatures + docstrings only — bodies belong to task blueprints, FEAT-545)*:
  ```python
  # service.py — new module-level helper, placed directly after _write_snapshot_if_changed (line 48)
  def _read_snapshot_rows(dest: Path) -> list[dict[str, Any]]:
      """Blocking half of the reconciliation pre-pass — run via ``asyncio.to_thread``.

      Returns the JSON rows already in ``dest`` (``[]`` when the file is missing).
      A line that is not a JSON object carrying a string ``issue_id`` is logged at
      WARNING with its 1-based line number and skipped — it is not a valid issue row and
      cannot be reconciled.
      """

  # service.py — modifies LedgerService.export_snapshot (line 424)
  async def export_snapshot(self, dest: Path, *, reconcile: bool = True) -> bool:
      """Write ``sdd/ledger/issues.jsonl`` deterministically, reconciling against ``dest``.

      Local state is authoritative for every issue this ledger has recorded (the
      existing status filter applies). With ``reconcile=True`` (default) every row already
      in ``dest`` whose ``issue_id`` is unknown to this ledger is carried forward
      unchanged, so an export from a machine whose event log is behind never drops
      another machine's issues; the number of carried rows is logged at INFO when > 0.
      ``reconcile=False`` rebuilds the snapshot from the local view only (destructive —
      explicit opt-in). Returns ``True`` if the written content differs from disk.
      """
  ```
- **Decided details**: `known = {issue_id for issue_id, _ in issues}`; `carried = [row for
  row in existing if row["issue_id"] not in known]`; `rows = local_rows + carried` then the
  existing `rows.sort(key=lambda row: row["issue_id"])`. Read `dest` **before** writing (the
  write happens in `_write_snapshot_if_changed`). No change to the local status filter.

### Module 2: CLI flag
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
- **Responsibility**: expose the opt-out.
- **Depends on**: Module 1.
- **Interface Skeleton**:
  ```python
  # cli.py — modifies ledger_export (line 3420-3431)
  @ledger.command("export")
  @click.option("--dest", default="sdd/ledger/issues.jsonl", help="Export destination.")
  @click.option(
      "--no-reconcile", is_flag=True, default=False,
      help="Rebuild from this machine's ledger only; drops issues it has never seen (destructive).",
  )
  @remote_cli.remote_aware(proxied=False)
  def ledger_export(dest: str, no_reconcile: bool) -> None:
      """Export the ledger snapshot."""
      # service.export_snapshot(dest_path, reconcile=not no_reconcile)
      # echo format unchanged: "Exported <dest> (changed)" | "(unchanged)"
  ```

### Module 3: Docs
- **Paths**: `.claude/commands/sdd-done.md` (§9.1 prose, lines 414-417),
  `.agent/workflows/sdd-done.md` (same paragraph, lines 308-311), `docs/wiki/cheatsheet.md:253`.
- **Responsibility**: state the invariant where operators read it. Replace the 9.1 intro
  paragraph in both twins with the same text, which must say: the export **reconciles**
  against the committed snapshot — rows for issues this checkout's ledger has never seen are
  carried forward, local state wins for known issues, so a run from a machine whose event log
  is behind never drops issues (FEAT-671); `--no-reconcile` is the explicit, destructive
  opt-out and is never used by `/sdd-done`. Both twins must end up with identical paragraphs.
  The bash block in 9.1 is **not** modified. Cheatsheet: append `[--no-reconcile]` to the
  `ledger export` mention.
- **Depends on**: Module 1, Module 2.
- **Codex twin**: `.agents/skills/sdd-done/SKILL.md` does not contain §9.1 — leave it alone.

### Module 4: Tests
- **Path**: `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` (new)
- **Responsibility**: lock the reconciliation contract (see §4).
- **Depends on**: Modules 1, 2.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_export_carries_forward_rows_unknown_to_local_ledger` | M1 | `dest` pre-seeded with two foreign rows (one `open`, one `closed`, canonical shape); local has one open issue → output has 3 rows, sorted by `issue_id`, foreign rows byte-identical to the seed; returns `True` |
| `test_export_local_state_wins_for_known_issue` | M1 | `dest` holds the local issue's id with `status: open`; local closed it → exported row is `closed` with `closed_reason`; no duplicate `issue_id` |
| `test_export_drops_locally_compacted_issue` | M1 | local issue closed, then `await svc.compact(older_than_days=0)`; `dest` still lists it as `closed` → row absent from output (compaction is local evidence) |
| `test_export_no_reconcile_rebuilds_from_local_only` | M1 | same seed as the first test, `reconcile=False` → only the local row remains |
| `test_export_deterministic_and_idempotent` | M1 | second `export_snapshot(dest)` with no state change returns `False` and leaves the bytes untouched (FEAT-566 §4 `test_export_snapshot_deterministic`, finally written) |
| `test_export_missing_dest_creates_file` | M1 | no `dest` → parents created, local rows only, returns `True` |
| `test_export_skips_malformed_snapshot_lines` | M1 | `dest` contains a non-JSON line and an object without `issue_id` between two valid foreign rows → both valid rows carried, both bad lines skipped, a WARNING naming the line numbers is in `caplog` |
| `test_cli_export_no_reconcile_flag` | M2 | `CliRunner().invoke(wiki, ["ledger", "export", "--dest", str(dest), "--no-reconcile"])` with `LedgerService.from_root` and `remote_or_none` monkeypatched → foreign row dropped, output ends with `(changed)`; without the flag the row is kept |

### Integration Tests
| Test | Description |
|---|---|
| — | none; the `/sdd-done` script is unchanged and is exercised manually (§5) |

### Test Data / Fixtures
```python
# Same isolated-ledger fixture as tests/knowledge/wiki/test_ledger_list_issues.py:16-24
@pytest.fixture
def service(tmp_path: Path) -> LedgerService:
    ledger_dir = tmp_path / ".parrot" / "ledger"
    ledger_dir.mkdir(parents=True)
    store = LedgerStore(ledger_dir / "ledger.db", wiki_name="ledger",
                        sqlite_policy=SQLitePragmaPolicy(busy_timeout_s=1.0))
    log = LedgerLog(str(ledger_dir / "events.jsonl"))
    return LedgerService(LedgerIndex(store, log), store, log, tmp_path)

def _foreign_row(issue_id: str, status: str = "open") -> dict[str, Any]:
    """A canonical 12-key snapshot row for an issue this ledger never recorded."""

# CLI test: monkeypatch.setattr("parrot.knowledge.wiki.remote_cli.remote_or_none",
#           lambda path_=None: (None, None, None))
#           monkeypatch.setattr(LedgerService, "from_root", classmethod(lambda cls, root=None: svc))
```
pytest runs in `asyncio_mode = auto` (`packages/ai-parrot/pyproject.toml:1043`) — bare
`async def` tests, no marker.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py -q` passes (8 tests).
- [ ] `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/test_ledger_from_dir.py packages/ai-parrot/tests/knowledge/wiki/test_ledger_list_issues.py packages/ai-parrot/tests/knowledge/wiki/test_cli_remote.py -q` still passes.
- [ ] `ruff check` clean on every touched file.
- [ ] Manual check on the developer machine: copy the committed snapshot to a scratch path, run `wikitoolkit ledger export --dest <copy>`; the row count is ≥ the committed count (279 on 2026-10-14) and every committed `issue_id` is still present (zero drops). With `--no-reconcile` the count falls back to the local view (102 on 2026-10-14).
- [ ] `/sdd-done` step 9.1 bash block is byte-identical before/after; only its prose changed, identically in both twins.
- [ ] `wikitoolkit ledger export` output still contains the literal `(changed)` / `(unchanged)` tokens.
- [ ] No breaking change to `export_snapshot(dest)` positional callers (new keyword is keyword-only with default `True`).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.service import LedgerService          # verified: tests/knowledge/wiki/test_ledger_from_dir.py:3
from parrot.knowledge.wiki.ledger.index import LedgerIndex, _decode_issue_body  # verified: ledger/service.py:28
from parrot.knowledge.wiki.ledger.log import LedgerLog                  # verified: ledger/service.py:29
from parrot.knowledge.wiki.ledger.store import LedgerStore              # verified: ledger/service.py:30
from parrot.knowledge.wiki.store import SQLitePragmaPolicy              # verified: ledger/service.py:36
from parrot.knowledge.wiki.cli import wiki                              # verified: tests/knowledge/wiki/test_cli.py:56 (runner.invoke(wiki, ...))
from click.testing import CliRunner                                     # verified: tests/knowledge/wiki/test_cli.py:18
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py
def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool:            # line 41
def _issue_dict(issue_id: str, state: dict[str, Any]) -> dict[str, Any]:         # line 80 (12 keys)
class LedgerService:
    def __init__(self, index: LedgerIndex, store: LedgerStore, log: LedgerLog, shared_root: Path) -> None  # line 101
    @classmethod
    def from_root(cls, root: Path | None = None) -> "LedgerService"               # line 116
    @classmethod
    def from_dir(cls, ledger_dir: Path, *, sqlite_policy: SQLitePragmaPolicy | None = None) -> "LedgerService"  # line 146
    async def _sync_best_effort(self) -> None                                      # line 169
    async def _all_issues(self) -> list[tuple[str, dict[str, Any]]]                # line 176 — every issue page, incl. closed + compacted
    async def open_issue(self, title, body, kind="bug", severity="minor", discovered_from="", about=None, actor="agent:sdd") -> str  # line 192
    async def claim(self, issue_id: str, actor: str) -> bool                       # line 281
    async def close_issue(self, issue_id: str, reason: str, actor: str, resolved_by: str | None = None) -> bool  # line 314
    async def export_snapshot(self, dest: Path) -> bool                            # line 424 — status filter at line 445
    async def compact(self, older_than_days: int = 30) -> int                      # line 452

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/index.py
class LedgerIndex:
    async def compact(self, older_than_days: int = 30) -> int                      # line 532 — sets "compacted": True (line 574); never deletes a page

# packages/ai-parrot/src/parrot/knowledge/wiki/cli.py
@ledger.command("export")                                                           # line 3420
@click.option("--dest", default="sdd/ledger/issues.jsonl", help="Export destination.")
@remote_cli.remote_aware(proxied=False)
def ledger_export(dest: str) -> None                                               # line 3423 — echoes "Exported {dest} (changed|unchanged)"

# packages/ai-parrot/src/parrot/knowledge/wiki/remote_cli.py
def remote_aware(*, proxied: bool, tool: str | None = None)                        # line 97 — wrapper calls remote_or_none(kwargs.get("path_")) (line 113)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_read_snapshot_rows` | `export_snapshot` | `await asyncio.to_thread(_read_snapshot_rows, dest)` | `service.py:450` (same pattern as the write) |
| `export_snapshot(reconcile=)` | `ledger_export` CLI | `service.export_snapshot(dest_path, reconcile=not no_reconcile)` | `cli.py:3427` |
| `/sdd-done` §9.1 | `wikitoolkit ledger export` | unchanged `EXPORT_OUTPUT=$(cd "$TEMP_WORKTREE" && wikitoolkit ledger export 2>&1)` | `.claude/commands/sdd-done.md:440` |

### Does NOT Exist (Anti-Hallucination)
- ~~`LedgerService.reconcile()`~~ / ~~`LedgerService.merge_snapshot()`~~ — do not exist; the pre-pass lives inside `export_snapshot`.
- ~~`wikitoolkit ledger delete`~~ / ~~`issue.deleted` event~~ — the ledger cannot delete an issue.
- ~~`wikitoolkit ledger merge`~~ — no such subcommand.
- ~~`export_snapshot(dest, merge=True)`~~ — the keyword is `reconcile`, keyword-only.
- ~~`test_export_snapshot_deterministic`~~ — listed in FEAT-566 §4 but never written; this spec writes it under `test_export_deterministic_and_idempotent`.
- ~~`.claude/skills/sdd-done/SKILL.md`~~ — does not exist; the only twins are `.claude/commands/sdd-done.md` and `.agent/workflows/sdd-done.md`.

### Edit Sites (Blueprint Anchors)

Verified against: `b92037579`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `def _write_snapshot_if_changed(dest: Path, new_content: str) -> bool:` | `service.py:41` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py` | MODIFY | `    async def export_snapshot(self, dest: Path) -> bool:` | `service.py:424` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` | MODIFY | `def ledger_export(dest: str) -> None:` | `cli.py:3423` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `For feature flows (not hotfixes), regenerate \`sdd/ledger/issues.jsonl\` from a` | `sdd-done.md:414` | 1 |
| `.agent/workflows/sdd-done.md` | MODIFY | `For feature flows (not hotfixes), regenerate \`sdd/ledger/issues.jsonl\` from a` | `sdd-done.md:308` | 1 |
| `docs/wiki/cheatsheet.md` | MODIFY | `wikitoolkit ledger audit · wikitoolkit ledger export --dest <dir> · wikitoolkit ledger compact` | `cheatsheet.md:253` | 1 |
| `packages/ai-parrot/tests/knowledge/wiki/test_ledger_export_snapshot.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Blocking file I/O goes through `asyncio.to_thread` exactly like `_write_snapshot_if_changed`.
- Logging via the module `logger` (`service.py:38`); no `print`.
- Keep `rows.sort(key=lambda row: row["issue_id"])` and `json.dumps(row, sort_keys=True)` —
  they are the determinism contract of FEAT-566 §3 Module 6.
- Google-style docstrings, strict type hints, 120 columns.

### Known Risks / Gotchas
- **Compaction test timing**: `compact(older_than_days=0)` folds pages whose `updated_at <
  now`; `updated_at` is an isoformat with microseconds set at close time, so a 0-day cutoff
  folds it deterministically.
- **`_all_issues()` reads the SQLite index**, so the pre-pass must run after
  `_sync_best_effort()` (already first in the method). A busy writer lock leaves the index
  stale — same behaviour as today; reconciliation only makes a stale index *safer*
  (stale ⇒ more rows look unknown ⇒ carried forward unchanged, never dropped).
- **Carried rows are never re-validated** against the local status filter: a foreign
  `closed` row stays until its owning machine compacts and exports. This is intended.
- **Do not touch the 9.1 bash block** — `/sdd-done` greps the literal `(changed)`.
- Tests inside a worktree must run with `PYTHONPATH=packages/ai-parrot/src` (shared `.venv`
  is editable-installed against the main checkout).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| — | — | none added |

---

## 8. Open Questions

- [x] Should an export that would *remove* rows be refused instead? — *Resolved: no.* With
  reconciliation the only removals are backed by local evidence (compaction); refusing would
  block the legitimate case. The destructive path exists only behind `--no-reconcile`. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Status: **skipped** (ledger fix lane — the design is fully determined by
> `issue:62038221413a`, its predecessor `issue:1e13dd5b188b`, and the restore commit
> `a029275b9`; no exploration doc exists to cross-check).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| — | — | — | — | — |

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-10-14 | Jesus Lara | Initial spec from `/sdd-fix issue:62038221413a` |
