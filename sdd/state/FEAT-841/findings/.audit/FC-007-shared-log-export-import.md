---
id: FC-007
query_id: Q022
type: read
intent: "Read the shared log writer: how events.jsonl is appended/synced and who may rotate it."
executed_at: 2026-11-07T01:22:26Z
duration_ms: 2000
parent_id: null
depth: 0
---

# FC-007 — The committed ledger log is append-only, union-merged, filtered by is_shareable, rotated only by /sdd-done

## Summary

`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py` (374 lines, FEAT-694) moves events between the machine-local `.parrot/ledger/events.jsonl` and the committed `sdd/ledger/events.jsonl` (+ `sdd/ledger/archive/events-YYYY-MM.jsonl`). `export_events()` (144-177) appends every local event whose `event_id` is unknown to the committed files, **verbatim raw lines in local order**, skipping `is_shareable()==False` (only local-only insight categories are filtered). `import_events()` (209-) appends committed-unknown lines to the local log via `append_line` and tracks live claims. `rotate_events()` (278-) archives old terminal lines and is run only by /sdd-done 9.1. Consequence for escrow: any new `work.completed`/`escrow.*` kind is automatically shareable and will travel cross-machine with no further work, but a consumer tailing `events.jsonl` must tolerate the committed file being a union of machines and the local file being per-machine.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 21-22
  symbol: `SHARED_LOG_REL_PATH`
  excerpt: |
    SHARED_LOG_REL_PATH: Path = Path("sdd/ledger/events.jsonl")
    ARCHIVE_REL_DIR: Path = Path("sdd/ledger/archive")

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 73-75
  symbol: `is_shareable`
  excerpt: |
    def is_shareable(event: LedgerEvent) -> bool:
        """Return whether an event belongs in the cross-machine shared log."""
        return not (event.kind.startswith("insight.") and event.payload.get("category") in LOCAL_ONLY_INSIGHT_CATEGORIES)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 144-146
  symbol: `export_events`
  excerpt: |
    def export_events(local: LedgerLog, repo_root: Path) -> SharedLogExportReport:
        """Append unknown, shareable local events to the committed log in local order."""
        known = read_shared_event_ids(shared_log_files(repo_root))

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 158-167
  symbol: `export_events`
  excerpt: |
        with dest.open("a", encoding="utf-8") as handle:
            for raw, event in read_raw_events(Path(local.path)):
                if not is_shareable(event):
                    skipped_local_only += 1
                    continue
                if event.event_id in known:
                    continue
                handle.write(raw + "\n")

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 209-212
  symbol: `import_events`
  excerpt: |
    def import_events(
        """Append committed unknown events to a local log, archives before the current log.

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 278-281
  symbol: `rotate_events`
  excerpt: |
    def rotate_events(
        """Move old terminal lines of the committed log into monthly archive files (deterministic)."""

## Notes

- `is_shareable` has an allowlist-by-exclusion shape: escrow events would need an explicit decision whether verdicts are shared (they should be: /sdd-done on another machine must see them).
