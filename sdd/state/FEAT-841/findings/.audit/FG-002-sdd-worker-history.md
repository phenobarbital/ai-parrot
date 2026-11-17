---
id: FG-002
query_id: Q043
type: git_log
intent: "Recent history of the sdd-worker agent prompt — the closing/review protocol evolution (FEAT-549)."
executed_at: 2026-11-07T01:19:11Z
duration_ms: 700
parent_id: null
depth: 0
---

# FG-002 — sdd-worker.md: 15 commits in 120 days; completion protocol added by FEAT-793 (2026-11-03)

## Summary

`.claude/agents/sdd-worker.md` has 15 commits between 2026-11-03 and 2026-11-06, all within the last week of the window. The closing contract was formalised by `a606cd1450` (TASK-5124, FEAT-793 tmux-notify-worker: "Worker completion protocol and operator documentation", merged as PR #1950 `9976896626`) and `e4fff64f38` (gh-only sandbox; /sdd-done is host-side). Subsequent commits are sandbox/worktree plumbing (native sandbox default, baseline checkout `9c3c1ecbcb`, FEAT-806 sync-base `fe84359100`, FEAT-802 worktree root `3b81175974`). The worker's "I am done" signal is therefore very recent (FEAT-793) and is the natural seam to replace with a `work.completed` emission.

## Citations

- path: `.claude/agents/sdd-worker.md`
  symbol: `a606cd1450`
  excerpt: |
    a606cd1450 2026-11-03 Jesus Lara feat(tmux-notify-worker): TASK-5124 — Worker completion protocol and operator documentation
    9976896626 2026-11-04 phenobarbital Merge pull request #1950 from phenobarbital/feat-FEAT-793-tmux-notify-worker
- path: `.claude/agents/sdd-worker.md`
  symbol: `e4fff64f38`
  excerpt: |
    e4fff64f38 2026-11-03 Jesus Lara docs(sdd-worker-gh-only-sandbox): HOTFIX-sdd-worker-gh-only-sandbox-2 — gh-only access, host-side /sdd-done
- path: `.claude/agents/sdd-worker.md`
  symbol: `406c07752d`
  excerpt: |
    406c07752d 2026-11-03 Jesus Lara fix(sdd-worker): use python3 for the execution_id UUID command (C29 bare-python guard)
- path: `.claude/agents/sdd-worker.md`
  symbol: `9c3c1ecbcb`
  excerpt: |
    9c3c1ecbcb 2026-11-04 Jesus feat(sdd): parrot sdd worktree baseline — runnable base-ref checkout with native .so synced
    d9a4596c05 2026-11-04 Jesus Lara fix(sdd): never ship a guard hook baked to one machine's venv
    540130d96e 2026-11-04 Jesus Lara fix: sdd-native-sandbox-default task 4 trust launcher backend and skip no-op rewrites
- path: `.claude/agents/sdd-worker.md`
  symbol: `fe84359100`
  excerpt: |
    fe84359100 2026-11-05 Jesus feat(worktree-sync-base): TASK-5210 — engine-committed coder deliverable
    3b81175974 2026-11-05 Jesus feat(worktree-root-under-parrot): TASK-5180 — engine-committed coder deliverable
    bd060dd13d 2026-11-05 Jesus Lara test: fix dev CI — stale 2.5-pro row, FEAT-804 note in action counts, worktree literal
    ae66b611cc 2026-11-06 Jesus merge: origin/dev into feat-FEAT-802-worktree-root-under-parrot

## Notes

- [cross-lane: type=read, intent=read the "Worker completion protocol" section of .claude/agents/sdd-worker.md introduced by a606cd1450 and the matching worker_notification.py to see exactly what is emitted at feature end]
- FEAT-793's spec (tmux-notify-worker) likely defines the completion message schema; a `work.completed` event would extend, not replace, that notification.
