---
id: F013
query_id: Q022
type: read
intent: Confirm PreToolUse hook resolves a single root and is unaffected by namespaces
executed_at: 2026-08-23T02:20:00Z
depth: 0
---
# F013 — The Claude hook only needs the local root's is_built(); namespaces do not touch it

## Summary
`hook.py:183` `find_project_root(cwd)`, `190` `config.is_built(root)`, `197`
`config.storage_path(root)` for the throttle stamp. It never opens a store. Adding a
`namespaces` field to `WikiProjectConfig` is backwards-compatible for the hook as long as the
model keeps defaults and stays stdlib+pydantic (F009).

## Citations
- path: `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py`
  lines: 175-215
  symbol: `build_nudge`
  excerpt: |
    root = find_project_root(cwd)        # 183
    if not config.is_built(root):        # 190
    storage = config.storage_path(root)  # 197
