---
id: F007
query_id: Q022
type: read
intent: "Read the shared log writer: how events.jsonl is appended/synced and who may rotate it."
executed_at: 2026-11-07T01:22:26Z
duration_ms: 2000
parent_id: null
depth: 1
merged_from: [FC-007, FW-003]
---

# F007 — The committed ledger log is append-only, union-merged, filtered by is_shareable, rotated only by /sdd-done

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


---

<!-- merged from FW-003 -->

# F007 — Ledger events travel repo→repo through committed sdd/ledger/events.jsonl (FEAT-694 hooks) and worktree→ledger branch through the outbox (FEAT-758); feature PRs never carry ledger data

## Summary

`shared_log.py` exports/imports between the machine-local `.parrot/ledger/events.jsonl` and the committed `sdd/ledger/events.jsonl` (+ `archive/events-YYYY-MM.jsonl`): append-only, deduped by `event_id`, union-merged; import runs incremental `LedgerIndex.sync()`. FEAT-758 moved feature-side delivery to an outbox: `/sdd-done` 9.1 seals local events into `<ledger-dir>/outbox/pending/<uuid>/` and an integrator pushes them to `ledger_branch` (default `dev`) from a temporary checkout — "Feature PRs contain code and task artifacts only". Rotation is explicit maintenance now, no longer run by `/sdd-done`. For escrow: a verdict written on the host lands in the ledger branch through the same outbox path, independent of the code PR; `/sdd-done` on the same machine can read it from the local journal immediately, other machines after import.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 20-27
  symbol: `SHARED_LOG_REL_PATH`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py
  excerpt: |
    SHARED_LOG_REL_PATH: Path = Path("sdd/ledger/events.jsonl")
    ARCHIVE_REL_DIR: Path = Path("sdd/ledger/archive")
    MARKER_FILENAME: str = "shared_log.marker"
    ROTATION_DAYS_DEFAULT: int = 30
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  lines: 1-1
  symbol: `export_events`
  excerpt: |
    def is_shareable(event): Return whether an event belongs in the cross-machine shared log.
    def export_events(local, repo_root): Append unknown, shareable local events to the committed log in local order.
    def import_events(local, repo_root, marker): Append committed unknown events to a local log, archives before the current log.
    def rotate_events(repo_root): Move old terminal lines of the committed log into monthly archive files (deterministic).
- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 1-60
  symbol: `FEAT-694 Goals G1-G9`
  wiki_page_id: file:sdd/specs/ledger-shared-event-log.spec.md
  score: 0.50
- path: `wiki/sdd-tooling/sdd/ledger-outbox.md`
  lines: 1-30
  symbol: `Ledger outbox (FEAT-758) — Model`
  wiki_page_id: file:wiki/sdd-tooling/sdd/ledger-outbox.md
  excerpt: |
    wikitoolkit ledger outbox prepare seals a finite, complete prefix into <ledger-dir>/outbox/pending/<uuid>/
    Feature PRs contain code and task artifacts only. Canonical ledger data is delivered independently to origin/dev.
    Rotation is explicit maintenance ... and is no longer run by /sdd-done.
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py`
  lines: 1-1
  symbol: `outbox (references shared_log)`
  wiki_page_id: file:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/outbox.py

## Notes

wiki_related on shared_log.py (Q012): referenced by `ledger/outbox.py`, `ledger/integration.py`, `wiki/cli.py` and three integration tests. `is_shareable` filters only `insight.*` with the `coder_suspension` category — a new verdict kind is shareable by default. Memory `mem-13cde1da79f4`: "Ledger is per-machine; issues.jsonl snapshot is export-only" (never imported).
