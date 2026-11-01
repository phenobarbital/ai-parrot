---
id: F027
query_id: Q005
type: wiki_query
intent: "Orient: ledger index schema, plane tables and migration pattern."
executed_at: 2026-10-30T22:40:30Z
duration_ms: 0
parent_id: null
depth: 1
lane: wiki
merged_from: ['FW-008']
---

# F027 — The ledger's plane-in-its-own-dir pattern is `LedgerStore(SQLiteWikiStore)` + `LedgerService.from_root`, with a read-first latched migration

## Summary

The source's plan to add a `usage` plane to the ledger lands on an established template. A prior
proposal's finding states it directly: "LedgerStore(SQLiteWikiStore) + LedgerService.from_root are
the plane-in-its-own-dir template" (`sdd/state/FEAT-600/findings/F005-ledger-plane-template.md`,
score=0.46). The SQLite schema migration convention is read-first and latched (TASK-3218), with a
worked v1→v2 example under `tests/knowledge/wiki/test_store_migration_v2.py` (score=1.00) and a
v2→v3 FTS migration (TASK-3301). Event-kind extension has its own worked precedent: TASK-3387
added the `issue.unclaimed` event kind together with its payload model **and** its index reducer —
i.e. a new kind is a three-part change (enum + payload model + reducer), not just an enum entry.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  lines: 1-1
  symbol: package contents
  excerpt: |
    coder_feedback.py coder_reviews.py coder_suspensions.py events.py
    fix_planner.py index.py integration.py log.py operations.py outbox.py
    sdd_ingest.py sdd_meta.py service.py shared_log.py store.py

- path: `sdd/state/FEAT-600/findings/F005-ledger-plane-template.md`
  lines: 1-1
  symbol: prior finding
  excerpt: |
    F005 — LedgerStore(SQLiteWikiStore) + LedgerService.from_root are the
           plane-in-its-own-dir template

- path: `sdd/tasks/completed/TASK-3218-read-first-latched-migration.md`
  lines: 1-1
  symbol: migration convention
  excerpt: |
    TASK-3218: Read-first, latched schema migration

- path: `sdd/tasks/completed/TASK-3387-unclaimed-event-kind-and-reducer.md`
  lines: 1-1
  symbol: event-kind extension precedent
  excerpt: |
    TASK-3387: `issue.unclaimed` event kind, payload model and index reducer

- path: `tests/knowledge/wiki/test_store_migration_v2.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "FEAT-498 (TASK-2747) — SQLite schema v1 -> v2 migration."

- path: `tests/knowledge/wiki/test_ledger_shared_log.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "FEAT-694 M1 — shared ledger event log core."

- path: `packages/ai-parrot/tests/knowledge/wiki/test_ledger_outbox.py`
  lines: 1-1
  symbol: test module
  excerpt: |
    # "FEAT-758 M1 — durable ledger outbox."

- path: `sdd/specs/sdd-work-ledger.spec.md`
  lines: 1-1
  symbol: governing spec
  excerpt: |
    # Feature Specification: SDD Work Ledger — Discovered Work, Spec Graph and
    # Insights on the LLM Wiki Plane

## Notes

Two open ledger defects bear on a high-volume usage plane:
- `issue:62038221413a` — "Ledger export (export_snapshot) overwrites sdd/ledger/issues.jsonl instead
  of reconciling against the committed snapshot" (supersedes `issue:1e13dd5b188b`). The source
  assumes `export_snapshot` covers a usage plane "for free"; it is currently defective for issues.
- `issue:d436426cd1d9` — "shared_log.py hardening: rotation dup on crash ... (skip event_ids already
  in archive)". A per-request usage event stream is exactly the volume that forces rotation.

Also relevant: `TASK-4381-helix-ledger-store.md` is ACTIVE ("HelixLedgerStore + LedgerService backend
dispatch", FEAT-670) — a second ledger backend is in flight, so a new plane must go through
`LedgerService` dispatch rather than binding SQLite directly.

[cross-lane: type=read, intent=Read ledger/events.py for the LedgerEventKind enum and LedgerEvent envelope verbatim]
[cross-lane: type=read, intent=Read ledger/index.py for the reducer + DDL pattern a usage reducer must follow]
