---
id: F025
query_id: Q041
type: grep
intent: "Does /sdd-status or /sdd-next already read any completion/verdict state that an escrow line would extend?"
executed_at: 2026-11-07T01:26:34Z
duration_ms: 800
parent_id: null
depth: 0
merged_from: [FC-025]
---

# F025 — /sdd-status drives its per-feature panel from the index header completed_at and worktree_status --reconcile; no verdict state exists

## Summary

Grep `completed_at|worktree_status|verified` over `sdd-status.md`, `sdd-next.md`, `worktree_status.py`: `/sdd-status` states that header fields (including `completed_at`) "drive the per-feature panel" (line 28) and delegates worktree reconciliation to `parrot.sdd.scripts.worktree_status --reconcile` (210). `worktree_status.py` models per-task `completed_at` (44, 161) and computes `dev_closed = bool(dev_index.get("completed_at")) or (all tasks terminal)` (482, 514) to decide whether dev already considers the feature finished. No hit in `sdd-next.md`. So the status surface already distinguishes "finished on dev" vs "worktree still open" from the header; an `escrow: awaiting_verdict | approved @sha` line would be a third state derived from the same header block plus the ledger.

## Citations

- path: `.claude/commands/sdd-status.md`
  lines: 28-28
  symbol: null
  excerpt: |
    `completed_at`) drive the per-feature panel; the `tasks[]` array drives

- path: `.claude/commands/sdd-status.md`
  lines: 210-210
  symbol: null
  excerpt: |
    - Worktree reconciliation: `parrot.sdd.scripts.worktree_status` (`--reconcile`)

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py`
  lines: 44-44
  symbol: null
  excerpt: |
        completed_at: str | None = None

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py`
  lines: 482-482
  symbol: null
  excerpt: |
        #: dev already considers the feature finished (completed_at, or all tasks terminal)

- path: `packages/ai-parrot/src/parrot/sdd/scripts/worktree_status.py`
  lines: 514-514
  symbol: null
  excerpt: |
        dev_closed = bool(dev_index.get("completed_at")) or (

## Notes

- `worktree_status` already compares the dev index vs the worktree index per feature — the same comparison a "stale verdict" (head moved) check needs.
