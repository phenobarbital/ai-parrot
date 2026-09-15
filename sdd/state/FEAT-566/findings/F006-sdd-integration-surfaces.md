---
id: F006
query_id: Q013
type: read
executed_at: 2026-09-14T00:05:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F006 — SDD command lifecycle has clear emission and consumption seams

## Summary

`/sdd-start` verifies task dependencies, creates or reuses a worktree, and directly marks the per-spec index in progress. `close_task.sh` is the idempotent state transition to completed. `/sdd-next` currently derives readiness solely from task indexes, code review has critical/major/minor buckets but an optional report, and `/sdd-done --merge` merges then heals active-task orphans.

## Citations

- path: `.claude/commands/sdd-start.md`
  lines: 38-48
  symbol: null
  excerpt: |
    Status must be "pending" and every task in `depends_on` must have status "done".
- path: `.claude/commands/sdd-start.md`
  lines: 50-81
  symbol: null
  excerpt: |
    `python -m scripts.sdd.ensure_worktree` provisions the worktree;
    each feature owns its own index file.
- path: `.claude/commands/sdd-start.md`
  lines: 83-105
  symbol: null
  excerpt: |
    The task status becomes "in-progress" and the per-spec index is committed.
- path: `scripts/sdd/close_task.sh`
  lines: 3-30
  symbol: null
  excerpt: |
    Moves a task from active to completed, marks it done in its per-spec index,
    and hard-verifies no active copy survives.
- path: `.claude/commands/sdd-next.md`
  lines: 20-46
  symbol: null
  excerpt: |
    Aggregate `sdd/tasks/index/*.json`; a pending task is unblocked when all
    `depends_on` tasks are done.
- path: `.claude/commands/sdd-codereview.md`
  lines: 136-163
  symbol: null
  excerpt: |
    Critical, Major and Minor findings are rendered; saving the review report is optional.
- path: `.claude/commands/sdd-done.md`
  lines: 153-174
  symbol: null
  excerpt: |
    Partial work can be marked `done-with-issues`; verification is stamped on
    the feature branch rather than by rerunning close_task.sh.
- path: `.claude/commands/sdd-done.md`
  lines: 276-308
  symbol: null
  excerpt: |
    `--merge` directly merges the feature, heals active-task orphans, then pushes the base branch.

## Notes

The draft's proposed start, review, next and done touchpoints match existing workflow boundaries, but each command has platform twins that must be included in a later specification.
