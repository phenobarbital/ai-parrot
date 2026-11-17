---
id: FC-019
query_id: Q035
type: read
intent: "Read the header + event schema sections of the FEAT-694 ledger-shared-event-log spec (authoritative kinds/ids/sync contract)."
executed_at: 2026-11-07T01:25:27Z
duration_ms: 2000
parent_id: null
depth: 0
---

# FC-019 — FEAT-694 (approved): events.jsonl travels through git with managed hooks, append-only, merge=union, dedup by event_id; rotation only in /sdd-done 9.1

## Summary

`sdd/specs/ledger-shared-event-log.spec.md` (FEAT-694, status approved, 2026-10-16) is the authoritative contract behind FC-007. Goals: G1 event log travels as `sdd/ledger/events.jsonl`; G2 zero explicit commands — managed git hooks export on `pre-commit` and import on `post-merge`/`post-checkout`/`post-rewrite`; G3 import is append-only; G4 `merge=union` + dedup by content-addressed `event_id`; G6 concurrent claims are surfaced, never silently resolved; G8 `ledger claim` imports before claiming; G9 only /sdd-done 9.1 rotates. Non-goals: deterministic cross-machine claim resolution (reducer keeps "first claim in local log order wins"), hook-triggered rotation, MCP changes. Implication for escrow: a verdict event written on machine A reaches machine B's local log on B's next pull (hook import), but only if it was committed — a verdict written to the local log and not yet exported/pushed is invisible to another host. /sdd-done's guard must therefore read both the committed shared log and the local log, or require the verdict to be committed.

## Citations

- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 11-15
  symbol: null
  excerpt: |
    **Feature ID**: FEAT-694
    **Date**: 2026-10-16
    **Status**: approved

- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 54-59
  symbol: null
  excerpt: |
    - G1. The **event log** (`events.jsonl`), not just the state snapshot, travels through git
      as an append-only, union-mergeable file: `sdd/ledger/events.jsonl`.
    - G2. **Zero explicit commands** in the steady state: managed git hooks export local
      events on `pre-commit` ... and import committed events on `post-merge`, `post-checkout` and `post-rewrite`

- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 64-66
  symbol: null
  excerpt: |
    - G4. Concurrent appends on two machines merge **without git conflicts**
      (`.gitattributes` → `merge=union`) and without duplicates (dedup by content-addressed
      `event_id`, `events.py:88`).

- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 69-71
  symbol: null
  excerpt: |
    - G6. A `claim` made on two machines for the same issue before either pulled is
      **surfaced** (hook output + `ledger audit`), never silently resolved differently per
      machine without a trace.

- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 80-84
  symbol: null
  excerpt: |
    - G9. The committed log is **rotated** by `/sdd-done` step 9.1 only: shareable lines older
      than 30 days whose subject is terminal move, deterministically, to
      `sdd/ledger/archive/events-<YYYY-MM>.jsonl`.

- path: `sdd/specs/ledger-shared-event-log.spec.md`
  lines: 117-122
  symbol: null
  excerpt: |
    1. **Export (local → repo)** — `wikitoolkit ledger export-log --stage`, run by the managed
       `pre-commit` block. Reads the local `<shared>/.parrot/ledger/events.jsonl`, computes the
       set of `event_id`s already present in `<checkout>/sdd/ledger/events.jsonl` **and**
       `<checkout>/sdd/ledger/archive/*.jsonl`, appends the missing **shareable** local lines

## Notes

- FC-002 §9.1 shows a later layer (FEAT-758 "ledger outbox"): events are delivered to a `ledger_branch` via `wikitoolkit ledger outbox prepare|integrate`, never inside the feature PR. A verdict event follows the same outbox path.
