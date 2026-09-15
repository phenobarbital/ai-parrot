---
id: F007
query_id: Q016
type: git_log
executed_at: 2026-09-14T00:05:00Z
duration_ms: 100
parent_id: null
depth: 0
---

# F007 — Recent history shows active maintenance in both wiki and SDD surfaces

## Summary

The recent history includes ongoing wiki installer and namespace work, plus recent SDD worktree-ownership and task-index changes. This supports treating the affected surfaces as active and requiring narrow, compatibility-conscious changes rather than broad refactors.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py`
  lines: 1-1
  symbol: null
  excerpt: |
    2d69b8b680 fix(claude-install-mcp-autoenable): close MCP-approval collision gap + parity fixes from code review
- path: `.claude/commands/sdd-start.md`
  lines: 50-81
  symbol: null
  excerpt: |
    9d1fea8be5c feat(worktree-creation-ownership): TASK-3155 — /sdd-start provisions its own worktree
- path: `.claude/commands/sdd-task.md`
  lines: 27-30
  symbol: null
  excerpt: |
    1bb2ac94ce feat(worktree-creation-ownership): TASK-3156 — /sdd-task stops creating worktrees

## Notes

The log evidence was used only for maintenance activity and not to infer current runtime behavior.
