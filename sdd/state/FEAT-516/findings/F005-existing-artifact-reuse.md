---
id: F005
query_id: Q008
type: read
intent: Locate tests for flow interruption, resume, idempotency, and repeated node execution.
executed_at: 2026-08-31T15:21:00+02:00
duration_ms: 165
parent_id: null
depth: 0
---

# F005 - Research and development already contain partial reuse primitives

## Summary

Research safely reuses only a registered worktree on the expected branch and records prior commits/diffs for development. Development can rebuild a `TaskScheduler` from the per-spec index; tasks already marked `done` are excluded from pending waves. These primitives are the correct recovery validators for a development node that was interrupted mid-operation.

## Citations

- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 1228-1303
  symbol: `ResearchNode._ensure_worktree_safe`
  excerpt: |
    Path is a registered git worktree on the expected branch -> reuse.
    A mismatched branch or unregistered directory fails fast.
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py`
  lines: 1337-1349
  symbol: `ResearchNode._assess_prior_work`
  excerpt: |
    Inspect a reused worktree for existing commits and changes.
    The returned dict is consumed by DevelopmentNode to avoid repeating work.
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`
  lines: 70-108
  symbol: `TaskScheduler.from_index_file`
  excerpt: |
    if task.status == "done":
        self._done.add(task.id)
    else:
        self._pending.add(task.id)
- path: `packages/ai-parrot/src/parrot/flows/dev_loop/task_scheduler.py`
  lines: 166-182
  symbol: `TaskScheduler.next_wave`
  excerpt: |
    if all(dep in self._done for dep in task.depends_on):
        wave.append(task)

