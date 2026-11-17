---
id: F039
query_id: Q014
type: wiki_query
intent: "Recorded decisions/lessons that constrain the design: ledger per-machine, snapshot export-only, snapshot removal guard."
executed_at: 2026-11-07T01:23:54Z
duration_ms: 600
parent_id: FW-006
depth: 2
merged_from: [FW-012]
---

# F039 — Constraints inherited from recorded decisions: ledger is per-machine with issues.jsonl export-only; FEAT-712 CI guard forbids rows vanishing from the snapshot; events.jsonl is deliberately NOT guarded (append-only by construction)

## Summary

Memory `mem-13cde1da79f4` ("Ledger is per-machine; issues.jsonl snapshot is export-only"): `ledger list|ready|show` read `.parrot/ledger/ledger.db` materialised from the git-ignored local `events.jsonl`; the committed snapshot is never imported. FEAT-712 (`sdd/specs/ledger-service-fixes.spec.md`, approved): CI `scripts/sdd/check_ledger_snapshot.py` fails any commit that removes an `open`/`claimed` row from `sdd/ledger/issues.jsonl` vs the base ref; explicit non-goal "Guarding `sdd/ledger/events.jsonl` (append-only, rotated by /sdd-done)". `LedgerService.export_snapshot` reconciles (FEAT-671). Implications: (1) a verdict must be an **event**, never a snapshot edit; (2) a host-side guard reading "is there an APPROVED for HEAD" must read the local journal/index (same machine as the worker) or import first — cross-machine visibility is eventual; (3) new event kinds must not break `check_ledger_snapshot` (it reads issues.jsonl only) nor the index reducer's auto-rebuild caveat (FEAT-694 G3: never trigger the rebuild path that wipes `spec:`/`task:` pages).

## Citations

- path: `sdd/specs/ledger-service-fixes.spec.md`
  lines: 1-70
  symbol: `FEAT-712 Goals / Non-Goals`
  wiki_page_id: file:sdd/specs/ledger-service-fixes.spec.md
  score: 0.20
  excerpt: |
    Fail CI on any commit that removes a row from `sdd/ledger/issues.jsonl` whose base-ref status is `open` or `claimed`.
    Non-Goal: Guarding `sdd/ledger/events.jsonl` (append-only, rotated by `/sdd-done`).
    A read-only Python guard, `scripts/sdd/check_ledger_snapshot.py` ... mirrors `check_id_collisions.py` and `check_task_state.py`
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  lines: 1-1
  symbol: `LedgerService.export_snapshot`
  wiki_page_id: sym:packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py#LedgerService.export_snapshot
  score: 0.64
  excerpt: |
    Write ``sdd/ledger/issues.jsonl`` deterministically, reconciling against ``dest``.
- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 20-45
  symbol: `FEAT-694 G3 / G4`
  wiki_page_id: file:sdd/specs/ledger-shared-event-log.spec.md
  excerpt: |
    G3. Import is append-only ... only the incremental `sync()` runs — never the auto-rebuild path, which would wipe the non-event-sourced `spec:`/`task:` graph
    G4. Concurrent appends on two machines merge without git conflicts (`.gitattributes` → `merge=union`) and without duplicates
- path: `.parrot/ledger/events.jsonl`
  lines: 1-1
  symbol: `local journal (git-ignored)`
  wiki_page_id: mem-13cde1da79f4
  score: 1.00

## Notes

The brainstorm's "⚠️ VERIFY whether the ledger feature has landed" is answered: FEAT-694 (shared log), FEAT-758 (outbox), FEAT-712 (snapshot guard) are all approved and in-tree; the temporary `sdd/escrow/<FEAT>/verdicts.jsonl` sink proposed as fallback is unnecessary.
