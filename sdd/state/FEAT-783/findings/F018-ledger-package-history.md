---
id: F018
query_id: Q035
type: git_log
intent: "Recent history of the ledger package - the migration/compaction pattern in motion and any in-flight work that would collide."
executed_at: 2026-10-30T22:38:00Z
duration_ms: 900
parent_id: null
depth: 0
lane: git
merged_from: ['FG-001']
---

# F018 — Ledger package: 30 commits/90d, dominated by FEAT-694 shared log and FEAT-758 outbox; no usage plane, no collision

## Summary

30 commits touched `knowledge/wiki/ledger/` in the last 90 days, authored
entirely by Jesus Lara. Three waves dominate: **FEAT-694 shared event log**
(TASK-4405/4406/4408/4416, 2026-10-16→22), **FEAT-758 ledger outbox
integration** (TASK-4857/4858/4859/4862, 2026-10-28, merged as PR #1845), and
**FEAT-694 follow-ups / wiki-cli-fixes** (TASK-4895/4896, 2026-10-30). Not one
commit touches tokens, usage or cost — the brainstorm's claim that no ledger
plane stores usage is consistent with 90 days of history. The pattern a new
plane must follow is visible and recent: a plane is added as its own module
(`coder_feedback.py`, `outbox.py`, `integration.py`) plus reducer wiring in
`index.py`, delivered one TASK per module. **No in-flight branch touches
`ledger/`**, so a `usage.py` plane would not collide. The live churn is
concentrated in `integration.py`/`outbox.py`, not in `events.py` or `index.py`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  symbol: `git log --since=90.days.ago`
  excerpt: |
    823d5e9a88|2026-10-30|fix(ci): register ai-parrot-squawk ... -> ledger/sdd_meta.py
    68d2fcf896|2026-10-30|fix(wiki-cli-fixes): TASK-4896 — outbox integrator cleanup and CLI error mapping
                           -> ledger/integration.py, ledger/outbox.py
    152c5ad116|2026-10-30|feat(wiki-cli-fixes): TASK-4895 — redundant ledger closes never block delivery
                           -> ledger/integration.py, ledger/outbox.py
    a6fd22172c|2026-10-30|wiki ledger -> ledger/index.py   (hand commit, today)

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/integration.py`
  symbol: `FEAT-758 ledger-outbox-integration`
  excerpt: |
    3593d016d4|2026-10-28|fix(ledger-outbox-integration): review fixes for FEAT-758
    f8faf675e4|2026-10-28|feat(ledger-outbox-integration): TASK-4859 -> integration.py
    624143dd54|2026-10-28|feat(ledger-outbox-integration): TASK-4858 -> integration.py
    22a628adf5|2026-10-28|feat(ledger-outbox-integration): TASK-4857 -> outbox.py

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/shared_log.py`
  symbol: `FEAT-694 ledger-shared-event-log`
  excerpt: |
    267c66b240|2026-10-22|feat(ledger-shared-event-log): TASK-4416
    e20d9b1ade|2026-10-22|fix(ledger-shared-event-log): TASK-4416 review fixes — drift digest uses repo_root
    e3047407e8|2026-10-16|feat(ledger-shared-event-log): TASK-4408
    b4f2bf3266|2026-10-16|feat(ledger-shared-event-log): TASK-4406
    c96dd500ef|2026-10-16|feat(ledger-shared-event-log): TASK-4405

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/coder_feedback.py`
  symbol: `retract() + tombstone-aware replay`
  excerpt: |
    f9029f0f11|2026-10-22|feat(ledger-coder-feedback-fixes): TASK-4603 — retract() + tombstone-aware replay

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/service.py`
  symbol: `export_snapshot`
  excerpt: |
    cc05f88076|2026-10-14|feat(commands-sdd-done-fixes): TASK-4295 — reconciling export_snapshot + service tests
    23f68486b5|2026-10-08|fix(ledger): make close_issue and unclaim atomic like claim_issue

## Notes

`git branch -r --no-merged origin/dev` returns no branch touching `ledger/`.
The delivery cadence (one module per TASK, reducer wiring separate) is the
template a `usage` plane should copy.

[cross-lane: type=read, intent=read ledger/index.py reducer registration to confirm how a new plane's tables are declared and migrated]
