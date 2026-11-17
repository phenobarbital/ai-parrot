---
id: FW-003
query_id: Q009
type: wiki_page
intent: "Read the ledger shared-log page: API outline of shared_log/log/events."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 1100
parent_id: null
depth: 1
---

# FW-003 — Ledger events travel repo→repo through committed sdd/ledger/events.jsonl (FEAT-694 hooks) and worktree→ledger branch through the outbox (FEAT-758); feature PRs never carry ledger data

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
