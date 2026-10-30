---
id: FC-016
query_id: Q022
type: read
intent: "Read the shared append-only log to confirm the concurrency guarantees claimed for multi-worktree writers."
executed_at: 2026-10-30T23:09:00Z
duration_ms: 300
parent_id: null
depth: 0
---

# FC-016 — The event log is an O_APPEND file with a 4 KiB per-event cap; the WAL/BEGIN-IMMEDIATE hardening belongs to the index, not the log

## Summary

`LedgerLog.append` opens the log with `O_APPEND | O_WRONLY | O_CREAT` and writes one
`os.write()` **"capped at 4 KiB"** for atomicity against concurrent appenders;
`append_line` does the same for raw lines. The source's description — "Hardened for
concurrent worktree writers (WAL, `busy_timeout`, `BEGIN IMMEDIATE`)" — conflates two
layers: those pragmas belong to `ledger.db` via `SQLiteWikiStore._write()` (FC-003), while
the log's guarantee is POSIX atomic append under a size cap.

`shared_log.py` is a cross-machine sync layer, not a writer path: `is_shareable(event)`
filters which events may be published, `export_events` / `import_events` move them between
the local log and the committed `sdd/ledger/`, `digest_files` hashes the set,
`live_claims` resolves claim state, and `rotate_events` archives. A new `usage.*` kind
would have to declare itself in `is_shareable` — usage records are machine-local and
almost certainly must NOT be shared into the committed log, which is an explicit decision
the source does not make.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py`
  lines: 21-25
  symbol: `LedgerLog.append`
  excerpt: |
    def append(self, event: LedgerEvent) -> tuple[str, int]:
        ...
        ``os.write()`` under ``O_APPEND``, capped at 4 KiB — within the

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py`
  lines: 59-63
  symbol: `LedgerLog.append`
  excerpt: |
    # Open with O_APPEND | O_WRONLY | O_CREAT
    fd = os.open(self.path, os.O_APPEND | os.O_WRONLY | os.O_CREAT)
    ...
    # Since we opened with O_APPEND, writes always go to the end, but we want to know

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/log.py`
  lines: 83-111
  symbol: `append_line` / `iter_events`
  excerpt: |
    def append_line(self, line: str) -> int:
    fd = os.open(self.path, os.O_APPEND | os.O_WRONLY | os.O_CREAT)
    def iter_events(self, from_offset: int = 0) -> Iterator[tuple[LedgerEvent, int]]:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 73-144
  symbol: `shared-log API`
  excerpt: |
    def is_shareable(event: LedgerEvent) -> bool:
    def read_raw_events(path: Path) -> list[tuple[str, LedgerEvent]]:
    def shared_log_files(repo_root: Path) -> list[Path]:
    def read_shared_event_ids(files: list[Path]) -> set[str]:
    def digest_files(files: list[Path], repo_root: Path | None = None) -> str:
    def export_events(local: LedgerLog, repo_root: Path) -> SharedLogExportReport:

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 180-278
  symbol: `claims / import / rotate`
  excerpt: |
    def live_claims(events: Sequence[LedgerEvent]) -> list[LedgerEvent]:
    def import_events(...)
    def rotate_events(...)

## Notes

- Note the 4 KiB log cap against the sdd-coder telemetry sink's 8 KiB cap (FC-004,
  telemetry.py:25) — the two append-only logs in this repo do not agree on a row budget, and
  a usage row with a `turn_series` would exceed the ledger's.
- The committed `sdd/ledger/events.jsonl` is git-tracked and synced by git hooks. Adding
  per-request usage events to a shareable kind would put token counts into git history for
  every machine; keeping them unshareable keeps them per-machine, which conflicts with the
  source's "one usage plane" goal for a multi-developer team.
