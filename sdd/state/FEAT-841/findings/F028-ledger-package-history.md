---
id: F028
query_id: Q044
type: git_log
intent: "History of the ledger package — when FEAT-694 shared log and outbox landed; who touches event kinds."
executed_at: 2026-11-07T01:19:11Z
duration_ms: 800
parent_id: null
depth: 0
merged_from: [FG-003]
---

# F028 — ledger package: 20 commits in 90 days; FEAT-694 shared log landed ~2026-10-22, FEAT-758 outbox 2026-10-28

## Summary

`packages/ai-parrot/src/parrot/knowledge/wiki/ledger/` shows 20 commits from 2026-10-22 to 2026-11-07. The FEAT-694 shared event log work is visible at `e20d9b1ade` (TASK-4416 review fixes, drift digest) and the merge `46270bd951` (origin/dev into feat-FEAT-694). Retract/tombstone replay arrived with `f9029f0f11` (TASK-4603). FEAT-758 ledger-outbox-integration landed 2026-10-28 (`22a628adf5`, `624143dd54`, `f8faf675e4`, review fixes `3593d016d4`). Later commits harden claimant semantics (`cd54e4b7d7`), terminal-issue unclaims (`6cbdcbbb18`) and sdd_meta parsing (`4ec570ec8f`, 2026-11-07). The package is actively maintained (single author) and already models events with retraction — a verdict event kind fits an existing, live append/replay path.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  symbol: `e20d9b1ade`
  excerpt: |
    e20d9b1ade 2026-10-22 Jesus Lara fix(ledger-shared-event-log): TASK-4416 review fixes — drift digest uses repo_root
    46270bd951 2026-10-22 Jesus Merge remote-tracking branch 'origin/dev' into feat-FEAT-694-ledger-shared-event-log
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  symbol: `f9029f0f11`
  excerpt: |
    f9029f0f11 2026-10-22 Jesus Lara feat(ledger-coder-feedback-fixes): TASK-4603 — retract() + tombstone-aware replay
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  symbol: `22a628adf5`
  excerpt: |
    22a628adf5 2026-10-28 Jesus feat(ledger-outbox-integration): TASK-4857 — engine-committed coder deliverable
    624143dd54 2026-10-28 Jesus feat(ledger-outbox-integration): TASK-4858 — engine-committed coder deliverable
    f8faf675e4 2026-10-28 Jesus feat(ledger-outbox-integration): TASK-4859 — engine-committed coder deliverable
    3593d016d4 2026-10-28 Jesus fix(ledger-outbox-integration): review fixes for FEAT-758
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  symbol: `cd54e4b7d7`
  excerpt: |
    cd54e4b7d7 2026-11-03 Jesus Lara feat(parrot-installer): TASK-5120 — ledger close/unclaim respect the claimant
    6cbdcbbb18 2026-11-05 Jesus Lara fix(ledger-outbox): set aside unclaims of terminal issues instead of blocking the batch
    152c5ad116 2026-10-30 Jesus Lara feat(wiki-cli-fixes): TASK-4895 — redundant ledger closes never block delivery
    68d2fcf896 2026-10-30 Jesus Lara fix(wiki-cli-fixes): TASK-4896 — outbox integrator cleanup and CLI error mapping
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/`
  symbol: `4ec570ec8f`
  excerpt: |
    4ec570ec8f 2026-11-07 Jesus Lara feat(ledger-sdd-meta-fixes): TASK-5295 — sdd_meta.parse() derives type for brief frontmatter
    380436e808 2026-11-05 Jesus feat(worktree-root-under-parrot): TASK-5177 — engine-committed coder deliverable
    31f6f1ac5c 2026-11-05 Jesus feat(worktree-root-under-parrot): TASK-5176 — engine-committed coder deliverable

## Notes

- The brainstorm's "⚠️ VERIFY whether the ledger feature has landed" is resolved: it landed (FEAT-694, FEAT-758) and `sdd/ledger/events.jsonl` is live on dev.
- "claimant respected" semantics (cd54e4b7d7) show the ledger already carries an actor identity on writes — relevant to "signed" verdicts. [cross-lane: type=grep, intent=confirm the actor/claimant field on ledger events and whether any cryptographic signature exists]
