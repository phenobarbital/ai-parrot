---
id: F012
query_id: Q011
type: wiki_page
intent: One managed hook block serves post-commit and post-merge with a POSIX linked-worktree guard
executed_at: 2026-09-24T20:41:46+00:00
duration_ms: 0
parent_id: null
depth: 0
---

# F012 — One managed hook block serves post-commit and post-merge with a POSIX linked-worktree guard

## Summary

claude_code/assets.py git_hook_block(root) L166-190 renders the managed block used by both hooks: `if [ ! -f .git ]; then <wikitoolkit> upsert --changed --quiet; fi` — the guard mirrors is_linked_worktree without invoking Python. tests/knowledge/wiki/test_installer_worktree_guard.py (TASK-3237) covers both hooks. A schema ingest-ddl line belongs inside the same `if`.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py`
  lines: 166-190
  symbol: `git_hook_block`
  excerpt: |
    if [ ! -f .git ]; then\n    {wt_bin} upsert --changed --quiet >/dev/null 2>&1 || true\nfi
- path: `tests/knowledge/wiki/test_installer_worktree_guard.py`
  lines: 1-
  symbol: `TestLinkedWorktreeHookSkipsUpsert`
  excerpt: |
    A linked worktree's hook exits before the upsert ever runs.
